"""Thin async wrapper around the Telegram Bot API.

No pydantic models for responses — Bot API 10.1 fields are still settling,
and we treat the JSON as plain dicts so unknown keys never crash us.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class BotAPIError(RuntimeError):
    def __init__(self, method: str, code: int, description: str, parameters: dict | None = None):
        super().__init__(f"{method} -> {code}: {description}")
        self.method = method
        self.code = code
        self.description = description
        self.parameters = parameters or {}


class BotAPINetworkError(RuntimeError):
    def __init__(self, method: str, cause: httpx.HTTPError):
        super().__init__(f"{method}: could not connect to Telegram: {cause!r}")
        self.method = method
        self.cause = cause


class BotAPI:
    """Thin async Bot API client.

    Pass files as ('field_name', (filename, bytes, content_type)) in `files=`.
    Everything else goes through `params=` as a JSON body.
    """

    def __init__(self, token: str, base: str = "https://api.telegram.org") -> None:
        self._token = token
        self._base = base
        self._url = f"{base}/bot{token}"
        self._file_url = f"{base}/file/bot{token}"
        # Telegram's API works over HTTP/1.1. Keeping HTTP/2 disabled also
        # avoids reusing a broken multiplexed connection after a long poll.
        self._client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def download_file(self, file_path: str) -> bytes:
        """Fetch a file via Telegram's file API (path from getFile)."""
        resp = await self._client.get(f"{self._file_url}/{file_path}")
        resp.raise_for_status()
        return resp.content

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        *,
        max_retries: int = 5,
    ) -> Any:
        """POST <method> and return the unwrapped `result` field."""
        url = f"{self._url}/{method}"
        attempt = 0
        backoff = 1.0
        while True:
            attempt += 1
            try:
                if files:
                    # multipart: scalars must be strings; nested data goes as JSON-encoded strings
                    data = {k: _to_form(v) for k, v in (params or {}).items()}
                    resp = await self._client.post(url, data=data, files=files)
                else:
                    resp = await self._client.post(url, json=params or {})
            except httpx.HTTPError as e:
                if attempt > max_retries:
                    raise BotAPINetworkError(method, e) from e
                log.warning(
                    "network error on %s (%r); retry in %.1fs",
                    method, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue

            payload = resp.json()
            if payload.get("ok"):
                return payload.get("result")

            code = payload.get("error_code", resp.status_code)
            desc = payload.get("description", "unknown error")
            params_field = payload.get("parameters") or {}

            if code == 429 and attempt <= max_retries:
                wait = float(params_field.get("retry_after", backoff))
                log.warning("429 on %s; sleeping %.1fs", method, wait)
                await asyncio.sleep(wait)
                continue
            if 500 <= code < 600 and attempt <= max_retries:
                log.warning("%d on %s; retry in %.1fs", code, method, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue

            raise BotAPIError(method, code, desc, params_field)


def _to_form(value: Any) -> str:
    """Coerce a JSON-ish value into a form field string."""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
