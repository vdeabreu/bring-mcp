# bring-mcp

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

Requirements: Python 3.12+ and a Bring! account that signs in with an email and
password (if you use Google or Apple sign-in, set a password in the Bring app).

```bash
git clone https://github.com/vdeabreu/bring-mcp && cd bring-mcp
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
```

Add the server to `claude_desktop_config.json`. Open it from Claude Desktop →
Settings → Developer → Edit Config, or directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "bring": {
      "command": "/path/to/bring-mcp/.venv/bin/bring-mcp",
      "env": {
        "BRING_EMAIL": "you@example.com",
        "BRING_PASSWORD": "your-bring-password",
        "BRING_DEFAULT_LIST": "Shopping"
      }
    }
  }
}
```

On Windows, use `C:\\path\\to\\bring-mcp\\.venv\\Scripts\\bring-mcp.exe`. Fully
quit and restart Claude Desktop after editing the file.

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

See **[docs/deploy.md](docs/deploy.md)** for the full guide (Docker, reverse
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
see [SECURITY.md](SECURITY.md).

## Limitations

- Catalog matching relies on bring-api's translation tables, read through private
  attributes; bring-api is pinned for that reason.
- Name matching ignores case, accents and a final `s`/`x`; it doesn't know other
  plurals or synonyms.
- Item photos, list sharing, notifications and loyalty cards are not supported.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Tests don't need a Bring account: they cover the tools against a fake list
(merging, catalog names, list lookup, staples), input validation, re-login after
an expired session, and the OAuth flow (redirect allowlist, client cap, lockout,
security headers, startup checks).

## License

[MIT](LICENSE)
