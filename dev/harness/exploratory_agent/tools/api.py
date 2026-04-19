"""Direct-HTTP tool for API-level exploration.

Bypasses the browser entirely so the agent can probe endpoints without
running the full wizard flow (useful for fuzzing validators, checking
CSRF enforcement, sending malformed JSON, etc.).

Uses httpx. Short timeout (5 s). Body output truncated at 8 KB.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from . import register

_BODY_MAX = 8_192


class ApiTools:
    def __init__(self, base_url: str, csrf_token_getter: Callable[[], Optional[str]]) -> None:
        self.base_url = base_url.rstrip("/")
        self._get_csrf = csrf_token_getter
        self._client = httpx.Client(timeout=5.0)

    def api_request_sync(
        self,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        json: Optional[dict] = None,
        raw_body: Optional[str] = None,
        csrf: str = "auto",
    ) -> dict:
        hdrs = dict(headers or {})
        if csrf == "auto":
            tok = self._get_csrf()
            if tok is not None:
                hdrs["X-CSRF-Token"] = tok
        elif csrf == "skip":
            pass
        else:
            hdrs["X-CSRF-Token"] = csrf

        url = self.base_url + path
        try:
            if raw_body is not None:
                resp = self._client.request(method, url, headers=hdrs, content=raw_body)
            else:
                resp = self._client.request(method, url, headers=hdrs, json=json)
        except httpx.TimeoutException:
            return {"status": 0, "headers": {}, "body_text": "", "error": "timeout"}
        except httpx.HTTPError as e:
            return {"status": 0, "headers": {}, "body_text": "", "error": str(e)}

        body_text = resp.text[:_BODY_MAX]
        out: dict[str, Any] = {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body_text": body_text,
        }
        try:
            out["body_json"] = resp.json()
        except ValueError:
            pass
        return out


_API_SCHEMAS: list[dict] = [
    {
        "name": "api_request",
        "description": (
            "Send a raw HTTP request to the wizard's API, bypassing the "
            "browser. Use this to fuzz endpoint validators, test CSRF "
            "enforcement, or send malformed JSON. csrf=\"auto\" attaches "
            "the current meta-tag token; \"skip\" omits the header "
            "entirely; any other string is sent as the literal token."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                "path": {"type": "string"},
                "headers": {"type": "object"},
                "json": {"type": "object"},
                "raw_body": {"type": "string"},
                "csrf": {"type": "string"},
            },
            "required": ["method", "path"],
        },
    },
]


def _factory(ctx):
    return ctx.api.api_request_sync


register("api_request", _factory, _API_SCHEMAS[0])

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_API_SCHEMAS)
