from collections import defaultdict
from itertools import combinations
import math
from matplotlib.pyplot import boxplot
from matplotlib import pyplot as plt
import statistics
import random
import csv

import numpy

from cvxpy import Problem, Variable, Parameter, Maximize, sum as cvxsum
from . import models

import logging

log = logging.getLogger(__name__)

# TODO: find the irrigation type by trying many values and see which ones work across the whole growing season (all timesteps)
# TODO: make sure all units are the same between production, ET, and precip
# TODO: Also doesn't include applied water efficiency in the algorithm?
## TODO - make it look for the specific crop in the service area as a constraint - if the crop doesn't exist, then just add it to the crop group constraints instead
# TODO: Check out sampling method in Monte Carlo
# TODO: Add fallow field constraint where no water should be attached to it - can't have that constraint in conjunction with existing constraints, so need to conditionally apply both

MAX_BENEFIT_DISTANCE_METERS = 3000  # how far should we allow water to travel where the benefit is greater than the cost? Includes some extra for well positioning error (which is significant)
MARGIN = 0.5  # TODO: I should be higher - closer to 0.95!!
FIELD_DEMAND_MARGIN = 0.75
WELL_ALLOCATION_MARGIN = 0
SINGLE_CROP_WELL_ALLOCATION_MARGIN = 0

FULL_RESET = False  # change if we want to overwrite calculated values for names/variables in the DB. Runs much slower

MAX_WELLS_PER_FIELD = 5

def get_parts(cost_timestep=1,
              year=2018,
              service_area=None,
              use_crop_constraints=True,
              add_debug=False,
              well_allocation_margin=WELL_ALLOCATION_MARGIN,
              single_crop_well_allocation_margin=SINGLE_CROP_WELL_ALLOCATION_MARGIN,
              field_demand_margin=FIELD_DEMAND_MARGIN
              ):
    # so, we want to satisfy the demand of every ag field
    benefits = []
    costs = []
    constraints = []

    vars_by_field = defaultdict(list)
    vars_by_well = defaultdict(list)
    vars_by_name = {}
    demands_by_field = {}

    if service_area is not None:
        ag_fields = models.AgField.objects.filter(ucm_service_area_id=service_area)
    else:
        ag_fields = models.AgField.objects.all()

    for field in ag_fields:
        # get all the pipes for the field, except get the shortest ones first, and then limit it so we actually only get up to MAX_WELLS_PER_FIELD pipes to reduce model complexity
        for pipe in field.pipes.all().order_by('distance')[:MAX_WELLS_PER_FIELD]:  # we'll only use the pipes connected to the fields here
            well = pipe.well  # which means we only get the wells connected to those pipes, not others

            do_save = False
            if pipe.variable_name is None or FULL_RESET:
                do_save = True

            pipe.variable_name = f"well_{well.well_id}_field_{field.liq_id}"
            variable = Variable(name=pipe.variable_name, nonneg=True)
            # see if we can store the connections to the Django objects on the optimization variables
            variable.alloc_pipe = pipe
            variable.alloc_field = field
            variable.alloc_well = well
            vars_by_name[pipe.variable_name] = variable

            if do_save:
                pipe.save()  # temporarily not saving for testing

            benefits.append(variable * MAX_BENEFIT_DISTANCE_METERS)  # benefit is the amount of water times the max distance we can send
            cost = variable * pipe.distance  # the cost is the amount of water sent over each pipe times the distance of the pipe
            costs.append(cost)  # this way, once we subtract costs from benefits, costs only exceed benefits if the water travels more than the max distance.

            # index the vars so we can set constraints after this is all over
            vars_by_well[well.well_id].append(variable)
            vars_by_field[field.liq_id].append(variable)

        if add_debug:
            debug_var_name = f"field_{field.liq_id}_debug"
            debug_var = Variable(name=debug_var_name, nonneg=True)

            costs.append(debug_var * MAX_BENEFIT_DISTANCE_METERS * 1000)  # make this water cost an extra high amount to make sure it doesn't use it unless it's trying to make the model feasible

            # add it to the field's mass balance only so the field can pull water in from here, and that water has no limit,
            # but it's super high cost
            vars_by_field[field.liq_id].append(debug_var)
            vars_by_name[debug_var_name] = debug_var

    irrigation_efficiency_params = {}
    for field in vars_by_field:  # for each field, make sure the allocations to it are less than the demand
        #log.info(f"Field: {field}, timestep: {cost_timestep}")
        try:
            field_demand = models.AgField.objects.get(liq_id=field).timesteps.get(timestep=cost_timestep).demand
        except models.AgFieldTimestep.DoesNotExist:
            field_demand = 0  # if we don't know the demand for the field, assume it wasn't planted and allocate 0 applied water

        log.info(f"Field Demand: {field_demand}")
        irrigation_efficiency_params[field] = Parameter(name=f"{field}_irrigation_efficiency", value=0.75)
        demand = float(field_demand) / irrigation_efficiency_params[field]
        demands_by_field[field] = demand
        constraints.append(cvxsum(vars_by_field[field]) <= demand)  # make sure it doesn't go very high - should maybe do this with the benefit function and not a constraint
        constraints.append(cvxsum(vars_by_field[field]) >= field_demand_margin * demand)  # make sure that we get close to the amount of water required. Leaving a bit of slosh to allow for data misalignments

    for well in vars_by_well:  # for each well, make sure the allocations it sends out are less than its capacity
        well_obj = models.Well.objects.get(well_id=well)
        annual_production = well_obj.annual_production(year)
        log.info(f"Well production: {annual_production}")
        if annual_production is None:
            annual_production = 0

        constraints.append(cvxsum(vars_by_well[well]) <= float(annual_production))  # can't overallocate the well
        constraints.append(cvxsum(vars_by_well[well]) >= well_allocation_margin * float(annual_production))  # but we also know the well produced a certain amount of water - make sure it's applied

        # we specified nonneg = True in variable creation so we don't need this. Nonneg = True provides a bit more info to the analyzer
        #for field in vars_by_field:
        #    for pipe_allocation in vars_by_field[field]:
        #        constraints.append(pipe_allocation >= 0)  # don't allow any pipe to have negative values, or else the model does strange things (and we don't suck water out of fields, anyway)

        # now make sure that water from the well that we know went to a specific crop gets allocated to that crop
        if use_crop_constraints:
            set_crop_constraints(constraints, vars_by_name, well, well_obj, single_crop_well_allocation_margin)

    return {"benefits": benefits,
            "costs": costs,
            "constraints": constraints,
            "vars_by_well": vars_by_well,
            "vars_by_field": vars_by_field,
            "demands_by_field": demands_by_field,
            "irrigation_efficiency_params": irrigation_efficiency_params
            }


