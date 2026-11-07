"""
Known running routes for Garmin Connect MCP Server

Long runs and threshold runs often follow familiar streets on asphalt, which a random loop generator cannot reproduce. This module
keeps a small local store of
  - places: a street or a point with a coordinate (geocoded, or pinned by hand when the geocoder only finds a town centre) and notes,
  - loops: named, ordered lists of places,
  - learned loops: recurring routes found in the user's own earlier GPS tracks (Garmin Connect activity details),
and composes a route through chosen stops with a foot router: total and per-leg length, ascent and surface share (when the
OpenRouteService key is set), a GPX, and ways to lengthen or shorten the route to a target distance.

Local only: the store is ~/.garmin-coach/known_routes.json and GPX files go to ~/.garmin-coach/routes/ (override the directory with
GARMIN_COACH_DATA_DIR). Nothing here uploads to Garmin (create_garmin_course does that, only when the user agrees). The routing and
geocoding services receive coordinates (the geocoder also the street text) and nothing else; the generic client name carries no contact
details. The default router is the public OpenStreetMap foot instance (no key, fair use); "ors" uses OpenRouteService when
OPENROUTESERVICE_API_KEY is set.
"""
import datetime
import difflib
import json
import math
import os
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path
from typing import List, Optional

import requests

from . import routes

garmin_client = None

OSM_FOOT_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
_HEADERS = {"User-Agent": "garmin-firefighter-coach-route-composer/1.0"}
_COARSE_LAYERS = {"locality", "localadmin", "county", "macrocounty", "region", "macroregion", "country", "coarse", "borough", "neighbourhood"}
_UNPAVED_SURFACES = {2, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18}  # OpenRouteService surface codes: unpaved, gravel, dirt, ground, ice, sand, ...
_DETOUR_FACTOR = 1.3  # street distance over straight line, only used to rank suggestions before the router checks them
_MAX_STOPS = 40
_TOLERANCE_KM = 0.3
_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


# ---------------------------------------------------------------------------------------------------------------- the local store

class StoreError(Exception):
    pass


def _data_dir() -> Path:
    return Path(os.environ.get("GARMIN_COACH_DATA_DIR") or (Path.home() / ".garmin-coach"))


def _store_path() -> Path:
    return _data_dir() / "known_routes.json"


def _load() -> dict:
    path = _store_path()
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise StoreError(f"{path} is not valid JSON ({exc}); fix or move it, nothing was changed") from exc
    data.setdefault("places", {})
    data.setdefault("loops", {})
    return data


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _norm(name: str) -> str:
    """Case and accent insensitive key: 'Mátyás Király utca' == 'matyas kiraly utca'"""
    text = unicodedata.normalize("NFKD", name.strip())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).casefold()


def _find(table: dict, name: str) -> Optional[str]:
    key = _norm(name)
    for stored in table:
        if _norm(stored) == key:
            return stored
    return None


def _resolve(spec: str, data: dict):
    """A stop given as a known place name or as 'lat,lon' -> ((label, lat, lon), None) or (None, error message)"""
    match = _COORD_RE.match(spec)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, f"{spec!r} is not a valid lat,lon pair"
        return (f"{lat:.5f},{lon:.5f}", lat, lon), None
    stored = _find(data["places"], spec)
    if stored is None:
        names = list(data["places"])
        close = difflib.get_close_matches(_norm(spec), [_norm(n) for n in names], n=3, cutoff=0.6)
        hints = [n for n in names if _norm(n) in close]
        return None, f"Unknown place {spec!r}" + (f" - did you mean {hints}?" if hints else " - save it first with save_known_place")
    place = data["places"][stored]
    return (stored, place["lat"], place["lon"]), None


def _dist_m(a, b) -> float:
    """metres between two (label, lat, lon) points"""
    return routes._haversine_m(a[2], a[1], b[2], b[1])


# ---------------------------------------------------------------------------------------------------------------------- routing

