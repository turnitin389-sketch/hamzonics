"""Admin portal: login, add keys, automatic rotation when a key runs out of credits."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

H = {"X-Requested-With": "hamzonics"}
KEY1, KEY2, KEY3 = "a" * 40, "b" * 40, "c" * 40


@pytest.fixture()
def admin(client: TestClient, monkeypatch):  # type: ignore[no-untyped-def]
    from api.config import get_settings

    monkeypatch.setenv("ADMIN_PASSWORD", "correct horse battery staple")
    get_settings.cache_clear()
    from api.routers import admin as admin_router

    admin_router._failures.clear()
    r = client.post("/api/admin/login", json={"password": "correct horse battery staple"}, headers=H)
    assert r.status_code == 200
    return client


def test_portal_disabled_without_password(client: TestClient) -> None:
    assert client.get("/api/admin/keys", headers=H).status_code == 404


def test_login_rules(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from api.config import get_settings
    from api.routers import admin as admin_router

    monkeypatch.setenv("ADMIN_PASSWORD", "secret-password-123")
    get_settings.cache_clear()
    admin_router._failures.clear()
    assert client.get("/api/admin/keys", headers=H).status_code == 401
    assert client.post("/api/admin/login", json={"password": "secret-password-123"}).status_code == 403  # no header
    for _ in range(5):
        assert client.post("/api/admin/login", json={"password": "nope"}, headers=H).status_code == 401
    assert client.post("/api/admin/login", json={"password": "secret-password-123"}, headers=H).status_code == 429


def test_add_list_and_manage_keys(admin: TestClient) -> None:
    r = admin.post("/api/admin/keys", json={"keys": f"{KEY1}\n{KEY2}, {KEY1}"}, headers=H)
    assert r.status_code == 200
    keys = r.json()
    assert [k["masked"][-4:] for k in keys] == ["aaaa", "bbbb"]  # duplicate dropped, order kept
    assert [k["status"] for k in keys] == ["in use", "waiting"]
    assert all(KEY1 not in json.dumps(k) for k in keys)  # the key itself is never sent back
    assert admin.post("/api/admin/keys", json={"keys": "short"}, headers=H).status_code == 422
    k2 = keys[1]["id"]
    keys = admin.patch(f"/api/admin/keys/{k2}", json={"move": "up"}, headers=H).json()
    assert [k["masked"][-4:] for k in keys] == ["bbbb", "aaaa"]
    keys = admin.patch(f"/api/admin/keys/{k2}", json={"active": False}, headers=H).json()
    assert keys[0]["status"] == "disabled" and keys[1]["status"] == "in use"
    keys = admin.delete(f"/api/admin/keys/{k2}", headers=H).json()
    assert len(keys) == 1
    assert admin.get("/api/admin/stats", headers=H).json()["usable_keys"] == 1


def test_key_rotation_when_credits_run_out(admin: TestClient) -> None:
    from engine.similarity.web import SerperProvider
    from worker.key_pool import KeyPool

    admin.post("/api/admin/keys", json={"keys": f"{KEY1} {KEY2} {KEY3}"}, headers=H)
    seen: list[str] = []

    def serper(request: httpx.Request) -> httpx.Response:
        key = request.headers["X-API-KEY"]
        seen.append(key[0])
        if key == KEY1:
            return httpx.Response(403, json={"message": "Not enough credits"})
        return httpx.Response(200, json={"organic": [{"link": "https://example.org/page"}]})

    pool = KeyPool("serper")
    p = SerperProvider(pool, httpx.Client(transport=httpx.MockTransport(serper)))
    assert p.urls("some phrase", 5) == ["https://example.org/page"]
    assert p.urls("another phrase", 5) == ["https://example.org/page"]
    assert seen == ["a", "b", "b"]  # key 1 tried once, then key 2 for this and later searches
    pool.flush_usage()

    keys = admin.get("/api/admin/keys", headers=H).json()
    assert [k["status"] for k in keys] == ["used up", "in use", "waiting"]
    assert "Not enough credits" in keys[0]["last_error"]
    assert [k["searches_used"] for k in keys] == [0, 2, 0]

    # After buying more credits the admin resets key 1: it is used first again.
    keys = admin.patch(f"/api/admin/keys/{keys[0]['id']}", json={"reset": True}, headers=H).json()
    assert keys[0]["status"] == "in use"


def test_all_keys_used_up_means_search_unavailable(admin: TestClient) -> None:
    from engine.similarity.web import SerperProvider
    from worker.key_pool import KeyPool

    admin.post("/api/admin/keys", json={"keys": KEY1}, headers=H)
    p = SerperProvider(KeyPool("serper"), httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(403, json={"message": "Not enough credits"}))))
    assert p.urls("x y z", 5) == [] and p.failed == 1 and p.ok == 0