def get_sa_total(service_area_id, year=2018, cost_timestep=1):
    sa_demands = 0
    sa_supplies = 0

    for field in models.AgField.objects.filter(ucm_service_area_id=service_area_id):
        try:
            sa_demands += field.timesteps.get(timestep=cost_timestep).demand
        except models.AgFieldTimestep.DoesNotExist:
            continue

    for well in models.Well.objects.filter(ucm_service_area_id=service_area_id):
        well_prod = well.annual_production(year=year)
        if well_prod is not None:
            sa_supplies += well_prod

    return {"demands": sa_demands, "supplies": float(sa_supplies)}


def report_sa_totals():
    all_supplies = 0
    all_demands = 0
    for service_area in sorted(list(models.AgField.objects.values_list("ucm_service_area_id").distinct())):
        totals = get_sa_total(service_area[0])
        if totals["demands"] == 0:
            totals["demands"] = 0.0001
        ratio = totals["supplies"] / totals["demands"]
        if ratio > 1.35:  # ranges skewed from irrigation efficiency
            status = "Oversupply - Can't allocate"
        elif ratio < 1:
            status = "Undersupply - can't meet demand"
        else:
            status = "OK"
        all_supplies += totals["supplies"]
        all_demands += totals["demands"]
        print(f"{service_area[0]} - Supplies: {totals['supplies']}, Demands: {totals['demands']}, Ratio: {ratio}, Status: {status}")

    print(f"Total Supply: {all_supplies}, Total Demand: {all_demands}")


