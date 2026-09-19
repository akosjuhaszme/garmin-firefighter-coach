"""
Running route generation + Garmin Course upload for Garmin MCP Server

Route generation is not a Garmin API - Garmin has no public route-generation
endpoint at all (the official "Courses API" is business/institution-gated).
Uses OpenRouteService's free "round trip" directions feature instead: given
a start point and a target distance, it generates a loop route on real
streets and paths. Requires OPENROUTESERVICE_API_KEY as an environment
variable.

Getting a generated route onto the watch as a navigable Garmin "Course" IS
now supported (create_garmin_course) - python-garminconnect has no course
support at all, so this reverse-engineers Garmin's undocumented
course-service endpoints instead, based on the (independently-maintained,
TypeScript) garmin-connect npm package's implementation
(github.com/florianpasteur/garmin-connect), then live-verified end to end
against a real account: created a real course (HTTP 200, real courseId
assigned, real distance/elevation computed by Garmin) and deleted it again
(HTTP 204) with no leftover residue. Same garth/garminconnect client and
~/.garminconnect token as the rest of this server - no extra auth step.

Known quirk, confirmed by live testing against a real account: OpenRouteService's
own docs call "length" a "preferred value", and in practice it's a weak
preference - the same length with different seeds produced actual distances
anywhere from -0% to +100%+ of the target in testing (e.g. asking for 6km at
points=3 returned results ranging 5.88-12.37km across 25 seeds), and for a
FIXED seed, changing "length" often changed nothing at all (4.32km, 4.5km and
6.0km requests all returned the identical 8.28km route). Length alone cannot
be trusted to hit a target - see the seed-search loop below.
"""
import json
import math
import os
import re

import requests

DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"
GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"

# GpxActivityType enum values, per garmin-connect (TS) src/garmin/types/gpx.ts -
# confirmed working live for RUNNING.
_ACTIVITY_TYPE_IDS = {"running": 1, "cycling": 10, "hiking": 3, "other": 4}

# The garmin_client will be set by the main file
garmin_client = None


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def _haversine_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _parse_gpx_trkpts(gpx: str) -> list:
    """Extract [lon, lat] pairs from a GPX string's <trkpt lat=".." lon=".."> tags
    (the format this module's own _build_gpx produces, and typical of any
    standard GPX 1.1 track)."""
    matches = re.findall(r'<trkpt\s+lat="([\-\d.]+)"\s+lon="([\-\d.]+)"', gpx)
    return [[float(lon), float(lat)] for lat, lon in matches]

# How many seeds to try (when the caller doesn't pin one) before returning the
# closest match. ~15 calls took ~3s in testing - cheap against the free tier's
# per-minute limit, and found a match within 2% of target in practice.
_AUTO_SEED_ATTEMPTS = 15


def _build_gpx(coordinates: list, name: str) -> str:
    """Build a minimal GPX 1.1 track from a list of [lon, lat] or [lon, lat,
    elevation] tuples (an <ele> tag is added when elevation is present)."""
    lines = []
    for point in coordinates:
        lon, lat = point[0], point[1]
        if len(point) > 2 and point[2] is not None:
            lines.append(f'      <trkpt lat="{lat}" lon="{lon}"><ele>{point[2]}</ele></trkpt>')
        else:
            lines.append(f'      <trkpt lat="{lat}" lon="{lon}"></trkpt>')
    trkpts = "\n".join(lines)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="garmin-firefighter-coach" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk>\n    <name>{name}</name>\n    <trkseg>\n{trkpts}\n"
        "    </trkseg>\n  </trk>\n</gpx>"
    )


