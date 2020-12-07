from singer import metadata
from singer.catalog import Catalog, CatalogEntry, Schema


def generate_catalog(streams):

    catalog = Catalog([])

    for stream in streams:
        schema = stream.load_schema()

        mdata = metadata.new()
        mdata = metadata.get_standard_metadata(
            schema=schema,
            key_properties=stream.key_properties,
            valid_replication_keys=stream.replication_key or None,
            replication_method=stream.replication_method or None
        )

        catalog.streams.append(CatalogEntry(
            stream=stream.name,
            tap_stream_id=stream.name,
            key_properties=stream.key_properties,
            schema=Schema.from_dict(schema),
            metadata=mdata
        ))
        # catalog_entry = {
        #     'stream': stream.name,
        #     'tap_stream_id': stream.name,
        #     'schema': schema,
        #     'metadata': singer.metadata.get_standard_metadata(
        #         schema=schema,
        #         key_properties=stream.key_properties,
        #         valid_replication_keys=stream.valid_replication_keys,
        #         replication_method=stream.replication_method)
        # }
        # catalog['streams'].append(catalog_entry)

    return catalog
