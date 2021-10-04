from django.db import models


class Crop(models.Model):
    """
        We'll keep a list of crops primarily so that when wells reported providing water to a specific
        crop, we can match it
    """
    name = models.TextField()
    liq_code = models.TextField()
    _efficiency_options = models.TextField()  # this will be a comma separated string of floating point values

    @property
    def efficiency_options(self):
        # return the efficiency options as a list of floats
        return [float(option) for option in self._efficiency_options.split(",")]


class Well(models.Model):
    """

    """
    well_id = models.TextField()  # valley water's well identifier
    ucm_service_area_id = models.TextField()  # our identifier for the service area this well is a part of

    allocated_amount = models.DecimalField(max_digits=16, decimal_places=4)

    @property
    def losses(self):
        """
            These aren't really losses, but it's the unaccounted for water. It's really the maximum potential
            water savings for this well
        :return:
        """
        return self.capacity - self.allocated_amount

    @property
    def capacity(self):
        # todo - make sure this sums up all of the production items below
        return self.production.all().values('quantity').annotate(capacity=models.Sum('quantity')).first().capacity


class WellProduction(models.Model):
    class Meta:
        unique_together = ["well", "timestep"]

    well = models.ForeignKey(Well, on_delete=models.CASCADE, related_name="production")
    timestep = models.SmallIntegerField()

    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, null=True, blank=True, related_name="production")
    quantity = models.DecimalField(max_digits=16, decimal_places=4)


class AgField(models.Model):
    crop = models.ForeignKey(Crop, on_delete=models.SET_NULL)
    liq_id = models.TextField()
    openet_id = models.TextField(null=True)


class AgFieldTimestep(models.Model):
    class Meta:
        unique_together = ["agfield", "timestep"]

    agfield = models.ForeignKey(AgField, on_delete=models.CASCADE, related_name="timesteps")
    timestep = models.SmallIntegerField()

    consumptive_use = models.DecimalField(max_digits=16, decimal_places=4)
    precip = models.DecimalField(max_digits=16, decimal_places=4)

    @property
    def demand(self):
        return self.consumptive_use - self.precip

class Pipe(models.Model):
    well = models.ForeignKey(Well, on_delete=models.CASCADE, related_name="pipes")
    agfield = models.ForeignKey(AgField, on_delete=models.CASCADE, related_name="pipes")
    distance = models.DecimalField(max_digits=16, decimal_places=4)

    variable_name = models.TextField(null=True)  # when the model runs, store the variable name for the pipe here
    allocation = models.DecimalField(max_digits=16, decimal_places=4)
