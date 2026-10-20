"""
Unit tests for the PacePro tools (pacepro.py)

A small stateful fake stands in for course-service/pacebands. It checks a new plan the way the real
server did when it was probed with deliberately invalid bodies: paceBandSummary needs name, goalTime,
goalSpeed, splitType (DISTANCE_KILOMETER / DISTANCE_MILE / ELEVATION) and totalDistance, and
paceBandSplits needs at least one split with splitDistance, splitAvgSpeed, cumulativeDistanceFromStart
and cumulativeTimeFromStart. garth raises GarthHTTPError for every error status.
"""
import copy
import itertools
import json
from types import SimpleNamespace

import pytest
from garth.exc import GarthHTTPError
from mcp.server.fastmcp import FastMCP
from requests import HTTPError

from garmin_workouts_mcp import pacepro

_SPLIT_TYPES = {"DISTANCE_KILOMETER", "DISTANCE_MILE", "ELEVATION"}
_SUMMARY_FIELDS = ("goalSpeed", "goalTime", "name", "splitType", "totalDistance")
_SPLIT_FIELDS = ("cumulativeDistanceFromStart", "cumulativeTimeFromStart", "splitAvgSpeed", "splitDistance")


def _response(status, body=None):
    text = "" if body is None else json.dumps(body)
    return SimpleNamespace(status_code=status, text=text, json=lambda: body)


class FakePaceBands:
    def __init__(self):
        self.store = {}
        self.calls = []
        self._ids = itertools.count(500)
        self.devices = [{"deviceId": 111, "productDisplayName": "watch one", "primary": True}]
        self.send_status = 200
        self.sent = []

    def _fail(self, status, body):
        raise GarthHTTPError(msg="Error in request", error=HTTPError(response=_response(status, body)))

    def _validate(self, body):
        errors = []
        summary, splits = body.get("paceBandSummary"), body.get("paceBandSplits")
        if summary is None:
            errors.append("'createPaceBand.arg1.paceBandSummary' must not be null (provided value: null)")
        else:
            for field in _SUMMARY_FIELDS:
                if summary.get(field) is None:
                    errors.append(f"'createPaceBand.arg1.paceBandSummary.{field}' must not be null (provided value: null)")
            if summary.get("splitType") is not None and summary["splitType"] not in _SPLIT_TYPES:
                self._fail(400, {"message": f"Invalid value '{summary['splitType']}' for paceBandSummary.splitType",
                                 "error": "InvalidFormatException"})
        if not splits:
            errors.append("'createPaceBand.arg1.paceBandSplits' size must be between 1 and 2147483647")
        else:
            for number, split in enumerate(splits):
                for field in _SPLIT_FIELDS:
                    if split.get(field) is None:
                        errors.append(f"'createPaceBand.arg1.paceBandSplits[{number}].{field}' must not be null")
        if errors:
            self._fail(400, {"errors": errors})

    def request(self, method, subdomain, path, api=False, json=None, **kw):
        self.calls.append((method, path))
        if path == "device-service/deviceregistration/devices" and method == "GET":
            return _response(200, copy.deepcopy(self.devices))
        if "/device/" in path and method == "POST":  # course-service/pacebands/{id}/device/{deviceId}
            plan_id, device_id = int(path.split("/")[2]), int(path.split("/")[4])
            if plan_id not in self.store:
                self._fail(404, {"message": "not found"})
            if self.send_status >= 400:
                self._fail(self.send_status, {"message": "device refused"})
            self.sent.append((plan_id, device_id))
            return _response(self.send_status)
        if path == "course-service/pacebands" and method == "GET":
            return _response(200, copy.deepcopy(list(self.store.values())))
        if path == "course-service/pacebands" and method == "POST":
            self._validate(json)
            plan = copy.deepcopy(json)
            plan["paceBandSummary"]["paceBandPk"] = next(self._ids)
            self.store[plan["paceBandSummary"]["paceBandPk"]] = plan
            return _response(200, copy.deepcopy(plan))
        plan_id = int(path.rsplit("/", 1)[1])
        if plan_id not in self.store:
            self._fail(404, {"message": "not found"})
        if method == "GET":
            return _response(200, copy.deepcopy(self.store[plan_id]))
        if method == "DELETE":
            del self.store[plan_id]
            return _response(204)
        raise AssertionError((method, path))

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PUT", "DELETE")]


