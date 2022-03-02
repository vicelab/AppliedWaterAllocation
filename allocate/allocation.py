from collections import defaultdict

from cvxpy import Problem, Variable, Maximize, sum as cvxsum
from . import models

import logging

log = logging.getLogger(__name__)

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
            variable = Variable(name=pipe.variable_name)
            vars_by_name[pipe.variable_name] = variable

            if do_save:
                pipe.save()  # temporarily not saving for testing

            benefits.append(variable * MAX_BENEFIT_DISTANCE_METERS)  # benefit is the amount of water times the max distance we can send
            cost = variable * pipe.distance  # the cost is the amount of water sent over each pipe times the distance of the pipe
            costs.append(cost)  # this way, once we subtract costs from benefits, costs only exceed benefits if the water travels more than the max distance.

            # index the vars so we can set constraints after this is all over
            vars_by_well[well.well_id].append(variable)
            vars_by_field[field.liq_id].append(variable)

    for field in vars_by_field:  # for each field, make sure the allocations to it are less than the demand
        #log.info(f"Field: {field}, timestep: {cost_timestep}")
        try:
            field_demand = models.AgField.objects.get(liq_id=field).timesteps.get(timestep=cost_timestep).demand
        except models.AgFieldTimestep.DoesNotExist:
            field_demand = 0  # if we don't know the demand for the field, assume it wasn't planted and allocate 0 applied water

        log.info(f"Field Demand: {field_demand}")
        demands_by_field[field] = field_demand
        constraints.append(cvxsum(vars_by_field[field]) <= float(field_demand))  # make sure it doesn't go very high - should maybe do this with the benefit function and not a constraint
        constraints.append(cvxsum(vars_by_field[field]) >= FIELD_DEMAND_MARGIN * float(field_demand))  # make sure that we get close to the amount of water required. Leaving a bit of slosh to allow for data misalignments

    for well in vars_by_well:  # for each well, make sure the allocations it sends out are less than its capacity
        well_obj = models.Well.objects.get(well_id=well)
        annual_production = well_obj.annual_production(year)
        log.info(f"Well production: {annual_production}")
        if annual_production is None:
            annual_production = 0

        constraints.append(cvxsum(vars_by_well[well]) <= float(annual_production))  # can't overallocate the well
        constraints.append(cvxsum(vars_by_well[well]) >= WELL_ALLOCATION_MARGIN * float(annual_production))  # but we also know the well produced a certain amount of water - make sure it's applied

        for field in vars_by_field:
            for pipe_allocation in vars_by_field[field]:
                constraints.append(pipe_allocation >= 0)  # don't allow any pipe to have negative values, or else the model does strange things (and we don't suck water out of fields, anyway)

        # now make sure that water from the well that we know went to a specific crop gets allocated to that crop
        if use_crop_constraints:
            set_crop_constraints(constraints, vars_by_name, well, well_obj)

    return {"benefits": benefits, "costs": costs, "constraints": constraints, "vars_by_well": vars_by_well, "vars_by_field": vars_by_field, "demands_by_field": demands_by_field}


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
        if demand == 0:
            continue
        log.info(f"Field {field} - demand: {demand:.3f}, allocations: {allocation_values}")

    log.info(f"Total Allocations: {total_allocations:.3f}")