def _route_osm(points):
    """points: [(lat, lon), ...] -> (route dict, None) or (None, error)"""
    path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    try:
        response = requests.get(OSM_FOOT_URL + path, params={"overview": "full", "geometries": "geojson", "steps": "false"},
                                headers=_HEADERS, timeout=25)
    except requests.exceptions.RequestException as exc:
        return None, f"Error contacting the OpenStreetMap foot router: {exc}"
    if response.status_code != 200:
        return None, f"The OpenStreetMap foot router answered HTTP {response.status_code}: {response.text[:200]}"
    data = response.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        return None, f"The foot router found no route ({data.get('code')}: {data.get('message', '')})"
    route = data["routes"][0]
    return {"provider": "osm", "total_m": route["distance"], "legs_m": [leg["distance"] for leg in route.get("legs", [])],
            "coords": route["geometry"]["coordinates"], "ascent_m": None, "descent_m": None, "surface": None}, None


def _surface_summary(extras) -> Optional[dict]:
    summary = ((extras or {}).get("surface") or {}).get("summary") or []
    if not summary:
        return None
    total = sum(s.get("distance", 0) for s in summary)
    unpaved = sum(s.get("distance", 0) for s in summary if s.get("value") in _UNPAVED_SURFACES)
    unknown = sum(s.get("distance", 0) for s in summary if s.get("value") == 0)
    return {"paved_km": round((total - unpaved - unknown) / 1000, 2), "unpaved_km": round(unpaved / 1000, 2), "unknown_km": round(unknown / 1000, 2)}


def _route_ors(points, api_key):
    body = {"coordinates": [[lon, lat] for lat, lon in points], "elevation": True, "extra_info": ["surface"], "instructions": False}
    try:
        response = requests.post(routes.DIRECTIONS_URL, headers={"Authorization": api_key, "Content-Type": "application/json; charset=utf-8"},
                                 json=body, timeout=25)
    except requests.exceptions.RequestException as exc:
        return None, f"Error contacting OpenRouteService: {exc}"
    if response.status_code != 200:
        return None, f"OpenRouteService answered HTTP {response.status_code}: {response.text[:200]}"
    features = response.json().get("features") or []
    if not features:
        return None, "OpenRouteService found no route"
    feature = features[0]
    props = feature.get("properties", {})
    coords = feature.get("geometry", {}).get("coordinates", [])
    ascent, descent = props.get("ascent"), props.get("descent")
    if ascent is None and descent is None:
        ascent, descent = routes._ascent_descent_from_coords(coords)
    return {"provider": "ors", "total_m": props.get("summary", {}).get("distance", 0), "legs_m": [s.get("distance", 0) for s in props.get("segments", [])],
            "coords": coords, "ascent_m": ascent, "descent_m": descent, "surface": _surface_summary(props.get("extras"))}, None


def _route(points, provider):
    if provider == "ors":
        key = os.environ.get("OPENROUTESERVICE_API_KEY")
        if not key:
            return None, "provider 'ors' needs the OPENROUTESERVICE_API_KEY environment variable"
        return _route_ors(points, key)
    return _route_osm(points)


def _compose(points, provider):
    """points: [(label, lat, lon), ...] in running order (already closed if wanted) -> (result dict, None) or (None, error)"""
    route, error = _route([(p[1], p[2]) for p in points], provider)
    if error:
        return None, error
    legs = [{"from": points[i][0], "to": points[i + 1][0], "km": round(m / 1000, 2)} for i, m in enumerate(route["legs_m"]) if i + 1 < len(points)]
    return {"total_km": round(route["total_m"] / 1000, 2), "legs": legs, "ascent_m": route["ascent_m"], "descent_m": route["descent_m"],
            "surface": route["surface"], "coords": route["coords"], "provider": route["provider"]}, None


