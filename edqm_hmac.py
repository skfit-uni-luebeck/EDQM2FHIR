import base64
import hashlib
import hmac
from typing import Callable


def edqm_hmac(api_key: str,
              message: str,
              truncate_last: int | None = 22,
              algorithm: Callable = hashlib.sha512) -> str:
    b_secret = bytes(api_key, encoding='utf-8')
    b_message = bytes(message, encoding='utf-8')
    digest = hmac.new(b_secret, b_message, algorithm).digest()
    signature = base64.b64encode(digest)
    sig_str = str(signature, encoding='utf-8')
    if truncate_last:
        return sig_str[(-truncate_last):]
    return sig_str


if __name__ == '__main__':
    # reference: https://www.jokecamp.com/blog/examples-of-creating-base64-hashes-using-hmac-sha256-in-different-languages/
    # signature: https://stackoverflow.com/a/72233146
    message = "GET&/standardterms/api/v1/languages&standardterms.edqm.eu&Mon, 07 Feb 2022 14:20:00 GMT"
    h = edqm_hmac(api_key="mysecret", message=message, truncate_last=22, algorithm=hashlib.sha512)
    assert h == "Z3DZ5tAtcmHGjeA4MUQw=="
    print(f"Signed '{message}' to: '{h}'")
