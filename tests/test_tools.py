"""Tools against a fake Bring account (no network)."""

import asyncio
import json

import pytest
from bring_api import BringItemOperation
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from bring_mcp import tools
from bring_mcp.bring_client import BringClient, Item
from bring_mcp.staples import set_staples
from bring_mcp.store import Store

CATALOG = {"tomate": "Tomates", "oeuf": "Oeufs", "lait": "Lait"}


class FakeClient(BringClient):
    def __init__(self, to_buy=(), recent=()):
        super().__init__("me@example.com", "pw", None)
        self.to_buy = list(to_buy)
        self.recent = list(recent)
        self.applied: list[tuple[list[dict], BringItemOperation]] = []

    async def lists(self):
        return [{"name": "Courses", "uuid": "u1"}, {"name": "Party", "uuid": "u2"}]

    async def items(self, list_uuid):
        return self.to_buy, self.recent

    async def apply(self, list_uuid, changes, operation):
        if changes:
            self.applied.append((changes, operation))

    async def catalog_name(self, list_uuid, name):
        from bring_mcp.bring_client import normalize

        return CATALOG.get(normalize(name), name.strip())


@pytest.fixture
def env(tmp_path):
    client = FakeClient(to_buy=[Item("i1", "Lait", "1 L")], recent=[Item("i2", "Pain", "")])
    store = Store(tmp_path / "db.sqlite")
    mcp = MCPServer("test")
    tools.register(mcp, client, store)

    def call(tool_name, **args):
        result = asyncio.run(mcp.call_tool(tool_name, args))
        if result.structured_content is not None:
            return result.structured_content.get("result", result.structured_content)
        return json.loads(result.content[0].text)

    return client, store, call


def test_add_items_merges_and_uses_catalog_names(env):
    client, _, call = env
    out = call("add_items", items=[{"name": "tomate", "spec": "6"}, {"name": "lait", "spec": "2 L"}])
    # The list name is reported, not the last item name.
    assert out == {"list": "Courses", "added": ["Tomates"], "merged": ["Lait (1 L + 2 L)"]}
    changes, op = client.applied[0]
    assert op == BringItemOperation.ADD
    assert {"itemId": "Tomates", "spec": "6", "uuid": None} in changes
    assert {"itemId": "Lait", "spec": "1 L + 2 L", "uuid": "i1"} in changes


def test_list_is_chosen_by_name_case_insensitively(env):
    _, _, call = env
    assert call("get_list", list="party")["list"] == "Party"


def test_unknown_list_is_a_readable_error(env):
    _, _, call = env
    with pytest.raises(ToolError, match="Available lists: Courses, Party"):
        call("get_list", list="nope")


def test_update_missing_item_is_a_readable_error(env):
    _, _, call = env
    with pytest.raises(ToolError, match="is not on the list"):
        call("update_item", name="Beurre", spec="250 g")


def test_complete_only_looks_at_items_to_buy(env):
    client, _, call = env
    out = call("complete_items", names=["lait", "pain"])
    assert out == {"list": "Courses", "done": ["Lait"], "not_found": ["pain"]}
    assert client.applied[0][1] == BringItemOperation.COMPLETE


def test_remove_also_looks_at_recent_items(env):
    client, _, call = env
    out = call("remove_items", names=["pain"])
    assert out["done"] == ["Pain"]
    assert client.applied[0][1] == BringItemOperation.REMOVE


def test_add_staples_skips_items_already_listed(env):
    client, store, call = env
    set_staples(store, [{"name": "Lait", "spec": ""}, {"name": "oeufs", "spec": "12"}])
    assert call("add_staples")["added"] == ["Oeufs"]
    assert client.applied[0][0] == [{"itemId": "Oeufs", "spec": "12", "uuid": None}]


def test_staples_roundtrip(env):
    _, _, call = env
    call("set_staples_list", items=[{"name": "Café", "spec": "1 paquet"}])
    assert call("get_staples_list") == [{"name": "Café", "spec": "1 paquet"}]


@pytest.mark.parametrize("name", ["Lait\nSELECT", "a\rb", "tab\there", ""])
def test_item_names_must_be_single_line(env, name):
    client, _, call = env
    with pytest.raises(ToolError):
        call("add_items", items=[{"name": name}])
    assert client.applied == []


def test_item_count_is_capped(env):
    _, _, call = env
    with pytest.raises(ToolError):
        call("add_items", items=[{"name": f"x{i}"} for i in range(tools.MAX_ITEMS + 1)])


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://a b"])
def test_recipe_url_must_be_http(env, url):
    _, _, call = env
    with pytest.raises(ToolError):
        call("fetch_recipe", url=url)


def test_annotations(env):
    _, _, _ = env
    mcp = MCPServer("t")
    tools.register(mcp, FakeClient(), Store.__new__(Store))
    by_name = {t.name: t.annotations for t in asyncio.run(mcp.list_tools())}
    assert by_name["get_list"].read_only_hint is True
    assert by_name["remove_items"].destructive_hint is True
    assert by_name["set_staples_list"].destructive_hint is True
    assert by_name["add_items"].read_only_hint is False
