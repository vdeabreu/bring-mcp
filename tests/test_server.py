"""Remote server startup checks (run in a subprocess: importing server.py reads the configuration)."""

import os
import subprocess
import sys

BASE_ENV = {
    "PUBLIC_URL": "https://bring.example.com",
    "MCP_PASSWORD": "x" * 24,
    "BRING_EMAIL": "me@example.com",
    "BRING_PASSWORD": "p",
}


def _import_server(tmp_path, **env):
    full = {**os.environ, **BASE_ENV, "DATA_DIR": str(tmp_path), **env}
    full = {k: v for k, v in full.items() if v is not None}
    code = (
        "import asyncio; from bring_mcp import server; "
        "print(sorted(t.name for t in asyncio.run(server.mcp.list_tools())))"
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=full)


def test_starts_with_all_tools(tmp_path):
    r = _import_server(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "add_items" in r.stdout and "fetch_recipe" in r.stdout


def test_refuses_public_listen_address(tmp_path):
    r = _import_server(tmp_path, LISTEN_HOST="0.0.0.0")
    assert r.returncode != 0
    assert "not a loopback address" in r.stderr


def test_public_listen_needs_explicit_opt_in(tmp_path):
    r = _import_server(tmp_path, LISTEN_HOST="0.0.0.0", ALLOW_NON_LOOPBACK_LISTEN="true")
    assert r.returncode == 0, r.stderr


def test_short_password_refused(tmp_path):
    r = _import_server(tmp_path, MCP_PASSWORD="short")
    assert r.returncode != 0
    assert "at least 20 characters" in r.stderr


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "url", ["", "bring.example.com", "http://bring.example.com", "https://bring.example.com/mcp", "https://"]
)
def test_bad_public_url_refused(tmp_path, url):
    r = _import_server(tmp_path, PUBLIC_URL=url)
    assert r.returncode != 0
    assert "must be the server's public https URL" in r.stderr


def test_public_url_trailing_slash_and_local_http_accepted(tmp_path):
    assert _import_server(tmp_path, PUBLIC_URL="https://bring.example.com/").returncode == 0
    assert _import_server(tmp_path, PUBLIC_URL="http://localhost:8765").returncode == 0


def _client_seen_by_app(trusted: str, forwarded_for: str) -> str:
    import asyncio

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen = {}

    async def app(scope, receive, send):
        seen["client"] = scope["client"][0]

    scope = {
        "type": "http", "scheme": "http", "client": ("172.20.0.1", 40000),  # the Docker gateway
        "headers": [(b"x-forwarded-for", forwarded_for.encode())],
    }
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return seen["client"]


def test_forwarded_ip_trust_from_compose_cannot_be_spoofed():
    """With the compose setting, the logged address is the one the proxy saw, not one the client sent."""
    # Apache appends the real client address to whatever X-Forwarded-For the client sent.
    assert _client_seen_by_app("172.16.0.0/12", "6.6.6.6, 203.0.113.7") == "203.0.113.7"
    assert _client_seen_by_app("*", "6.6.6.6, 203.0.113.7") == "6.6.6.6"  # why compose doesn't use "*"