@pytest.fixture
def fake():
    return FakePaceBands()


@pytest.fixture
def app(fake):
    pacepro.configure(SimpleNamespace(garth=fake))
    application = FastMCP("Test pacepro")
    pacepro.register_tools(application)
    return application


async def call(app, name, args):
    return (await app.call_tool(name, args))[0][0].text


async def call_json(app, name, args):
    return json.loads(await call(app, name, args))


# ----------------------------------------------------------- split math


def test_even_splits_add_up_and_end_with_a_partial_split():
    splits = pacepro.build_splits(21097.5, 6120, 1000.0)
    assert len(splits) == 22
    assert [s["splitDistance"] for s in splits[:21]] == [1000.0] * 21
    assert splits[-1]["splitDistance"] == 97.5
    assert splits[-1]["cumulativeDistanceFromStart"] == 21097.5
    assert splits[-1]["cumulativeTimeFromStart"] == 6120.0
    assert {round(s["splitAvgSpeed"], 6) for s in splits} == {round(21097.5 / 6120, 6)}  # even pace


def test_exact_distance_has_no_empty_last_split():
    splits = pacepro.build_splits(10000.0, 3000, 1000.0)
    assert len(splits) == 10
    assert splits[-1]["cumulativeDistanceFromStart"] == 10000.0


def test_negative_split_second_half_is_faster_and_still_finishes_on_time():
    splits = pacepro.build_splits(20000.0, 6000, 1000.0, second_half_faster_percent=4.0)
    first_half = [s["splitAvgSpeed"] for s in splits[:10]]
    second_half = [s["splitAvgSpeed"] for s in splits[10:]]
    assert max(first_half) < min(second_half)
    assert second_half[0] / first_half[0] == pytest.approx(1 / 0.96, rel=1e-4)  # pace 4 % faster = speed 1/0.96
    assert splits[-1]["cumulativeTimeFromStart"] == pytest.approx(6000, abs=0.01)


def test_split_that_straddles_the_halfway_point_mixes_both_paces():
    splits = pacepro.build_splits(21097.5, 6000, 1000.0, second_half_faster_percent=4.0)
    straddling = splits[10]  # 10-11 km contains the halfway point 10.5487 km
    first, last = splits[9]["splitAvgSpeed"], splits[11]["splitAvgSpeed"]
    assert first < straddling["splitAvgSpeed"] < last


def test_positive_split_and_mile_splits():
    splits = pacepro.build_splits(42195.0, 14400, 1609.344, second_half_faster_percent=-3.0)
    assert splits[0]["splitDistance"] == 1609.344
    assert splits[0]["splitAvgSpeed"] > splits[-2]["splitAvgSpeed"]  # slower at the end
    assert splits[-1]["cumulativeTimeFromStart"] == pytest.approx(14400, abs=0.01)
    assert len(splits) == 27


@pytest.mark.parametrize("text, metres", [
    ("half", 21097.5), ("Half Marathon", 21097.5), ("marathon", 42195.0), ("5k", 5000.0), ("10", 10000.0),
    ("30", 30000.0), ("42,2", 42195.0), ("15km", 15000.0), ("21.1", 21097.5),
])
def test_parse_distance(text, metres):
    assert pacepro._parse_distance(text) == pytest.approx(metres, rel=0.001)


@pytest.mark.parametrize("text", ["far", "0.5", "300", ""])
def test_parse_distance_rejects(text):
    with pytest.raises(ValueError):
        pacepro._parse_distance(text)


# ------------------------------------------------------------- the tools


@pytest.mark.asyncio
async def test_create_previews_by_default_and_writes_nothing(app, fake):
    data = await call_json(app, "create_pacepro_plan", {"name": "City Half", "distance": "half", "goal_time": "1:42:00"})
    assert data["status"] == "preview"
    plan = data["plan"]
    assert plan["distance_km"] == 21.098 and plan["goal_time"] == "1:42:00" and len(plan["splits"]) == 22
    assert plan["splits"][0]["pace"] == "4:50/km"  # 6120 s / 21.0975 km = 4:50 per km
    assert plan["splits"][-1]["elapsed"] == "1:42:00"
    assert fake.writes() == []


