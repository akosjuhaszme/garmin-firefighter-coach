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
        self.race_search = []  # the same races as race-search/events returns them
        self.race_search_params = None
        self.calls = []
        self._ids = itertools.count(9000)

    def _subscribe(self, uuid):
        """POST event/{uuid}/subscription: the organiser's entry lands on the calendar. Organiser events
        are not served by their numeric id (GET/PUT/DELETE answer 404), only by uuid."""
        source = next((e for e in self.catalog if e.get("shareableEventUuid") == uuid), None)
        if source is None:
            self._fail(404, "HTTP 404 Not Found")
        km = source["completionTarget"]["value"] * 0.001
        event = _event(source["id"], source["eventName"], source["date"], km=km, privacy="PUBLIC_SHAREABLE_DISCOVERABLE")
        event.update({
            "eventOrganizer": False, "shareableEventUuid": uuid, "provider": source["eventsProvider"],
            "subscribed": True, "race": True,
        })
        self.store[event["id"]] = event
        return _response(201)

    def _organiser_by_uuid(self, uuid):
        found = [e for e in self.store.values() if e.get("shareableEventUuid") == uuid]
        if not found:
            self._fail(404, "HTTP 404 Not Found")
        return found[0]

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
        if path == "race-search/events":
            self.race_search_params = dict(params)
            words = (params.get("searchPhrase") or "").casefold().split()
            wanted = params["verifiedStatuses"].split(",")
            low, high = params.get("completionTargetMinValue"), params.get("completionTargetMaxValue")
            rows = []
            for e in self.race_search:
                meters = [t["value"] for t in e["completionTargets"]]
                fits = not meters or any((low is None or m >= low) and (high is None or m <= high) for m in meters)
                if (
                    params["fromDate"] <= e["eventDate"] <= params["toDate"]
                    and all(w in e["eventName"].casefold() for w in words)
                    and e["verifiedStatus"] in wanted
                    and (not params.get("eventsProviders") or e["provider"] == params["eventsProviders"])
                    and fits
                ):
                    rows.append(e)
            return _response(200, copy.deepcopy(rows))
        assert path == "calendar-service/events"
        rows = [
            e for e in self.store.values()
            if params["startDate"] <= e["date"] <= params["endDate"]
        ]
        return _response(200, copy.deepcopy(rows))

    def request(self, method, subdomain, path, api=False, json=None, **kw):
        self.calls.append((method, path))
        parts = path.split("/")
        if len(parts) == 4 and parts[3] in ("subscription", "customization"):  # event/{uuid}/...
            uuid = parts[2]
            if parts[3] == "subscription" and method == "POST":
                return self._subscribe(uuid)
            event = self._organiser_by_uuid(uuid)
            if parts[3] == "customization" and method == "PUT":
                event["eventCustomization"] = copy.deepcopy(json)
                return _response(204)
            if parts[3] == "subscription" and method == "DELETE":
                del self.store[event["id"]]
                return _response(204)
            raise AssertionError((method, path))
        if path == "calendar-service/event" and method == "POST":
            if json["date"] > _in_days(364):
                self._fail(400, "Event date must be less than a year in the future")
            event = copy.deepcopy(json)
            event["id"] = next(self._ids)
            self.store[event["id"]] = event
            return _response(200, copy.deepcopy(event))
        event_id = int(path.rsplit("/", 1)[1])
        if event_id not in self.store or self.store[event_id].get("eventOrganizer") is False:
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


def _uuid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def _race_result(name, date, km=21.1, uuid_n=1, status="VERIFIED", provider="ahotu", extra_km=()):
    """One result as race-search/events returns it (a race can offer several distances)."""
    return {
        "provider": provider,
        "eventName": name,
        "eventDate": date,
        "eventStartTime": {"startTimeHhMm": "08:00", "timeZoneId": "Europe/Paris"},
        "eventUrl": "https://example.org/race",
        "completionTargets": [{"value": d * 1000, "unit": "meter"} for d in (km, *extra_km)],
        "eventType": "running",
        "administrativeArea": {"countryCode": "XX", "cityEn": "Springfield"},
        "hasCourse": False,
        "verifiedStatus": status,
        "garminEventUuid": _uuid(uuid_n),
        "isOfficial": status == "OFFICIAL",
    }


