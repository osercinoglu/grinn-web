"""Internal-token gate for the backend API.

The backend port is reachable from the internet (via the SSH tunnel), but
almost every route is only meant to be called server-side by the Dash
frontend. Those routes require ``X-Internal-Token`` to match
``INTERNAL_API_TOKEN``. Only the routes that browsers, dashboards or remote
workers call directly are public:

- ``GET /api/health``                      Docker healthcheck / uptime probes
- ``GET /api/jobs/<id>/download``          result download links in the UI
- ``/api/dashboard/<job_id>/...``          per-job dashboard proxy, heartbeat, close
- ``POST /api/workers/register|heartbeat`` remote workers (own token check)

Kept Flask-free so it can be unit tested without importing the app.
"""

from __future__ import annotations

import hmac
import re
from typing import Mapping, Optional

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

_PUBLIC_ENDPOINTS = [
    ({"GET"}, re.compile(r"/api/health")),
    ({"GET"}, re.compile(r"/api/jobs/[^/]+/download")),
    (None, re.compile(r"/api/dashboard/[^/]+(/.*)?")),  # any method
    ({"POST"}, re.compile(r"/api/workers/(register|heartbeat)")),
]


def is_public_endpoint(method: str, path: str) -> bool:
    """Return True if ``method path`` may be called without the internal token."""
    for methods, pattern in _PUBLIC_ENDPOINTS:
        if (methods is None or method in methods) and pattern.fullmatch(path):
            return True
    return False


def check_api_access(method: str, path: str, headers: Mapping[str, str],
                     expected_token: Optional[str]) -> bool:
    """Return True if the request may proceed.

    Fails closed: when ``expected_token`` is empty, protected routes are denied.
    """
    if is_public_endpoint(method, path):
        return True
    if not expected_token:
        return False
    provided = headers.get(INTERNAL_TOKEN_HEADER) or ""
    return hmac.compare_digest(provided.encode(), expected_token.encode())
