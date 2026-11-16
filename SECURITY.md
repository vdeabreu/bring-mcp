# Security policy

This server gives an AI assistant access to a Bring! account, so security
reports are welcome and taken seriously.

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting instead:
the repository's **Security** tab → **Report a vulnerability**.

Include what an attacker can do, the steps to reproduce, and the version or
commit. You should get a first answer within a week.

## In scope

- Reading or changing lists without the user's approval, including through text
  in a recipe page.
- Bypassing the OAuth login, the lockout or the token checks of the remote server.
- Leaking the Bring credentials or OAuth tokens.

## Out of scope

- Vulnerabilities in Bring!, bring-api, the MCP SDK or the MCP clients themselves
  (report them to their maintainers).
- A model making a change the user approved.
