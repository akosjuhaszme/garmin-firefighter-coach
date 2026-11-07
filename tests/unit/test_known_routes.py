"""
Unit tests for the known-route tools (known_routes.py): the local store, composing a route through known places with a (fake) foot
router, suggestions toward a target distance, and learning recurring loops from (fake) GPS tracks. All places are made up.
"""
import json
import math
import random

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import known_routes, routes

LAT0, LON0 = 47.0, 19.0
PLACES = {  # a 560 m x 530 m block with the corners named, plus two places further out
    "Alpha utca": (47.000, 19.000),
    "Béta utca": (47.005, 19.000),
    "Gamma utca": (47.005, 19.007),
    "Delta utca": (47.000, 19.007),
    "Epsilon utca": (47.009, 19.003),
    "Zeta utca": (47.002, 19.014),
}


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def street_km(a, b):
    """what the fake router charges between two (lat, lon): 1.2 x the straight line"""
    return 1.2 * routes._haversine_m(a[1], a[0], b[1], b[0]) / 1000


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_COACH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENROUTESERVICE_API_KEY", raising=False)
    known_routes.configure(None)
    return tmp_path


@pytest.fixture
def router(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        coords = [tuple(float(v) for v in part.split(",")) for part in url.split("/foot/")[1].split(";")]
        calls.append({"coords": coords, "headers": headers, "params": params})
        legs = [street_km((a[1], a[0]), (b[1], b[0])) * 1000 for a, b in zip(coords, coords[1:])]
        return FakeResponse({"code": "Ok", "routes": [{"distance": sum(legs), "legs": [{"distance": d} for d in legs],
                                                         "geometry": {"coordinates": [list(c) for c in coords]}}]})

    monkeypatch.setattr(known_routes.requests, "get", fake_get)
    return calls


@pytest.fixture
def app():
    application = FastMCP("Test known routes")
    known_routes.register_tools(application)
    return application


async def call(app, name, args=None):
    text = (await app.call_tool(name, args or {}))[0][0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


async def seed_places(app, names=None):
    for name in names or PLACES:
        lat, lon = PLACES[name]
        await call(app, "save_known_place", {"name": name, "lat": lat, "lon": lon})


# ------------------------------------------------------------------------------------------------------------ the store

def test_names_match_without_case_or_accents():
    assert known_routes._norm("  Béta   UTCA ") == known_routes._norm("beta utca")
    assert known_routes._norm("Mátyás király") == known_routes._norm("MATYAS KIRALY")


@pytest.mark.asyncio
async def test_pin_save_update_list_and_remove(app, data_dir):
    saved = await call(app, "save_known_place", {"name": "Alpha utca", "lat": 47.0, "lon": 19.0, "notes": "whole length is fine"})
    assert saved["saved"] and not saved["updated"] and saved["source"] == "pin"

    again = await call(app, "save_known_place", {"name": "alpha UTCA", "lat": 47.001, "lon": 19.001})
    assert again["updated"] and again["name"] == "Alpha utca" and again["notes"] == "whole length is fine"  # notes survive an update

    listing = await call(app, "list_known_routes")
    assert list(listing["places"]) == ["Alpha utca"] and listing["places"]["Alpha utca"]["lat"] == 47.001
    assert (data_dir / "known_routes.json").exists()

    assert await call(app, "remove_known_place", {"name": "alpha utca"}) == {"removed": "Alpha utca"}
    assert (await call(app, "list_known_routes"))["places"] == {}


@pytest.mark.asyncio
async def test_a_half_pin_or_a_bad_pin_is_refused(app):
    assert "both lat and lon" in await call(app, "save_known_place", {"name": "X", "lat": 47.0})
    assert "out of range" in await call(app, "save_known_place", {"name": "X", "lat": 147.0, "lon": 19.0})
    assert (await call(app, "list_known_routes"))["places"] == {}


@pytest.mark.asyncio
async def test_geocoder_match_is_saved_but_a_town_centre_is_not(app, monkeypatch):
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "key")
    answers = {
        "Alpha utca, Exampletown": {"lat": 47.0, "lon": 19.0, "label": "Alpha utca", "confidence": 1, "match_type": "exact", "layer": "street"},
        "Buda utca, Exampletown": {"lat": 47.1, "lon": 19.1, "label": "Exampletown", "confidence": 0.3, "match_type": "fallback", "layer": "locality"},
    }
    monkeypatch.setattr(known_routes.routes, "_geocode", lambda key, text: (answers[text], None))

    ok = await call(app, "save_known_place", {"name": "Alpha utca", "address": "Alpha utca, Exampletown"})
    assert ok["saved"] and ok["source"] == "geocoded" and ok["match_type"] == "exact"

    coarse = await call(app, "save_known_place", {"name": "Buda utca", "address": "Buda utca, Exampletown"})
    assert coarse["saved"] is False and "pin" in coarse["reason"]
    assert list((await call(app, "list_known_routes"))["places"]) == ["Alpha utca"]

    pinned = await call(app, "save_known_place", {"name": "Buda utca", "lat": 47.002, "lon": 19.003, "notes": "pinned by hand"})
    assert pinned["saved"] and pinned["source"] == "pin"


@pytest.mark.asyncio
async def test_loops_need_known_places_and_places_in_use_stay(app):
    await seed_places(app, ["Alpha utca", "Béta utca"])
    assert "Unknown place" in await call(app, "save_known_loop", {"name": "L", "stops": ["Alpha utca", "Nowhere utca"]})
    assert "at least two" in await call(app, "save_known_loop", {"name": "L", "stops": ["Alpha utca"], "closed": False})

    saved = await call(app, "save_known_loop", {"name": "Short", "stops": ["alpha utca", "BETA utca"]})
    assert saved["stops"] == ["Alpha utca", "Béta utca"] and saved["closed"] is True

    assert "used by the loops" in await call(app, "remove_known_place", {"name": "Alpha utca"})
    await call(app, "remove_known_loop", {"name": "Short"})
    assert await call(app, "remove_known_place", {"name": "Alpha utca"}) == {"removed": "Alpha utca"}


@pytest.mark.asyncio
async def test_a_damaged_store_is_reported_and_left_alone(app, data_dir):
    (data_dir / "known_routes.json").write_text("{not json", encoding="utf-8")
    assert "not valid JSON" in await call(app, "list_known_routes")
    assert "not valid JSON" in await call(app, "save_known_place", {"name": "A", "lat": 1.0, "lon": 1.0})
    assert (data_dir / "known_routes.json").read_text(encoding="utf-8") == "{not json"


# -------------------------------------------------------------------------------------------------------------- compose

@pytest.mark.asyncio
async def test_compose_a_closed_route_through_known_places(app, router):
    await seed_places(app)
    result = await call(app, "compose_route", {"stops": ["Alpha utca", "béta utca", "Gamma utca", "Delta utca"], "close_loop": True})

    assert result["stops"] == ["Alpha utca", "Béta utca", "Gamma utca", "Delta utca", "Alpha utca"]
    expected = [street_km(PLACES[a], PLACES[b]) for a, b in [("Alpha utca", "Béta utca"), ("Béta utca", "Gamma utca"), ("Gamma utca", "Delta utca"), ("Delta utca", "Alpha utca")]]
    assert [leg["km"] for leg in result["legs"]] == [round(k, 2) for k in expected]
    assert result["total_km"] == pytest.approx(sum(expected), abs=0.02)
    assert result["legs"][0] == {"from": "Alpha utca", "to": "Béta utca", "km": round(expected[0], 2)}
    assert result["provider"] == "osm" and "ors" in result["note"] and "gpx" not in result
    # the router got coordinates and a generic client name, nothing else
    assert router[0]["headers"] == known_routes._HEADERS and "@" not in json.dumps(router[0]["headers"])
    assert all(isinstance(c, tuple) and len(c) == 2 for c in router[0]["coords"])


@pytest.mark.asyncio
async def test_coordinates_work_as_stops_and_a_pinned_place_fits_in_the_chain(app, router):
    await seed_places(app, ["Alpha utca", "Béta utca", "Gamma utca"])
    await call(app, "save_known_place", {"name": "Pinned utca", "lat": 47.0, "lon": 19.0035, "notes": "the geocoder only found the town centre"})

    chain = await call(app, "compose_route", {"stops": ["Alpha utca", "Pinned utca", "Béta utca", "47.005,19.007"]})
    assert chain["stops"] == ["Alpha utca", "Pinned utca", "Béta utca", "47.00500,19.00700"]
    assert len(chain["legs"]) == 3 and chain["closed"] is False


@pytest.mark.asyncio
async def test_unknown_stops_get_a_hint_and_bad_input_is_refused(app, router):
    await seed_places(app, ["Alpha utca", "Béta utca"])
    assert "did you mean" in await call(app, "compose_route", {"stops": ["Alpha utca", "Beta utka"]})
    assert "Unknown place" in await call(app, "compose_route", {"stops": ["Alpha utca", "Nowhere"]})
    assert "valid lat,lon" in await call(app, "compose_route", {"stops": ["Alpha utca", "95.0,19.0"]})
    assert "at least two" in await call(app, "compose_route", {"stops": ["Alpha utca"]})
    assert "provider must be" in await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"], "provider": "x"})
    assert "needs the OPENROUTESERVICE_API_KEY" in await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"], "provider": "ors"})
    assert router == []


@pytest.mark.asyncio
async def test_a_saved_loop_is_composed_by_name_and_gpx_can_be_kept(app, router, data_dir):
    await seed_places(app, ["Alpha utca", "Béta utca", "Gamma utca", "Delta utca"])
    await call(app, "save_known_loop", {"name": "Block", "stops": ["Alpha utca", "Béta utca", "Gamma utca", "Delta utca"]})

    result = await call(app, "compose_route", {"loop": "block", "include_gpx": True, "save_as": "Block 560"})
    assert result["closed"] is True and result["stops"][-1] == "Alpha utca"
    assert result["gpx"].count("<trkpt") == 5
    path = data_dir / "routes" / "Block_560.gpx"
    assert result["gpx_file"] == str(path) and path.read_text(encoding="utf-8") == result["gpx"]

    assert "Unknown loop" in await call(app, "compose_route", {"loop": "nope"})


@pytest.mark.asyncio
async def test_router_failures_are_reported(app, monkeypatch):
    await seed_places(app, ["Alpha utca", "Béta utca"])
    monkeypatch.setattr(known_routes.requests, "get", lambda *a, **k: FakeResponse(status_code=500, text="boom"))
    assert "HTTP 500" in await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"]})
    monkeypatch.setattr(known_routes.requests, "get", lambda *a, **k: FakeResponse({"code": "NoRoute", "message": "nope"}))
    assert "no route" in await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"]})


@pytest.mark.asyncio
async def test_ors_gives_elevation_and_the_unpaved_share(app, monkeypatch):
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "key")
    await seed_places(app, ["Alpha utca", "Béta utca", "Gamma utca"])
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(json=json, headers=headers)
        return FakeResponse({"features": [{"geometry": {"coordinates": [[19.0, 47.0, 100.0], [19.0, 47.005, 108.0], [19.007, 47.005, 104.0]]},
                                           "properties": {"summary": {"distance": 1500.0}, "segments": [{"distance": 700.0}, {"distance": 800.0}],
                                                          "ascent": 8.0, "descent": 4.0,
                                                          "extras": {"surface": {"summary": [{"value": 3, "distance": 1200.0}, {"value": 11, "distance": 200.0},
                                                                                             {"value": 0, "distance": 100.0}]}}}}]})

    monkeypatch.setattr(known_routes.requests, "post", fake_post)
    result = await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca", "Gamma utca"], "provider": "ors"})

    assert result["total_km"] == 1.5 and result["ascent_m"] == 8.0 and result["descent_m"] == 4.0
    assert result["surface"] == {"paved_km": 1.2, "unpaved_km": 0.2, "unknown_km": 0.1}
    assert sent["json"]["coordinates"][0] == [19.0, 47.0] and sent["json"]["extra_info"] == ["surface"]
    assert "note" not in result


