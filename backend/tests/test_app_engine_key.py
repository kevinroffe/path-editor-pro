import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import app as app_module

FIXTURE = Path(__file__).parent / "fixtures" / "revit_level.json"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("QBIQ_ENGINE_KEY", "s3cret")


def test_missing_key_403_when_set(client, keyed):
    resp = client.get("/api/demo")
    assert resp.status_code == 403


def test_wrong_key_403(client, keyed):
    assert client.get("/api/demo", headers={"X-Qbiq-Key": "nope"}).status_code == 403


def test_right_key_ok(client, keyed):
    assert client.get("/api/demo", headers={"X-Qbiq-Key": "s3cret"}).status_code == 200


def test_no_key_env_allows_all(client, monkeypatch):
    monkeypatch.delenv("QBIQ_ENGINE_KEY", raising=False)
    assert client.get("/api/demo").status_code == 200


def test_static_assets_need_no_key(client, keyed):
    assert client.get("/").status_code == 200
    assert client.get("/frontend/img/qbiq-logo.svg").status_code == 200


def test_non_ascii_room_name_round_trips_through_upload(client):
    p = copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    p["rooms"].append({"id": "x", "name": "Café Lounge", "number": "300", "polygon": None, "area": 0.0,
                       "placed": False, "enclosed": False})
    body = client.post("/api/upload-revit", json=p).get_json()
    assert body["room_issues"] == [{"room_id": "x", "name": "Café Lounge", "problem": "unplaced"}]


def test_run_refuses_remote_host_without_flag():
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "run.py"), "--host", "0.0.0.0", "--port", "5999"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "--allow-remote" in (r.stdout + r.stderr)