@pytest.mark.asyncio
async def test_create_saves_a_body_the_server_accepts(app, fake):
    data = await call_json(app, "create_pacepro_plan", {
        "name": "City Half", "distance": "half", "goal_time": "1:42:00", "save": True,
    })
    assert data["status"] == "saved"
    assert data["plan"]["plan_id"] == 500 and data["plan"]["splits"] == 22
    stored = fake.store[500]["paceBandSummary"]
    assert stored["splitType"] == "DISTANCE_KILOMETER"
    assert stored["totalDistance"] == 21097.5 and stored["goalTime"] == 6120.0
    assert stored["goalSpeed"] == pytest.approx(21097.5 / 6120, abs=1e-5)
    assert stored["manualPaceEdit"] is False
    assert [c[0] for c in fake.writes()] == ["POST"]


@pytest.mark.asyncio
async def test_negative_split_plan_is_marked_as_edited_and_miles_use_the_mile_type(app, fake):
    data = await call_json(app, "create_pacepro_plan", {
        "name": "Marathon plan", "distance": "marathon", "goal_time": "3:30:00",
        "split_unit": "mile", "second_half_faster_percent": 2.5, "save": True,
    })
    assert data["status"] == "saved"
    stored = fake.store[data["plan"]["plan_id"]]["paceBandSummary"]
    assert stored["splitType"] == "DISTANCE_MILE" and stored["manualPaceEdit"] is True
    assert data["splits"][0]["pace"].endswith("/mi")
    assert data["splits"][0]["pace"] != data["splits"][-2]["pace"]  # the second half runs at another pace


@pytest.mark.asyncio
async def test_create_refuses_a_second_plan_with_the_same_name(app, fake):
    args = {"name": "City Half", "distance": "half", "goal_time": "1:42:00", "save": True}
    await call_json(app, "create_pacepro_plan", args)
    again = await call_json(app, "create_pacepro_plan", {**args, "name": "  city   half "})
    assert again["status"] == "duplicate"
    assert again["existing_plan"]["plan_id"] == 500
    assert len(fake.store) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("args, fragment", [
    ({"name": " ", "distance": "half", "goal_time": "1:42:00"}, "name"),
    ({"name": "x", "distance": "far", "goal_time": "1:42:00"}, "distance"),
    ({"name": "x", "distance": "half", "goal_time": "fast"}, "goal_time"),
    ({"name": "x", "distance": "half", "goal_time": "0:30:00"}, "realistic"),
    ({"name": "x", "distance": "half", "goal_time": "9:00:00"}, "realistic"),
    ({"name": "x", "distance": "half", "goal_time": "1:42:00", "split_unit": "yard"}, "split_unit"),
    ({"name": "x", "distance": "half", "goal_time": "1:42:00", "second_half_faster_percent": 25}, "between"),
    ({"name": "x" * 101, "distance": "half", "goal_time": "1:42:00"}, "too long"),
])
async def test_create_rejects_bad_input_without_writing(app, fake, args, fragment):
    text = await call(app, "create_pacepro_plan", {**args, "save": True})
    assert text.startswith("Error") and fragment in text
    assert fake.writes() == []


@pytest.mark.asyncio
async def test_create_passes_garmin_rejection_through(app, fake):
    original = fake._validate

    def strict(body):
        fake._fail(400, {"errors": ["'createPaceBand.arg1.paceBandSummary.distanceUnit' is wrong"]})

    fake._validate = strict
    data = await call_json(app, "create_pacepro_plan", {"name": "x", "distance": "10k", "goal_time": "0:50", "save": True})
    fake._validate = original
    assert data["status"] == "failed" and data["http_status"] == 400
    assert "distanceUnit" in data["message"] and "Nothing was stored" in data["note"]
    assert fake.store == {}


