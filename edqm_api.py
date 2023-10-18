import logging
from typing import Any, List, Dict

import requests

from edqm_headers import HeaderBuilder, HttpMethod


class EdqmApi:
    header_builder: HeaderBuilder
    session = requests.Session()

    def __init__(self, username, api_key):
        self.header_builder = HeaderBuilder(username, api_key)

    def execute_request(self,
                        url: str,
                        method: HttpMethod = HttpMethod.GET) -> Dict[str, List] | None:
        request = self.__build_request(method=method, url=url)
        rx = self.session.send(request)
        if rx.status_code != 200:
            logging.warning("Status code %d; request: %s", rx.status_code, rx)
            return None
        else:
            j = rx.json()
            return j

    def __build_request(self,
                        method: HttpMethod,
                        url: str,
                        host: str = "standardterms.edqm.eu",
                        protocol: str = "https",
                        url_prefix: str | None = "/standardterms/api/v1"):
        rel_url = f"/{url_prefix.strip('/')}/{url.lstrip('/')}"  # the URL reletive to the host, anchored to /
        request_url = f"{protocol}://{host}/{rel_url.lstrip('/')}"  # the full URL of the service
        logging.debug("Requesting: %s %s", method, request_url)
        headers = self.header_builder.generate_headers(rel_url, method, host=host)
        prepped = requests.Request(method=str(method), url=request_url, headers=headers).prepare()
        return prepped