def set_crop_constraints(constraints, vars_by_name, well, well_obj, single_crop_well_allocation_margin):
    for production in models.WellProduction.objects.filter(well=well_obj):
        crop = production.crop
        if crop is None:
            continue

        pipes_for_well_and_crop = models.Pipe.objects.filter(well=well_obj, agfield__crop=crop)
        # get the variables for the pipes
        crop_variables = [vars_by_name[f"well_{well}_field_{pipe.agfield}"] for pipe in pipes_for_well_and_crop]
        # set constraints so that the
        constraints.append(cvxsum(crop_variables) <= float(production.quantity))
        constraints.append(cvxsum(crop_variables) >= single_crop_well_allocation_margin * float(production.quantity))


def build_problem(service_area=None, use_crop_constraints=True, add_debug=False):
    problem_info = get_parts(service_area=service_area, use_crop_constraints=use_crop_constraints, add_debug=add_debug)
    problem = Problem(Maximize(cvxsum(problem_info["benefits"]) - cvxsum(problem_info["costs"])), problem_info["constraints"])
    return problem, problem_info


def solve_and_report(problem, problem_info):
    problem.solve(verbose=True)

    total_allocations = 0
    for variable in problem.variables():
        if variable.value is None:
            continue
        total_allocations += variable.value

    for field in problem_info["vars_by_field"]:
        #ignore1, well, ignore2, field = variable.name().split("_")
        allocations = problem_info["vars_by_field"][field]
        allocation_arrays = [str(round(float(val.value), 3)) for val in allocations]
        allocation_values = ", ".join(allocation_arrays)
        demand = problem_info['demands_by_field'][field]
        print(demand)
        original_demand = float(str(demand).split(" / ")[0])
        if original_demand == 0:
            continue
        log.info(f"Field {field} - evaporative demand: {original_demand:.3f}, allocations: {allocation_values}")

    log.info(f"Total Allocations: {total_allocations:.3f}")


