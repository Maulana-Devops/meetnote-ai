"""Logging terstruktur dan request ID untuk operasional on-prem.

Semua log baris tunggal JSON agar mudah dikonsumsi tooling tanpa mengubah
format pesan yang sudah ada di modul lain. Request ID juga dikirim balik lewat
header ``X-Request-ID`` supaya log backend bisa dicocokkan dengan laporan UI.
"""

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Formatter JSON minimal dengan field yang stabil."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Pasang formatter JSON pada root logger sekali saat startup."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_meetnote_json", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._meetnote_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class RequestIDMiddleware:
    """Buat/terima request ID dan menambahkannya ke header respons."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                incoming = value.decode("latin-1").strip()
                break
        request_id = incoming or uuid.uuid4().hex

        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        logger = logging.getLogger("meetnote.request")
        try:
            await self.app(scope, receive, send_with_request_id)
            logger.info(
                "request_finished method=%s path=%s",
                scope.get("method", "-"),
                scope.get("path", "-"),
            )
        finally:
            request_id_var.reset(token)
