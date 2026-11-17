# AGENTS.md

Notes for coding agents (and humans) working on this repository. The README covers
what the project does and how to set it up; this file covers what to keep in mind
when changing it.

## Layout

- `src/bring_mcp/tools.py`: every tool and prompt, plus `INSTRUCTIONS`. `register()`
  adds them to any `MCPServer`; it is the only place tools are defined.
- `src/bring_mcp/bring_client.py`: wrapper around bring-api (login, lists by name,
  catalog names, recipe parser) and the name-matching helpers (`normalize`,
  `find`, `merge_spec`).
- `src/bring_mcp/__main__.py`: local stdio server (`bring-mcp`).
  `src/bring_mcp/server.py`: remote HTTP server for claude.ai (OAuth, audit log).
- `src/bring_mcp/auth.py`: OAuth provider (password page, lockout, redirect
  allowlist). Ported from proton-mcp's `remote/auth.py`: a security fix in one
  probably applies to the other.
- `src/bring_mcp/store.py`: SQLite key-value store (OAuth clients/tokens, staples).
  `src/bring_mcp/staples.py`: staples, and the cron command `python -m bring_mcp.staples`.
- `deploy/`: example reverse-proxy configs. `docs/deploy.md`: the full server guide.

## Commands

```bash
pip install -e ".[dev]"
pytest
ruff check .
docker build -t bring-mcp .
```

Tests need no Bring account and no network: `tests/test_tools.py` runs the tools
against a `FakeClient`, `tests/test_client.py` fakes `bring_api.Bring` including
its private attributes. `server.py` reads its configuration at import time, so
`tests/test_server.py` imports it in a subprocess.

## Releasing

Bump `version` in `pyproject.toml`, commit, then push a tag `vX.Y.Z` with the same
version. `.github/workflows/release.yml` checks the tag matches, runs the tests,
publishes to PyPI (trusted publishing, environment `pypi`), then publishes
`server.json` to the MCP Registry as `io.github.vdeabreu/bring-mcp` (GitHub OIDC). The
registry checks ownership through the `mcp-name:` comment at the top of the
README: keep it.

## Invariants: don't break these

- **Bounded, single-line inputs.** Item names, specs and list names go through the
  `ItemName` / `Spec` / `ListArg` types in `tools.py` (no control characters,
  length limits), and a call takes at most `MAX_ITEMS` items. Use them for any new
  argument.
- **No account-level tools.** The server reads and edits list items and staples
  only. Don't add tools that delete lists, share them, invite users or change
  account settings.
- **Annotations stay honest.** Read tools are `readOnlyHint`; `remove_items` and
  `set_staples_list` are `destructiveHint`, so clients can ask before running them.
- **Recipe pages are untrusted.** `fetch_recipe` passes the URL to Bring's parser
  (the server never downloads the page itself), accepts `http(s)` only and returns
  only ingredient names and specs. `INSTRUCTIONS` tell the model not to follow text
  from recipe pages; keep it that way.
- **Errors are readable, internals aren't.** Bring and lookup errors
  (`BringException`, `ValueError`) become a `ToolError` with a short message the
  model can act on (e.g. the list of available lists). Any other exception is logged
  with its traceback and reported as a generic message.
- **Shared lists are untrusted too.** Item names come from everyone the list is
  shared with; `INSTRUCTIONS` tell the model to treat them as data.
- **Private data directory.** `Store` creates the directory 0700 and the SQLite
  file 0600: it holds OAuth tokens.