def _suggest(points, target_km, total_km, closed, provider, places):
    """Ways to move the route toward the target: a known place to add, an inner stop to skip, or turning back early. Ranked with a
    straight-line estimate, then each of the best few is routed for the real length."""
    gap = target_km - total_km
    if abs(gap) <= _TOLERANCE_KM:
        return []

    def est(a, b):
        return _dist_m(a, b) * _DETOUR_FACTOR / 1000

    candidates = []
    if gap > 0:
        used = {_norm(p[0]) for p in points}
        for name, place in places.items():
            if _norm(name) in used:
                continue
            cand = (name, place["lat"], place["lon"])
            best = min(((est(points[i], cand) + est(cand, points[i + 1]) - est(points[i], points[i + 1]), i) for i in range(len(points) - 1)),
                       key=lambda item: abs(total_km + item[0] - target_km))
            extra, i = best
            candidates.append((abs(total_km + extra - target_km),
                               {"action": "add", "place": name, "between": [points[i][0], points[i + 1][0]]},
                               points[:i + 1] + [cand] + points[i + 1:]))
    else:
        for i in range(1, len(points) - 1):
            saved = est(points[i - 1], points[i]) + est(points[i], points[i + 1]) - est(points[i - 1], points[i + 1])
            candidates.append((abs(total_km - saved - target_km), {"action": "skip", "place": points[i][0]}, points[:i] + points[i + 1:]))
        if closed:
            for j in range(1, len(points) - 2):
                dropped = sum(est(points[k], points[k + 1]) for k in range(j, len(points) - 1)) - est(points[j], points[0])
                candidates.append((abs(total_km - dropped - target_km),
                                   {"action": "turn_back_after", "place": points[j][0], "skips": [p[0] for p in points[j + 1:-1]]},
                                   points[:j + 1] + [points[0]]))
    candidates.sort(key=lambda item: item[0])
    checked = []
    for _, action, new_points in candidates[:4]:
        result, error = _compose(new_points, provider)
        if error:
            continue
        action = dict(action, new_total_km=result["total_km"], change_km=round(result["total_km"] - total_km, 2))
        checked.append(action)
    checked.sort(key=lambda a: abs(a["new_total_km"] - target_km))
    return checked[:3]


def _long_run_limit_km(today: Optional[datetime.date] = None) -> Optional[float]:
    """The +10 % rule: a long run is at most 10 % longer than the longest run of the last 30 days (None when Garmin cannot say)"""
    if garmin_client is None:
        return None
    try:
        end = today or datetime.date.today()
        start = end - datetime.timedelta(days=30)
        activities = garmin_client.get_activities_by_date(start.isoformat(), end.isoformat(), "running") or []
        longest = max((a.get("distance") or 0 for a in activities), default=0) / 1000
    except Exception:
        return None
    return math.floor(longest * 1.1 * 10) / 10 if longest else None


# ------------------------------------------------------------------------------------------------------------------ learned loops

def _project(lat, lon, lat0, lon0):
    return ((lon - lon0) * math.cos(math.radians(lat0)) * 111320.0, (lat - lat0) * 110540.0)


