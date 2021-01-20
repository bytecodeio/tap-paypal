import os
from datetime import timedelta

import singer
import singer.metrics
from singer import Transformer
from singer.utils import now, strftime, strptime_to_utc

LOGGER = singer.get_logger()
DATE_WINDOW_SIZE = 1
DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
INVOICE_DATETIME_FMT = "%Y-%m-%d"


class Stream:
    # pylint: disable=too-many-instance-attributes,no-member
    def __init__(self,
                 client=None,
                 config=None,
                 stream_schema=None,
                 stream_metadata=None,
                 state=None):
        self.client = client
        self.config = config
        self.stream_schema = stream_schema
        self.stream_metadata = stream_metadata
        self.state = state

    @staticmethod
    def get_abs_path(path):
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)

    def load_schema(self):
        schema_path = self.get_abs_path('schemas')
        schema = singer.utils.load_json('{}/{}.json'.format(
            schema_path, self.name))
        if 'definitions' in schema:
            resolved_schema = singer.resolve_schema_references(
                schema, schema['definitions'])
            del resolved_schema['definitions']
        else:
            resolved_schema = schema
        return resolved_schema

    def write_schema(self):
        schema = self.load_schema()
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

    @staticmethod
    def remove_hours_local(dttm):
        new_dttm = dttm.replace(hour=0, minute=0, second=0, microsecond=0)
        return new_dttm

    # Round time based to day
    def round_times(self, start=None, end=None):
        start_rounded = None
        end_rounded = None
        # Round min_start, max_end to hours or dates
        start_rounded = self.remove_hours_local(start) - timedelta(days=1)
        end_rounded = self.remove_hours_local(end)
        return start_rounded, end_rounded

    # Determine absolute start and end times w/ attribution_window constraint
    # abs_start/end and window_start/end must be rounded to nearest hour or day (granularity)
    # Graph API enforces max history of 28 days
    def get_absolute_start_end_time(self, last_dttm, lookback=0):
        now_dttm = now()
        abs_start, abs_end = self.round_times(
            last_dttm - timedelta(days=lookback), now_dttm)
        return abs_start, abs_end

    def sync(self, client, **kwargs):
        pass

    # pylint: disable=unused-argument
    def transform(self, data, **kwargs):
        LOGGER.info('No transform for stream: %s', self.name)
        return data


class Transactions(Stream):
    name = 'transactions'
    version = 'v1'
    api_method = 'GET'
    data_key = 'transaction_details'
    key_properties = ['transaction_info_transaction_id']
    replication_method = 'INCREMENTAL'
    replication_key = 'transaction_info_transaction_updated_date'
    endpoint = 'reporting/transactions'
    valid_replication_keys = ['transaction_info_transaction_updated_date']
    account_id = 'account_number'

    def transform(self, data, **kwargs):
        account_id = kwargs['account_id']
        last_refreshed_datetime = kwargs['last_refreshed_datetime']
        response_data = {}
        for field, obj in data.items():
            for key, value in obj.items():
                response_data[field + "_" + key] = value
            response_data['account_id'] = account_id
            response_data['last_refreshed_datetime'] = last_refreshed_datetime
        return response_data

    @staticmethod
    def build_params(start_date, end_date):
        return {
            "start_date": start_date,
            "end_date": end_date,
            "fields": "all",
            "balance_affecting_records_only":"N"
        }

    def sync(self, client, **kwargs):
        startdate = kwargs['startdate']
        start, end = self.get_absolute_start_end_time(
            startdate, lookback=int(self.config.get('lookback')))
        next_window = start + timedelta(days=DATE_WINDOW_SIZE)
        max_bookmark_dttm = start

        with singer.metrics.record_counter(endpoint=self.name) as counter:
            while start != end:
                start_str = start.strftime(DATETIME_FMT)
                next_window_str = next_window.strftime(DATETIME_FMT)
                params = self.build_params(start_date=start_str,
                                           end_date=next_window_str)
                results = client.get_paginated_data(self.api_method,
                                                    self.version,
                                                    self.endpoint,
                                                    data_key=self.data_key,
                                                    params=params)

                max_bookmark_value = strftime(max_bookmark_dttm)
                with Transformer(
                        integer_datetime_fmt="no-integer-datetime-parsing"
                ) as transformer:
                    for page in results:
                        for record in page.get(self.data_key):
                            transformed_record = self.transform(
                                record,
                                account_id=page['account_number'],
                                last_refreshed_datetime=page[
                                    'last_refreshed_datetime'])

                            record_timestamp = strptime_to_utc(
                                transformed_record[self.replication_key])
                            if record_timestamp > max_bookmark_dttm:
                                max_bookmark_value = strftime(record_timestamp)

                            if record_timestamp > start:
                                singer.write_record(
                                    stream_name=self.name,
                                    record=transformer.transform(
                                        data=transformed_record,
                                        schema=self.stream_schema,
                                        metadata=self.stream_metadata),
                                    time_extracted=singer.utils.now())
                                counter.increment()
                start = start + timedelta(days=DATE_WINDOW_SIZE)
                next_window = next_window + timedelta(days=DATE_WINDOW_SIZE)
                self.update_bookmark(self.name, max_bookmark_value)
            return counter.value


