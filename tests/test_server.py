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


def test_missing_public_url(tmp_path):
    r = _import_server(tmp_path, PUBLIC_URL="")
    assert r.returncode != 0
    assert "PUBLIC_URL must be set" in r.stderr
