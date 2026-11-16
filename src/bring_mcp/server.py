"""Remote Bring! MCP server: streamable HTTP + OAuth, for claude.ai custom connectors.

Same tools as the local stdio server (tools.py). Differences:
- every request needs an OAuth token (password page, see auth.py);
- every tool call is logged with its arguments.
"""

import ipaddress
import logging
import os
from urllib.parse import urlsplit

import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import tools
from .auth import DEFAULT_REDIRECT_URIS, SCOPE, PasswordOAuthProvider
from .bring_client import BringClient
from .store import Store, db_path

# The mcp library configures the root logger first, so ours get their own handler.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
_root = logging.getLogger("bring-mcp")
_root.addHandler(_handler)
_root.setLevel(logging.INFO)
_root.propagate = False
log = logging.getLogger("bring-mcp.server")


def _env_true(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def _public_url(value: str) -> str:
    """Base URL clients see: https, a host, no path (OAuth metadata and the Host check derive from it)."""
    url = urlsplit(value.strip().rstrip("/"))
    local = url.hostname in ("localhost", "127.0.0.1")
    if not url.hostname or url.path or url.query or (url.scheme != "https" and not (local and url.scheme == "http")):
        raise SystemExit(
            f"PUBLIC_URL={value!r} must be the server's public https URL without path, e.g. https://bring.example.com"
        )
    return f"{url.scheme}://{url.netloc}"


PUBLIC_URL = _public_url(os.environ.get("PUBLIC_URL", ""))
LISTEN_HOST = os.environ.get("LISTEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
FORWARDED_ALLOW_IPS = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
ALLOWED_REDIRECT_URIS = os.environ.get("ALLOWED_REDIRECT_URIS", ",".join(DEFAULT_REDIRECT_URIS)).split(",")


def _check_listen_host(host: str) -> None:
    """The server speaks plain HTTP: it must sit behind a TLS reverse proxy on the same machine."""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback and not _env_true("ALLOW_NON_LOOPBACK_LISTEN"):
        raise SystemExit(
            f"LISTEN_HOST={host!r} is not a loopback address. The server speaks plain HTTP; keep it on "
            "127.0.0.1 behind a reverse proxy, or set ALLOW_NON_LOOPBACK_LISTEN=true if a private "
            "container network isolates it."
        )


_check_listen_host(LISTEN_HOST)
if not os.environ.get("MCP_PASSWORD"):
    raise SystemExit("MCP_PASSWORD must be set")

store = Store(db_path())
provider = PasswordOAuthProvider(store, os.environ["MCP_PASSWORD"], PUBLIC_URL, ALLOWED_REDIRECT_URIS)
client = BringClient.from_env()

mcp = MCPServer(
    name="bring",
    title="Bring! shopping list",
    instructions=tools.INSTRUCTIONS,
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=PUBLIC_URL,
        resource_server_url=f"{PUBLIC_URL}/mcp",
        validate_token_resource=False,
        required_scopes=[SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
)
tools.register(mcp, client, store, log_calls=True)


@mcp.custom_route("/login", methods=["GET", "POST"])
async def login(request: Request):
    return await provider.login_page(request)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


def main() -> None:
    public_host = urlsplit(PUBLIC_URL).netloc
    app = mcp.streamable_http_app(
        host=LISTEN_HOST,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[public_host, "localhost:*", "127.0.0.1:*"],
            allowed_origins=[PUBLIC_URL, "https://claude.ai", "http://localhost:*", "http://127.0.0.1:*"],
        ),
    )
    log.info("starting on %s:%d, public %s", LISTEN_HOST, PORT, PUBLIC_URL)
    uvicorn.run(app, host=LISTEN_HOST, port=PORT, proxy_headers=True, forwarded_allow_ips=FORWARDED_ALLOW_IPS)


if __name__ == "__main__":
    main()
