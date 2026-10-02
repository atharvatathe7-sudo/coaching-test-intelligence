"""
Request body size limits, enforced while the body is being received.

A Content-Length above the limit is rejected immediately, before any of
the body is read. Bodies without a Content-Length (chunked uploads) are
counted as they stream in and rejected as soon as they exceed the limit,
so an oversized upload is never buffered or parsed in full.

The reverse proxy (deploy/Caddyfile) applies the same limit in front of
the application.
"""

import json

from .. import config


class _TooLarge(Exception):
    pass


def _limit_for(path: str) -> int:
    if path.startswith("/api/imports/"):
        return config.MAX_IMPORT_REQUEST_BYTES
    return config.MAX_REQUEST_BYTES


async def _reject(send) -> None:
    body = json.dumps(
        {"detail": "The request is too large. CSV files may be up to "
                   f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for(scope["path"])
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")

        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                await _reject(send)
                return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge()
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send)