class MonteCarloController(object):
    """
        We'll run a Monte Carlo for each service area - we'll check the number of fields and the number of
        irrigation options for each field - if the set of combinations is small, we'll just run a brute
        force of all combinations. E.g. 6 fields with 3 irrigation types each should just be brute forced.
        If it's large, we'll run a Monte Carlo - maybe with 1000 iterations? We'll see how fast they run
        once we can get them parameterized and then how good it is.

        We'll validate the approach and verify results against some service areas that we calculate the
        most likely irrigation combinations by hand.

        For each type, we'll start with a prior probability of the irrigation type for each field based on
        the landiq crop in the field, which we'll use when selecting irrigation type mixes. We'll then
        score each mix of irrigation types based on how much (or little) error it contains in the final
        mass balance when we allocate water from different pipes. We can increase the likelihood of
        getting the right irrigation type by using multiple timesteps (by month, which we don't
        *always* have - but we should consider using it for the fields that have it), where maybe
        an irrigation type completes the mass balance well the first month, but poorly in the next,
        but another irrigation type does slightly worse the first month, but much better the second.
        We'd probably prefer the second at that point.

        We'll then do something akin to a bayesian update, where we'll adjust the probabilities of each
        field's irrigation type according to the error values.
    """
    service_area = None
    fields = list()
    field_efficiencies = dict()
    problem = None
    problem_info = None
    use_crop_constraints = True
    monte_carlo_iterations = 1000
    brute_force_combinations_threshold = 100
    # fallow_crop_id = None
    null_crop_priors = list()
    results = list()
    best_result_objective_value = 0
    best_result = None
    well_allocation_margin = WELL_ALLOCATION_MARGIN
    single_crop_well_allocation_margin = SINGLE_CROP_WELL_ALLOCATION_MARGIN
    field_demand_margin = FIELD_DEMAND_MARGIN

    def __init__(self, service_area_id, use_crop_constraints, debug=False, random_seed='20220330'):
        self.service_area = service_area_id
        self.use_crop_constraints = use_crop_constraints
        self.debug = debug
        #self.fallow_crop_id = models.Crop.objects.get()

        random.seed(random_seed, version=2)

        irrigation_types = models.IrrigationType.objects.all()  # if we don't recognize it, use all of the irrigation type options
        number_of_types = len(irrigation_types)
        for irrig in irrigation_types:
            prior = models.CropIrrigationTypePrior(
                crop=None,
                irrigation_type=irrig,
                probability=1/number_of_types
            )
            self.null_crop_priors.append(prior)

        self.build()

    def build(self):
        self.problem, self.problem_info = build_problem(self.service_area, use_crop_constraints=self.use_crop_constraints, add_debug=self.debug)

    def run(self, iterations=None):
        if iterations is None:
            iterations = self.monte_carlo_iterations

        self.efficiency_information = self.get_combinations()
        for iteration in range(iterations):
            if iteration % 250 == 0:
                print(iteration)
            self.run_iteration(efficiency_information=self.efficiency_information)

        print("Complete")

    def view_results(self, field_id):
        irrigation_options = self.efficiency_information[field_id]["irrigation"]
        effectivenesses = [item["effectiveness"] for item in irrigation_options]

        for irrig_type in irrigation_options:
            mean = statistics.mean(irrig_type["effectiveness"])
            print(f"{irrig_type['name']}: {mean}")

        boxplot(effectivenesses)
        plt.show()

    def get_combinations(self):
        fields = models.AgField.objects.filter(ucm_service_area_id=self.service_area)
        irrigation_nums = []
        field_irrigation_options = {}

        # we don't technically need to collapse this into a custom object here, but I think it might help to
        # avoid random hits to the DB later on.
        for field in fields:
            use_defaults = False  # use a flag, because we need to use the null crop priors if the crop is unknown or if we don't have priors for the crop
            if field.crop is not None:  # if we recognize the field's crop, use the known irrigation options
                priors = field.crop.irrigation_priors.all()
                if len(priors) > 0:
                    crop_name = field.crop.vw_crop_name
                    crop_id = field.crop_id
                    irrigation_nums.append(len(priors))
                else:
                    use_defaults = True
            else:
                use_defaults = True

            if use_defaults:
                priors = self.null_crop_priors
                crop_name = "Unknown"
                crop_id = -1
                irrigation_nums.append(len(self.null_crop_priors))

            field_irrigation_options[field.liq_id] = {
                'liq_id': field.liq_id,
                'crop_name': crop_name,
                'crop_id': crop_id,
                'irrigation': [{
                    'irrigation_id': prior.irrigation_type.id,
                    #'prior_id': prior.id,
                    'name': prior.irrigation_type.name,
                    'efficiency': prior.irrigation_type.efficiency,
                    'probability': prior.probability,
                    "effectiveness": []  # how good did the full model fit after running it - this will be appended to after each model run, and we'll use it for one big bayesian update
                } for prior in priors],
            }

            # we'll want to use numpy.random.choice, and for that we need lists of the efficiencies to choose and their individual probabilities - cache these so
            # that we don't run the list comprehension every time. Though we'll need to update the list of probabilities when we do Bayesian updates
            field_irrigation_options[field.liq_id]["efficiencies"] = [float(item["efficiency"]) for item in field_irrigation_options[field.liq_id]["irrigation"]]
            field_irrigation_options[field.liq_id]["probabilities"] = [float(item["probability"]) for item in field_irrigation_options[field.liq_id]["irrigation"]]

        return field_irrigation_options
        #num_combinations = math.prod(irrigation_nums)
        #if num_combinations > self.brute_force_combinations_threshold:
        #    return None
        #else:
        #    return

    def run_iteration(self, efficiency_information):
        # for each iteration, set new irrigation efficiencies for each field by choosing from the available options
        # based on their probability
        for field in self.problem_info["irrigation_efficiency_params"]:
            field_param = self.problem_info["irrigation_efficiency_params"][field]
            field_options = efficiency_information[field]

            # I don't actually think we should get the value based on the prior probability since it might bias the sample
            # - we likely would want a true random sample of the efficiency options and to then go from there. But does
            # that then make our prior probability almost moot?
            field_param.value = numpy.random.choice(field_options["efficiencies"], replace=True)

        self.problem.solve()
        #self.update_results(efficiency_information)

        log.info("Solved, processing results")
        results = ServiceAreaResult(self.problem, self.problem_info, efficiency_information)
        if results.objective_value is not False:
            if results.objective_value > self.best_result_objective_value:
                self.best_result_objective_value = results.objective_value
                self.best_result = results
            self.results.append(results)

    def update_results(self, efficiency_information):

        for field in self.problem_info["irrigation_efficiency_params"]:
            field_param = self.problem_info["irrigation_efficiency_params"][field]
            field_info = efficiency_information[field]
            irrigation_type = next((item for item in field_info["irrigation"] if math.isclose(item["efficiency"], field_param.value)), None)

            # what we'll actually want to do here is to see *how* effective it was, not just a binary yes/no based
            # on whether it was feasible or not
            if self.problem.status in ["infeasible", "unbounded"]:
                irrigation_type["effectiveness"].append(0)
            else:
                irrigation_type["effectiveness"].append(self.problem.value)


