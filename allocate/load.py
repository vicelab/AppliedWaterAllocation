import django.db.utils

from WellAllocation import settings
from allocate import models

import csv

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

	try:
		return sanitize_input(record[field])  # if it's not a foreign key, then this is simple
	except KeyError:
		return None


def generic_csv_import(model, csv_file, field_map, skip_failed_create=False):
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

	with open(csv_file, 'r') as csv_data:
		records = csv.DictReader(csv_data)
		for record in records:
			values = {model_key: get_value(record, field_map[model_key]) for model_key in field_map}

			try:
				model.objects.get_or_create(**values)
			except django.db.utils.IntegrityError:
				if skip_failed_create:
					pass
				else:
					raise

def load(crop_file=settings.CROP_DATA,
		 well_file=settings.WELL_DATA,
		 production_files=settings.PRODUCTION_DATA_FILES,
		 field_file=settings.FIELD_DATA,
		 agtimestep_file=settings.ET_DATA,
		 pipe_file=settings.PIPE_FILE):

	load_crops(crop_file)
	load_wells(well_file)
	load_fields(field_file)

	load_et_data(agtimestep_file)

	generic_csv_import(models.Pipe, pipe_file, {
		"well": {"Well.well_id": "Well_Nbr"},
		"agfield": {"AgField.liq_id": "UniqueID"},
		"distance": "NEAR_DIST",
	})

	for production_file in production_files:
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
		"crop": {"Crop.liq_group_code": "CLASS2"},
		"ucm_service_area_id": "ucm_well_service_area_id",
		"liq_id": "UniqueID",
	},
	skip_failed_create=True)



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