- **Remote hardening.** The HTTP server refuses a non-loopback `LISTEN_HOST` unless
  `ALLOW_NON_LOOPBACK_LISTEN=true` (`_check_listen_host`); `MCP_PASSWORD` must be
  20+ characters; OAuth registration only accepts the claude.ai callback URLs; the
  login page sends anti-framing headers. Every tool call is logged with its
  arguments (shopping items aren't sensitive enough to hide).

## Bring and bring-api behaviour (learned the hard way)

- **bring-api hides what we need.** The catalog translations, the list locale and
  the translate function are name-mangled private attributes
  (`_Bring__translations`, `_Bring__locale`, `_Bring__translate`). That's why
  bring-api is pinned in `pyproject.toml`: before bumping it, check these still
  exist and run the tests.
- **Catalog keys are Swiss German.** Bring identifies catalog items by their de-CH
  name (`BRING_DEFAULT_LOCALE`), so there is no translation table for de-CH: for a
  de-CH list, the catalog is the table's keys. The recipe parser returns these keys
  too, hence `_to_list_language()`.
- **Names are in the list's language both ways.** `get_list` returns items
  translated to the list's language, and `batch_update_list` translates `itemId`
  back to the catalog key. So always send names in the list's language, spelled
  as in the catalog (`catalog_name()`): a name that doesn't match exactly is stored
  as a custom item, without icon or section.
- **Matching is ours.** Bring doesn't deduplicate "tomate" and "Tomates".
  `normalize()` ignores case, accents, œ/æ and a final s/x on words longer than 3
  letters; `find()` uses it to merge with existing items.
- **One operation, three effects.** `ADD` with an existing item's `uuid` replaces
  its spec (that's how `update_item` and merging work). `COMPLETE` moves an item to
  "recently bought"; `REMOVE` works on both sections.
- **Sessions.** Login is lazy (first tool call), so the server starts without
  network. bring-api refreshes the access token by itself; when the refresh token
  expires it raises `BringAuthException`, and `BringClient._call()` logs in again
  once. A failed login itself is never retried (wrong credentials would double the
  attempts on every call and risk a rate limit on the Bring account). List settings (locales) are loaded at login: a list created later uses the
  account locale until the next login.
- **Accounts** must sign in with email and password; Google/Apple sign-in accounts
  need a password set in the Bring app first.
- **de-CH only accounts.** bring-api loads no translation table for de-CH, so the
  catalog comes from the `articles.de-CH.json` file bring-api ships.

## MCP SDK notes (mcp 2.3.0)

- The server class is `mcp.server.mcpserver.MCPServer`. `Tool` fields are
  snake_case (`input_schema`, `annotations.read_only_hint`).
- `Annotated[..., Field(...)]` parameters become JSON Schema constraints and are
  validated before the tool runs (a bad argument is a `ToolError`).
- A tool returning `dict` has no output schema: `call_tool()` gives
  `structured_content=None` and the JSON in `content[0].text` (see the `call`
  helper in `tests/test_tools.py`).

## Deployment notes

- Unlike proton-mcp, the container uses a normal Docker network, not the host
  network: it only talks to the internet, and the host network would let it reach
  other loopback services (such as Proton Mail Bridge on the same host). So in
  `compose.yml` it listens on 0.0.0.0 inside the container, the port is published
  on `127.0.0.1` only, and `FORWARDED_ALLOW_IPS` trusts Docker's default pool
  (172.16.0.0/12) because requests come from the Docker gateway. Never `"*"`: uvicorn
  then takes the *leftmost* `X-Forwarded-For` value, which the client controls, so
  anyone could forge the address in "wrong password from ..." log lines.
- The reverse proxy should target `127.0.0.1:8765`, not `localhost` (Docker
  doesn't publish the port on `::1`).
- Rebuilding the container keeps OAuth tokens (`data/bring-mcp.sqlite`), so
  claude.ai stays connected. Raising the password rules (e.g. the 20-character
  minimum) stops the server from starting until `.env` is updated.

## Conventions

- Python 3.12+, ruff with line length 120. Code, docs and tool descriptions in
  English; the model answers in the user's language anyway.
- Tool docstrings are what the model reads: keep them accurate and short.
- Add a test with each change, especially for name matching, input validation and
  anything that reads bring-api's private attributes.
- Dependencies and the Docker base image are pinned (image by digest, actions by
  SHA). Dependabot opens the update PRs.
- Keep the repo generic: no personal domains, IPs or host names (use
  `bring.example.com`).
