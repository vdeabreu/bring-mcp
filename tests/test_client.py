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
        self._Bring__translations = {"fr-FR": {"Eier": "Oeufs", "Tomaten": "Tomates", "Milch": "Lait"}}
        self.user_list_settings = {"u1": {"listArticleLanguage": locale}}
        self.reloads = 0
        self.lists = [("Courses", "u1")]
        self._locale = locale
        self.fail_once = fail_once
        self.calls = 0

    def _Bring__locale(self, list_uuid):
        return self._locale

    def _Bring__translate(self, item_id, *, to_locale):
        return item_id if to_locale == "de-CH" else self._Bring__translations[to_locale].get(item_id, item_id)

    async def reload_user_list_settings(self):
        self.reloads += 1
        self.user_list_settings["u2"] = {"listArticleLanguage": self._locale}

    async def reload_article_translations(self):
        pass

    async def load_lists(self):
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise BringAuthException("expired")

        lists = [type("L", (), {"name": name, "listUuid": uuid})() for name, uuid in self.lists]
        return type("R", (), {"lists": lists})()


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


def test_catalog_name_translates_other_languages():
    client = _client_with(FakeBring())
    assert asyncio.run(client.catalog_name("u1", "Milk")) == "Lait"
    assert asyncio.run(client.catalog_name("u1", "eggs")) == "Oeufs"
    assert asyncio.run(client.catalog_name("u1", "Lait")) == "Lait"


def test_catalog_name_does_not_return_keys_for_unknown_list_language():
    client = _client_with(FakeBring(locale="xx-XX"))
    assert asyncio.run(client.catalog_name("u1", "Milk")) == "Milk"


def test_lookup_matches_an_item_named_in_another_language():
    client = _client_with(FakeBring())
    items = [Item("1", "Lait", "1 L"), Item("2", "Oeufs", "")]
    assert asyncio.run(client.lookup("u1", items, "milk")).uuid == "1"
    assert asyncio.run(client.lookup("u1", items, "Oeuf")).uuid == "2"
    assert asyncio.run(client.lookup("u1", items, "Butter")) is None


def test_list_created_after_login_reloads_settings_once():
    fake = FakeBring()
    fake.lists.append(("Demo", "u2"))
    client = _client_with(fake)
    assert asyncio.run(client.resolve_list("Demo")) == ("u2", "Demo")
    assert asyncio.run(client.resolve_list("demo")) == ("u2", "Demo")
    assert asyncio.run(client.resolve_list("Courses")) == ("u1", "Courses")
    assert fake.reloads == 1