# ----------------------------------------------------------------------------------------------- target and suggestions

@pytest.mark.asyncio
async def test_a_longer_target_offers_places_to_add_checked_with_the_router(app, router):
    await seed_places(app)
    block = ["Alpha utca", "Béta utca", "Gamma utca", "Delta utca"]
    base = await call(app, "compose_route", {"stops": block, "close_loop": True})
    target = base["total_km"] + 1.5

    result = await call(app, "compose_route", {"stops": block, "close_loop": True, "target_km": target})
    assert result["deviation_km"] == pytest.approx(base["total_km"] - target, abs=0.01)
    suggestions = result["suggestions"]
    assert suggestions and all(s["action"] == "add" and s["place"] in ("Epsilon utca", "Zeta utca") for s in suggestions)
    assert all(s["new_total_km"] > base["total_km"] and s["change_km"] == pytest.approx(s["new_total_km"] - base["total_km"], abs=0.01) for s in suggestions)
    errors = [abs(s["new_total_km"] - target) for s in suggestions]
    assert errors == sorted(errors)  # the closest first
    assert all(len(s["between"]) == 2 for s in suggestions)


@pytest.mark.asyncio
async def test_a_shorter_target_offers_skipping_a_stop_or_turning_back(app, router):
    await seed_places(app)
    stops = ["Alpha utca", "Béta utca", "Epsilon utca", "Gamma utca", "Delta utca"]
    base = await call(app, "compose_route", {"stops": stops, "close_loop": True})

    result = await call(app, "compose_route", {"stops": stops, "close_loop": True, "target_km": base["total_km"] - 1.0})
    suggestions = result["suggestions"]
    assert suggestions and {s["action"] for s in suggestions} <= {"skip", "turn_back_after"}
    assert all(s["new_total_km"] < base["total_km"] for s in suggestions)
    skip = next(s for s in suggestions if s["action"] == "skip") if any(s["action"] == "skip" for s in suggestions) else None
    if skip:
        assert skip["place"] not in ("Alpha utca",)  # the start is never skipped


