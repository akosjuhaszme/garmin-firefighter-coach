"""
Running route generation for Garmin MCP Server

Not a Garmin API - Garmin has no public route/course-generation endpoint at
all (the official "Courses API" is business/institution-gated). Uses
OpenRouteService's free "round trip" directions feature instead: given a
start point and a target distance, it generates a loop route on real streets
and paths. Requires OPENROUTESERVICE_API_KEY as an environment variable.

This only generates the route (coordinates + a shareable link + a GPX
string). Getting it onto the watch as a navigable Garmin "Course" is a
separate, still-unsolved problem - python-garminconnect has no course
upload support and Garmin's course-service endpoints are undocumented.
Until that's solved, hand the GPX/link to the user to import manually.

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
import os

import requests

DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/foot-walking/geojson"

# How many seeds to try (when the caller doesn't pin one) before returning the
# closest match. ~15 calls took ~3s in testing - cheap against the free tier's
# per-minute limit, and found a match within 2% of target in practice.
_AUTO_SEED_ATTEMPTS = 15


def _build_gpx(coordinates: list, name: str) -> str:
    """Build a minimal GPX 1.1 track from a list of [lon, lat] pairs."""
    trkpts = "\n".join(
        f'      <trkpt lat="{lat}" lon="{lon}"></trkpt>' for lon, lat in coordinates
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="garmin-firefighter-coach" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk>\n    <name>{name}</name>\n    <trkseg>\n{trkpts}\n"
        "    </trkseg>\n  </trk>\n</gpx>"
    )


def _google_maps_link(coordinates: list) -> str:
    """Build a Google Maps directions link from a sampled subset of waypoints
    (Maps caps the number of waypoints in a URL, so this is a fallback for
    manual use, not an exact replay of the generated route)."""
    if len(coordinates) <= 10:
        sample = coordinates
    else:
        step = len(coordinates) // 9
        sample = coordinates[::step][:9] + [coordinates[-1]]
    points = "/".join(f"{lat},{lon}" for lon, lat in sample)
    return f"https://www.google.com/maps/dir/{points}"


def _request_route(api_key, start_lat, start_lon, distance_km, points, seed):
    """Make one round-trip request to OpenRouteService. Returns
    (result_dict_or_None, error_message_or_None)."""
    round_trip = {"length": distance_km * 1000, "points": max(3, points), "seed": seed}

    try:
        response = requests.post(
            DIRECTIONS_URL,
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "coordinates": [[start_lon, start_lat]],
                "options": {"round_trip": round_trip},
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return None, f"Error contacting OpenRouteService: {str(e)}"

    if response.status_code in (401, 403):
        return None, "OpenRouteService rejected the API key - check OPENROUTESERVICE_API_KEY."
    if response.status_code != 200:
        return None, f"OpenRouteService request failed: HTTP {response.status_code} - {response.text[:300]}"

    data = response.json()
    features = data.get("features") or []
    if not features:
        return None, None  # no route found for this seed - not a hard error, just skip it

    feature = features[0]
    coords = feature.get("geometry", {}).get("coordinates", [])
    summary = feature.get("properties", {}).get("summary", {})
    return {
        "seed": seed,
        "coords": coords,
        "actual_km": round(summary.get("distance", 0) / 1000, 2),
        "duration_min": round(summary.get("duration", 0) / 60, 1),
    }, None


def register_tools(app):
    """Register route-generation tools with the MCP server app"""

    @app.tool()
    async def generate_running_route(
        start_lat: float,
        start_lon: float,
        distance_km: float,
        points: int = 3,
        seed: int = 0,
    ) -> str:
        """Generate a round-trip running route on real streets/paths starting
        and ending at the given point, matching the target distance as
        closely as OpenRouteService's routing can manage

        Uses OpenRouteService's round-trip routing (foot-walking profile).
        OpenRouteService's "length" parameter is only a weak preference (see
        module docstring) - to actually hit the target distance, this tool
        tries several seeds internally and returns whichever one came
        closest, reporting the deviation so you know how good the match is.

        Pass an explicit non-zero `seed` to instead get that EXACT route back
        (e.g. to regenerate the same route a previous call already found and
        reported as good) - skips the search and returns it as-is, whatever
        its actual distance turns out to be.

        Does NOT push anything to the Garmin watch - that requires a Garmin
        "Course" upload, which isn't supported yet (see module docstring).
        Returns a GPX string (for manual import into Garmin Connect ->
        Courses -> Import) and a Google Maps link as a quick preview.

        Args:
            start_lat: Starting point latitude
            start_lon: Starting point longitude
            distance_km: Target route distance in kilometers
            points: Number of waypoints shaping the loop - lower values
                stayed closer to the target distance in testing (default 3,
                the minimum OpenRouteService allows)
            seed: Optional integer to get back one EXACT specific route
                (skips the closest-match search); 0 (default) searches
                several seeds and returns the closest match
        """
        api_key = os.environ.get("OPENROUTESERVICE_API_KEY")
        if not api_key:
            return (
                "No OpenRouteService API key configured. Set the "
                "OPENROUTESERVICE_API_KEY environment variable (get a free key "
                "at https://openrouteservice.org/dev/#/signup) and restart this "
                "MCP server."
            )

        if seed:
            result, error = _request_route(api_key, start_lat, start_lon, distance_km, points, seed)
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
                    api_key, start_lat, start_lon, distance_km, points, candidate_seed
                )
                if error:
                    errors.append(error)
                    continue
                if result is None:
                    continue
                deviation = abs(result["actual_km"] - distance_km)
                if best is None or deviation < best[0]:
                    best = (deviation, result)

            if best is None:
                return errors[0] if errors else "OpenRouteService found no valid route for this start point/distance."
            result = best[1]
            candidates_tried = _AUTO_SEED_ATTEMPTS

        route_name = f"Generated route {distance_km}km from ({start_lat},{start_lon})"

        return json.dumps({
            "requested_distance_km": distance_km,
            "actual_distance_km": result["actual_km"],
            "deviation_km": round(abs(result["actual_km"] - distance_km), 2),
            "seed_used": result["seed"],
            "seeds_tried": candidates_tried,
            "estimated_walking_duration_min": result["duration_min"],
            "waypoint_count": len(result["coords"]),
            "google_maps_preview": _google_maps_link(result["coords"]),
            "gpx": _build_gpx(result["coords"], route_name),
        }, indent=2)

    return app
