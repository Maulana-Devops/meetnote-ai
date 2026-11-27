"""Pembatas ukuran request sebelum multipart diproses.

Pemeriksaan di handler upload tetap dipertahankan sebagai pertahanan kedua,
tetapi Starlette/python-multipart membaca body lebih dulu. Middleware ini
menolak ``Content-Length`` yang jelas melebihi batas agar body besar tidak
dispool ke disk host terlebih dahulu.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import settings

# Ruang untuk boundary, header field, dan form fields lain.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
UPLOAD_PATH_SUFFIX = "/recording"

_REJECT_BODY = b'{"detail":"Ukuran permintaan melebihi batas."}'


def upload_request_limit_bytes() -> int:
    """Batas total body multipart yang masih masuk akal."""
    return settings.MAX_AUDIO_FILE_BYTES + MULTIPART_OVERHEAD_BYTES


class UploadSizeLimitMiddleware:
    """Tolak POST upload dengan Content-Length di atas batas sebelum parsing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not str(scope.get("path", "")).endswith(UPLOAD_PATH_SUFFIX)
        ):
            await self.app(scope, receive, send)
            return

        declared = self._declared_length(scope)
        limit = upload_request_limit_bytes()
        if declared is not None and declared > limit:
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    async def _reject(send: Send) -> None:
        message: Message = {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_REJECT_BODY)).encode("ascii")),
            ],
        }
        await send(message)
        await send({"type": "http.response.body", "body": _REJECT_BODY})
