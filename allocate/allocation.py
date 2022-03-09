from collections import defaultdict
from itertools import combinations
import math

import numpy

from cvxpy import Problem, Variable, Parameter, Maximize, sum as cvxsum
from . import models

import logging

log = logging.getLogger(__name__)

# TODO: find the irrigation type by trying many values and see which ones work across the whole growing season (all timesteps)
# TODO: make sure all units are the same between production, ET, and precip
# TODO: Also doesn't include applied water efficiency in the algorithm?
## TODO - make it look for the specific crop in the service area as a constraint - if the crop doesn't exist, then just add it to the crop group constraints instead

MAX_BENEFIT_DISTANCE_METERS = 3000  # how far should we allow water to travel where the benefit is greater than the cost? Includes some extra for well positioning error (which is significant)
MARGIN = 0.1  # TODO: I should be higher - closer to 0.95!!
FIELD_DEMAND_MARGIN = MARGIN
WELL_ALLOCATION_MARGIN = MARGIN
SINGLE_CROP_WELL_ALLOCATION_MARGIN = MARGIN

FULL_RESET = False  # change if we want to overwrite calculated values for names/variables in the DB. Runs much slower


def get_parts(cost_timestep=1, year=2018, service_area=None, use_crop_constraints=True):
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
        for pipe in field.pipes.all():
            well = pipe.well

            do_save = False
            if pipe.variable_name is None or FULL_RESET:
                do_save = True

            pipe.variable_name = f"well_{well.well_id}_field_{field.liq_id}"
            variable = Variable(name=pipe.variable_name, nonneg=True)
            vars_by_name[pipe.variable_name] = variable

            if do_save:
                pipe.save()  # temporarily not saving for testing

            benefits.append(variable * MAX_BENEFIT_DISTANCE_METERS)  # benefit is the amount of water times the max distance we can send
            cost = variable * pipe.distance  # the cost is the amount of water sent over each pipe times the distance of the pipe
            costs.append(cost)  # this way, once we subtract costs from benefits, costs only exceed benefits if the water travels more than the max distance.

            # index the vars so we can set constraints after this is all over
            vars_by_well[well.well_id].append(variable)
            vars_by_field[field.liq_id].append(variable)

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
        constraints.append(cvxsum(vars_by_field[field]) >= FIELD_DEMAND_MARGIN * demand)  # make sure that we get close to the amount of water required. Leaving a bit of slosh to allow for data misalignments

    for well in vars_by_well:  # for each well, make sure the allocations it sends out are less than its capacity
        well_obj = models.Well.objects.get(well_id=well)
        annual_production = well_obj.annual_production(year)
        log.info(f"Well production: {annual_production}")
        if annual_production is None:
            annual_production = 0

        constraints.append(cvxsum(vars_by_well[well]) <= float(annual_production))  # can't overallocate the well
        constraints.append(cvxsum(vars_by_well[well]) >= WELL_ALLOCATION_MARGIN * float(annual_production))  # but we also know the well produced a certain amount of water - make sure it's applied

        # we specified nonneg = True in variable creation so we don't need this. Nonneg = True provides a bit more info to the analyzer
        #for field in vars_by_field:
        #    for pipe_allocation in vars_by_field[field]:
        #        constraints.append(pipe_allocation >= 0)  # don't allow any pipe to have negative values, or else the model does strange things (and we don't suck water out of fields, anyway)

        # now make sure that water from the well that we know went to a specific crop gets allocated to that crop
        if use_crop_constraints:
            set_crop_constraints(constraints, vars_by_name, well, well_obj)

    return {"benefits": benefits,
            "costs": costs,
            "constraints": constraints,
            "vars_by_well": vars_by_well,
            "vars_by_field": vars_by_field,
            "demands_by_field": demands_by_field,
            "irrigation_efficiency_params": irrigation_efficiency_params
            }


def set_crop_constraints(constraints, vars_by_name, well, well_obj):
    for production in models.WellProduction.objects.filter(well=well_obj):
        crop = production.crop
        if crop is None:
            continue

        pipes_for_well_and_crop = models.Pipe.objects.filter(well=well_obj, agfield__crop=crop)
        # get the variables for the pipes
        crop_variables = [vars_by_name[f"well_{well}_field_{pipe.agfield}"] for pipe in pipes_for_well_and_crop]
        # set constraints so that the
        constraints.append(cvxsum(crop_variables) <= float(production.quantity))
        constraints.append(cvxsum(crop_variables) >= SINGLE_CROP_WELL_ALLOCATION_MARGIN * float(production.quantity))


def build_problem(service_area=None, use_crop_constraints=True):
    problem_info = get_parts(service_area=service_area, use_crop_constraints=use_crop_constraints)
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

    def __init__(self, service_area_id, use_crop_constraints):
        self.service_area = service_area_id
        self.use_crop_constraints = use_crop_constraints
        self.build()

    def build(self):
        self.problem, self.problem_info = build_problem(self.service_area, use_crop_constraints=self.use_crop_constraints)

    def run(self, iterations=None):
        if iterations is None:
            iterations = self.monte_carlo_iterations

        efficiency_information = self.get_combinations()
        for iteration in range(iterations):
            self.run_iteration(efficiency_information=efficiency_information)

    def get_combinations(self):
        fields = models.AgField.objects.filter(ucm_service_area_id=self.service_area)
        irrigation_nums = []
        field_irrigation_options = {}

        # we don't technically need to collapse this into a custom object here, but I think it might help to
        # avoid random hits to the DB later on.
        for field in fields:
            priors = field.crop.irrigation_priors
            irrigation_nums.append(len(priors))
            field_irrigation_options[field.liq_id] = {
                'liq_id': field.liq_id,
                'crop_name': field.crop.vw_crop_name,
                'crop_id': field.crop_id,
                'irrigation': [{
                    'irrigation_id': prior.irrigation_type.id,
                    'prior_id': prior.id,
                    'name': prior.irrigation_type.name,
                    'efficiency': prior.irrigation_type.efficiency,
                    'probability': prior.probability
                } for prior in priors],
            }

            # we'll want to use numpy.random.choice, and for that we need lists of the efficiencies to choose and their individual probabilities - cache these so
            # that we don't run the list comprehension every time. Though we'll need to update the list of probabilities when we do Bayesian updates
            field_irrigation_options[field.liq_id]["efficiencies"] = [item.efficiency for item in field_irrigation_options[field.liq_id]["irrigation"]]
            field_irrigation_options[field.liq_id]["probabilities"] = [item.probability for item in field_irrigation_options[field.liq_id]["irrigation"]]

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
            field_param.value = numpy.random.choice(field_options["efficiencies"], replace=True, p=field_options["probabilities"])




    def update_results(self):
        pass
