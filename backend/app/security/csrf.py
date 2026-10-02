"""
CSRF protection for cookie-authenticated requests.

Every state-changing request (anything but GET/HEAD/OPTIONS) must carry
`X-Requested-With: fetch`. A cross-site HTML form cannot set custom
headers, and with CORS disabled another origin's JavaScript cannot send
one either. This is enforced server-side for every route, including
login, independently of the SameSite cookie attribute.
"""

import json

from .. import config

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_HEADER = config.CSRF_HEADER.lower().encode()
_VALUE = config.CSRF_HEADER_VALUE.encode()


class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            headers = dict(scope.get("headers") or [])

            if headers.get(_HEADER, b"").lower() != _VALUE:
                body = json.dumps(
                    {"detail": "Missing or invalid request header."}
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)
