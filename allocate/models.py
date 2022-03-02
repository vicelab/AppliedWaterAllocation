from django.db import models


class Crop(models.Model):
    """
        We'll keep a list of crops primarily so that when wells reported providing water to a specific
        crop, we can match it
    """
    vw_crop_name = models.TextField(unique=True)
    ucm_group = models.TextField(null=True)
    liq_crop_name = models.TextField(null=True)
    liq_crop_id = models.CharField(max_length=5, null=True)
    liq_group_code = models.CharField(max_length=5, null=True)
    liq_group_name = models.TextField(null=True)
    _efficiency_options = models.TextField(null=True)  # this will be a comma separated string of floating point values

    @property
    def efficiency_options(self):
        # return the efficiency options as a list of floats
        return [float(option) for option in self._efficiency_options.split(",")]


class Well(models.Model):
    """

    """
    well_id = models.TextField(unique=True)  # valley water's well identifier
    apn = models.TextField()
    ucm_service_area_id = models.TextField()  # our identifier for the service area this well is a part of

    allocated_amount = models.DecimalField(max_digits=16, decimal_places=4, null=True)

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
        return self.production.all().aggregate(models.Sum('quantity'))['quantity__sum']
        #return self.production.all().values('quantity').annotate(capacity=models.Sum('quantity')).first().capacity

    def _annual_production_only(self, year):
        query = self.production.filter(year=year, month=None, semi_year=None)
        if len(query) > 0:
            return query.aggregate(models.Sum('quantity'))['quantity__sum']

    def _semi_year_production(self, year, semi_year):
        # not using this yet - only aggregating up to annual
        query = self.production.filter(year=year, month=None, semi_year=semi_year)
        if len(query) > 0:
            return query.aggregate(models.Sum('quantity'))['quantity__sum']

    def _monthly_production(self, year, month):
        # not using this yet - only aggregating up to annual
        query = self.production.filter(year=year, month=month, semi_year=None)
        if len(query) > 0:
            return query.aggregate(models.Sum('quantity'))['quantity__sum']

    def annual_production(self, year):
        ann_prod = self._annual_production_only(year)
        if ann_prod is None:  # if we don't have annual data, aggregate the semi-annual data
            query = self.production.filter(year=year, month=None)
            if len(query) > 0:
                return query.aggregate(models.Sum('quantity'))['quantity__sum']
            else:  # and if we don't have that, then aggregate the monthly data for the year
                return self.production.filter(year=year, semi_year=None).aggregate(models.Sum('quantity'))['quantity__sum']


class WellProduction(models.Model):

    well = models.ForeignKey(Well, on_delete=models.CASCADE, related_name="production")
    year = models.SmallIntegerField()
    month = models.SmallIntegerField(null=True)
    semi_year = models.SmallIntegerField(null=True)

    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, null=True, blank=True, related_name="production")
    quantity = models.DecimalField(max_digits=16, decimal_places=4)


class AgField(models.Model):
    crop = models.ForeignKey(Crop, on_delete=models.SET_NULL, null=True)
    ucm_service_area_id = models.TextField()
    liq_id = models.TextField(unique=True)
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
    class Meta:
        unique_together = ["well", "agfield"]

    well = models.ForeignKey(Well, on_delete=models.CASCADE, related_name="pipes")
    agfield = models.ForeignKey(AgField, on_delete=models.CASCADE, related_name="pipes")
    distance = models.DecimalField(max_digits=16, decimal_places=4)

    variable_name = models.TextField(null=True)  # when the model runs, store the variable name for the pipe here
    allocation = models.DecimalField(max_digits=16, decimal_places=4, null=True)