def _google_maps_link(coordinates: list) -> str:
    """Build an APPROXIMATE Google Maps preview link from a sampled subset of
    the route's waypoints - NOT the real route.

    Google's Directions URL API caps intermediate waypoints at 23 (25 stops
    total including origin/destination), so a route with 100+ real GPX points
    (typical for these routes - see generate_running_route's docstring) is
    necessarily reduced to a small fraction of them here. Google then draws
    its OWN path between those sampled points, which can diverge substantially
    from the real foot-routed GPX, especially in areas with sparse/rural
    roads - confirmed live: a real route's actual path looked nothing like
    what this preview showed near one rural stretch, because Google's routing
    invented a totally different connection between two widely-spaced sampled
    points than the real fine-grained GPX took. travelmode=walking at least
    keeps Google on footpaths rather than defaulting to driving directions,
    but this is still an approximation, not a preview of the actual route -
    treat the GPX as the only source of truth for the real path.
    """
    if len(coordinates) <= 25:
        sample = coordinates
    else:
        step = len(coordinates) // 23
        sample = coordinates[::step][:23] + [coordinates[-1]]

    origin_lon, origin_lat = sample[0][0], sample[0][1]
    dest_lon, dest_lat = sample[-1][0], sample[-1][1]
    via = sample[1:-1]
    waypoints = "|".join(f"{p[1]},{p[0]}" for p in via)

    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin_lat},{origin_lon}"
        f"&destination={dest_lat},{dest_lon}"
        "&travelmode=walking"
    )
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url


