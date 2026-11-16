"""Name matching, catalog lookup and re-login of the Bring client."""

import asyncio

import pytest
from bring_api.exceptions import BringAuthException

from bring_mcp.bring_client import BringClient, Item, find, merge_spec, normalize


@pytest.mark.parametrize(
    ("a", "b"),
    [("Œufs", "oeuf"), ("Tomates", "tomate"), ("Crème fraîche", "creme fraiche"), ("Noix", "noix"), ("LAIT", "lait")],
)
def test_normalize_matches_variants(a, b):
    assert normalize(a) == normalize(b)


def test_normalize_keeps_short_words():
    assert normalize("gaz") == "gaz" and normalize("bus") == "bus"


def test_find():
    items = [Item("1", "Tomates", ""), Item("2", "Lait", "")]
    assert find(items, "tomate").uuid == "1"
    assert find(items, "beurre") is None


@pytest.mark.parametrize(
    ("old", "new", "merged"),
    [("", "6", "6"), ("6", "", "6"), ("6", "6", "6"), ("1 L", "2 L", "1 L + 2 L"), ("bio", "BIO", "BIO")],
)
def test_merge_spec(old, new, merged):
    assert merge_spec(old, new) == merged


class FakeBring:
    """Stands in for bring_api.Bring, including the private attributes the client reads."""

    def __init__(self, locale="fr-FR", fail_once=False):
        self._Bring__translations = {"fr-FR": {"Eier": "Oeufs", "Tomaten": "Tomates"}}
        self._locale = locale
        self.fail_once = fail_once
        self.calls = 0

    def _Bring__locale(self, list_uuid):
        return self._locale

    async def load_lists(self):
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise BringAuthException("expired")

        class L:
            name, listUuid = "Courses", "u1"

        return type("R", (), {"lists": [L()]})()


def _client_with(*fakes):
    client = BringClient("me@example.com", "pw", None)
    queue = list(fakes)

    async def bring():
        if client._bring is None:
            client._bring = queue.pop(0)
        return client._bring

    async def close():
        client._bring = None

    client.bring = bring
    client.close = close
    return client


def test_catalog_name_uses_list_language():
    client = _client_with(FakeBring())
    assert asyncio.run(client.catalog_name("u1", "œuf")) == "Oeufs"
    assert asyncio.run(client.catalog_name("u1", " Quinoa ")) == "Quinoa"


def test_catalog_name_for_swiss_german_list_uses_catalog_keys():
    client = _client_with(FakeBring(locale="de-CH"))
    assert asyncio.run(client.catalog_name("u1", "eier")) == "Eier"


def test_catalog_for_swiss_german_list_without_any_table():
    fake = FakeBring(locale="de-CH")
    fake._Bring__translations = {}  # account with de-CH lists only: bring-api loads nothing
    client = _client_with(fake)
    assert asyncio.run(client.catalog_name("u1", "tomaten")) == "Tomaten"


def test_relogin_once_when_session_expired():
    first, second = FakeBring(fail_once=True), FakeBring()
    client = _client_with(first, second)
    assert asyncio.run(client.lists()) == [{"name": "Courses", "uuid": "u1"}]
    assert first.calls == 1 and second.calls == 1


def test_failed_login_is_not_retried():
    client = BringClient("me@example.com", "wrong", None)
    attempts = 0

    async def bring():
        nonlocal attempts
        attempts += 1
        raise BringAuthException("bad credentials")

    client.bring = bring
    with pytest.raises(BringAuthException):
        asyncio.run(client.lists())
    assert attempts == 1


def test_from_env_requires_credentials(monkeypatch):
    monkeypatch.delenv("BRING_EMAIL", raising=False)
    monkeypatch.delenv("BRING_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        BringClient.from_env()
