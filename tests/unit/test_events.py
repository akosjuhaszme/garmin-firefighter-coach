"""
Unit tests for the calendar event tools (events.py, get_calendar_events in recovery.py)

A small stateful fake stands in for Garmin's calendar-service so create, change and
delete run end to end without touching a real account. The fake mirrors what was seen
live: POST returns the event with its id, PUT/DELETE answer 204, a missing id is a 404
and a date a year or more ahead is a 400 - garth raises GarthHTTPError for every error
status.
"""
import copy
import datetime
import itertools
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from garth.exc import GarthHTTPError
from mcp.server.fastmcp import FastMCP
from requests import HTTPError

from garmin_workouts_mcp import events, recovery


def _in_days(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _response(status, body=None):
    text = "" if body is None else json.dumps(body)
    return SimpleNamespace(status_code=status, text=text, json=lambda: body)


class FakeGarth:
    def __init__(self, stored=()):
        self.store = {e["id"]: copy.deepcopy(e) for e in stored}
        self.catalog = []  # organiser-published events (calendar-service/events/discover)
        self.catalog_error = False
        self.calls = []
        self._ids = itertools.count(9000)

    def _fail(self, status, message):
        response = _response(status, {"message": message})
        raise GarthHTTPError(msg="Error in request", error=HTTPError(response=response))

    def get(self, subdomain, path, params=None, **kw):
        self.calls.append(("GET", path))
        if path == "calendar-service/events/discover":
            if self.catalog_error:
                self._fail(500, "catalog down")
            words = (params.get("searchPhrase") or "").casefold().split()
            rows = [
                e for e in self.catalog
                if params["fromDate"] <= e["date"] <= params["toDate"]
                and all(w in e["eventName"].casefold() for w in words)
            ]
            return _response(200, copy.deepcopy(rows[: int(params.get("limit", 100))]))
        assert path == "calendar-service/events"
        rows = [
            e for e in self.store.values()
            if params["startDate"] <= e["date"] <= params["endDate"]
        ]
        return _response(200, copy.deepcopy(rows))

    def request(self, method, subdomain, path, api=False, json=None, **kw):
        self.calls.append((method, path))
        if path == "calendar-service/event" and method == "POST":
            if json["date"] > _in_days(364):
                self._fail(400, "Event date must be less than a year in the future")
            event = copy.deepcopy(json)
            event["id"] = next(self._ids)
            self.store[event["id"]] = event
            return _response(200, copy.deepcopy(event))
        event_id = int(path.rsplit("/", 1)[1])
        if event_id not in self.store:
            self._fail(404, "not found")
        if method == "GET":
            return _response(200, copy.deepcopy(self.store[event_id]))
        if method == "PUT":
            self.store[event_id] = copy.deepcopy(json)
            return _response(204)
        if method == "DELETE":
            del self.store[event_id]
            return _response(204)
        raise AssertionError(method)

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PUT", "DELETE")]


def _event(event_id, name, date, km=42.2, goal=None, privacy="PRIVATE", zone="Europe/Paris"):
    return {
        "id": event_id,
        "eventName": name,
        "date": date,
        "url": None,
        "completionTarget": {"value": km, "unit": "kilometer", "unitType": "distance"},
        "eventTimeLocal": {"startTimeHhMm": "09:00", "timeZoneId": zone},
        "note": None,
        "location": "Springfield",
        "eventType": "running",
        "eventPrivacy": {"label": privacy, "isShareable": False, "isDiscoverable": False},
        "eventCustomization": {
            "customGoal": {"value": goal, "unit": "second", "unitType": "time"} if goal else None,
            "isPrimaryEvent": False,
        },
        "race": True,
    }


def _catalog_event(event_id, name, date, km=21.1, city="Springfield", subscribers=5, provider="ahotu"):
    return {
        "id": event_id,
        "eventName": name,
        "date": date,
        "eventStartTime": {"startTimeHhMm": "08:00", "timeZoneId": "Europe/Paris"},
        "url": "https://example.org/race",
        "completionTarget": {"value": km * 1000, "unit": "meter", "unitType": "distance"},
        "eventType": "running",
        "subscribersCount": subscribers,
        "administrativeArea": {"countryCode": "XX", "cityEn": city},
        "eventsProvider": provider,
        "official": False,
    }


@pytest.fixture
def garth_fake():
    return FakeGarth([
        _event(1, "City Marathon", _in_days(100), goal=13800),
        _event(2, "River Marathon", _in_days(300), km=42.16),
    ])


@pytest.fixture
def app(garth_fake):
    client = SimpleNamespace(garth=garth_fake)
    events.configure(client)
    recovery.configure(client)
    application = FastMCP("Test events")
    events.register_tools(application)
    recovery.register_tools(application)
    return application


async def call(app, name, args):
    result = await app.call_tool(name, args)
    return result[0][0].text


async def call_json(app, name, args):
    return json.loads(await call(app, name, args))


# -------------------------------------------------------------- helpers


def test_goal_time_round_trip():
    assert events.format_goal(13800) == "3:50:00"
    assert events.format_goal(None) is None
    assert events.parse_goal("1:40:00") == 6000
    assert events.parse_goal("3:50") == 13800
    for bad in ("", "100", "1:75:00", "a:b", "0:00:00"):
        with pytest.raises(ValueError):
            events.parse_goal(bad)


def test_month_range_crosses_year_end():
    assert events.month_range(2026, 11, 1) == ("2026-11-01", "2026-11-30")
    assert events.month_range(2026, 11, 4) == ("2026-11-01", "2027-02-28")


def test_event_row_converts_units_and_reads_goal():
    item = _event(7, "Mile", "2027-01-01", km=1.0, goal=480)
    item["completionTarget"] = {"value": 1.0, "unit": "mile", "unitType": "distance"}
    row = events.event_row(item)
    assert row["distance_km"] == 1.609
    assert row["goal_time"] == "0:08:00"
    assert row["privacy"] == "PRIVATE"
    assert row["event_id"] == 7


@pytest.mark.parametrize("a, b, km_a, km_b, expected", [
    ("Capital Air Half Marathon 2027", "Capital Air Half Marathon", 21.1, 21.098, True),
    ("Capital Air Half Marathon 2027", "42. Capital Air Félmaratón", 21.1, 21.1, True),
    ("Capital Air Half Marathon 2027", "Capitalair capital félmaraton", None, None, True),
    ("Capital Air Half Marathon", "Capital Air Félmaraton", None, None, True),
    ("City Half Marathon", "City Half Marathon 2027", None, None, True),
    ("Alpine Trail", "alpine  trail!", None, None, True),
    ("Capital Air Half Marathon", "The Big Half", 21.1, 21.1, False),
    ("City Marathon", "River Marathon", 42.2, 42.2, False),
    ("Capital Night Run", "Capital Air Half Marathon", 10, 21.1, False),
    ("Capital Marathon", "Capital Marathon 10K", 42.2, 10, False),
    ("Capital Marathon", "Capital Marathon 10K", None, None, True),
    ("", "Capital Marathon", None, None, False),
])
def test_similar_names(a, b, km_a, km_b, expected):
    assert bool(events.similar_names(a, b, km_a, km_b)) is expected


# ----------------------------------------------------------------- read


@pytest.mark.asyncio
async def test_get_calendar_events_returns_ids_goals_and_privacy(app):
    start = datetime.date.today()
    data = await call_json(app, "get_calendar_events", {
        "start_year": start.year, "start_month": start.month, "months": 24,
    })
    assert data["count"] == 2
    first = data["events"][0]
    assert first["event_id"] == 1
    assert first["title"] == "City Marathon"
    assert first["goal_time"] == "3:50:00"
    assert first["distance_km"] == 42.2
    assert first["privacy"] == "PRIVATE"
    assert data["events"][1]["goal_time"] is None


# --------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_private_with_goal_time(app, garth_fake):
    day = _in_days(200)
    data = await call_json(app, "create_calendar_event", {
        "name": "City Half", "date": day, "start_time": "8:00",
        "distance_km": 21.1, "location": "Budapest", "goal_time": "1:40:00",
    })
    assert data["status"] == "created"
    assert data["event"]["privacy"] == "PRIVATE"
    assert data["event"]["goal_time"] == "1:40:00"
    assert data["event"]["start_time"] == "08:00"
    assert data["event"]["distance_km"] == 21.1
    stored = garth_fake.store[data["event_id"]]
    assert stored["eventPrivacy"]["isDiscoverable"] is False
    assert stored["eventTimeLocal"]["timeZoneId"] == "Europe/Paris"  # taken from the existing events
    assert [c[0] for c in garth_fake.writes()] == ["POST", "PUT"]


@pytest.mark.asyncio
async def test_create_marks_race_without_making_it_public(app, garth_fake):
    plain = await call_json(app, "create_calendar_event", {"name": "Fun run", "date": _in_days(210)})
    assert plain["event"]["is_race"] is None  # nothing sent, nothing set
    assert [c[0] for c in garth_fake.writes()] == ["POST"]

    data = await call_json(app, "create_calendar_event", {
        "name": "Real race", "date": _in_days(220), "is_race": True,
    })
    assert data["status"] == "created"
    assert data["event"]["is_race"] is True
    assert data["event"]["privacy"] == "PRIVATE"
    assert garth_fake.store[data["event_id"]]["eventPrivacy"]["isDiscoverable"] is False


@pytest.mark.asyncio
async def test_create_refuses_duplicate_name_on_same_day(app, garth_fake):
    data = await call_json(app, "create_calendar_event", {
        "name": "  city   MARATHON ", "date": _in_days(100), "distance_km": 42.2,
    })
    assert data["status"] == "duplicate"
    assert data["existing_event"]["event_id"] == 1
    assert garth_fake.writes() == []


@pytest.mark.asyncio
async def test_create_stops_when_the_catalog_already_has_the_race(app, garth_fake):
    day = _in_days(200)
    garth_fake.catalog = [
        _catalog_event(501, "Capital Air Half Marathon", day, subscribers=74),
        _catalog_event(502, "42. Capital Air Félmaratón", day, km=21.1, subscribers=3),
        _catalog_event(503, "Capital Air Half Marathon", _in_days(201)),  # other date
        _catalog_event(504, "Capital Air 10K", day, km=10),  # other distance
        _catalog_event(505, "Seaside Half Marathon", day),  # other race
    ]
    args = {"name": "Capital Air Félmaraton 2027", "date": day, "distance_km": 21.1}
    data = await call_json(app, "create_calendar_event", args)
    assert data["status"] == "similar_event_found"
    assert [m["catalog_event_id"] for m in data["catalog_matches"]] == [501, 502]  # most subscribers first
    assert data["catalog_matches"][0]["distance_km"] == 21.1
    assert data["catalog_matches"][0]["city"] == "Springfield"
    assert data["own_calendar_matches"] == []
    assert garth_fake.writes() == []

    # the user agreed to a separate private event
    done = await call_json(app, "create_calendar_event", {**args, "create_anyway": True})
    assert done["status"] == "created"
    assert [c[0] for c in garth_fake.writes()] == ["POST"]


@pytest.mark.asyncio
async def test_create_ignores_unrelated_catalog_events(app, garth_fake):
    day = _in_days(200)
    garth_fake.catalog = [_catalog_event(601, "Seaside Half Marathon", day), _catalog_event(602, "Mountain 50K", day, km=50)]
    data = await call_json(app, "create_calendar_event", {"name": "Capital Air Half", "date": day, "distance_km": 21.1})
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_stops_on_similar_event_in_own_calendar(app, garth_fake):
    day = _in_days(100)  # "City Marathon" is on the calendar that day
    data = await call_json(app, "create_calendar_event", {"name": "City Marathon 2027", "date": day, "distance_km": 42.2})
    assert data["status"] == "similar_event_found"
    assert data["own_calendar_matches"][0]["event_id"] == 1
    assert data["own_calendar_matches"][0]["match"] == "same name"
    assert garth_fake.writes() == []


@pytest.mark.asyncio
async def test_create_stops_when_the_catalog_cannot_be_checked(app, garth_fake):
    garth_fake.catalog_error = True
    args = {"name": "Capital Air Half", "date": _in_days(200)}
    data = await call_json(app, "create_calendar_event", args)
    assert data["status"] == "check_failed"
    assert garth_fake.writes() == []
    done = await call_json(app, "create_calendar_event", {**args, "create_anyway": True})
    assert done["status"] == "created"


@pytest.mark.asyncio
async def test_create_warns_about_other_event_that_day(app):
    data = await call_json(app, "create_calendar_event", {
        "name": "Shakeout 5k", "date": _in_days(100), "distance_km": 5,
    })
    assert data["status"] == "created"
    assert data["other_events_that_day"][0]["title"] == "City Marathon"
    assert "warnings" in data


@pytest.mark.asyncio
@pytest.mark.parametrize("args, fragment", [
    ({"name": "x", "date": _in_days(-1)}, "in the past"),
    ({"name": "x", "date": _in_days(400)}, "less than a year"),
    ({"name": "x", "date": "2027-13-40"}, "YYYY-MM-DD"),
    ({"name": "x", "date": _in_days(50), "start_time": "25:00"}, "HH:MM"),
    ({"name": "x", "date": _in_days(50), "goal_time": "fast"}, "goal_time"),
    ({"name": "x", "date": _in_days(50), "distance_km": -3}, "distance_km"),
    ({"name": "   ", "date": _in_days(50)}, "name"),
    ({"name": "x", "date": _in_days(50), "latitude": 47.5}, "latitude and longitude"),
])
async def test_create_rejects_bad_input_without_writing(app, garth_fake, args, fragment):
    text = await call(app, "create_calendar_event", args)
    assert text.startswith("Error") and fragment in text
    assert garth_fake.writes() == []


@pytest.mark.asyncio
async def test_create_passes_garmin_rejection_through(app, garth_fake):
    # 365 days passes the local check (it allows 366) but the fake, like Garmin, says no
    data = await call_json(app, "create_calendar_event", {"name": "Edge", "date": _in_days(365)})
    assert data["status"] == "failed"
    assert data["http_status"] == 400
    assert "less than a year" in data["message"]
    assert len(garth_fake.store) == 2


@pytest.mark.asyncio
async def test_create_without_known_time_zone_asks_for_one(garth_fake):
    empty = FakeGarth()
    client = SimpleNamespace(garth=empty)
    events.configure(client)
    application = FastMCP("empty")
    events.register_tools(application)
    text = await call(application, "create_calendar_event", {"name": "First", "date": _in_days(30)})
    assert "timezone_id" in text
    assert empty.writes() == []
    data = await call_json(application, "create_calendar_event", {
        "name": "First", "date": _in_days(30), "timezone_id": "Europe/Paris",
    })
    assert data["status"] == "created"


# -------------------------------------------------------------- catalog


@pytest.mark.asyncio
async def test_search_event_catalog(app, garth_fake):
    garth_fake.catalog = [
        _catalog_event(701, "Capital Air Half Marathon", _in_days(200), subscribers=74),
        _catalog_event(702, "Seaside Half Marathon", _in_days(210)),
        _catalog_event(703, "Capital Air Half Marathon", _in_days(400)),  # outside the default 90 days window
    ]
    data = await call_json(app, "search_event_catalog", {
        "search_phrase": "capital air", "from_date": _in_days(150), "to_date": _in_days(260),
    })
    assert data["count"] == 1
    row = data["events"][0]
    assert row["catalog_event_id"] == 701
    assert row["distance_km"] == 21.1
    assert row["start_time"] == "08:00"
    assert row["subscribers"] == 74
    assert row["provider"] == "ahotu"
    assert "event_id" not in row  # not an id of the user's calendar
    assert garth_fake.writes() == []

    none = await call(app, "search_event_catalog", {"search_phrase": "nothing like this"})
    assert none.startswith("No catalog events")


@pytest.mark.asyncio
@pytest.mark.parametrize("args, fragment", [
    ({"from_date": "soon"}, "YYYY-MM-DD"),
    ({"from_date": "2027-02-02", "to_date": "2027-01-01"}, "before"),
    ({"latitude": 47.5, "longitude": 19.0}, "within_km"),
])
async def test_search_event_catalog_rejects_bad_input(app, args, fragment):
    assert fragment in await call(app, "search_event_catalog", args)


# --------------------------------------------------------------- update


@pytest.mark.asyncio
async def test_update_goal_time_and_clear_it(app, garth_fake):
    data = await call_json(app, "update_calendar_event", {"event_id": 2, "goal_time": "3:30:00"})
    assert data["status"] == "updated"
    assert data["changes"] == {"goal_time": {"from": None, "to": "3:30:00"}}
    assert garth_fake.store[2]["eventCustomization"]["customGoal"]["value"] == 12600.0
    assert garth_fake.store[2]["eventName"] == "River Marathon"  # untouched fields stay

    cleared = await call_json(app, "update_calendar_event", {"event_id": 2, "clear_goal_time": True})
    assert cleared["changes"] == {"goal_time": {"from": "3:30:00", "to": None}}
    assert garth_fake.store[2]["eventCustomization"]["customGoal"] is None


@pytest.mark.asyncio
async def test_update_race_flag_keeps_privacy(app, garth_fake):
    garth_fake.store[4] = _event(4, "Half", _in_days(250), km=21.1)
    garth_fake.store[4]["race"] = False
    data = await call_json(app, "update_calendar_event", {"event_id": 4, "is_race": True})
    assert data["status"] == "updated"
    assert data["changes"] == {"is_race": {"from": False, "to": True}}
    assert garth_fake.store[4]["race"] is True
    assert garth_fake.store[4]["eventPrivacy"]["label"] == "PRIVATE"

    off = await call_json(app, "update_calendar_event", {"event_id": 4, "is_race": False})
    assert off["changes"] == {"is_race": {"from": True, "to": False}}


@pytest.mark.asyncio
async def test_update_other_fields(app, garth_fake):
    data = await call_json(app, "update_calendar_event", {
        "event_id": 2, "name": "River Capital Marathon", "start_time": "10:30", "distance_km": 42.195,
        "note": "bib at expo",
    })
    assert data["status"] == "updated"
    assert set(data["changes"]) == {"title", "start_time", "distance_km", "distance", "note"}
    assert garth_fake.store[2]["eventTimeLocal"]["timeZoneId"] == "Europe/Paris"
    assert garth_fake.store[2]["eventPrivacy"]["label"] == "PRIVATE"


@pytest.mark.asyncio
async def test_update_checks_input_and_target(app, garth_fake):
    assert "nothing to change" in await call(app, "update_calendar_event", {"event_id": 2})
    assert "not both" in await call(app, "update_calendar_event", {
        "event_id": 2, "goal_time": "3:00", "clear_goal_time": True,
    })
    assert "in the past" in await call(app, "update_calendar_event", {"event_id": 2, "date": _in_days(-3)})
    missing = await call_json(app, "update_calendar_event", {"event_id": 404, "note": "x"})
    assert missing["status"] == "not_found"
    assert garth_fake.writes() == []


@pytest.mark.asyncio
async def test_update_refuses_move_onto_same_named_event(app, garth_fake):
    garth_fake.store[3] = _event(3, "City Marathon", _in_days(150))
    data = await call_json(app, "update_calendar_event", {"event_id": 3, "date": _in_days(100)})
    assert data["status"] == "duplicate"
    assert data["existing_event"]["event_id"] == 1
    assert garth_fake.writes() == []


@pytest.mark.asyncio
async def test_update_reports_field_garmin_does_not_keep(app, garth_fake):
    real_request = garth_fake.request

    def forgetful(method, subdomain, path, api=False, json=None, **kw):
        if method == "PUT":
            json = copy.deepcopy(json)
            json["note"] = None  # silently drops the note
        return real_request(method, subdomain, path, api=api, json=json, **kw)

    garth_fake.request = forgetful
    data = await call_json(app, "update_calendar_event", {"event_id": 2, "note": "bib at expo"})
    assert data["status"] == "updated_partly"
    assert "note" in data["warning"]


# --------------------------------------------------------------- delete


@pytest.mark.asyncio
async def test_delete_needs_confirmation(app, garth_fake):
    preview = await call_json(app, "delete_calendar_event", {"event_id": 2})
    assert preview["status"] == "confirmation_required"
    assert preview["event"]["title"] == "River Marathon"
    assert 2 in garth_fake.store
    assert garth_fake.writes() == []

    done = await call_json(app, "delete_calendar_event", {"event_id": 2, "confirm": True})
    assert done["status"] == "deleted"
    assert 2 not in garth_fake.store
    assert 1 in garth_fake.store  # the other event is untouched


@pytest.mark.asyncio
async def test_delete_unknown_id(app, garth_fake):
    for confirm in (False, True):
        data = await call_json(app, "delete_calendar_event", {"event_id": 404, "confirm": confirm})
        assert data["status"] == "not_found"
    assert garth_fake.writes() == []
