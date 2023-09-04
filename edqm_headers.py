from datetime import datetime
from typing import Dict
from enum import auto as enum_auto
from strenum import StrEnum
from edqm_hmac import edqm_hmac
import logging


class HttpMethod(StrEnum):
    GET = enum_auto()
    HEAD = enum_auto()
    POST = enum_auto()
    PUT = enum_auto()
    DELETE = enum_auto()
    CONNECT = enum_auto()
    OPTIONS = enum_auto()
    TRACE = enum_auto()
    PATCH = enum_auto()


class HeaderBuilder:
    username: str
    api_key: str
    host: str

    def __init__(self, username, api_key):
        self.username = username
        self.api_key = api_key

    @staticmethod
    def __generate_date_header() -> str:
        dt = datetime.utcnow()
        formatted = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        logging.debug("Formatted date header: %s", formatted)
        return formatted

    def __generate_x_stapi_auth(self, request_url, verb, date, host):
        string_to_sign = f"{verb}&{request_url}&{host}&{date}"
        logging.debug("Signing: \"%s\"", string_to_sign)
        signed = edqm_hmac(self.api_key, string_to_sign)
        header = f"{self.username}|{signed}"
        logging.debug("Generated header: \"%s\"", header)
        return header

    def generate_headers(self, request_url: str, verb: HttpMethod, host: str) -> Dict[str, str]:
        date = self.__generate_date_header()
        headers = {
            "Date": date,
            "X-STAPI-KEY": self.__generate_x_stapi_auth(request_url, verb, date, host),
            "Accept": "application/json"
        }

        logging.debug("Generated headers: %s", headers)
        return headers


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    builder = HeaderBuilder("example@exampe.org", "mysecret")
    generated_headers = builder.generate_headers("/standardterms/api/v1/languages", HttpMethod.GET, "standardterms.edqm.eu")
    print(generated_headers)
