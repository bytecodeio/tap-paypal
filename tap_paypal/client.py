import threading
import urllib
from enum import Enum

import backoff
import requests
import singer
import singer.metrics

LOGGER = singer.get_logger()  # noqa

TOKEN_URL = "https://api.paypal.com/v1/oauth2/token"
BASE_URL = 'https://api.paypal.com'
TOKEN_EXPIRATION_PERIOD = 3599
TOP_API_PARAM_DEFAULT = 500


class GraphVersion(Enum):
    BETA = 'beta'
    V1 = 'v1.0'


class Server5xxError(Exception):
    pass


class Server42xRateLimitError(Exception):
    pass


class PaypalClient:

    MAX_TRIES = 5

    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.login_timer = None
        self.access_token = None
        self.client_secret = None
        self.client_id = None

    @staticmethod
    def build_url(baseurl, version, path):
        # Returns a list in the structure of urlparse.ParseResult
        url_parts = list(urllib.parse.urlparse(baseurl))
        url_parts[2] = version + '/' + path
        return urllib.parse.unquote_plus(urllib.parse.urlunparse(url_parts))

    def login(self):
        LOGGER.info("Refreshing token")
        self.client_id = self.config.get('client_id')
        self.client_secret = self.config.get('client_secret')

        try:
            data = {'grant_type': 'client_credentials'}

            with singer.http_request_timer('POST get access token'):
                result = self.make_request(method='POST',
                                           url=TOKEN_URL,
                                           data=data,
                                           auth=(self.client_id,
                                                 self.client_secret))

            self.access_token = result['access_token']
            #self.access_token = result.get('access_token')

        finally:
            self.login_timer = threading.Timer(TOKEN_EXPIRATION_PERIOD,
                                               self.login)
            self.login_timer.start()

    def request(self, endpoint, params=None, **kwargs):
        pass

    @staticmethod
    def get_next_link(links):
        for link in links:
            if link['rel'] == 'next':
                return link['href']
        return None

    def get_paginated_data(self,
                           method,
                           version,
                           endpoint,
                           params,
                           data_key,
                           body=None):
        next_url = self.build_url(BASE_URL, version, endpoint)

        while next_url:
            LOGGER.info("Making request {} {} {} {}".format(
                method, next_url, params, body))
            result = self.make_request(method,
                                       url=next_url,
                                       params=params,
                                       json=body)

            if data_key in result and len(result[data_key]) > 0:
                yield result
            links = result.get('links', {})
            next_url = self.get_next_link(links)

    def get_balances(self, version, endpoint, params):
        url = self.build_url(BASE_URL, version, endpoint)
        LOGGER.info("Making request GET {}".format(url))
        return self.make_request('GET', url=url, params=params)

    def get_transactions(self, version, endpoint, params):
        next_url = self.build_url(BASE_URL, version, endpoint)

        while next_url:
            LOGGER.info("Making request GET {}".format(next_url))
            result = self.make_request('GET', url=next_url, params=params)

            if result['total_items'] > 0:
                yield result
            links = result.get('links', {})
            next_url = self.get_next_link(links)

    @backoff.on_exception(
        backoff.expo,
        (Server5xxError, ConnectionError, Server42xRateLimitError),
        max_time=900,
        base=3)
    def make_request(self, method, url=None, **kwargs):

        headers = {'Authorization': 'Bearer {}'.format(self.access_token)}

        if self.config.get('user_agent'):
            headers['User-Agent'] = self.config['user_agent']

        if method == "GET":
            LOGGER.info("Making {} request to {} with params: {}".format(
                method, url, kwargs['params']))
            response = self.session.get(url,
                                        headers=headers,
                                        params=kwargs['params'],
                                        allow_redirects=True)
        elif method == "POST":
            LOGGER.info("Making {} request to {}".format(method, url))
            response = self.session.post(url, headers=headers, **kwargs)
        else:
            raise Exception("Unsupported HTTP method")

        LOGGER.info("Received code: {}".format(response.status_code))

        if response.status_code == 401:
            LOGGER.info(
                "Received unauthorized error code, retrying: {}".format(
                    response.text))
            self.login()
        elif response.status_code == 429:
            LOGGER.info("Received rate limit response: {}".format(
                response.headers))
            raise Server42xRateLimitError()
        elif response.status_code >= 500:
            raise Server5xxError()

        if response.status_code not in [200, 201, 202]:
            raise RuntimeError(response.text)

        return response.json()
