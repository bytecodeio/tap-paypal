import json
import sys

import singer
from singer import metadata
from singer.utils import strptime_to_utc

from tap_paypal.catalog import generate_catalog
from tap_paypal.client import PaypalClient
from tap_paypal.streams import AVAILABLE_STREAMS

LOGGER = singer.get_logger()


def discover(client):
    LOGGER.info('Starting Discovery..')
    streams = [
        stream_class(client) for _, stream_class in AVAILABLE_STREAMS.items()
    ]
    catalog = generate_catalog(streams)
    json.dump(catalog.to_dict(), sys.stdout, indent=2)

def sync_streams(client, config, catalog, state):
    LOGGER.info('Starting Sync..')
    selected_streams = catalog.get_selected_streams(state)

    streams = []
    stream_keys = []
    for catalog_entry in selected_streams:
        streams.append(catalog_entry)
        stream_keys.append(catalog_entry.stream)

    for catalog_entry in streams:
        stream_schema = catalog_entry.schema.to_dict()
        stream_metadata = metadata.to_map(catalog_entry.metadata)
        stream = AVAILABLE_STREAMS[catalog_entry.stream](client=client,
                                                         config=config,
                                                         stream_schema=stream_schema,
                                                         stream_metadata=stream_metadata,
                                                         state=state)
        LOGGER.info('Syncing stream: %s', catalog_entry.stream)

        stream.update_currently_syncing(stream.name)
        stream.write_state()
        stream.write_schema()

        bookmark_date = stream.get_bookmark(stream.name,
                                            config['start_date'])
        bookmark_dttm = strptime_to_utc(bookmark_date)

        record_count = stream.sync(client, startdate=bookmark_dttm)
        LOGGER.info('Synced: {}, total_records: {}'.format(stream.name, record_count))

        stream.update_currently_syncing(None)
        stream.write_state()
        LOGGER.info('Finished Sync..')


def main():
    parsed_args = singer.utils.parse_args(required_config_keys=[
        'client_id', 'client_secret', 'start_date'
    ])
    config = parsed_args.config

    try:
        client = PaypalClient(config)
        client.login()

        if parsed_args.discover:
            discover(client=client)
        elif parsed_args.catalog:
            sync_streams(client, config, parsed_args.catalog, parsed_args.state)
    finally:
        if client:
            if client.login_timer:
                client.login_timer.cancel()


if __name__ == '__main__':
    main()
