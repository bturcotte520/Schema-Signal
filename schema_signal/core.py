"""HTTP, response validation, and redacted evidence. No network at import time."""

from __future__ import annotations

import copy
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

API = "https://openrouter.ai/api/v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": "Name of the purchased item"},
        "quantity": {"type": "integer", "description": "Number of items purchased"},
    },
    "required": ["item", "quantity"],
    "additionalProperties": False,
}
PROMPT = (
    'Extract the purchase from this synthetic sentence: "I bought 3 blue notebooks." '
    'Return only a JSON object with item (string) and quantity (integer).'
)


def make_request(model: str, required: bool, provider: str | None = None,
                 max_tokens: int = 256) -> dict:
    """The two requests differ in exactly one boolean."""
    preferences: dict[str, Any] = {"require_parameters": required}
    if provider:
        preferences.update(only=[provider], allow_fallbacks=False)
    return {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "stream": False,
        "provider": preferences,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "purchase", "strict": True,
                            "schema": copy.deepcopy(SCHEMA)},
        },
    }


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def strict_json(value: str | bytes):
    def reject_constant(_):
        raise ValueError("Non-finite JSON number")
    return json.loads(value, parse_constant=reject_constant,
                      object_pairs_hook=_no_duplicates)


def scrub(value: Any, secret: str = "") -> Any:
    """Defense in depth. Raw responses/errors never enter exported artifacts."""
    if isinstance(value, dict):
        return {str(scrub(key, secret)): scrub(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, secret) for item in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"sk-or-[A-Za-z0-9_-]+", "[REDACTED]", value)
        value = re.sub(r"(?i)bearer\s+[^\s\"']+", "Bearer [REDACTED]", value)
    return value


def label(value: Any) -> str | None:
    # Model/provider labels are operational metadata, never rendered as HTML.
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:/ ()-]{1,160}", value):
        return value
    return None


def numeric(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass
class Reply:
    status: int | None
    body: bytes = b""
    elapsed_ms: int = 0
    transport_error: str | None = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer credential to another URL.
        return None


class Client:
    def __init__(self, key: str, timeout: float = 30):
        self.key = key
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def send(self, path: str, payload: dict | None = None) -> Reply:
        if path != "/chat/completions" and not re.fullmatch(
            r"/generation\?id=gen-[A-Za-z0-9-]{1,124}", path
        ):
            raise ValueError("Only the fixed OpenRouter endpoints are allowed")
        request = urllib.request.Request(
            API + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json",
                     "User-Agent": "openrouter-schema-signal/0.1.0"},
            method="POST" if payload is not None else "GET",
        )
        start = time.monotonic()
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return Reply(response.code, elapsed_ms=self._elapsed(start),
                                 transport_error="response_too_large")
                return Reply(response.code, raw, self._elapsed(start))
        except (TimeoutError, OSError, urllib.error.URLError):
            # Exception text can include credentials or response content.
            return Reply(None, elapsed_ms=self._elapsed(start),
                         transport_error="network_or_timeout")

    @staticmethod
    def _elapsed(start: float) -> int:
        return round((time.monotonic() - start) * 1000)


def analyze(reply: Reply) -> tuple[dict, str | None]:
    """Return only allowlisted diagnostics, plus a private ID for metadata lookup."""
    result: dict[str, Any] = {
        "http_status": reply.status,
        "elapsed_ms": reply.elapsed_ms,
        "status": "unknown",
        "routing": {"provider": None, "source": "unavailable", "model": None},
        "validation": {"json_valid": None, "schema_valid": None},
    }
    if reply.transport_error:
        result["status"] = reply.transport_error
        return result, None
    try:
        body = strict_json(reply.body)
    except (ValueError, UnicodeError, RecursionError):
        result["status"] = "http_error" if not (200 <= (reply.status or 0) < 300) else "invalid_api_json"
        return result, None
    if not isinstance(body, dict):
        result["status"] = "http_error" if not (200 <= (reply.status or 0) < 300) else "malformed_response"
        return result, None
    routing = result["routing"]
    routing["model"] = label(body.get("model"))
    routing["provider"] = label(body.get("provider"))
    if routing["provider"]:
        routing["source"] = "chat_response.provider"
    generation_id = body.get("id")
    if not isinstance(generation_id, str) or not re.fullmatch(r"gen-[A-Za-z0-9-]{1,124}", generation_id):
        generation_id = None
    result["generation_id_available"] = generation_id is not None
    if not (200 <= (reply.status or 0) < 300) or "error" in body:
        result["status"] = "http_error" if not (200 <= (reply.status or 0) < 300) else "upstream_error"
        # Only numeric error codes, never provider error messages or metadata.raw.
        error = body.get("error")
        if isinstance(error, dict) and type(error.get("code")) is int:
            result["api_error_code"] = error["code"]
        return result, generation_id
    usage = body.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {k: usage[k] for k in
                           ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
                           if numeric(usage.get(k))}
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        result["status"] = "malformed_response"
        return result, generation_id
    choice = choices[0]
    reason = label(choice.get("finish_reason"))
    result["finish_reason"] = reason
    message = choice.get("message")
    if not isinstance(message, dict):
        result["status"] = "malformed_response"
        return result, generation_id
    if message.get("refusal") or reason == "content_filter":
        result["status"] = "refusal"
        return result, generation_id
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        result["status"] = "truncated" if reason == "length" else "missing_content"
        return result, generation_id
    result["content_bytes"] = len(content.encode("utf-8"))
    try:
        parsed = strict_json(content)
    except (ValueError, UnicodeError, RecursionError):
        result["validation"]["json_valid"] = False
        result["status"] = "truncated" if reason == "length" else "invalid_json"
        return result, generation_id
    result["validation"]["json_valid"] = True
    failures = list(Draft202012Validator(SCHEMA).iter_errors(parsed))
    result["validation"]["schema_valid"] = not failures
    # No values, names, or free-form validator messages in exported evidence.
    result["validation"]["failed_keywords"] = sorted({str(e.validator) for e in failures})
    result["status"] = "truncated" if reason == "length" else ("schema_mismatch" if failures else "valid")
    return result, generation_id


def probe(client: Client, request: dict) -> dict:
    result, generation_id = analyze(client.send("/chat/completions", request))
    result["require_parameters"] = request["provider"]["require_parameters"]
    if result["routing"]["provider"] or not generation_id:
        result["metadata_lookup"] = "not_needed" if result["routing"]["provider"] else "no_generation_id"
        return result
    metadata = client.send("/generation?" + urllib.parse.urlencode({"id": generation_id}))
    result["metadata_lookup"] = "unavailable"
    if metadata.status == 200 and not metadata.transport_error:
        try:
            body = strict_json(metadata.body)
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, dict) and label(data.get("provider_name")):
                result["routing"]["provider"] = label(data["provider_name"])
                result["routing"]["source"] = "generation.data.provider_name"
                result["metadata_lookup"] = "available"
                if not result["routing"]["model"]:
                    result["routing"]["model"] = label(data.get("model"))
        except (ValueError, UnicodeError, RecursionError):
            pass
    return result


class DemoClient:
    """Deterministic fictional responses. Not a claim about any live provider."""
    def send(self, path: str, payload: dict | None = None) -> Reply:
        required = payload["provider"]["require_parameters"]
        content = '{"item":"blue notebooks","quantity":3}' if required else '{"item":"blue notebooks","quantity":"3"}'
        return Reply(200, json.dumps({
            "model": "demo/model-not-live",
            "provider": "Fictional fixture provider",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }).encode())