def _densify(xy, step=15.0):
    out = [xy[0]]
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        d = math.hypot(x2 - x1, y2 - y1)
        for k in range(1, int(d // step) + 1):
            out.append((x1 + (x2 - x1) * k * step / d, y1 + (y2 - y1) * k * step / d))
        out.append((x2, y2))
    return out


def _grid(points, cell=30.0):
    grid = {}
    for x, y in points:
        grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    return grid


def _coverage(points, grid, tol=30.0, cell=30.0):
    """share of the points that have a point of the other route within tol metres (tol must not exceed cell)"""
    hit = 0
    for x, y in points:
        cx, cy = int(x // cell), int(y // cell)
        if any((px - x) ** 2 + (py - y) ** 2 <= tol * tol
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for px, py in grid.get((cx + dx, cy + dy), ())):
            hit += 1
    return hit / len(points) if points else 0.0


def _cluster(runs, threshold):
    """runs: dicts with 'dense' and 'grid', newest first -> list of lists of runs; a run joins the first cluster whose first run it
    matches both ways (each route's points lie near the other)"""
    clusters = []
    for run in runs:
        for cluster in clusters:
            lead = cluster[0]
            if min(_coverage(run["dense"], lead["grid"]), _coverage(lead["dense"], run["grid"])) >= threshold:
                cluster.append(run)
                break
        else:
            clusters.append([run])
    return clusters


def _simplify(xy, tol):
    """Douglas-Peucker on projected points -> indexes to keep"""
    if len(xy) < 3:
        return list(range(len(xy)))
    keep = {0, len(xy) - 1}
    stack = [(0, len(xy) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, index = 0.0, None
        for k in range(i + 1, j):
            x, y = xy[k]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm if norm else math.hypot(x - x1, y - y1)
            if d > best:
                best, index = d, k
        if index is not None and best > tol:
            keep.add(index)
            stack += [(i, index), (index, j)]
    return sorted(keep)


def _simplified_polyline(latlon, lat0, lon0, max_points=500):
    xy = [_project(lat, lon, lat0, lon0) for lat, lon in latlon]
    tol = 5.0
    keep = _simplify(xy, tol)
    while len(keep) > max_points:
        tol *= 1.5
        keep = _simplify(xy, tol)
    return [[round(latlon[i][0], 6), round(latlon[i][1], 6)] for i in keep]


def _polyline_km(latlon) -> float:
    return sum(routes._haversine_m(a[1], a[0], b[1], b[0]) for a, b in zip(latlon, latlon[1:])) / 1000


def _point_along(path, distance_m):
    """(lat, lon) at distance_m metres along a polyline"""
    walked = 0.0
    for p, q in zip(path, path[1:]):
        d = routes._haversine_m(p[1], p[0], q[1], q[0])
        if d and walked + d >= distance_m:
            f = (distance_m - walked) / d
            return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
        walked += d
    return tuple(path[-1])


def _sample_waypoints(polyline, spacing_m=600.0, max_points=_MAX_STOPS - 4):
    """[(lat, lon)] to route through so that the router follows a learned loop: its turns (the polyline simplified until at most
    max_points are left, so no corner is cut) plus a point about every spacing_m on long straight stretches; the start comes first and a
    final point near the start is dropped"""
    xy = [_project(lat, lon, polyline[0][0], polyline[0][1]) for lat, lon in polyline]
    tolerance = 20.0
    keep = _simplify(xy, tolerance)
    while len(keep) > max_points:
        tolerance *= 1.4
        keep = _simplify(xy, tolerance)
    out = []
    for a, b in zip(keep, keep[1:]):
        out.append(tuple(polyline[a]))
        path = polyline[a:b + 1]
        gap = _polyline_km(path) * 1000
        if gap > 1.5 * spacing_m:
            pieces = math.ceil(gap / spacing_m)
            out.extend(_point_along(path, gap * i / pieces) for i in range(1, pieces))
    out.append(tuple(polyline[keep[-1]]))
    if len(out) > 1 and routes._haversine_m(out[-1][1], out[-1][0], out[0][1], out[0][0]) < spacing_m / 2:
        out.pop()
    return out[:_MAX_STOPS]


# ------------------------------------------------------------------------------------------------------------------------ tools

def _is_coarse(geo: dict) -> bool:
    layer, match_type, confidence = geo.get("layer"), geo.get("match_type"), geo.get("confidence")
    if layer in _COARSE_LAYERS or match_type == "fallback":
        return True
    return confidence is not None and confidence < 0.5


def _file_stem(name: str) -> str:
    return re.sub(r"[^\w\- ]", "", name, flags=re.UNICODE).strip().replace(" ", "_")[:60] or "route"


def register_tools(app):
    """Register the known-route tools with the MCP server app"""

    @app.tool()
    async def save_known_place(name: str, lat: Optional[float] = None, lon: Optional[float] = None, address: str = "", notes: str = "") -> str:
        """Remember a street or point (with its coordinate) for compose_route - local file only

        Give lat and lon to PIN the place by hand (what to do when the geocoder cannot find the street), or leave them out and it is
        looked up with the OpenRouteService geocoder from `address` (default: the name). A match that only resolved to a town or
        district centre, or has low confidence, is NOT saved: the answer says so and asks for a pin. Saving an existing name updates it.

        Args:
            name: Name of the place, e.g. "Alpha utca" (case and accents do not matter when it is used later)
            lat: Latitude for a manual pin
            lon: Longitude for a manual pin
            address: Text for the geocoder, e.g. "Alpha utca, Exampletown, Hungary" (only used when no lat/lon is given)
            notes: Free text: surface, lighting, "can be run along its whole length", ...
        """
        try:
            data = _load()
            existing = _find(data["places"], name)
            if (lat is None) != (lon is None):
                return "Give both lat and lon for a pin, or neither."
            if lat is not None:
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    return "lat/lon out of range."
                place = {"lat": round(lat, 6), "lon": round(lon, 6), "source": "pin"}
            else:
                api_key = os.environ.get("OPENROUTESERVICE_API_KEY")
                if not api_key:
                    return "No OPENROUTESERVICE_API_KEY configured: pass lat and lon to pin the place by hand."
                geo, error = routes._geocode(api_key, address or name)
                if error:
                    return error
                if _is_coarse(geo):
                    return json.dumps({"saved": False, "reason": "the geocoder only found a coarse match (a town or district centre or low confidence), "
                                       "not the street itself: save it again with lat and lon (a manual pin)", "geocoded": geo}, ensure_ascii=False, indent=2)
                place = {"lat": round(geo["lat"], 6), "lon": round(geo["lon"], 6), "source": "geocoded",
                         "match_type": geo.get("match_type"), "confidence": geo.get("confidence")}
            if notes:
                place["notes"] = notes
            elif existing and "notes" in data["places"][existing]:
                place["notes"] = data["places"][existing]["notes"]
            data["places"][existing or name.strip()] = place
            _save(data)
        except StoreError as exc:
            return str(exc)
        return json.dumps({"saved": True, "updated": bool(existing), "name": existing or name.strip(), **place}, ensure_ascii=False, indent=2)

    @app.tool()
    async def list_known_routes() -> str:
        """List the saved places, the named loops (ordered stops) and the learned loops - read-only, local file"""
        try:
            data = _load()
        except StoreError as exc:
            return str(exc)
        loops = []
        for name, loop in data["loops"].items():
            row = {"name": name, "kind": loop.get("kind", "stops"), "closed": loop.get("closed", True), "notes": loop.get("notes", "")}
            if loop.get("kind") == "learned":
                row.update({"length_km": loop.get("length_km"), "runs": loop.get("runs"), "last_run": loop.get("last_run")})
            else:
                row["stops"] = loop.get("stops", [])
            loops.append(row)
        return json.dumps({"store": str(_store_path()), "places": data["places"], "loops": loops}, ensure_ascii=False, indent=2)

    @app.tool()
    async def remove_known_place(name: str) -> str:
        """Delete a saved place (refused while a named loop still uses it) - local file only

        Args:
            name: Name of the place
        """
        try:
            data = _load()
            stored = _find(data["places"], name)
            if stored is None:
                return f"Unknown place {name!r}."
            users = [n for n, loop in data["loops"].items() if any(_norm(s) == _norm(stored) for s in loop.get("stops", []))]
            if users:
                return f"{stored!r} is used by the loops {users}: remove or change them first."
            del data["places"][stored]
            _save(data)
        except StoreError as exc:
            return str(exc)
        return json.dumps({"removed": stored}, ensure_ascii=False)

    @app.tool()
    async def save_known_loop(name: str, stops: List[str], closed: bool = True, notes: str = "") -> str:
        """Save a named loop: an ordered list of known places (a closed loop returns to the first stop) - local file only

        Args:
            name: Name of the loop
            stops: Known place names (save_known_place) in running order; the first is the start
            closed: True when the loop ends where it starts (default)
            notes: Free text
        """
        if len(stops) < 2 and not (closed and len(stops) == 1):
            return "A loop needs at least two stops."
        try:
            data = _load()
            names = []
            for spec in stops:
                stored = _find(data["places"], spec)
                if stored is None:
                    _, error = _resolve(spec, data)
                    return error
                names.append(stored)
            existing = _find(data["loops"], name)
            if existing and data["loops"][existing].get("kind") == "learned":
                return f"{existing!r} is a learned loop; use another name."
            data["loops"][existing or name.strip()] = {"kind": "stops", "stops": names, "closed": closed, "notes": notes}
            _save(data)
        except StoreError as exc:
            return str(exc)
        return json.dumps({"saved": True, "updated": bool(existing), "name": existing or name.strip(), "stops": names, "closed": closed}, ensure_ascii=False, indent=2)

    @app.tool()
    async def remove_known_loop(name: str) -> str:
        """Delete a saved or learned loop - local file only (places stay)

        Args:
            name: Name of the loop
        """
        try:
            data = _load()
            stored = _find(data["loops"], name)
            if stored is None:
                return f"Unknown loop {name!r}."
            del data["loops"][stored]
            _save(data)
        except StoreError as exc:
            return str(exc)
        return json.dumps({"removed": stored}, ensure_ascii=False)

    @app.tool()
    async def compose_route(stops: Optional[List[str]] = None, loop: str = "", target_km: float = 0.0, close_loop: Optional[bool] = None,
                            provider: str = "osm", suggest: bool = True, include_gpx: bool = False, save_as: str = "") -> str:
        """Route through known places (or a saved or learned loop) on foot-routable streets, with the length of every leg

        Gives the total and per-leg kilometres. With provider "ors" (needs OPENROUTESERVICE_API_KEY) also ascent/descent and how
        much of the route is unpaved or of unknown surface. With a target_km it also reports how far the route is from it and up
        to three checked ways to get closer: a known place to add, an inner stop to skip, or turning back early. The +10 % long-run
        rule is checked against the longest run of the last 30 days (long_run_limit_km). Nothing is uploaded: to put a route on
        the watch, pass the GPX (include_gpx=true) to create_garmin_course, and only when the user agrees. The routers get
        coordinates only. A shortest foot path between stops can leave the intended streets (tracks, paths): check the surface
        share and the map before relying on it.

        Args:
            stops: Stops in running order: known place names or "lat,lon" strings (omit when `loop` is given)
            loop: Name of a saved or learned loop to run instead of `stops`
            target_km: Distance to aim for (0 = no target)
            close_loop: Return to the first stop (default: the loop's own setting, otherwise False)
            provider: "osm" (default, public OpenStreetMap foot router) or "ors" (OpenRouteService: elevation and surface)
            suggest: Offer ways to reach target_km (default true; each needs a few extra router calls)
            include_gpx: Include the GPX text in the answer
            save_as: Save the GPX as ~/.garmin-coach/routes/<save_as>.gpx and return the path
        """
        if provider not in ("osm", "ors"):
            return "provider must be 'osm' or 'ors'."
        try:
            data = _load()
        except StoreError as exc:
            return str(exc)
        closed = bool(close_loop)
        points = []
        if loop:
            stored = _find(data["loops"], loop)
            if stored is None:
                return f"Unknown loop {loop!r}; see list_known_routes."
            saved = data["loops"][stored]
            closed = saved.get("closed", True) if close_loop is None else bool(close_loop)
            if saved.get("kind") == "learned":
                points = [(f"{stored} #{i + 1}", lat, lon) for i, (lat, lon) in enumerate(_sample_waypoints(saved["polyline"]))]
            else:
                specs = saved.get("stops", [])
                if not specs:
                    return f"Loop {stored!r} has no stops."
                for spec in specs:
                    point, error = _resolve(spec, data)
                    if error:
                        return error
                    points.append(point)
        else:
            if not stops:
                return "Give stops (known place names or 'lat,lon') or a loop name."
            if len(stops) > _MAX_STOPS:
                return f"At most {_MAX_STOPS} stops."
            for spec in stops:
                point, error = _resolve(spec, data)
                if error:
                    return error
                points.append(point)
        if closed and len(points) > 1 and (points[-1][1], points[-1][2]) != (points[0][1], points[0][2]):
            points = points + [points[0]]
        elif closed and len(points) == 1:
            return "A closed route needs at least two different stops."
        if len(points) < 2:
            return "A route needs at least two stops."

        composed, error = _compose(points, provider)
        if error:
            return error
        result = {"stops": [p[0] for p in points], "closed": closed, "provider": composed["provider"], "total_km": composed["total_km"],
                  "legs": composed["legs"], "ascent_m": composed["ascent_m"], "descent_m": composed["descent_m"], "surface": composed["surface"],
                  "track_points": len(composed["coords"])}
        if composed["provider"] == "osm":
            result["note"] = "no elevation or surface from this provider: use provider 'ors' for ascent/descent and the unpaved share"
        limit = _long_run_limit_km()
        if limit is not None:
            result["long_run_limit_km"] = limit
            result["within_long_run_limit"] = composed["total_km"] <= limit + 0.05
        if target_km:
            result["target_km"] = target_km
            result["deviation_km"] = round(composed["total_km"] - target_km, 2)
            if suggest:
                result["suggestions"] = _suggest(points, target_km, composed["total_km"], closed, provider, data["places"])
        if include_gpx or save_as:
            gpx = routes._build_gpx(composed["coords"], save_as or loop or "Composed route")
            if include_gpx:
                result["gpx"] = gpx
            if save_as:
                path = _data_dir() / "routes" / f"{_file_stem(save_as)}.gpx"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(gpx, encoding="utf-8")
                result["gpx_file"] = str(path)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @app.tool()
    async def learn_known_routes(start_place: str = "", start_lat: float = 0.0, start_lon: float = 0.0, radius_m: int = 300, days: int = 120,
                                 min_km: float = 3.0, max_runs: int = 40, similarity: float = 0.8, min_runs: int = 2, save: bool = False,
                                 name_prefix: str = "Learned loop") -> str:
        """Find the routes the user runs again and again in their own earlier GPS tracks, and (with save=true) keep them

        Reads the running activities of the last `days` days that start near one point (a known place, lat/lon, or by default the
        most common start), downloads each track's polyline from Garmin Connect (read-only) and groups tracks whose points lie within
        about 30 m of each other both ways (default 80 % of the points). Each group with at least `min_runs` runs is reported (number
        of runs, typical and range of km, dates, activity ids); with save=true its newest track is stored as a learned loop in the local
        file, and compose_route(loop=...) can then run it, shorten it (skipping or turning back) or lengthen it (adding known places).
        Without save nothing is written. The coordinates stay on this machine.

        Args:
            start_place: Known place to measure from (default: the most common start of the recent runs)
            start_lat: Or a start latitude (with start_lon)
            start_lon: Start longitude
            radius_m: How far from that point a run may start (default 300)
            days: How far back to look (default 120)
            min_km: Ignore shorter runs (default 3)
            max_runs: At most this many newest runs are read (default 40)
            similarity: Share of points that must lie near the other track, both ways (default 0.8)
            min_runs: Report/save groups with at least this many runs (default 2)
            save: Store the groups as learned loops (default false: only report)
            name_prefix: Name for the saved loops ("<prefix> 1", ...; existing names are skipped)
        """
        if garmin_client is None:
            return "Garmin client not configured."
        try:
            data = _load()
            end = datetime.date.today()
            start_day = end - datetime.timedelta(days=days)
            activities = garmin_client.get_activities_by_date(start_day.isoformat(), end.isoformat(), "running") or []
            activities = [a for a in activities if (a.get("distance") or 0) >= min_km * 1000 and a.get("startLatitude") is not None
                          and a.get("startLongitude") is not None]
            if not activities:
                return "No running activities with a start position in that period."
            if start_place:
                point, error = _resolve(start_place, data)
                if error:
                    return error
                ref_lat, ref_lon = point[1], point[2]
            elif start_lat or start_lon:
                ref_lat, ref_lon = start_lat, start_lon
            else:
                common = Counter((round(a["startLatitude"], 3), round(a["startLongitude"], 3)) for a in activities).most_common(1)[0][0]
                ref_lat, ref_lon = common
            near = [a for a in activities if routes._haversine_m(a["startLongitude"], a["startLatitude"], ref_lon, ref_lat) <= radius_m]
            near.sort(key=lambda a: a.get("startTimeLocal", ""), reverse=True)
            near = near[:max_runs]
            runs = []
            for activity in near:
                try:
                    details = garmin_client.get_activity_details(activity["activityId"], maxchart=100, maxpoly=3000)
                except Exception:
                    continue
                poly = [(p["lat"], p["lon"]) for p in ((details or {}).get("geoPolylineDTO") or {}).get("polyline") or []
                        if p.get("lat") is not None and p.get("lon") is not None and p.get("valid", True)]
                if len(poly) < 50:
                    continue
                dense = _densify([_project(lat, lon, ref_lat, ref_lon) for lat, lon in poly])
                runs.append({"id": activity["activityId"], "date": (activity.get("startTimeLocal") or "")[:10], "km": (activity.get("distance") or 0) / 1000,
                             "latlon": poly, "dense": dense, "grid": _grid(dense)})
            clusters = [c for c in _cluster(runs, similarity)]
            kept = sorted((c for c in clusters if len(c) >= min_runs), key=len, reverse=True)
            report = []
            for cluster in kept:
                lead = cluster[0]
                latlon = lead["latlon"]
                closed = routes._haversine_m(latlon[0][1], latlon[0][0], latlon[-1][1], latlon[-1][0]) < 150
                row = {"runs": len(cluster), "typical_km": round(statistics.median(r["km"] for r in cluster), 2),
                       "range_km": [round(min(r["km"] for r in cluster), 2), round(max(r["km"] for r in cluster), 2)],
                       "first_run": min(r["date"] for r in cluster), "last_run": max(r["date"] for r in cluster),
                       "closed_loop": closed, "activity_ids": [r["id"] for r in cluster][:8]}
                if save:
                    number = 1
                    while _find(data["loops"], f"{name_prefix} {number}"):
                        number += 1
                    name = f"{name_prefix} {number}"
                    data["loops"][name] = {"kind": "learned", "closed": closed, "length_km": row["typical_km"], "runs": len(cluster),
                                           "last_run": row["last_run"], "source_activity": lead["id"],
                                           "polyline": _simplified_polyline(latlon, ref_lat, ref_lon), "notes": "learned from the user's own GPS tracks"}
                    row["saved_as"] = name
                report.append(row)
            if save and report:
                _save(data)
        except StoreError as exc:
            return str(exc)
        except Exception as exc:
            return f"learn_known_routes failed: {exc}"
        return json.dumps({"runs_read": len(runs), "one_off_runs": sum(1 for c in clusters if len(c) < min_runs), "groups": report,
                           "saved": bool(save and report)}, ensure_ascii=False, indent=2)

    return app
