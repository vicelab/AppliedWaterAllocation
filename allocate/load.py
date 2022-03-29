import logging

import django.db.utils

from WellAllocation import settings
from allocate import models

import csv

log = logging.getLogger(__name__)

class Constant(object):
	""" we'll use this in field maps - if it's a Constant type, then it won't look up the value"""
	def __init__(self, value):
		self.value = value


def sanitize_input(value):
	if value == "" or value == " ":
		return None
	return value


def get_value(record, field):
	if type(field) is Constant:
		return field.value

	if hasattr(field, "keys"):  # if it's a dict-like, then it's a foreign key,
		# so let's get the foreign object
		model_key = list(field.keys())[0]
		model, attribute = model_key.split(".")  # it'll be ModelName.attribute as the key and then the value for the lookup
		kwarg = dict()
		kwarg[attribute] = sanitize_input(record[field[model_key]])
		try:
			return getattr(models, model).objects.get(**kwarg)
		except getattr(models, model).DoesNotExist:
			return None
		except getattr(models, model).MultipleObjectsReturned:  # get the first option when multiple are returned. This is a simple way to just choose one crop for landiq crops that are groups
			return getattr(models, model).objects.filter(**kwarg).order_by("id").first()

	try:
		return sanitize_input(record[field])  # if it's not a foreign key, then this is simple
	except KeyError:
		return None


def generic_csv_import(model, csv_file, field_map, skip_failed_create=False, bulk=True):
	if field_map is None:
		with open(csv_file, 'r') as csv_data:
			records = csv.DictReader(csv_data)
			for record in records:
				field_map = {key: key for key in record.keys()}
				break
	else:
		for field in field_map:  # if the field map provides a None value for the field, then
			if field_map[field] is None:  # set the key as the value to look up in the csv - it means to use it for both
				field_map[field] = field

	items = []
	with open(csv_file, 'r') as csv_data:
		records = csv.DictReader(csv_data)
		for record in records:
			values = {model_key: get_value(record, field_map[model_key]) for model_key in field_map}

			if bulk:
				items.append(model(**values))
			else:
				try:
					model.objects.get_or_create(**values)
				except django.db.utils.IntegrityError:
					if skip_failed_create:
						pass
					else:
						raise

	if bulk:
		model.objects.bulk_create(items, ignore_conflicts=True)

def load(crop_file=settings.CROP_DATA,
		 well_file=settings.WELL_DATA,
		 production_files=settings.PRODUCTION_DATA_FILES,
		 field_file=settings.FIELD_DATA,
		 agtimestep_file=settings.ET_DATA,
		 pipe_file=settings.PIPE_FILE,
		 crop_irrigation_file=settings.CROP_IRRIGATION_TYPE_DATA):

	log.info("Crops")
	load_crops(crop_file)
	load_wells(well_file)
	load_fields(field_file)

	log.info("Crop Irrigation Types")
	load_irrigation_types()
	load_crop_irrigation_types(crop_irrigation_file)

	log.info("ET Data")
	load_et_data(agtimestep_file)

	log.info("Pipes")
	generic_csv_import(models.Pipe, pipe_file, {
		"well": {"Well.well_id": "Well_Nbr"},
		"agfield": {"AgField.liq_id": "UniqueID"},
		"distance": "NEAR_DIST",
	})

	log.info("Production Data")
	for production_file in production_files:
		log.info(production_file)
		generic_csv_import(models.WellProduction, production_file, {
			"well": {"Well.well_id": "well_id"},
			"crop": {"Crop.vw_crop_name": "factor"},
			"quantity": "af",
			"year": "calendar_year",
			"month": "month",
			"semi_year": "calendar_semi_year",
		},
		skip_failed_create=True
		)




def load_crops(crop_file=settings.CROP_DATA):
	generic_csv_import(models.Crop, crop_file, {"vw_crop_name": "VW_crop",
												"ucm_group": "UCM_group",
												"liq_crop_name": "LIQ_CropType",
												"liq_crop_id": "LIQ_CROPTYP2",
												"liq_group_name": "LIQ_class_name",
												"liq_group_code": "LIQ_CLASS2",
												"_efficiency_options": "efficiencies"})


def load_fields(field_file=settings.FIELD_DATA):
	generic_csv_import(models.AgField, field_file,{
		"crop": {"Crop.liq_crop_id": "CROPTYP2"},
		"ucm_service_area_id": "ucm_well_service_area_id",
		"liq_id": "UniqueID",
		"acres": "ACRES"
	},
	skip_failed_create=True)


def load_irrigation_types():
	#models.IrrigationType.objects.create(name="Flood Basin", code="FB", efficiency=0.83)
	#models.IrrigationType.objects.create(name="Flood Furrow", code="FF", efficiency=0.73)
	models.IrrigationType.objects.create(name="Sprinkler - Solid Set", type_code="SI", efficiency=0.7)
	models.IrrigationType.objects.create(name="Drip - Surface", type_code="SD", efficiency=0.86)
	#models.IrrigationType.objects.create(name="Drip - Subsurface", code="SSD", efficiency=0.86)
	#models.IrrigationType.objects.create(name="Other", code="OT", efficiency=None)
	#models.IrrigationType.objects.create(name="Center Pivot", code="CP", efficiency=0.8)
	models.IrrigationType.objects.create(name="Sprinkler - Microsprinkler", type_code="MS", efficiency=0.81)
	models.IrrigationType.objects.create(name="Fallow", type_code="F", efficiency=0.01)  # discourage applying water to fallow fields


def load_crop_irrigation_types(crop_irrigation_type_file=settings.CROP_IRRIGATION_TYPE_DATA):
	generic_csv_import(models.CropIrrigationTypePrior, crop_irrigation_type_file, {
		"crop": {"Crop.liq_crop_id": "crop_code"},
		"irrigation_type": {"IrrigationType.type_code": "irrigation_type"},
		"probability": "probability",
	})

def load_wells(well_file=settings.WELL_DATA):
	generic_csv_import(models.Well, well_file, {
		"well_id": "Well_Nbr",
		"ucm_service_area_id": "ucm_well_service_area_id",
		"apn": "APN",
	})


def load_et_data(agtimestep_file=settings.ET_DATA):
	generic_csv_import(models.AgFieldTimestep, agtimestep_file, {
		"agfield": {"AgField.liq_id": "UniqueID"},
		"timestep": Constant(1),
		"consumptive_use": "et",
		"precip": "precip"
	})


def override_service_areas():
	"""
	For running an area-wide model, we need to have everything be in a single service area
	:return:
	"""
	models.AgField.objects.update(ucm_service_area_id="sa_global")
	models.Well.objects.update(ucm_service_area_id="sa_global")