@pytest.mark.asyncio
async def test_get_pacepro_plans(app, fake):
    assert await call(app, "get_pacepro_plans", {}) == "No PacePro plans found."
    await call_json(app, "create_pacepro_plan", {"name": "City Half", "distance": "half", "goal_time": "1:42:00", "save": True})
    listing = await call_json(app, "get_pacepro_plans", {})
    assert listing["count"] == 1
    row = listing["plans"][0]
    assert (row["plan_id"], row["name"], row["distance_km"], row["goal_time"], row["splits"]) == (500, "City Half", 21.098, "1:42:00", 22)
    detail = await call_json(app, "get_pacepro_plans", {"plan_id": 500})
    assert detail["plan"]["split_type"] == "DISTANCE_KILOMETER" and len(detail["splits"]) == 22
    assert (await call_json(app, "get_pacepro_plans", {"plan_id": 999}))["status"] == "not_found"


async def _saved_plan(app):
    data = await call_json(app, "create_pacepro_plan", {"name": "City Half", "distance": "half", "goal_time": "1:42:00", "save": True})
    return data["plan"]["plan_id"]


@pytest.mark.asyncio
async def test_send_goes_to_the_primary_device(app, fake):
    plan_id = await _saved_plan(app)
    fake.devices = [
        {"deviceId": 222, "productDisplayName": "scale", "primary": False},
        {"deviceId": 111, "productDisplayName": "watch one", "primary": True},
    ]
    data = await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id})
    assert data["status"] == "sent"
    assert data["device"] == {"device_id": 111, "name": "watch one", "primary": True}
    assert data["plan"]["name"] == "City Half"
    assert fake.sent == [(plan_id, 111)]
    assert fake.calls[-1] == ("POST", f"course-service/pacebands/{plan_id}/device/111")


@pytest.mark.asyncio
async def test_send_to_a_chosen_device_and_device_checks(app, fake):
    plan_id = await _saved_plan(app)
    fake.devices = [
        {"deviceId": 111, "productDisplayName": "watch one", "primary": False},
        {"deviceId": 222, "productDisplayName": "watch two", "primary": False},
    ]
    needed = await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id})
    assert needed["status"] == "device_needed" and len(needed["devices"]) == 2
    unknown = await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id, "device_id": 999})
    assert unknown["status"] == "unknown_device"
    assert fake.sent == []
    chosen = await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id, "device_id": 222})
    assert chosen["status"] == "sent" and fake.sent == [(plan_id, 222)]


@pytest.mark.asyncio
async def test_send_with_a_single_unmarked_device_uses_it(app, fake):
    plan_id = await _saved_plan(app)
    fake.devices = [{"deviceId": 333, "productDisplayName": "only watch"}]
    assert (await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id}))["status"] == "sent"
    assert fake.sent == [(plan_id, 333)]


@pytest.mark.asyncio
async def test_send_failures_do_not_pretend(app, fake):
    plan_id = await _saved_plan(app)
    assert (await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": 12345}))["status"] == "not_found"
    fake.devices = []
    assert (await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id}))["status"] == "failed"
    fake.devices = [{"deviceId": 111, "productDisplayName": "watch one", "primary": True}]
    fake.send_status = 500
    data = await call_json(app, "send_pacepro_plan_to_watch", {"plan_id": plan_id})
    assert data["status"] == "failed" and data["http_status"] == 500 and "refused" in data["message"]
    assert fake.sent == []


@pytest.mark.asyncio
async def test_delete_needs_confirmation(app, fake):
    await call_json(app, "create_pacepro_plan", {"name": "City Half", "distance": "half", "goal_time": "1:42:00", "save": True})
    await call_json(app, "create_pacepro_plan", {"name": "Other", "distance": "10k", "goal_time": "0:50:00", "save": True})
    preview = await call_json(app, "delete_pacepro_plan", {"plan_id": 500})
    assert preview["status"] == "confirmation_required" and preview["plan"]["name"] == "City Half"
    assert 500 in fake.store and [c[0] for c in fake.writes()] == ["POST", "POST"]
    done = await call_json(app, "delete_pacepro_plan", {"plan_id": 500, "confirm": True})
    assert done["status"] == "deleted"
    assert 500 not in fake.store and 501 in fake.store
    assert (await call_json(app, "delete_pacepro_plan", {"plan_id": 500, "confirm": True}))["status"] == "not_found"
