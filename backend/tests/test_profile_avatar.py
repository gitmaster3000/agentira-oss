"""Profile avatars: presets and uploaded images (inline data URLs) round-trip."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


@pytest.mark.parametrize("account_type", ["external_agent", "agentira_agent"])
def test_admin_sets_robot_avatar_on_bot_profiles(client, account_type):
    from backend import models
    from backend.db import SessionLocal

    with SessionLocal() as db:
        p = models.Profile(name=f"bot-{account_type}", display_name="Bot", account_type=account_type)
        db.add(p)
        db.commit()
        pid = p.id
    r = client.patch(f"/api/profiles/{pid}", json={"avatar_url": "bot:5"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/profiles/{pid}").json()["avatar_url"] == "bot:5"