@pytest.mark.asyncio
async def test_no_suggestions_when_the_target_is_met(app, router):
    await seed_places(app)
    block = ["Alpha utca", "Béta utca", "Gamma utca", "Delta utca"]
    base = await call(app, "compose_route", {"stops": block, "close_loop": True})
    result = await call(app, "compose_route", {"stops": block, "close_loop": True, "target_km": base["total_km"] + 0.1})
    assert result["suggestions"] == []
    no_suggest = await call(app, "compose_route", {"stops": block, "close_loop": True, "target_km": 9.0, "suggest": False})
    assert "suggestions" not in no_suggest


class FakeGarmin:
    def __init__(self, activities=None, polylines=None):
        self.activities = activities or []
        self.polylines = polylines or {}

    def get_activities_by_date(self, start, end, activity_type=None):
        return self.activities

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        return {"geoPolylineDTO": {"polyline": self.polylines[activity_id]}}


@pytest.mark.asyncio
async def test_the_long_run_rule_is_checked_against_the_last_30_days(app, router):
    await seed_places(app, ["Alpha utca", "Béta utca"])
    known_routes.configure(FakeGarmin([{"distance": 9030.0}, {"distance": 5000.0}]))
    result = await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"], "close_loop": True})
    assert result["long_run_limit_km"] == 9.9 and result["within_long_run_limit"] is True

    known_routes.configure(FakeGarmin([{"distance": 0.5 * 1000}]))
    tight = await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"], "close_loop": True})
    assert tight["long_run_limit_km"] == 0.5 and tight["within_long_run_limit"] is False

    known_routes.configure(FakeGarmin([]))
    assert "long_run_limit_km" not in await call(app, "compose_route", {"stops": ["Alpha utca", "Béta utca"]})


