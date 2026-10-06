"""Minimal JSON-over-HTTP client (stdlib only) with retry."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Optional

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def request_json(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    payload: Any = None,
    timeout: float = 90.0,
    retries: int = 3,
) -> dict:
    """Send a JSON request and parse a JSON response.

    Retries network failures and 429/5xx with exponential backoff, then raises
    ProviderError with a short body snippet for diagnosis.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    all_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        all_headers.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=all_headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProviderError(f"non-JSON response from {url}: {raw[:200]}", body=raw[:500]) from exc
            if not isinstance(parsed, dict):
                return {"result": parsed}
            return parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            if exc.code in RETRYABLE_STATUS and attempt < retries:
                time.sleep(min(8.0, 1.5 * (2 ** attempt)))
                last_error = exc
                continue
            raise ProviderError(f"HTTP {exc.code} from {url}: {body}", status=exc.code, body=body) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                time.sleep(min(8.0, 1.5 * (2 ** attempt)))
                last_error = exc
                continue
            raise ProviderError(f"network error calling {url}: {exc}") from exc

    raise ProviderError(f"request to {url} failed after retries: {last_error}")