class Balances(Stream):
    name = 'balances'
    version = 'v1'
    api_method = 'GET'
    key_properties = ['account_id', 'as_of_time']
    replication_method = 'INCREMENTAL'
    replication_key = 'as_of_time'
    endpoint = 'reporting/balances'
    valid_replication_keys = ['as_of_time']

    @staticmethod
    def build_params(start_date):
        return {"as_of_time": start_date}

    def sync(self, client, **kwargs):
        startdate = kwargs['startdate']
        start, end = self.get_absolute_start_end_time(
            startdate, lookback=int(self.config.get('lookback')))

        max_bookmark_dttm = start

        with singer.metrics.record_counter(endpoint=self.name) as counter:
            while start != end:
                start_str = start.strftime(DATETIME_FMT)
                params = self.build_params(start_date=start_str)
                results = client.get_balances(self.version,
                                              self.endpoint,
                                              params=params)

                max_bookmark_value = strftime(max_bookmark_dttm)
                with Transformer(
                        integer_datetime_fmt="no-integer-datetime-parsing"
                ) as transformer:
                    record_timestamp = strptime_to_utc(
                        results[self.replication_key])
                    if record_timestamp > max_bookmark_dttm:
                        max_bookmark_value = strftime(record_timestamp)

                    singer.write_record(stream_name=self.name,
                                        record=transformer.transform(
                                            data=results,
                                            schema=self.stream_schema,
                                            metadata=self.stream_metadata),
                                        time_extracted=singer.utils.now())
                    counter.increment()
                start = start + timedelta(days=DATE_WINDOW_SIZE)
                self.update_bookmark(self.name, max_bookmark_value)
            return counter.value


class Invoices(Stream):
    name = 'invoices'
    version = 'v2'
    api_method = 'POST'
    key_properties = ['id']
    replication_method = 'INCREMENTAL'
    replication_key = 'detail_invoice_date'
    endpoint = 'invoicing/search-invoices'
    account_id = 'account_id'
    data_key = 'items'

    @staticmethod
    def build_body(start_date, end_date):
        return {"invoice_date_range": {"start": start_date, "end": end_date}}

    @staticmethod
    def build_params():
        return {"total_required": "true"}

    def sync(self, client, **kwargs):
        startdate = kwargs['startdate']
        start, end = self.get_absolute_start_end_time(
            startdate, lookback=int(self.config.get('lookback')))

        max_bookmark_dttm = start

        with singer.metrics.record_counter(endpoint=self.name) as counter:
            while start != end:
                start_str = start.strftime(INVOICE_DATETIME_FMT)
                next_window_str = start_str
                results = client.get_paginated_data(self.api_method,
                                                    self.version,
                                                    self.endpoint,
                                                    data_key=self.data_key,
                                                    params=self.build_params(),
                                                    body=self.build_body(
                                                        start_str,
                                                        next_window_str))

                max_bookmark_value = strftime(max_bookmark_dttm)
                with Transformer(
                        integer_datetime_fmt="no-integer-datetime-parsing"
                ) as transformer:
                    for page in results:
                        for record in page.get(self.data_key):
                            transformed_record = self.transform(record)

                            record_timestamp = strptime_to_utc(
                                transformed_record[self.replication_key])
                            if record_timestamp > max_bookmark_dttm:
                                max_bookmark_value = strftime(record_timestamp)

                            singer.write_record(
                                stream_name=self.name,
                                record=transformer.transform(
                                    data=transformed_record,
                                    schema=self.stream_schema,
                                    metadata=self.stream_metadata),
                                time_extracted=singer.utils.now())
                            counter.increment()
                start = start + timedelta(days=DATE_WINDOW_SIZE)
                self.update_bookmark(self.name, max_bookmark_value)
            return counter.value

    def transform(self, data, **kwargs):
        transformed = data
        for key in data['detail']:
            denested_key = 'detail_' + key
            transformed[denested_key] = data['detail'][key]
        del transformed['detail']
        return transformed


AVAILABLE_STREAMS = {
    "transactions": Transactions,
    "balances": Balances,
    "invoices": Invoices
}