class ServiceAreaResult(object):
    # stores the individual field level results for all fields in the SA for a single run
    results = dict()  # just a dict of results by each field
    objective_value = None  # objective value for the whole SA

    def __init__(self, problem, problem_info, efficiency_information):
        if problem.status in ["infeasible", "unbounded"]:
            self.objective_value = False
            return
        else:
            self.objective_value = problem.value

        for field in problem_info["irrigation_efficiency_params"]:
            field_param = problem_info["irrigation_efficiency_params"][field]
            field_info = efficiency_information[field]
            irrigation_type = next((item for item in field_info["irrigation"] if math.isclose(item["efficiency"], field_param.value)), None)

            # what we'll actually want to do here is to see *how* effective it was, not just a binary yes/no based
            # on whether it was feasible or not
            if problem.status in ["infeasible", "unbounded"]:
                irrigation_type["effectiveness"].append(0)
            else:
                irrigation_type["effectiveness"].append(problem.value)

        self.field_level_results(problem_info, efficiency_information)

    def dump_csvs(self, field_results_path):
        with open(field_results_path, 'wb') as fh:
            writer = csv.DictWriter(fh, fieldnames=self.results[0].result_dict.keys())
            writer.writeheader()
            for field in self.results:
                writer.writerow(field.result_dict)

    def field_level_results(self, problem_info, efficiency_information):
        for field in problem_info["vars_by_field"]:
            # ignore1, well, ignore2, field = variable.name().split("_")
            allocations = problem_info["vars_by_field"][field]
            allocation_arrays = [str(round(float(val.value), 3)) for val in allocations if val.value is not None]
            allocation_values = ", ".join(allocation_arrays)
            demand = problem_info['demands_by_field'][field]
            print(demand)
            original_demand = float(str(demand).split(" / ")[0])
            if original_demand == 0:
                continue
            log.info(f"Field {field} - evaporative demand: {original_demand:.3f}, allocations: {allocation_values}")

            self.results[field] = FieldResult(field, self, allocations, demand, problem_info["irrigation_efficiency_params"][field].value)


class FieldResult(object):
    field = None
    # field - reference to Django object? or just the ID?
    irrigation_efficiency_value = None
    irrigation_type = None
    allocations = list()
    net_water_demand = None  # net water demand - water demand remaining after allocation
    service_area_result = None

    def __init__(self, field, service_area_result, allocations, demand, irrigation_efficiency):
        self.field = field
        self.service_area_result = service_area_result
        self.allocations = [float(item.value) for item in allocations if item.value is not None]
        self.net_water_demand = demand - sum(self.allocations)
        self.irrigation_efficiency_value = irrigation_efficiency

    @property
    def total_allocations(self):
        return sum(self.allocations)

    @property
    def result_dict(self):
        return {'field': self.field, 'allocation': self.total_allocations, 'efficiency': self.irrigation_efficiency_value, 'available_water': self.total_allocations * self.irrigation_efficiency_value, 'excess_demand': self.net_water_demand}


"""
I don't think we need this - it seems like I was planning it for storing multiple results for the same set of input
efficiencies, but we don't need to do that, so we'll just use a list and append results.

class ResultRegistry(object):
    store = dict()

    def add_result(self, problem, problem_info, efficiency_information):
        # keys are a stringified combination of the sorted field ids with their corresponding efficiency values
        hash_key = f"-".join([f"{item['liq_id']}_{item['irrigation']['efficiency']}" for item in efficiency_information])
        result = ServiceAreaResult(problem, problem_info, efficiency_information)
        self.store[hash_key] = result

    # have an items dictionary
    # confirm the set is the same
    # store the values there

    # an alternative would be to just keep the best result, but I think we'll
    # want to know the spread
"""