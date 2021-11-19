import logging
from django.core.management.base import BaseCommand

from allocate import load

log = logging.getLogger(__name__)


class Command(BaseCommand):
	help = 'Loads data into the model'

	#def add_arguments(self, parser):
	#	parser.add_argument('--remote_api_address', type=str, dest="remote_api_address", default=None,)
	#	parser.add_argument('--remote_area_id', type=int, dest="remote_area_id", default=None,)
	#	parser.add_argument('--remote_token', type=str, dest="remote_token", default=None,)
	#	parser.add_argument('--local_area_id', type=int, dest="local_area_id", default=None,)
	#	parser.add_argument('--user_id_map', nargs='*', type=str, dest="user_id_map", default=None,)
	#	parser.add_argument('--system_user_id', type=int, dest="system_user_id", default=None,)
	#	parser.add_argument('--ignore_run_ids', nargs='*', type=int, dest="ignore_run_ids", help="A space separated list of run IDs on the remote server to ignore - recommended to include the base case here since it'll already be loaded", default=None,)
	#	parser.add_argument('--include_run_ids', nargs='*', type=int, dest="include_run_ids", help="A space separated list of run IDs on the remote server to include - defaults to including all runs if this is not specified. When specified, only the specified runs will be migrated", default=None,)
	#	parser.add_argument('--dry_run', type=bool, dest="dry_run", required=False)

	def handle(self, *args, **options):
		load.load()