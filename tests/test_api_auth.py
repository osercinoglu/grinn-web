"""Tests for the internal-token gate in front of the backend API."""

import pytest

from shared.api_auth import INTERNAL_TOKEN_HEADER, check_api_access, is_public_endpoint


TOKEN = "s3cret-internal-token"


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/health"),
    ("GET", "/api/jobs/6-sad-squid-snuggle-softly/download"),
    ("GET", "/api/dashboard/6-sad-squid-snuggle-softly/"),
    ("POST", "/api/dashboard/6-sad-squid-snuggle-softly/_dash-update-component"),
    ("POST", "/api/dashboard/6-sad-squid-snuggle-softly/heartbeat"),
    ("OPTIONS", "/api/dashboard/6-sad-squid-snuggle-softly/assets/x.css"),
    ("POST", "/api/workers/register"),
    ("POST", "/api/workers/heartbeat"),
])
def test_public_endpoints(method, path):
    assert is_public_endpoint(method, path)


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/create-job"),
    ("POST", "/api/jobs/x/upload"),
    ("POST", "/api/jobs/x/start"),
    ("POST", "/api/jobs/x/cancel"),
    ("POST", "/api/jobs/x/abort"),
    ("GET", "/api/jobs"),
    ("GET", "/api/jobs/x"),
    ("GET", "/api/jobs/x/logs"),
    ("POST", "/api/jobs/x/download"),     # only GET downloads are public
    ("GET", "/api/workers"),
    ("POST", "/api/workers/generate-token"),
    ("DELETE", "/api/workers/w1"),
    ("GET", "/api/stats"),
    ("GET", "/api/storage/stats"),
    ("DELETE", "/api/jobs/x/token-usage"),
    ("GET", "/api/healthz"),              # prefix lookalikes stay protected
    ("GET", "/api/jobs/x/download/../../workers"),
])
def test_protected_endpoints(method, path):
    assert not is_public_endpoint(method, path)


def test_protected_endpoint_without_token_is_rejected():
    assert check_api_access("POST", "/api/create-job", {}, TOKEN) is False


def test_protected_endpoint_with_wrong_token_is_rejected():
    headers = {INTERNAL_TOKEN_HEADER: "nope"}
    assert check_api_access("POST", "/api/create-job", headers, TOKEN) is False


def test_protected_endpoint_with_token_is_allowed():
    headers = {INTERNAL_TOKEN_HEADER: TOKEN}
    assert check_api_access("POST", "/api/create-job", headers, TOKEN) is True


def test_public_endpoint_needs_no_token():
    assert check_api_access("GET", "/api/health", {}, TOKEN) is True


def test_unconfigured_token_fails_closed():
    """An empty INTERNAL_API_TOKEN must not silently reopen the API."""
    assert check_api_access("POST", "/api/create-job", {INTERNAL_TOKEN_HEADER: ""}, "") is False
    assert check_api_access("POST", "/api/create-job", {}, None) is False
