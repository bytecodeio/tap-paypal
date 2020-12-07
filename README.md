# tap-paypal

This is a [Singer](https://singer.io) tap that produces JSON-formatted data
following the [Singer
spec](https://github.com/singer-io/getting-started/blob/master/SPEC.md).

This tap:

- Pulls raw data from the [Paypal API](https://developer.paypal.com/docs/api/overview/)
- Extracts the following resources:
  - [Transactions](https://developer.paypal.com/docs/api/transaction-search/v1/#transactions_get)
  - [Balances](https://developer.paypal.com/docs/api/transaction-search/v1/#balances_get)
  - [Invoices](https://developer.paypal.com/docs/api/invoicing/v2/#search-invoices)
- Outputs the schema for each resource
- Incrementally pulls data based on the input state

## Streams
[**transactions (GET v1)**](https://developer.paypal.com/docs/api/transaction-search/v1/#transactions_get)
- Endpoint: v1/reporting/transactions
- Primary keys: `transaction_info_transasction_id`
- Replication strategy: Incremental (query all by day, filter results)
  - Bookmark: transaction_info_transaction_updated_date (date-time)
- Transformations: De-nesting for `transaction_info`, `payer_info`, `shipping_info`, `cart_info` objects. `account_id` and `last_refreshed_datetime` injected to each record.
- Lookback window provided to account for API not provided any last modified field.

[**balances (GET v1)**](https://developer.paypal.com/docs/api/transaction-search/v1/#balances_get)
- Endpoint: reporting/balances
- Primary keys: 'account_id', 'as_of_time'
- Replication strategy: Incremental (query all by day, filter results)
  - Bookmark query field: as_of_time
  - Bookmark: as_of_time (date-time)
- Lookback window provided to account for API not provided any last modified field.

[**invoices (POST v2)**](https://developer.paypal.com/docs/api/invoicing/v2/#search-invoices)
- Endpoint: invoicing/search-invoicess
- Primary keys: id
- Replication strategy: Incremental (query all by day, filter results)
  - Bookmark query field: `invoice_date_range`
  - Bookmark: detail_invoice_date (date-time)
- Transformations: De-nest `detail` object.
- Lookback window provided to account for API not provided any last modified field.

## Quick Start

1. Install

    Clone this repository, and then install using setup.py. We recommend using a virtualenv:

    ```bash
    > virtualenv -p python3 venv
    > source venv/bin/activate
    > python setup.py install
    OR
    > cd .../tap-paypal
    > pip install .
    ```
2. Dependent libraries
    The following dependent libraries were installed.
    ```bash
    > pip install singer-python
    > pip install singer-tools
    > pip install target-stitch
    > pip install target-json
    
    ```
    - [singer-tools](https://github.com/singer-io/singer-tools)
    - [target-stitch](https://github.com/singer-io/target-stitch)

3. Create your tap's `config.json` file.

    ```json
    {
        "client_id": "**CLIENT_ID**",
        "client_secret": "**CLIENT_SECRET**",
        "start_date": "2020-11-17T00:00:00Z",
        "lookback": "0"
        "user_agent": "tap-paypal <api_user_email@your_company.com>"
    }
    ```
    
    Optionally, also create a `state.json` file. `currently_syncing` is an optional attribute used for identifying the last object to be synced in case the job is interrupted mid-stream. The next run would begin where the last job left off.

    ```json
    {
    "bookmarks": {
        "balances": "2020-12-06T00:00:00.000000Z",
        "invoices": "2020-12-06T00:00:00.000000Z",
        "transactions": "2020-12-06T22:30:08.000000Z"
        }
    }
    ```

4. Run the Tap in Discovery Mode
    This creates a catalog.json for selecting objects/fields to integrate:
    ```bash
    tap-paypal --config config.json --discover > catalog.json
    ```
   See the Singer docs on discovery mode
   [here](https://github.com/singer-io/getting-started/blob/master/docs/DISCOVERY_MODE.md#discovery-mode).

5. Run the Tap in Sync Mode (with catalog) and [write out to state file](https://github.com/singer-io/getting-started/blob/master/docs/RUNNING_AND_DEVELOPING.md#running-a-singer-tap-with-a-singer-target)

    For Sync mode:
    ```bash
    > tap-paypal --config tap_config.json --catalog catalog.json > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    To load to json files to verify outputs:
    ```bash
    > tap-paypal --config tap_config.json --catalog catalog.json | target-json > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    To pseudo-load to [Stitch Import API](https://github.com/singer-io/target-stitch) with dry run:
    ```bash
    > tap-paypal --config tap_config.json --catalog catalog.json | target-stitch --config target_config.json --dry-run > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```

6. Test the Tap
    
    While developing the Mambu tap, the following utilities were run in accordance with Singer.io best practices:
    Pylint to improve [code quality](https://github.com/singer-io/getting-started/blob/master/docs/BEST_PRACTICES.md#code-quality):
    ```bash
    > pylint tap_mambu -d missing-docstring -d logging-format-interpolation -d too-many-locals -d too-many-arguments
    ```
    Pylint test resulted in the following score:
    ```bash
    Your code has been rated at 9.87/10.
    ```

    To [check the tap](https://github.com/singer-io/singer-tools#singer-check-tap) and verify working:
    ```bash
    > tap-paypal --config tap_config.json --catalog catalog.json | singer-check-tap > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    Check tap resulted in the following:
    ```bash
    Checking stdin for valid Singer-formatted data
    The output is valid.
    It contained 109 messages for 3 streams.

        6 schema messages
        28 record messages
        75 state messages

    Details by stream:
    +--------------+---------+---------+
    | stream       | records | schemas |
    +--------------+---------+---------+
    | transactions | 5       | 1       |
    | balances     | 21      | 1       |
    | invoices     | 2       | 1       |
    +--------------+---------+---------+
    ```
---

Copyright &copy; 2019 Stitch
