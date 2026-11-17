# bring-mcp

[![PyPI](https://img.shields.io/pypi/v/bring-mcp)](https://pypi.org/project/bring-mcp/)
[![CI](https://github.com/vdeabreu/bring-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/vdeabreu/bring-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/vdeabreu/bring-mcp/blob/main/LICENSE)
[![Glama score](https://glama.ai/mcp/servers/vdeabreu/bring-mcp/badges/score.svg)](https://glama.ai/mcp/servers/vdeabreu/bring-mcp)

<!-- mcp-name: io.github.vdeabreu/bring-mcp -->

An [MCP](https://modelcontextprotocol.io) server that gives Claude (or any MCP
client) access to your **[Bring!](https://www.getbring.com)** shopping lists.

- **Lists**: read, add (with quantities), update, check off and remove items.
  Names are matched against the Bring catalog, so items get their section and icon.
- **Recipes**: extract the ingredients of a recipe page with Bring's own parser,
  then add them in one go.
- **Staples**: keep a list of items you buy every week and add the missing ones,
  from Claude or from cron (no LLM involved).
- Runs **locally** for Claude Desktop (stdio), or **remotely** as a claude.ai
  custom connector (streamable HTTP + OAuth).

> Unofficial project, not affiliated with or endorsed by Bring! Labs AG. It uses
> [bring-api](https://github.com/miaucl/bring-api), an unofficial client of the
> Bring! API, which may change without notice.

## Why this one

Other Bring! MCP servers map the API call by call (load list, save item, remove
item...). This one gives the model tools shaped like the tasks you ask for:

- **"Add what I need for this recipe"**: Bring's own recipe parser extracts the
  ingredients of a page in your list's language, and flags pantry items (salt,
  oil) so the model can ask before adding them.
- **"Add 2 more litres of milk"**: an item already on the list gets its quantity
  merged instead of replaced, and names are matched against the Bring catalog
  (case, accents, simple plurals), so items land in the right section with their icon.
- **Weekly staples**: keep the list of things you always buy and add the missing
  ones in one call, or from cron without any LLM.
- **Works in claude.ai on the web and on your phone**, not only in Claude Desktop:
  a remote mode with OAuth, Docker and reverse-proxy configs, and a full
  [deployment guide](https://github.com/vdeabreu/bring-mcp/blob/main/docs/deploy.md).

## Tools

| Tool | What it does |
| --- | --- |
| `list_lists` | Names of your Bring lists. |
| `get_list` | Items to buy and recently bought items. |
| `add_items` | Add items with an optional spec (`"6"`, `"500 g"`, `"organic"`). An item already on the list gets its spec merged (`1 L + 2 L`). |
| `update_item` | Replace the spec of an item. |
| `complete_items` | Check items off (they move to "recently bought"). |
| `remove_items` | Remove items. |
| `fetch_recipe` | Ingredients of a recipe URL, in the list's language, with a `pantry` flag (salt, oil...). Adds nothing by itself. |
| `get_staples_list` / `set_staples_list` | Read or replace your staples. |
| `add_staples` | Add the staples that aren't on the list yet. |

Every tool takes an optional `list` (name, case-insensitive); without it, the
server uses `BRING_DEFAULT_LIST`, or your first list.

Prompts: `add_recipe`, `clean_up_list`, `weekly_shopping`.

## Local setup (Claude Desktop)

Requirements: [uv](https://docs.astral.sh/uv/) (or Python 3.12+) and a Bring!
account that signs in with an email and password (if you use Google or Apple
sign-in, set a password in the Bring app).

Add the server to `claude_desktop_config.json`. Open it from Claude Desktop →
Settings → Developer → Edit Config, or directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bring": {
      "command": "uvx",
      "args": ["bring-mcp"],
      "env": {
        "BRING_EMAIL": "you@example.com",
        "BRING_PASSWORD": "your-bring-password",
        "BRING_DEFAULT_LIST": "Shopping"
      }
    }
  }
}
```

Fully quit and restart Claude Desktop after editing the file.

Without uv: `pip install bring-mcp`, then use `"command": "bring-mcp"` (the full
path to that script if it isn't on your `PATH`) and no `args`.

### Configuration

| Variable | Default | |
| --- | --- | --- |
| `BRING_EMAIL` | (required) | Bring account email |
| `BRING_PASSWORD` | (required) | Bring account password |
| `BRING_DEFAULT_LIST` | *(first list)* | List used when a tool gets no `list` |
| `DATA_DIR` | `~/.bring-mcp` | Where the SQLite file (staples, and OAuth tokens in remote mode) is kept |

The config file holds your Bring password: keep it readable by you only.

## Remote setup (claude.ai connector)

`python -m bring_mcp.server` (or `bring-mcp-remote`) serves the same tools over
streamable HTTP, behind a single-user OAuth password page, for claude.ai on the
web and mobile. A Dockerfile and compose file are included, plus Apache and Caddy
configs that only let Anthropic's IP ranges reach `/mcp`.

See **[docs/deploy.md](https://github.com/vdeabreu/bring-mcp/blob/main/docs/deploy.md)** for the full guide (Docker, reverse
proxy, claude.ai, weekly staples).

## Security

- **What's at stake.** Your Bring password gives full access to your Bring
  account; this server can read and change your lists. It has no tool to
  delete lists, change account settings or invite people.
- **Recipe pages are untrusted.** `fetch_recipe` asks Bring's servers to parse the
  page (this server never downloads it) and returns only ingredient names and
  quantities. The server instructions still tell the model not to follow text
  found there. Only `http(s)` URLs are accepted.
- **Inputs are bounded.** Item names and specs are single-line and length-limited,
  and a call handles at most 100 items. `remove_items` and `set_staples_list` carry
  the MCP `destructiveHint`, so clients can ask before running them.
- **Remote mode**:
  - OAuth with a 20+ character password, a lockout after 5 failures, and tokens
    stored in SQLite.
  - Only claude.ai's callback can be registered as redirect URI, and the number of
    clients is capped.
  - The password page says which client asks and can't be framed by another site.
  - `/mcp` is restricted to Anthropic's outbound IPs by the reverse proxy.
  - The server refuses to listen on a public address, every tool call is logged,
    and the container is read-only and unprivileged.
- **Remote mode, known limits:**
  - The lockout is global: anyone can make *new* logins wait 15 minutes by failing
    5 times. Tokens already issued keep working.
  - Anyone can add your server URL as a connector in *their own* claude.ai account
    and send you the resulting authorization link. If you type your password, their
    account gets access. Only type it right after clicking *Connect* yourself.

Keep `.env` and `claude_desktop_config.json` private. To report a vulnerability,
see [SECURITY.md](https://github.com/vdeabreu/bring-mcp/blob/main/SECURITY.md).

## Limitations

- Catalog matching relies on bring-api's translation tables, read through private
  attributes; bring-api is pinned for that reason.
- Name matching ignores case, accents and a final `s`/`x`; it doesn't know other
  plurals or synonyms.
- Item photos, list sharing, notifications and loyalty cards are not supported.

## Development

```bash
git clone https://github.com/vdeabreu/bring-mcp && cd bring-mcp
pip install -e ".[dev]"
pytest
ruff check .
```

Tests don't need a Bring account: they cover the tools against a fake list
(merging, catalog names, list lookup, staples), input validation, re-login after
an expired session, and the OAuth flow (redirect allowlist, client cap, lockout,
security headers, startup checks).

## License

[MIT](https://github.com/vdeabreu/bring-mcp/blob/main/LICENSE)
