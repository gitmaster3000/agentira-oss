"""Profile avatars: presets and uploaded images (inline data URLs) round-trip."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend import avatars, mcp_server, services
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def test_preset_avatar_round_trips(client):
    r = client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": "preset:7"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/profiles/{client.admin_id}").json()["avatar_url"] == "preset:7"


def test_uploaded_data_url_longer_than_500_chars_round_trips(client):
    data_url = "data:image/jpeg;base64," + "A" * 6000
    r = client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": data_url})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/profiles/{client.admin_id}").json()["avatar_url"] == data_url


def test_empty_avatar_resets_to_default(client):
    client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": "preset:2"})
    client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": ""})
    assert client.get(f"/api/profiles/{client.admin_id}").json()["avatar_url"] == ""


# ── Bot-set pictures: validation + MCP ────────────────────────────────────────

PNG = "data:image/png;base64," + base64.b64encode(b"x" * 1000).decode()
BIG = "data:image/png;base64," + base64.b64encode(b"x" * (avatars.MAX_IMAGE_BYTES + 10)).decode()


@contextmanager
def _actor(name):
    token = mcp_server.actor_ctx.set(name)
    try:
        yield
    finally:
        mcp_server.actor_ctx.reset(token)


@pytest.fixture
def bots(pg):
    services.create_service_account("bot-a")
    services.create_service_account("bot-b")


def _avatar(name):
    with services._session() as db:
        return services._get_profile_by_name(db, name).avatar_url


def _mcp_set(name, value):
    with _actor(name):
        return asyncio.run(mcp_server.update_profile(avatar_url=value))


def test_bot_lists_choices_and_current_picture(bots):
    _mcp_set("bot-a", "bot:2")
    with _actor("bot-a"):
        out = asyncio.run(mcp_server.list_avatar_choices())
    assert out["current"] == "bot:2"
    assert [s["value"] for s in out["robot_styles"]] == [f"bot:{i}" for i in range(len(avatars.BOT_STYLES))]
    assert all(s["label"] for s in out["robot_styles"])
    assert out["max_image_kb"] == 200


@pytest.mark.parametrize("value", ["bot:0", "https://example.com/a.png", PNG])
def test_bot_sets_robot_link_or_small_image(bots, value):
    _mcp_set("bot-a", value)
    assert _avatar("bot-a") == value


@pytest.mark.parametrize("value", [
    BIG,
    "data:text/html;base64,AAAA",
    "data:image/svg+xml;base64,AAAA",
    "data:image/png;base64,@@@@",
    "http://example.com/a.png",
    "javascript:alert(1)",
    "https://example.com/" + "a" * 1000,
    f"bot:{len(avatars.BOT_STYLES)}",
    "bot:x",
    "just text",
])
def test_invalid_picture_refused_and_old_stays(bots, value):
    _mcp_set("bot-a", "bot:1")
    with pytest.raises(ValueError) as e:
        _mcp_set("bot-a", value)
    assert "Allowed pictures" in str(e.value)
    assert _avatar("bot-a") == "bot:1"


def test_oversized_image_refused_over_rest_with_plain_message(client):
    client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": "preset:3"})
    r = client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": BIG})
    assert r.status_code == 400
    assert "too big" in r.text
    assert client.get(f"/api/profiles/{client.admin_id}").json()["avatar_url"] == "preset:3"


def test_bot_style_accepted_over_rest(client):
    r = client.patch(f"/api/profiles/{client.admin_id}", json={"avatar_url": "bot:1"})
    assert r.status_code == 200, r.text


def test_bot_cannot_change_another_profile(bots):
    _mcp_set("bot-b", "bot:3")
    _mcp_set("bot-a", "bot:0")
    assert _avatar("bot-b") == "bot:3"
    assert "profile_id" not in mcp_server.update_profile.__code__.co_varnames[:mcp_server.update_profile.__code__.co_argcount]
