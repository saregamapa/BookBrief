"""
Shared helpers for the Manus HTTP API (task.create, task.listMessages, etc.).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MANUS_BASE = "https://api.manus.ai"

# Transient Manus / gateway responses — safe to retry.
_RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})


def normalize_base(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return DEFAULT_MANUS_BASE
    return u.rstrip("/")


def json_headers(api_key: str) -> Dict[str, str]:
    return {
        "x-manus-api-key": api_key.strip(),
        "Content-Type": "application/json",
    }


def get_headers(api_key: str) -> Dict[str, str]:
    """Headers for GET — omit Content-Type (some gateways mishandle GET + JSON content-type)."""
    return {"x-manus-api-key": api_key.strip()}


def raise_for_manus(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception as exc:
        resp.raise_for_status()
        raise RuntimeError("Manus API returned non-JSON body") from exc
    if not data.get("ok"):
        err = data.get("error") or {}
        msg = err.get("message") or str(data)
        raise RuntimeError(f"Manus API error: {msg}")
    return data


def extract_task_id(data: Dict[str, Any]) -> str:
    """Resolve task_id from task.create response (shape varies by API version)."""
    tid = data.get("task_id")
    if tid:
        return str(tid).strip()
    inner = data.get("data")
    if isinstance(inner, dict):
        tid = inner.get("task_id") or inner.get("id")
        if tid:
            return str(tid).strip()
    task = data.get("task")
    if isinstance(task, dict):
        tid = task.get("id") or task.get("task_id")
        if tid:
            return str(tid).strip()
    raise RuntimeError("Manus task.create response missing task_id")


def _get_list_messages_once(
    client: httpx.Client,
    url: str,
    api_key: str,
    task_id: str,
    *,
    order: str,
    limit: int,
    request_timeout: float,
) -> httpx.Response:
    return client.get(
        url,
        headers=get_headers(api_key),
        params={"task_id": task_id, "order": order, "limit": limit},
        timeout=request_timeout,
    )


def _get_list_messages_with_transient_retries(
    client: httpx.Client,
    url: str,
    api_key: str,
    task_id: str,
    *,
    order: str,
    limit: int,
    request_timeout: float,
    max_retries: int = 12,
    base_delay: float = 2.0,
) -> httpx.Response:
    """
    Poll listMessages; Manus occasionally returns 500/502/503 — retry with backoff.
    """
    delay = base_delay
    last: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        r = _get_list_messages_once(
            client,
            url,
            api_key,
            task_id,
            order=order,
            limit=limit,
            request_timeout=request_timeout,
        )
        last = r
        if r.status_code not in _RETRYABLE_HTTP:
            return r
        if attempt >= max_retries:
            return r
        logger.warning(
            "manus_list_messages_transient_http status=%s task_id_prefix=%s limit=%s attempt=%s/%s",
            r.status_code,
            task_id[:24],
            limit,
            attempt + 1,
            max_retries,
        )
        time.sleep(delay)
        delay = min(delay * 1.55, 45.0)
    if last is not None:
        return last
    raise RuntimeError("Manus listMessages: no response from retry loop")


def list_task_messages(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    task_id: str,
    *,
    order: str = "asc",
    limit: int = 200,
    request_timeout: float = 120.0,
    not_found_retries: int = 15,
    not_found_delay: float = 1.5,
) -> List[Dict[str, Any]]:
    """
    GET /v2/task.listMessages with retries on HTTP 404 (eventual consistency / propagation).
    """
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("empty task_id for listMessages")

    base = normalize_base(base_url)
    url = f"{base}/v2/task.listMessages"
    lim = max(1, min(int(limit), 200))

    last_resp: httpx.Response | None = None
    for attempt in range(not_found_retries + 1):
        r = _get_list_messages_with_transient_retries(
            client,
            url,
            api_key,
            tid,
            order=order,
            limit=lim,
            request_timeout=request_timeout,
        )
        last_resp = r

        # If asc+limit keeps hitting 5xx, try newest-first then reverse so callers still see
        # chronological order (asc+small limit would drop the latest messages — bad).
        if r.status_code in _RETRYABLE_HTTP and order == "asc":
            r_desc = _get_list_messages_with_transient_retries(
                client,
                url,
                api_key,
                tid,
                order="desc",
                limit=lim,
                request_timeout=request_timeout,
            )
            r = r_desc
            last_resp = r
            if r.status_code not in _RETRYABLE_HTTP:
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"Manus task.listMessages returned HTTP {r.status_code}. "
                        "Check MANUS_API_KEY and MANUS_API_BASE."
                    ) from exc
                data = raise_for_manus(r)
                msgs = list(data.get("messages") or [])
                msgs.reverse()
                logger.info(
                    "manus_list_messages_desc_fallback_ok task_id_prefix=%s count=%s",
                    tid[:24],
                    len(msgs),
                )
                return msgs

        if r.status_code == 404:
            logger.warning(
                "manus_list_messages_404 task_id_prefix=%s attempt=%s/%s",
                tid[:24],
                attempt + 1,
                not_found_retries + 1,
            )
            if attempt < not_found_retries:
                time.sleep(not_found_delay)
                continue
            detail = client.get(
                f"{base}/v2/task.detail",
                headers=get_headers(api_key),
                params={"task_id": tid},
                timeout=60.0,
            )
            if detail.status_code == 404:
                raise RuntimeError(
                    "Manus returned 404 for task.listMessages and task.detail — "
                    "invalid or unknown task_id, or wrong MANUS_API_BASE."
                )
            detail.raise_for_status()
            raise RuntimeError(
                "Manus task.listMessages kept returning 404 while task.detail succeeded — "
                "try again later or contact Manus support."
            )

        if r.status_code in _RETRYABLE_HTTP:
            raise RuntimeError(
                f"Manus task.listMessages failed after retries (HTTP {r.status_code}). "
                "Their API may be overloaded — wait a few minutes and try again, "
                "or check https://status.manus.ai if available."
            )

        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Manus task.listMessages returned HTTP {r.status_code}. "
                "Check MANUS_API_KEY and MANUS_API_BASE."
            ) from exc

        data = raise_for_manus(r)
        return list(data.get("messages") or [])

    if last_resp is not None:
        if last_resp.status_code in _RETRYABLE_HTTP:
            raise RuntimeError(
                f"Manus task.listMessages failed (HTTP {last_resp.status_code}). "
                "Retry later or contact Manus support if it persists."
            )
        last_resp.raise_for_status()
    raise RuntimeError("Manus listMessages: unexpected empty retry loop")
