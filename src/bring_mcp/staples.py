"""Staple items, and a command that adds the missing ones to the list (no LLM involved).

Run it from cron, e.g. every Saturday at 9:00:
    0 9 * * 6  docker exec bring-mcp python -m bring_mcp.staples
"""

import asyncio

from bring_api import BringItemOperation

from .bring_client import BringClient, find
from .store import Store, db_path


def get_staples(store: Store) -> list[dict[str, str]]:
    return (store.get("staples", "default") or {}).get("items", [])


def set_staples(store: Store, items: list[dict[str, str]]) -> None:
    store.put("staples", "default", {"items": items})


async def add_missing_staples(client: BringClient, store: Store, list_name: str | None = None) -> dict:
    list_uuid, name = await client.resolve_list(list_name)
    to_buy, _ = await client.items(list_uuid)
    changes = []
    for staple in get_staples(store):
        if find(to_buy, staple["name"]):
            continue
        item_id = await client.catalog_name(list_uuid, staple["name"])
        changes.append({"itemId": item_id, "spec": staple.get("spec", ""), "uuid": None})
    await client.apply(list_uuid, changes, BringItemOperation.ADD)
    return {"list": name, "added": [c["itemId"] for c in changes]}


async def _main() -> None:
    client = BringClient.from_env()
    try:
        result = await add_missing_staples(client, Store(db_path()))
    finally:
        await client.close()
    print(f"{result['list']}: {', '.join(result['added']) or 'nothing to add'}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
