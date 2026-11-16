# Remote deployment (claude.ai connector)

This guide runs the server on a Linux host so you can add it as a custom
connector in claude.ai (web and mobile). It was written for Debian 13 with
Docker, but any Linux with Docker and a reverse proxy works.

```
claude.ai ──HTTPS──> reverse proxy :443 (bring.example.com) ──> 127.0.0.1:8765 bring-mcp (Docker) ──HTTPS──> Bring! API
```

- Only the reverse proxy is reachable from the internet. The container's port is
  published on the host's 127.0.0.1 only.
- Each claude.ai connection goes through an OAuth password page (`MCP_PASSWORD`).
  After 5 wrong passwords in 15 minutes, login is locked for 15 minutes.
- `/mcp` only accepts Anthropic's outbound IP ranges (reverse proxy rule).
- Each tool call is logged with its arguments: `docker logs bring-mcp`.

Read [Security](../README.md#security) first.

## 1. DNS

Create an `A` (and/or `AAAA`) record for your chosen name, e.g.
`bring.example.com`, pointing to the host.

## 2. MCP server

```bash
git clone https://github.com/vdeabreu/bring-mcp && cd bring-mcp
cp .env.example .env && chmod 600 .env
mkdir -p data && chmod 700 data
openssl rand -base64 30          # -> MCP_PASSWORD
nano .env                        # Bring email/password, MCP_PASSWORD, PUBLIC_URL
docker compose up -d --build
docker logs bring-mcp            # "starting on 0.0.0.0:8765, public https://bring.example.com"
curl -s http://127.0.0.1:8765/health
```

The container runs as uid 1000; if your user has another uid, `chown 1000 data`.

Inside the container the server listens on all interfaces of its own Docker
network (`ALLOW_NON_LOOPBACK_LISTEN=true` in `compose.yml`); on the host, the port
is only published on 127.0.0.1. Don't change the `ports:` line to `8765:8765`:
Docker publishes ports past host firewalls such as ufw.

## 3. Reverse proxy + certificate

Pick one, and replace `bring.example.com` with your domain:

- **Apache**: [`deploy/apache/bring-mcp.conf`](../deploy/apache/bring-mcp.conf)
  (steps at the top of the file, certificate with certbot).
- **Caddy**: [`deploy/caddy/Caddyfile`](../deploy/caddy/Caddyfile)
  (certificate is automatic).

Both restrict `/mcp` to Anthropic's outbound ranges. Check them:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://bring.example.com/mcp   # 403 from your machine
curl -s https://bring.example.com/.well-known/oauth-protected-resource/mcp        # JSON, open
```

## 4. claude.ai

Settings → Connectors → Add custom connector → `https://bring.example.com/mcp`.
The password page opens, saying that **Claude** asks for access and that the
authorization goes to **claude.ai**. Type `MCP_PASSWORD`.

Only type the password on a page you opened by clicking *Connect* yourself: an
authorization link someone sends you would connect *their* account.

## Weekly staples (no LLM)

Set your staples once from Claude ("my staples are milk, eggs, bread"), then let
cron add the missing ones every Saturday at 9:00:

```bash
docker exec bring-mcp python -m bring_mcp.staples      # try it
crontab -e   # 0 9 * * 6 docker exec bring-mcp python -m bring_mcp.staples
```

## Hardening checklist

- Automatic security updates: `sudo apt install unattended-upgrades`.
- SSH with keys only: `PasswordAuthentication no` in `/etc/ssh/sshd_config`.
- Make sure nothing else on the host exposes services you didn't mean to
  (`ss -tlnp`, and a port scan from outside).
- Look at the logs now and then: `docker logs bring-mcp | grep bring-mcp`.
  An unknown `login ok`, a burst of `wrong password` or `registration refused`
  deserves attention.
- If login says *"Too many attempts"* although you typed nothing wrong, someone
  is failing on purpose to lock you out. Wait 15 minutes, or restart the
  container (`docker compose restart`) to reset the counter. Existing claude.ai
  sessions are not affected.

## Revoke access

- Stop everything: `docker compose down`.
- Revoke all claude.ai tokens: `docker compose down`, delete `data/bring-mcp.sqlite`
  (this also deletes your staples), then `docker compose up -d` and reconnect the
  connector.
- Cut Bring access entirely: change your Bring password.