def _geocode(api_key, address):
    """Resolve a free-text address to (lat, lon, label, confidence) using the
    same OpenRouteService API key (Pelias-backed geocoder - same account,
    no separate signup). Returns (result_dict_or_None, error_message_or_None).

    Confidence is Pelias's own 0-1 match-quality score; a low score or a
    coarse match_type (e.g. "fallback") usually means it only resolved to a
    town/locality centroid, not the exact street - common for addresses in
    small towns/villages where street-level data is sparse. Callers should
    surface confidence/match_type to the user rather than silently trusting
    a coarse match as if it were the exact address.
    """
    try:
        response = requests.get(
            GEOCODE_URL,
            params={"api_key": api_key, "text": address, "size": 1},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return None, f"Error contacting OpenRouteService geocoder: {str(e)}"

    if response.status_code in (401, 403):
        return None, "OpenRouteService rejected the API key - check OPENROUTESERVICE_API_KEY."
    if response.status_code != 200:
        return None, f"OpenRouteService geocoder request failed: HTTP {response.status_code} - {response.text[:300]}"

    features = response.json().get("features") or []
    if not features:
        return None, f"No location found for address: {address!r}"

    feature = features[0]
    lon, lat = feature["geometry"]["coordinates"]
    props = feature.get("properties", {})
    return {
        "lat": lat,
        "lon": lon,
        "label": props.get("label"),
        "confidence": props.get("confidence"),
        "match_type": props.get("match_type"),
        "layer": props.get("layer"),
    }, None


def _ascent_descent_from_coords(coords):
    """Fallback: sum positive/negative elevation deltas from 3D [lon, lat, ele]
    coordinates, for when the API response doesn't include an ascent/descent
    summary field directly."""
    ascent = descent = 0.0
    for i in range(1, len(coords)):
        if len(coords[i]) < 3 or len(coords[i - 1]) < 3:
            return None, None
        delta = coords[i][2] - coords[i - 1][2]
        if delta > 0:
            ascent += delta
        else:
            descent += -delta
    return round(ascent, 1), round(descent, 1)


def _request_route(api_key, start_lat, start_lon, distance_km, points, seed, elevation=False):
    """Make one round-trip request to OpenRouteService. Returns
    (result_dict_or_None, error_message_or_None).

    elevation=True adds a 3rd (elevation, in meters) value to each
    coordinate and an ascent_m/descent_m pair to the result - NOT yet
    independently live-verified against a real account (hit OpenRouteService's
    request quota mid-development before this could be confirmed); the
    "elevation" request field and the ascent/descent extraction below follow
    OpenRouteService's documented format, but treat ascent_m/descent_m as
    unconfirmed until someone checks a real response against this code.
    """
    round_trip = {"length": distance_km * 1000, "points": max(3, points), "seed": seed}
    body = {
        "coordinates": [[start_lon, start_lat]],
        "options": {"round_trip": round_trip},
    }
    if elevation:
        body["elevation"] = True

    try:
        response = requests.post(
            DIRECTIONS_URL,
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json; charset=utf-8",
            },
            json=body,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return None, f"Error contacting OpenRouteService: {str(e)}"

    if response.status_code in (401, 403):
        return None, f"OpenRouteService rejected the request (HTTP {response.status_code}) - check OPENROUTESERVICE_API_KEY, or you may have hit its request quota: {response.text[:200]}"
    if response.status_code != 200:
        return None, f"OpenRouteService request failed: HTTP {response.status_code} - {response.text[:300]}"

    data = response.json()
    features = data.get("features") or []
    if not features:
        return None, None  # no route found for this seed - not a hard error, just skip it

    feature = features[0]
    coords = feature.get("geometry", {}).get("coordinates", [])
    summary = feature.get("properties", {}).get("summary", {})
    result = {
        "seed": seed,
        "coords": coords,
        "actual_km": round(summary.get("distance", 0) / 1000, 2),
        "duration_min": round(summary.get("duration", 0) / 60, 1),
    }
    if elevation:
        ascent = summary.get("ascent")
        descent = summary.get("descent")
        if ascent is None and descent is None:
            ascent, descent = _ascent_descent_from_coords(coords)
        result["ascent_m"] = ascent
        result["descent_m"] = descent
    return result, None


def register_tools(app):
    """Register route-generation tools with the MCP server app"""

    @app.tool()
    async def geocode_address(address: str) -> str:
        """Resolve a free-text address/place name to coordinates, for use
        with generate_running_route's start_lat/start_lon

        Uses OpenRouteService's geocoder (same API key/account as the route
        tool - no separate signup). Always check `confidence` and
        `match_type` in the result: a low confidence or match_type
        "fallback" usually means the address only resolved to a town/village
        centroid, not the exact street - common for small-town addresses
        where street-level data is sparse. Don't silently treat a coarse
        match as if it were the exact requested address; surface it to the
        user instead.

        Args:
            address: Free-text address or place name, e.g. "Fő utca 12, Isaszeg, Hungary"
        """
        api_key = os.environ.get("OPENROUTESERVICE_API_KEY")
        if not api_key:
            return (
                "No OpenRouteService API key configured. Set the "
                "OPENROUTESERVICE_API_KEY environment variable (get a free key "
                "at https://openrouteservice.org/dev/#/signup) and restart this "
                "MCP server."
            )
        result, error = _geocode(api_key, address)
        if error:
            return error
        return json.dumps(result, indent=2)

    @app.tool()
    async def generate_running_route(
        distance_km: float,
        start_lat: float = 0.0,
        start_lon: float = 0.0,
        start_address: str = "",
        points: int = 3,
        seed: int = 0,
        prefer: str = "distance",
    ) -> str:
        """Generate a round-trip running route on real streets/paths starting
        and ending at the given point, matching the target distance as
        closely as OpenRouteService's routing can manage

        Uses OpenRouteService's round-trip routing (foot-walking profile).
        OpenRouteService's "length" parameter is only a weak preference (see
        module docstring) - to actually hit the target distance, this tool
        tries several seeds internally and returns whichever one came
        closest (or hilliest/flattest - see `prefer`), reporting the
        deviation so you know how good the match is.

        Pass an explicit non-zero `seed` to instead get that EXACT route back
        (e.g. to regenerate the same route a previous call already found and
        reported as good) - skips the search and returns it as-is, whatever
        its actual distance/elevation turns out to be.

        Does NOT push anything to the Garmin watch by itself - pass the
        returned "gpx" to create_garmin_course for that. Also returns a
        `google_maps_preview_approximate` link, which is NOT the real route:
        it's Google's own driving/walking directions between a handful of
        sampled waypoints (Google's URL API caps waypoints at 23, far fewer
        than the route's real 100+ points), and can diverge noticeably from
        the actual GPX, especially on sparse rural roads - confirmed live,
        don't treat it as ground truth for what the route actually looks like.

        Args:
            distance_km: Target route distance in kilometers
            start_lat: Starting point latitude - provide this + start_lon, OR start_address, not both
            start_lon: Starting point longitude
            start_address: Free-text starting address/place name - resolved via the same
                geocoder as geocode_address(); if given, start_lat/start_lon are ignored.
                The response includes which resolved address/coordinates were actually
                used, and its geocoding confidence - check it before trusting the route,
                since a low-confidence match may only be a town centroid, not the exact
                street asked for.
            points: Number of waypoints shaping the loop OpenRouteService's
                round_trip algorithm targets. There's a real trade-off here,
                confirmed live - it's not simply "higher is better":
                lower values (default 3, the minimum OpenRouteService allows)
                stayed closer to the target distance in testing, but can
                produce a long out-and-back spur (walking out, then folding
                back along nearly the same streets) that feels like hitting
                a dead end mid-run. Higher values (e.g. 5) tended to produce
                more genuinely loop-shaped routes with fewer/shorter spurs,
                at some cost to distance accuracy. If the first result has an
                awkward spur, retrying with a higher points value (or a
                different seed) is worth it before assuming 3 is always right.
            seed: Optional integer to get back one EXACT specific route
                (skips the closest-match search); 0 (default) searches
                several seeds and returns the closest match
            prefer: "distance" (default) picks the seed closest to distance_km.
                "hilly" or "flat" additionally request elevation data and pick
                the seed with the most/least total ascent among the same
                candidates, still reporting distance so you can judge the
                trade-off. NOTE: elevation support is implemented against
                OpenRouteService's documented request/response format but
                NOT YET independently live-verified end to end (development
                hit OpenRouteService's request quota before this could be
                confirmed against a real response) - treat ascent_m/descent_m
                in the result with more caution than the rest of this tool's
                output until that's done.
        """
        api_key = os.environ.get("OPENROUTESERVICE_API_KEY")
        if not api_key:
            return (
                "No OpenRouteService API key configured. Set the "
                "OPENROUTESERVICE_API_KEY environment variable (get a free key "
                "at https://openrouteservice.org/dev/#/signup) and restart this "
                "MCP server."
            )
        if prefer not in ("distance", "hilly", "flat"):
            return "prefer must be one of: distance, hilly, flat"
        want_elevation = prefer != "distance"

        geocode_info = None
        if start_address:
            geocoded, error = _geocode(api_key, start_address)
            if error:
                return error
            start_lat, start_lon = geocoded["lat"], geocoded["lon"]
            geocode_info = geocoded
        elif not (start_lat or start_lon):
            return "Provide either start_lat+start_lon or start_address."

        if seed:
            result, error = _request_route(
                api_key, start_lat, start_lon, distance_km, points, seed, want_elevation
            )
            if error:
                return error
            if result is None:
                return f"OpenRouteService found no route for seed={seed} - try a different seed."
            candidates_tried = 1
        else:
            best = None
            errors = []
            for candidate_seed in range(1, _AUTO_SEED_ATTEMPTS + 1):
                result, error = _request_route(
                    api_key, start_lat, start_lon, distance_km, points, candidate_seed, want_elevation
                )
                if error:
                    errors.append(error)
                    continue
                if result is None:
                    continue
                if prefer == "hilly":
                    score = -(result.get("ascent_m") or 0)
                elif prefer == "flat":
                    score = result.get("ascent_m") or 0
                else:
                    score = abs(result["actual_km"] - distance_km)
                if best is None or score < best[0]:
                    best = (score, result)

            if best is None:
                return errors[0] if errors else "OpenRouteService found no valid route for this start point/distance."
            result = best[1]
            candidates_tried = _AUTO_SEED_ATTEMPTS

        route_name = f"Generated route {distance_km}km from ({start_lat},{start_lon})"

        response = {
            "start_lat": start_lat,
            "start_lon": start_lon,
            "requested_distance_km": distance_km,
            "actual_distance_km": result["actual_km"],
            "deviation_km": round(abs(result["actual_km"] - distance_km), 2),
            "seed_used": result["seed"],
            "seeds_tried": candidates_tried,
            "estimated_walking_duration_min": result["duration_min"],
            "waypoint_count": len(result["coords"]),
            "google_maps_preview_approximate": _google_maps_link(result["coords"]),
            "gpx": _build_gpx(result["coords"], route_name),
        }
        if want_elevation:
            response["ascent_m"] = result.get("ascent_m")
            response["descent_m"] = result.get("descent_m")
            response["_elevation_caveat"] = (
                "ascent_m/descent_m follow OpenRouteService's documented format "
                "but are not yet independently live-verified - see prefer's docstring."
            )
        if geocode_info is not None:
            response["geocoded_from_address"] = start_address
            response["geocoded_label"] = geocode_info["label"]
            response["geocode_confidence"] = geocode_info["confidence"]
            response["geocode_match_type"] = geocode_info["match_type"]

        return json.dumps(response, indent=2)

    @app.tool()
    async def create_garmin_course(
        gpx: str,
        course_name: str,
        activity_type: str = "running",
        private: bool = True,
    ) -> str:
        """Upload a GPX route (e.g. from generate_running_route) to Garmin
        Connect as a navigable "Course" - syncs to the watch like any other
        course, so it can actually be followed turn-by-turn on a run

        Reverse-engineered from Garmin's undocumented course-service API (see
        module docstring for the source and live-verification details) -
        there is no public/official API for this. Uses the same account
        auth as the rest of this server, no extra login.

        Args:
            gpx: A GPX string containing <trkpt lat=".." lon=".."> points,
                e.g. the "gpx" field from generate_running_route's response
            course_name: Name shown for the course in Garmin Connect/on the watch
            activity_type: One of "running", "cycling", "hiking", "other" (default "running")
            private: Keep the course private to this account (default True) -
                set False to make it publicly visible/searchable on Garmin Connect
        """
        if garmin_client is None:
            return "Garmin client not configured."

        activity_type_id = _ACTIVITY_TYPE_IDS.get(activity_type.lower())
        if activity_type_id is None:
            return f"Unknown activity_type {activity_type!r} - use one of {list(_ACTIVITY_TYPE_IDS)}."

        coords = _parse_gpx_trkpts(gpx)
        if len(coords) < 2:
            return "GPX contained fewer than 2 track points - nothing to upload."

        geo_points = []
        cum_dist = 0.0
        for i, (lon, lat) in enumerate(coords):
            if i > 0:
                prev_lon, prev_lat = coords[i - 1]
                cum_dist += _haversine_m(prev_lon, prev_lat, lon, lat)
            geo_points.append({
                "latitude": lat,
                "longitude": lon,
                "elevation": None,
                "distance": round(cum_dist, 2),
                "timestamp": None,
            })

        course_request = {
            "activityTypePk": activity_type_id,
            "hasTurnDetectionDisabled": False,
            "geoPoints": geo_points,
            "courseLines": [],
            "coursePoints": [],
            "startPoint": geo_points[0],
            "elapsedSeconds": None,
            "openStreetMap": False,
            "coordinateSystem": "WGS84",
            "rulePK": 2 if private else 1,
            "courseName": course_name,
            "matchedToSegments": False,
            "includeLaps": False,
            "hasPaceBand": False,
            "hasPowerGuide": False,
            "favorite": False,
            "speedMeterPerSecond": None,
            "sourceTypeId": 3,
        }

        try:
            response = garmin_client.garth.post(
                "connectapi", "course-service/course", json=course_request
            )
        except Exception as e:
            return f"Error creating course: {str(e)}"

        if response.status_code != 200:
            return f"Course creation failed: HTTP {response.status_code} - {response.text[:300]}"

        created = response.json()
        return json.dumps({
            "status": "success",
            "course_id": created.get("courseId"),
            "course_name": created.get("courseName"),
            "distance_meters": created.get("distanceMeter"),
            "elevation_gain_meters": created.get("elevationGainMeter"),
            "private": private,
        }, indent=2)

    @app.tool()
    async def list_garmin_courses() -> str:
        """List all Garmin Connect courses on this account (id, name, distance,
        activity type) - read-only"""
        if garmin_client is None:
            return "Garmin client not configured."
        try:
            response = garmin_client.garth.get("connectapi", "web-gateway/course/owner/")
        except Exception as e:
            return f"Error listing courses: {str(e)}"
        if response.status_code != 200:
            return f"Listing courses failed: HTTP {response.status_code} - {response.text[:300]}"
        return json.dumps(response.json(), indent=2, default=str)

    @app.tool()
    async def delete_garmin_course(course_id: int) -> str:
        """Permanently delete a Garmin Connect course by id (from
        create_garmin_course's response or list_garmin_courses)"""
        if garmin_client is None:
            return "Garmin client not configured."
        try:
            response = garmin_client.garth.delete(
                "connectapi", f"course-service/course/{course_id}", api=True
            )
        except Exception as e:
            return f"Error deleting course: {str(e)}"
        if response.status_code in (200, 204):
            return json.dumps({"status": "success", "course_id": course_id}, indent=2)
        return f"Delete failed: HTTP {response.status_code} - {response.text[:300]}"

    return app
