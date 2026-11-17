"""Thin async wrapper around bring-api: one logged-in session, lists by name.

bring-api keeps the catalog translations and the list locales private, so a few
helpers below reach into its name-mangled attributes. bring-api is pinned in
pyproject.toml for that reason; the tests cover these helpers.
"""

import asyncio
import json
import os
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import TypeVar

import aiohttp
from bring_api import Bring, BringItemOperation
from bring_api.const import BRING_DEFAULT_LOCALE
from bring_api.exceptions import BringAuthException

T = TypeVar("T")


@dataclass
class Item:
    uuid: str
    name: str
    spec: str


class BringClient:
    def __init__(self, email: str, password: str, default_list: str | None):
        self.email = email
        self.password = password
        self.default_list = default_list or None
        self._bring: Bring | None = None
        self._session: aiohttp.ClientSession | None = None
        self._catalogs: dict[str, dict[str, str]] = {}
        self._settings_checked: set[str] = set()
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "BringClient":
        email, password = os.environ.get("BRING_EMAIL"), os.environ.get("BRING_PASSWORD")
        if not email or not password:
            raise SystemExit("BRING_EMAIL and BRING_PASSWORD must be set")
        return cls(email, password, os.environ.get("BRING_DEFAULT_LIST"))

    async def bring(self) -> Bring:
        async with self._lock:
            if self._bring is None:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
                bring = Bring(session, self.email, self.password)
                try:
                    await bring.login()  # also loads list settings and catalog translations
                except BaseException:
                    await session.close()
                    raise
                self._bring, self._session = bring, session
            return self._bring

    async def close(self) -> None:
        async with self._lock:
            if self._session is not None:
                await self._session.close()
            self._bring = self._session = None
            self._catalogs.clear()
            self._settings_checked.clear()

    async def _call(self, op: Callable[[Bring], Awaitable[T]]) -> T:
        """Run `op`; if Bring rejects an existing session (refresh token expired), log in again once.

        A failed *login* is not retried: wrong credentials would otherwise double the login
        attempts on every tool call, which could get the Bring account rate-limited."""
        bring = await self.bring()
        try:
            return await op(bring)
        except BringAuthException:
            await self.close()
            return await op(await self.bring())

    async def lists(self) -> list[dict[str, str]]:
        response = await self._call(lambda b: b.load_lists())
        return [{"name": lst.name, "uuid": lst.listUuid} for lst in response.lists]

    async def resolve_list(self, name_or_uuid: str | None) -> tuple[str, str]:
        """Return (uuid, name) for a list name or uuid; default list if None."""
        lists = await self.lists()
        if not lists:
            raise ValueError("This Bring! account has no shopping list")
        wanted = name_or_uuid or self.default_list
        if not wanted:
            await self._ensure_list_settings(lists[0]["uuid"])
            return lists[0]["uuid"], lists[0]["name"]
        for lst in lists:
            if wanted == lst["uuid"] or lst["name"].casefold() == wanted.casefold():
                await self._ensure_list_settings(lst["uuid"])
                return lst["uuid"], lst["name"]
        raise ValueError(f"Unknown list: {wanted}. Available lists: {', '.join(lst['name'] for lst in lists)}")

    async def _ensure_list_settings(self, list_uuid: str) -> None:
        """bring-api reads list settings once, at login. A list created since then has none, so
        its items would be translated with the account language instead of the list's. Reload
        the settings and translations the first time such a list is used."""
        if list_uuid in self._settings_checked:
            return
        bring = await self.bring()
        if list_uuid not in bring.user_list_settings:
            await self._call(lambda b: b.reload_user_list_settings())
            await self._call(lambda b: b.reload_article_translations())
            self._catalogs.clear()
        self._settings_checked.add(list_uuid)

    async def items(self, list_uuid: str) -> tuple[list[Item], list[Item]]:
        """(to buy, recently bought). Names are in the list's language."""
        data = (await self._call(lambda b: b.get_list(list_uuid))).items

        def to_item(p) -> Item:
            return Item(p.uuid, p.itemId, p.specification)

        return [to_item(p) for p in data.purchase], [to_item(p) for p in data.recently]

    async def apply(self, list_uuid: str, changes: list[dict], operation: BringItemOperation) -> None:
        if changes:
            await self._call(lambda b: b.batch_update_list(list_uuid, changes, operation))

    async def parse_recipe(self, list_uuid: str, url: str) -> dict:
        recipe = await self._call(lambda b: b.parse_recipe(url))
        bring = await self.bring()
        ingredients = recipe.items or recipe.ingredients
        return {
            "name": recipe.name or recipe.title,
            "servings": recipe.baseQuantity,
            "ingredients": [
                {"name": self._to_list_language(bring, list_uuid, i.itemId), "spec": i.spec or "", "pantry": i.stock}
                for i in ingredients
            ],
        }

    async def catalog_name(self, list_uuid: str, name: str) -> str:
        """Catalog spelling of `name` in the list's language ("œuf" -> "Oeufs"), so
        Bring files it under the right section with its icon. A catalog name in another
        language is translated ("Milk" -> "Lait" on a French list); unknown names pass through."""
        bring = await self.bring()
        local = self._local_catalog(bring, list_uuid)
        if hit := local.get(normalize(name)):
            return hit
        key = _catalog_keys_any_language().get(normalize(name))
        locale = bring._Bring__locale(list_uuid)
        if key and (locale == BRING_DEFAULT_LOCALE or locale in bring._Bring__translations):
            return self._to_list_language(bring, list_uuid, key)
        return name.strip()

    async def lookup(self, list_uuid: str, items: list[Item], name: str) -> Item | None:
        """The item of `items` that `name` designates, by name or by catalog entry."""
        return find(items, name) or find(items, await self.catalog_name(list_uuid, name))

    def _local_catalog(self, bring: Bring, list_uuid: str) -> dict[str, str]:
        locale = bring._Bring__locale(list_uuid)
        if locale not in self._catalogs:
            translations: dict[str, dict[str, str]] = bring._Bring__translations
            if locale in translations:
                names = translations[locale].values()
            elif locale == BRING_DEFAULT_LOCALE:
                # Bring's catalog keys are Swiss German, so bring-api loads no table for de-CH lists.
                names = _bundled_catalog_keys()
            else:
                names = []
            self._catalogs[locale] = {normalize(v): v for v in names}
        return self._catalogs[locale]

    @staticmethod
    def _to_list_language(bring: Bring, list_uuid: str, item_id: str) -> str:
        # The recipe parser returns catalog keys (Swiss German).
        try:
            return bring._Bring__translate(item_id, to_locale=bring._Bring__locale(list_uuid))
        except Exception:
            return item_id