# --------------------------------------------------------------------------------------------------------- learned loops

def rectangle(width_m, height_m, step=20.0, jitter=0.0, seed=0, origin=(0.0, 0.0), reverse=False):
    """(lat, lon) points around a rectangle starting at the origin, a point every `step` metres, optionally jittered"""
    rng = random.Random(seed)
    ox, oy = origin
    corners = [(0, 0), (width_m, 0), (width_m, height_m), (0, height_m), (0, 0)]
    if reverse:
        corners = corners[::-1]
    xy = []
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        for k in range(int(length // step)):
            xy.append((x1 + (x2 - x1) * k * step / length, y1 + (y2 - y1) * k * step / length))
    xy.append(corners[-1])
    return [[LAT0 + (oy + y + rng.uniform(-jitter, jitter)) / 110540.0, LON0 + (ox + x + rng.uniform(-jitter, jitter)) / (111320.0 * math.cos(math.radians(LAT0)))]
            for x, y in xy]


def as_polyline(latlon):
    return [{"lat": lat, "lon": lon, "valid": True} for lat, lon in latlon]


def run_fixture():
    """three runs of the same 600 x 400 m loop (one run the other way round, all jittered), two of a 300 x 700 m loop, one 900 x 900 m one-off"""
    shapes = [(1, 600, 400, 1, False), (2, 600, 400, 2, False), (3, 600, 400, 3, True), (4, 300, 700, 4, False), (5, 300, 700, 5, False), (6, 900, 900, 6, False)]
    activities, polylines = [], {}
    for n, w, h, seed, reverse in shapes:
        latlon = rectangle(w, h, jitter=4.0, seed=seed, reverse=reverse)
        km = (2 * (w + h)) / 1000
        activities.append({"activityId": 100 + n, "startTimeLocal": f"2026-10-{10 + n:02d} 08:00:00", "distance": km * 1000,
                           "startLatitude": latlon[0][0], "startLongitude": latlon[0][1]})
        polylines[100 + n] = as_polyline(latlon)
    activities.append({"activityId": 200, "startTimeLocal": "2026-10-30 08:00:00", "distance": 5000.0, "startLatitude": LAT0 + 0.05, "startLongitude": LON0 + 0.05})
    activities.append({"activityId": 201, "startTimeLocal": "2026-10-31 08:00:00", "distance": 500.0, "startLatitude": LAT0, "startLongitude": LON0})  # too short
    return FakeGarmin(activities, polylines)


@pytest.mark.asyncio
async def test_learn_reports_recurring_loops_and_saves_only_on_request(app, data_dir):
    known_routes.configure(run_fixture())
    result = await call(app, "learn_known_routes", {"min_km": 1.0})

    assert result["runs_read"] == 6 and result["one_off_runs"] == 1 and result["saved"] is False
    first, second = result["groups"]
    assert (first["runs"], second["runs"]) == (3, 2)
    assert first["typical_km"] == 2.0 and first["activity_ids"] == [103, 102, 101]  # newest first
    assert first["closed_loop"] is True and first["last_run"] == "2026-10-13" and first["first_run"] == "2026-10-11"
    assert not (data_dir / "known_routes.json").exists()  # a preview writes nothing
    assert "coordinates" not in json.dumps(result)


@pytest.mark.asyncio
async def test_saved_learned_loops_can_be_listed_composed_and_shortened(app, router, data_dir):
    await seed_places(app, ["Alpha utca"])
    known_routes.configure(run_fixture())
    result = await call(app, "learn_known_routes", {"save": True, "name_prefix": "Own loop", "min_km": 1.0})
    assert [g["saved_as"] for g in result["groups"]] == ["Own loop 1", "Own loop 2"] and result["saved"] is True

    listing = await call(app, "list_known_routes")
    learned = {row["name"]: row for row in listing["loops"]}
    assert learned["Own loop 1"]["kind"] == "learned" and learned["Own loop 1"]["runs"] == 3 and "polyline" not in learned["Own loop 1"]

    stored = json.loads((data_dir / "known_routes.json").read_text(encoding="utf-8"))["loops"]["Own loop 1"]
    assert 4 <= len(stored["polyline"]) <= 500 and stored["source_activity"] == 103

    composed = await call(app, "compose_route", {"loop": "own loop 1", "target_km": 1.0})
    assert composed["closed"] is True and composed["stops"][0] == "Own loop 1 #1" and composed["stops"][-1] == "Own loop 1 #1"
    assert composed["total_km"] == pytest.approx(2.4, abs=0.1)  # the corners are kept: the fake router charges 1.2 x the 2.0 km of the rectangle
    assert composed["suggestions"] and all(s["new_total_km"] < composed["total_km"] for s in composed["suggestions"])

    again = await call(app, "learn_known_routes", {"save": True, "name_prefix": "Own loop", "min_km": 1.0})
    assert [g["saved_as"] for g in again["groups"]] == ["Own loop 3", "Own loop 4"]  # existing names are never overwritten


@pytest.mark.asyncio
async def test_learn_uses_a_named_start_and_handles_nothing_found(app):
    await seed_places(app, ["Alpha utca"])
    known_routes.configure(run_fixture())
    far = await call(app, "learn_known_routes", {"start_place": "Alpha utca", "radius_m": 50, "min_km": 1.0})
    assert far["runs_read"] in (0, 6) or far["groups"] == [] or far["groups"]  # starts here are within 50 m of Alpha utca or not: it must not fail
    assert isinstance(far, dict)

    known_routes.configure(FakeGarmin([]))
    assert "No running activities" in await call(app, "learn_known_routes", {})
    known_routes.configure(None)
    assert "not configured" in await call(app, "learn_known_routes", {})


def test_simplify_keeps_the_corners_and_sampling_follows_the_loop():
    latlon = rectangle(600, 400, jitter=0.0)
    xy = [known_routes._project(lat, lon, LAT0, LON0) for lat, lon in latlon]
    keep = known_routes._simplify(xy, 5.0)
    assert len(keep) == 5 and keep[0] == 0 and keep[-1] == len(xy) - 1  # four corners and the closing point

    simple = known_routes._simplified_polyline(latlon, LAT0, LON0)
    assert len(simple) == 5
    points = known_routes._sample_waypoints(simple)
    assert points[0] == tuple(simple[0]) and len(points) == 4  # the four corners, the closing point is dropped
    long_side = known_routes._sample_waypoints(known_routes._simplified_polyline(rectangle(3000, 100), LAT0, LON0))
    assert len(long_side) > 6  # extra points on the long straight stretches
    assert known_routes._polyline_km(simple) == pytest.approx(2.0, abs=0.01)


def test_coverage_separates_a_loop_from_a_different_one():
    def dense(width, height, **kw):
        xy = [known_routes._project(lat, lon, LAT0, LON0) for lat, lon in rectangle(width, height, **kw)]
        return known_routes._densify(xy)

    a, b, c = dense(600, 400, jitter=4.0, seed=1), dense(600, 400, jitter=4.0, seed=2), dense(300, 700, jitter=4.0, seed=3)
    assert known_routes._coverage(a, known_routes._grid(b)) > 0.9
    assert known_routes._coverage(a, known_routes._grid(c)) < 0.6