def _catalog_event(event_id, name, date, km=21.1, city="Springfield", subscribers=5, provider="ahotu"):
    return {
        "id": event_id,
        "shareableEventUuid": _uuid(event_id),
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


# ---------------------------------------------------------- 401 retry


def _http_error(status):
    return GarthHTTPError(msg="Error in request", error=HTTPError(response=_response(status, {"message": "x"})))


def test_a_read_is_retried_once_on_401_and_other_errors_are_not_swallowed():
    calls = []

    def flaky(statuses):
        def call():
            calls.append(1)
            status = statuses.pop(0)
            if status != 200:
                raise _http_error(status)
            return "ok"
        return call

    assert events.retry_once_on_401(flaky([401, 200])) == "ok" and len(calls) == 2
    calls.clear()
    with pytest.raises(GarthHTTPError):
        events.retry_once_on_401(flaky([401, 401]))  # a second 401 is the caller's problem
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(GarthHTTPError):
        events.retry_once_on_401(flaky([500, 200]))  # only 401 is retried
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reads_survive_one_401_but_a_write_is_never_repeated(app, garth_fake):
    real_get, real_request = garth_fake.get, garth_fake.request
    state = {"left": 1}

    def get_401_once(*a, **k):
        if state["left"]:
            state["left"] -= 1
            garth_fake._fail(401, "token expired")
        return real_get(*a, **k)

    garth_fake.get = get_401_once
    data = await call_json(app, "get_calendar_events", {"start_year": datetime.date.today().year, "start_month": datetime.date.today().month, "months": 24})
    assert data["count"] == 2  # the 401 on the first read did not show

    posts = []

    def post_401(method, subdomain, path, api=False, json=None, **kw):
        if method == "POST":
            posts.append(path)
            garth_fake._fail(401, "token expired")
        return real_request(method, subdomain, path, api=api, json=json, **kw)

    garth_fake.request = post_401
    result = await call_json(app, "create_calendar_event", {"name": "Zzz Quux Fun Run", "date": _in_days(120), "create_anyway": True})
    assert result["status"] == "failed" and result["http_status"] == 401
    assert len(posts) == 1  # not repeated


# -------------------------------------------------------------- catalog


@pytest.mark.asyncio
async def test_search_event_catalog_defaults_to_official_and_verified(app, garth_fake):
    garth_fake.race_search = [
        _race_result("Capital Air Half Marathon", _in_days(200), uuid_n=701),
        _race_result("Capital Air Half Marathon (10 km)", _in_days(200), km=10, uuid_n=702),
        _race_result("Seaside Official Run", _in_days(210), uuid_n=703, status="OFFICIAL", provider="garmin-events"),
        _race_result("Capital Air Fun Run", _in_days(220), uuid_n=704, status="NONE", provider="gc-discoverable-events"),
        _race_result("Capital Air Half Marathon", _in_days(500), uuid_n=705),  # outside the default year
    ]
    data = await call_json(app, "search_event_catalog", {"search_phrase": "capital air"})
    assert [r["catalog_uuid"] for r in data["events"]] == [_uuid(701), _uuid(702)]  # user-created one left out
    row = data["events"][0]
    assert row["distance_km"] == 21.1
    assert row["start_time"] == "08:00"
    assert row["verified_status"] == "VERIFIED"
    assert row["provider"] == "ahotu"
    assert row["city"] == "Springfield"
    assert "event_id" not in row  # not an id of the user's calendar
    assert garth_fake.race_search_params["verifiedStatuses"] == "OFFICIAL,VERIFIED"
    assert garth_fake.race_search_params["includeVirtual"] == "false"
    assert garth_fake.race_search_params["completionTargetDurationType"] == "distance"
    assert garth_fake.writes() == []

    assert (await call(app, "search_event_catalog", {"search_phrase": "nothing like this"})).startswith("No catalog events")


@pytest.mark.asyncio
async def test_search_event_catalog_source_filter(app, garth_fake):
    garth_fake.race_search = [
        _race_result("Seaside Official Run", _in_days(210), uuid_n=1, status="OFFICIAL", provider="garmin-events"),
        _race_result("Seaside Partner Run", _in_days(211), uuid_n=2),
        _race_result("Seaside Users Run", _in_days(212), uuid_n=3, status="NONE", provider="gc-discoverable-events"),
    ]

    async def titles(**args):
        data = await call_json(app, "search_event_catalog", {"search_phrase": "seaside", **args})
        return [r["title"] for r in data["events"]]

    assert await titles(source="official") == ["Seaside Official Run"]
    assert await titles(source="unverified") == ["Seaside Users Run"]
    assert await titles(source="Official, Verified") == ["Seaside Official Run", "Seaside Partner Run"]
    assert await titles(source="all") == ["Seaside Official Run", "Seaside Partner Run", "Seaside Users Run"]
    assert await titles(source="all", provider="ahotu") == ["Seaside Partner Run"]
    assert garth_fake.race_search_params["eventsProviders"] == "ahotu"
    assert "source must be" in await call(app, "search_event_catalog", {"source": "famous"})


@pytest.mark.asyncio
async def test_search_event_catalog_by_distance_and_place(app, garth_fake):
    garth_fake.race_search = [
        _race_result("Seaside Half", _in_days(200), km=21.1, uuid_n=1),
        _race_result("Seaside Marathon", _in_days(200), km=42.2, uuid_n=2),
        _race_result("Seaside Ten", _in_days(200), km=10, uuid_n=3),
        _race_result("Seaside Festival", _in_days(201), km=10, uuid_n=4, extra_km=(21.1, 42.2)),  # three distances
    ]
    data = await call_json(app, "search_event_catalog", {
        "min_km": 21, "max_km": 22, "latitude": 47.5, "longitude": 19.0, "within_km": 100,
    })
    assert [(r["title"], r["distance_km"]) for r in data["events"]] == [
        ("Seaside Half", 21.1), ("Seaside Festival", 21.1),  # only the matching distance of a multi-distance race
    ]
    params = garth_fake.race_search_params
    assert (params["completionTargetMinValue"], params["completionTargetMaxValue"]) == (21000, 22000)
    assert (params["poiLat"], params["poiLon"], params["withinMeters"]) == (47.5, 19.0, 100000)

    # a race that offers several distances is listed once per distance
    everything = await call_json(app, "search_event_catalog", {"search_phrase": "festival"})
    assert [r["distance_km"] for r in everything["events"]] == [10, 21.1, 42.2]


@pytest.mark.asyncio
@pytest.mark.parametrize("args, fragment", [
    ({"from_date": "soon"}, "YYYY-MM-DD"),
    ({"from_date": "2027-02-02", "to_date": "2027-01-01"}, "before"),
    ({"latitude": 47.5, "longitude": 19.0}, "within_km"),
    ({"min_km": 30, "max_km": 20}, "min_km"),
])
async def test_search_event_catalog_rejects_bad_input(app, args, fragment):
    assert fragment in await call(app, "search_event_catalog", args)


@pytest.mark.asyncio
async def test_add_catalog_event_to_calendar(app, garth_fake):
    day = _in_days(200)
    garth_fake.catalog = [_catalog_event(801, "Capital Air Half Marathon", day, subscribers=74)]
    data = await call_json(app, "add_catalog_event_to_calendar", {
        "catalog_uuid": _uuid(801).upper(), "goal_time": "1:42:00",
    })
    assert data["status"] == "added"
    assert data["event"]["title"] == "Capital Air Half Marathon"
    assert data["event"]["is_race"] is True
    assert data["event"]["goal_time"] == "1:42:00"
    assert data["event"]["distance_km"] == 21.1
    assert data["event"]["privacy"] == "PUBLIC_SHAREABLE_DISCOVERABLE"  # organiser events are public
    assert [c[0] for c in garth_fake.writes()] == ["POST", "PUT"]
    assert garth_fake.writes()[0][1] == f"calendar-service/event/{_uuid(801)}/subscription"

    # nothing is added twice
    again = await call_json(app, "add_catalog_event_to_calendar", {"catalog_uuid": _uuid(801)})
    assert again["status"] == "already_on_calendar"
    assert len(garth_fake.writes()) == 2


@pytest.mark.asyncio
async def test_add_catalog_event_warns_about_private_stand_in(app, garth_fake):
    day = _in_days(200)
    garth_fake.store[5] = _event(5, "Capital Air Half Marathon 2027", day, km=21.1)  # the user's own stand-in
    garth_fake.catalog = [_catalog_event(802, "Capital Air Half Marathon", day)]
    data = await call_json(app, "add_catalog_event_to_calendar", {"catalog_uuid": _uuid(802)})
    assert data["status"] == "added"
    assert data["similar_events_on_calendar"][0]["event_id"] == 5
    assert "warnings" in data


@pytest.mark.asyncio
async def test_add_catalog_event_rejects_bad_input_and_unknown_race(app, garth_fake):
    assert "UUID" in await call(app, "add_catalog_event_to_calendar", {"catalog_uuid": "29915693"})
    assert "goal_time" in await call(app, "add_catalog_event_to_calendar", {"catalog_uuid": _uuid(1), "goal_time": "fast"})
    data = await call_json(app, "add_catalog_event_to_calendar", {"catalog_uuid": _uuid(999)})
    assert data["status"] == "failed"
    assert data["http_status"] == 404
    assert len(garth_fake.store) == 2


@pytest.mark.asyncio
async def test_catalog_events_on_the_calendar_can_get_a_goal_time_and_be_removed(app, garth_fake):
    garth_fake.catalog = [_catalog_event(803, "Capital Air Half Marathon", _in_days(200))]
    added = await call_json(app, "add_catalog_event_to_calendar", {"catalog_uuid": _uuid(803)})
    event_id = added["event_id"]  # the numeric id is not served by GET, only the uuid works

    data = await call_json(app, "update_calendar_event", {"event_id": event_id, "goal_time": "1:40:00"})
    assert data["status"] == "updated"
    assert data["changes"] == {"goal_time": {"from": None, "to": "1:40:00"}}

    refused = await call_json(app, "update_calendar_event", {"event_id": event_id, "name": "My own name"})
    assert refused["status"] == "organiser_event"
    assert garth_fake.store[event_id]["eventName"] == "Capital Air Half Marathon"

    preview = await call_json(app, "delete_calendar_event", {"event_id": event_id})
    assert preview["status"] == "confirmation_required"
    assert event_id in garth_fake.store
    done = await call_json(app, "delete_calendar_event", {"event_id": event_id, "confirm": True})
    assert done["status"] == "deleted"
    assert event_id not in garth_fake.store
    assert garth_fake.writes()[-1][1] == f"calendar-service/event/{_uuid(803)}/subscription"


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
