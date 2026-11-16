"""Thin async wrapper around bring-api: one logged-in session, lists by name.

bring-api keeps the catalog translations and the list locales private, so a few
helpers below reach into its name-mangled attributes. bring-api is pinned in
pyproject.toml for that reason; the tests cover these helpers.
"""

import asyncio
import os
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
        self._catalogs: dict[str, dict[str, str]] = {}
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
                self._bring = bring
            return self._bring

    async def close(self) -> None:
        async with self._lock:
            if self._bring is not None:
                await self._bring._session.close()
                self._bring = None
                self._catalogs.clear()

    async def _call(self, op: Callable[[Bring], Awaitable[T]]) -> T:
        """Run `op`; if Bring rejects the session (refresh token expired), log in again once."""
        try:
            return await op(await self.bring())
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
            return lists[0]["uuid"], lists[0]["name"]
        for lst in lists:
            if wanted == lst["uuid"] or lst["name"].casefold() == wanted.casefold():
                return lst["uuid"], lst["name"]
        raise ValueError(f"Unknown list: {wanted}. Available lists: {', '.join(lst['name'] for lst in lists)}")

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
        Bring files it under the right section with its icon; unknown names pass through."""
        bring = await self.bring()
        locale = bring._Bring__locale(list_uuid)
        if locale not in self._catalogs:
            translations: dict[str, dict[str, str]] = bring._Bring__translations
            if locale in translations:
                names = translations[locale].values()
            else:
                # Bring's catalog keys are Swiss German, so a de-CH list has no translation table.
                names = next(iter(translations.values()), {}).keys() if locale == BRING_DEFAULT_LOCALE else []
            self._catalogs[locale] = {normalize(v): v for v in names}
        return self._catalogs[locale].get(normalize(name), name.strip())

    @staticmethod
    def _to_list_language(bring: Bring, list_uuid: str, item_id: str) -> str:
        # The recipe parser returns catalog keys (Swiss German).
        try:
            return bring._Bring__translate(item_id, to_locale=bring._Bring__locale(list_uuid))
        except Exception:
            return item_id


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
