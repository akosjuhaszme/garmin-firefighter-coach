"""
Unit tests for the Garmin Personal API client (personal_api.py)

A fake requests session stands in for personal.connectapi.garmin.com. No real key or token is used,
and the tests check that neither ever shows up in an error message.
"""
import json
from types import SimpleNamespace

import pytest

from garmin_workouts_mcp import personal_api
from garmin_workouts_mcp.personal_api import PersonalApiClient, PersonalApiError

KEY = "GCDC_fake-key-for-tests.1234567890"


def _resp(status, body=None, text=None):
    raw = text if text is not None else ("" if body is None else json.dumps(body))

    def parse():
        if body is None:
            raise ValueError("no json")
        return body

    return SimpleNamespace(status_code=status, text=raw, json=parse)


class FakeSession:
    def __init__(self, token_answers=None, get_answers=None):
        self.token_answers = list(token_answers or [_resp(200, {"access_token": "TOKEN-1", "expires_in": 86400})])
        self.get_answers = list(get_answers or [_resp(200, {"ok": True})])
        self.posts, self.gets = [], []

    def post(self, url, headers=None, timeout=None):
        self.posts.append((url, dict(headers or {})))
        return self.token_answers.pop(0) if len(self.token_answers) > 1 else self.token_answers[0]

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append((url, dict(params or {}), dict(headers or {})))
        return self.get_answers.pop(0) if len(self.get_answers) > 1 else self.get_answers[0]


def test_token_exchange_uses_the_key_header_and_the_documented_url():
    session = FakeSession()
    client = PersonalApiClient(key=KEY, session=session)
    assert client.token() == "TOKEN-1"
    url, headers = session.posts[0]
    assert url == "https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token"
    assert headers == {"Authorization": f"ApiKey {KEY}"}
    assert client.token_shape == ["access_token", "expires_in"]


def test_get_sends_a_bearer_token_and_drops_empty_params():
    session = FakeSession(get_answers=[_resp(200, [{"activityId": 1}])])
    client = PersonalApiClient(key=KEY, session=session)
    status, body = client.get("/activitylist-service/activities/search/activities", {"limit": 5, "start": None})
    assert (status, body) == (200, [{"activityId": 1}])
    url, params, headers = session.gets[0]
    assert url == "https://personal.connectapi.garmin.com/activitylist-service/activities/search/activities"
    assert params == {"limit": 5}
    assert headers == {"Authorization": "Bearer TOKEN-1"}


def test_token_is_reused_until_it_expires():
    now = [1000.0]
    session = FakeSession(token_answers=[
        _resp(200, {"accessToken": "TOKEN-A", "expires_in": 3600}),
        _resp(200, {"accessToken": "TOKEN-B", "expires_in": 3600}),
    ])
    client = PersonalApiClient(key=KEY, session=session, clock=lambda: now[0])
    assert client.token() == "TOKEN-A" and client.token() == "TOKEN-A"
    assert len(session.posts) == 1
    now[0] += 3600  # past the lifetime (minus the safety margin)
    assert client.token() == "TOKEN-B"
    assert len(session.posts) == 2


def test_a_401_gets_one_retry_with_a_fresh_token():
    session = FakeSession(
        token_answers=[_resp(200, {"token": "OLD"}), _resp(200, {"token": "NEW"})],
        get_answers=[_resp(401, {"message": "expired"}), _resp(200, {"ok": 1})],
    )
    client = PersonalApiClient(key=KEY, session=session)
    assert client.get("/userprofile-service/userprofile/settings") == (200, {"ok": 1})
    assert [g[2]["Authorization"] for g in session.gets] == ["Bearer OLD", "Bearer NEW"]
    # a second 401 is returned, not retried forever
    session2 = FakeSession(get_answers=[_resp(401, {"message": "no"})])
    assert PersonalApiClient(key=KEY, session=session2).get("/x")[0] == 401
    assert len(session2.gets) == 2


def test_other_token_answer_shapes():
    plain = FakeSession(token_answers=[_resp(200, None, text="PLAIN-TOKEN")])
    assert PersonalApiClient(key=KEY, session=plain).token() == "PLAIN-TOKEN"
    empty = FakeSession(token_answers=[_resp(200, {"unrelated": 1})])
    with pytest.raises(PersonalApiError, match="no token"):
        PersonalApiClient(key=KEY, session=empty).token()


def test_errors_never_contain_the_key_or_the_token():
    refused = FakeSession(token_answers=[_resp(403, {"message": f"bad {KEY}"}, text=f"bad {KEY}")])
    with pytest.raises(PersonalApiError) as caught:
        PersonalApiClient(key=KEY, session=refused).token()
    assert KEY not in str(caught.value) and "403" in str(caught.value)

    session = FakeSession(token_answers=[_resp(200, {"access_token": "SECRET-TOKEN"})],
                          get_answers=[_resp(500, None, text="boom SECRET-TOKEN boom")])
    client = PersonalApiClient(key=KEY, session=session)
    status, body = client.get("/x")
    assert status == 500 and "SECRET-TOKEN" not in body and "***" in body


def test_missing_key_is_explained_without_any_request(tmp_path, monkeypatch):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY", raising=False)
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY_FILE", str(tmp_path / "nothing.txt"))
    session = FakeSession()
    client = PersonalApiClient(session=session)
    assert client.configured is False
    with pytest.raises(PersonalApiError, match="No Personal API key"):
        client.token()
    assert session.posts == []


def test_key_comes_from_the_environment_or_a_file(tmp_path, monkeypatch):
    key_file = tmp_path / "key.txt"
    key_file.write_text("﻿  FILE-KEY \r\n", encoding="utf-8")
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY", raising=False)
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY_FILE", str(key_file))
    assert personal_api.load_key() == "FILE-KEY"  # BOM, spaces and the line break are ignored
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", " ENV-KEY ")
    assert personal_api.load_key() == "ENV-KEY"  # the environment wins
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY")
    key_file.write_text("   \n", encoding="utf-8")
    assert personal_api.load_key() is None


def test_find_values_digs_into_nested_json():
    data = {"a": {"sleepTimeSeconds": 25200, "list": [{"score": 81}, {"score": 70}]}, "score": {"x": 1}}
    assert personal_api.find_values(data, "sleepTimeSeconds") == [25200]
    assert personal_api.find_values(data, "score", limit=2) == [81, 70]
    assert personal_api.find_values(data, "missing") == []