def _bundled_catalog_keys() -> list[str]:
    """Catalog item ids, from the translation table bring-api ships for de-CH."""
    path = resources.files("bring_api") / "locales" / f"articles.{BRING_DEFAULT_LOCALE}.json"
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


@cache
def _catalog_keys_any_language() -> dict[str, str]:
    """Normalized catalog name in any language bring-api ships -> catalog key.

    English tables come first, then the others alphabetically: when two languages use the
    same word for different items, the first one wins."""
    folder = resources.files("bring_api") / "locales"
    files = sorted(
        (f for f in folder.iterdir() if f.name.startswith("articles.") and f.name.endswith(".json")),
        key=lambda f: (not f.name.startswith("articles.en-"), f.name),
    )
    index: dict[str, str] = {}
    for f in files:
        try:
            table = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, value in table.items():
            index.setdefault(normalize(key), key)
            index.setdefault(normalize(value), key)
    return index


def normalize(name: str) -> str:
    """Loose key for matching names: no case, accents, ligatures or plural s/x."""
    name = name.casefold().replace("œ", "oe").replace("æ", "ae")
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", name)
    return " ".join(w[:-1] if len(w) > 3 and w[-1] in "sx" else w for w in words)


def find(items: list[Item], name: str) -> Item | None:
    key = normalize(name)
    return next((i for i in items if normalize(i.name) == key), None)


def merge_spec(old: str, new: str) -> str:
    old, new = old.strip(), new.strip()
    if not old or old.casefold() == new.casefold():
        return new or old
    if not new:
        return old
    return f"{old} + {new}"
