"""
	Let's find the crop coefficients that are most likely to be in use. What we need is
	1. Multiple months of ET data,
	2. Some well "service areas"
	3. precip
	4. aggregate applied water for the service area
	5. a set of efficiency options for each crop within the VW area

	What we'll so is make an LP that has variables for irrigation efficiency in each field. It will apply
	water evenly by each crop type, setting irrigation efficiencies to one of a set of choices for each
	crop (may not be possible - may need to make a range). Across many months, the irrigation efficiencies
	will remain constant, but the ET and applied water may change, helping tease out which irrigation
	efficiencies best satisy all requirements. The LP will minimize the amount of water that's unaccounted
	for after choosing irrigation efficiencies for each crop (eg, minimize the error)
"""

import models


def get_parts(service_area_id):
	"""
		These are effectively separate models by service area, so we'll run them separately
	:param service_area_id:
	:return:
	"""

	wells = models.Well.objects.filter(ucm_service_area_id=service_area_id)
	fields = models.AgField.objects.filter(ucm_service_area_id=service_area_id)

	#pumped_water =