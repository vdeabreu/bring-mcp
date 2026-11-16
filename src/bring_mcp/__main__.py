"""Local Bring! MCP server over stdio, for Claude Desktop and other local MCP clients."""

from mcp.server.mcpserver import MCPServer

from . import tools
from .bring_client import BringClient
from .store import Store, db_path


def build() -> MCPServer:
    mcp = MCPServer("bring", title="Bring! shopping list", instructions=tools.INSTRUCTIONS)
    tools.register(mcp, BringClient.from_env(), Store(db_path()))
    return mcp


def main() -> None:
    build().run("stdio")


if __name__ == "__main__":
    main()
