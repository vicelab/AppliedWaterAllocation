from collections import defaultdict

from cvxpy import Problem, Variable, Minimize
import models

# TODO: mass balance doesn't include precip yet

MARGIN = 0.95
FIELD_DEMAND_MARGIN = MARGIN
WELL_ALLOCATION_MARGIN = MARGIN
SINGLE_CROP_WELL_ALLOCATION_MARGIN = MARGIN


def get_parts(timestep):
    # so, we want to satisfy the demand of every ag field
    costs = []
    constraints = []

    vars_by_field = defaultdict(list)
    vars_by_well = defaultdict(list)
    vars_by_name = {}

    for field in models.AgField.objects.all():
        for pipe in field.pipes.all():
            well = pipe.well
            pipe.variable_name = f"well_{well.well_id}_field_{field.liq_id}"
            variable = Variable(name=pipe.variable_name)
            vars_by_name[pipe.variable_name] = variable
            pipe.save()

            cost = variable * pipe.distance  # the cost is the amount of water sent over each pipe times the distance of the pipe
            costs.append(cost)

            # index the vars so we can set constraints after this is all over
            vars_by_well[well.well_id].append(variable)
            vars_by_field[field.liq_id].append(variable)

    for field in vars_by_field:  # for each field, make sure the allocations to it are less than the demand
        field_demand = models.AgField.objects.get(liq_id=field).timesteps.get(timestep=timestep).demand
        constraints.append(sum(vars_by_field[field]) < field_demand)
        constraints.append(sum(vars_by_field) >= FIELD_DEMAND_MARGIN * field_demand)  # make sure that we get close to the amount of water required. Leaving a bit of slosh to allow for data misalignments

    for well in vars_by_well:  # for each well, make sure the allocations it sends out are less than its capacity
        well_obj = models.Well.objects.get(well_id=well)
        constraints.append(sum(vars_by_well[well] < well_obj.capacity))  # can't overallocate the well
        constraints.append(sum(vars_by_well[well] > WELL_ALLOCATION_MARGIN * well_obj.capacity))  # but we also know the well produced a certain amount of water - make sure it's applied

        # now make sure that water from the well that we know went to a specific crop gets allocated to that crop
        for production in models.WellProduction.objects.filter(well=well_obj):
            crop = production.crop
            if crop is None:
                continue

            pipes_for_well_and_crop = models.Pipe.objects.filter(well=well_obj, agfield__crop=crop)
            # get the variables for the pipes
            crop_variables = [vars_by_name[f"well_{well}_field_{pipe.agfield}"] for pipe in pipes_for_well_and_crop]
            # set constrainsts so that the
            constraints.append(sum(crop_variables) < production.quantity)
            constraints.append(sum(crop_variables) >= SINGLE_CROP_WELL_ALLOCATION_MARGIN * production.quantity)

    return {"costs": costs, "constraints": constraints}


def build_problem():
    problem_info = get_parts()
    problem = Problem(Minimize(sum(problem_info["costs"])), problem_info["constraints"])