import os
from datetime import timedelta

import humps
import singer
import singer.metrics
from singer.utils import now, strptime_to_utc
#from tap_ms_teams.client import GraphVersion
from tap_paypal.transform import transform

LOGGER = singer.get_logger()
#TOP_API_PARAM_DEFAULT = 100

class Stream:
    # pylint: disable=too-many-instance-attributes,no-member
    def __init__(self, client=None, config=None, catalog=None, state=None):
        self.client = client
        self.config = config
        self.catalog = catalog
        self.state = state
        #self.top = TOP_API_PARAM_DEFAULT

    @staticmethod
    def get_abs_path(path):
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

    def load_schema(self):
        schema_path = self.get_abs_path('schemas')
        # pylint: disable=no-member
        return singer.utils.load_json('{}/{}.json'.format(
            schema_path, self.name))

    def write_schema(self):
        schema = self.load_schema()
        # pylint: disable=no-member
        return singer.write_schema(stream_name=self.name,
                                   schema=schema,
                                   key_properties=self.key_properties)

    def write_state(self):
        return singer.write_state(self.state)

    def update_bookmark(self, stream, value):
        if 'bookmarks' not in self.state:
            self.state['bookmarks'] = {}
        self.state['bookmarks'][stream] = value
        LOGGER.info('Stream: {} - Write state, bookmark value: {}'.format(
            stream, value))
        self.write_state()

    def get_bookmark(self, stream, default):
        # default only populated on initial sync
        if (self.state is None) or ('bookmarks' not in self.state):
            return default
        return self.state.get('bookmarks', {}).get(stream, default)

    # Currently syncing sets the stream currently being delivered in the state.
    # If the integration is interrupted, this state property is used to identify
    #  the starting point to continue from.
    # Reference: https://github.com/singer-io/singer-python/blob/master/singer/bookmarks.py#L41-L46
    def update_currently_syncing(self, stream_name):
        if (stream_name is None) and ('currently_syncing' in self.state):
            del self.state['currently_syncing']
        else:
            singer.set_currently_syncing(self.state, stream_name)
        singer.write_state(self.state)
        LOGGER.info('Stream: {} - Currently Syncing'.format(stream_name))

    # Returns max key and date time for all replication key data in record
    def max_from_replication_dates(self, record):
        date_times = {
            dt: strptime_to_utc(record[dt])
            for dt in self.valid_replication_keys if record[dt] is not None
        }
        max_key = max(date_times)
        return date_times[max_key]

    def remove_hours_local(self, dttm):
        new_dttm = dttm.replace(hour=0, minute=0, second=0, microsecond=0)
        return new_dttm

    # Round time based to day
    def round_times(self, start=None, end=None):
        start_rounded = None
        end_rounded = None
        # Round min_start, max_end to hours or dates
        start_rounded = self.remove_hours_local(start) - timedelta(days=1)
        end_rounded = self.remove_hours_local(end) + timedelta(days=1)
        return start_rounded, end_rounded

    # Determine absolute start and end times w/ attribution_window constraint
    # abs_start/end and window_start/end must be rounded to nearest hour or day (granularity)
    # Graph API enforces max history of 28 days
    def get_absolute_start_end_time(self, last_dttm, attribution_window):
        now_dttm = now()
        delta_days = (now_dttm - last_dttm).days
        if delta_days < attribution_window:
            start = now_dttm - timedelta(days=attribution_window)
        # 28 days NOT including current
        elif delta_days > 26:
            start = now_dttm - timedelta(26)
            LOGGER.info(
                'Start date exceeds max. Setting start date to {}'
                .format(start))
        else:
            start = last_dttm

        abs_start, abs_end = self.round_times(start, now_dttm)
        return abs_start, abs_end

    # pylint: disable=unused-argument
    def sync(self, client, startdate=None):
        resources = client.get_all_resources(self.version,
                                             self.endpoint,
                                             #top=self.top,
                                             orderby=self.orderby)

        yield humps.decamelize(resources)

class Transactions(Stream):
    name = 'transactions'
    version = 'v1'
    key_properties = ['transaction_id']
    replication_method = 'FULL_TABLE'
    replication_key = None
    endpoint = 'reporting/transactions'
    valid_replication_keys = []
    date_fields = []
    orderby = None



AVAILABLE_STREAMS = {
    "transactions": Transactions
}