"""
Calendar events (races) for Garmin Connect MCP Server

Shared helpers for the Events feature of the Garmin Connect calendar
(calendar-service/events, calendar-service/event/{id}) plus tools to create,
change and delete one event. get_calendar_events (recovery.py) reads through the
same helpers.

The write tools were checked live against a throwaway event that was created,
changed and deleted again; nothing else on the calendar was touched. Garmin
rejects a new event that is a year or more in the future.
"""
import calendar
import datetime
import difflib
import json
import re
import unicodedata
from typing import Optional

from garth.exc import GarthHTTPError

# The garmin_client will be set by the main file
garmin_client = None

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_PRIVATE = {"label": "PRIVATE", "isShareable": False, "isDiscoverable": False}
_KM_PER_UNIT = {"kilometer": 1.0, "meter": 0.001, "mile": 1.609344}


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


# ---------------------------------------------------------------- helpers


def format_goal(seconds) -> Optional[str]:
    """Goal time in seconds -> 'h:mm:ss' (None when there is no goal)."""
    if seconds in (None, ""):
        return None
    total = int(round(float(seconds)))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def parse_goal(text: str) -> int:
    """'h:mm:ss' or 'h:mm' (hours:minutes) -> seconds."""
    parts = str(text).strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError("goal_time must look like 1:40:00 (h:mm:ss) or 3:50 (h:mm)")
    numbers = [int(p) for p in parts]
    hours, minutes, seconds = numbers[0], numbers[1], (numbers[2] if len(numbers) == 3 else 0)
    if minutes > 59 or seconds > 59:
        raise ValueError("goal_time minutes and seconds must be below 60")
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("goal_time must be longer than zero")
    return total


def event_row(item: dict) -> dict:
    """One calendar event in the shape the tools return."""
    target = item.get("completionTarget") or {}
    goal = (item.get("eventCustomization") or {}).get("customGoal")
    goal_seconds = goal.get("value") if isinstance(goal, dict) else goal
    value, unit = target.get("value"), target.get("unit")
    factor = _KM_PER_UNIT.get(unit)
    return {
        "event_id": item.get("id"),
        "title": item.get("eventName") or item.get("title"),
        "date": item.get("date"),
        "start_time": (item.get("eventTimeLocal") or {}).get("startTimeHhMm"),
        "event_type": item.get("eventType"),
        "location": item.get("location") or None,
        "distance_km": round(value * factor, 3) if value is not None and factor else None,
        "distance": value,
        "distance_unit": unit,
        "goal_time": format_goal(goal_seconds),
        "privacy": (item.get("eventPrivacy") or {}).get("label"),
        "url": item.get("url") or None,
        "note": item.get("note") or None,
        "is_race": item.get("race", item.get("isRace")),
    }


def fetch_events(client, start_date: str, end_date: str) -> list:
    """Raw event objects between two dates (YYYY-MM-DD, inclusive), sorted by date."""
    response = client.garth.get(
        "connectapi",
        "calendar-service/events",
        params={"startDate": start_date, "endDate": end_date},
    )
    rows = response.json() or []
    return sorted(rows, key=lambda r: (r.get("date") or "", r.get("id") or 0))


def month_range(start_year: int, start_month: int, months: int):
    """First and last day (YYYY-MM-DD) of `months` consecutive calendar months."""
    end_year, end_month = start_year, start_month + months - 1
    end_year += (end_month - 1) // 12
    end_month = (end_month - 1) % 12 + 1
    last_day = calendar.monthrange(end_year, end_month)[1]
    return (
        f"{start_year}-{start_month:02d}-01",
        f"{end_year}-{end_month:02d}-{last_day:02d}",
    )


def _request(method: str, path: str, **kwargs):
    """(status code, parsed body). garth raises on every HTTP error status, so
    unwrap that into a plain result."""
    try:
        response = garmin_client.garth.request(method, "connectapi", path, api=True, **kwargs)
        status, text = response.status_code, response.text
    except GarthHTTPError as e:
        response = getattr(getattr(e, "error", None), "response", None)
        status = getattr(response, "status_code", None)
        text = getattr(response, "text", "") or str(e)
    try:
        body = json.loads(text) if text else None
    except ValueError:
        body = text
    return status, body


def _problem(body) -> str:
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return str(body)[:300] if body else "no details"


def _check_date(text: str) -> str:
    try:
        day = datetime.date.fromisoformat(text)
    except (TypeError, ValueError):
        raise ValueError("date must be YYYY-MM-DD")
    today = datetime.date.today()
    if day < today:
        raise ValueError(f"{text} is in the past")
    if day > today + datetime.timedelta(days=366):
        raise ValueError(
            f"{text} is too far ahead: Garmin only accepts events less than a year in the future"
        )
    return day.isoformat()


def _check_time(text: str) -> str:
    match = _TIME_RE.match(str(text).strip())
    if not match:
        raise ValueError("start_time must be HH:MM (24 hour clock)")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _check_distance(km) -> float:
    if km is None or float(km) <= 0 or float(km) > 1000:
        raise ValueError("distance_km must be between 0 and 1000")
    return float(km)


def _same_name(a: Optional[str], b: Optional[str]) -> bool:
    return " ".join((a or "").casefold().split()) == " ".join((b or "").casefold().split())


def _events_around_today() -> list:
    today = datetime.date.today()
    return fetch_events(
        garmin_client,
        (today - datetime.timedelta(days=365)).isoformat(),
        (today + datetime.timedelta(days=800)).isoformat(),
    )


def _same_day_report(rows: list, date: str, name: str, skip_id=None):
    """(duplicate raw event or None, other events that day as rows)."""
    duplicate, others = None, []
    for row in rows:
        if row.get("date") != date or row.get("id") == skip_id:
            continue
        if _same_name(row.get("eventName"), name):
            duplicate = row
        else:
            others.append(event_row(row))
    return duplicate, others


# Words that say "this is a race" but not WHICH race, so they never count as a match
# on their own ("Capital Air Half Marathon" and "Seaside Half Marathon").
_GENERIC_WORDS = {
    "the", "and", "of", "half", "marathon", "halfmarathon", "maraton", "felmaraton",
    "polmaraton", "run", "running", "race", "edition", "km",
}


def _name_tokens(name: Optional[str]) -> list:
    """Lower-case words without accents or punctuation ('Félmaratón' -> 'felmaraton')."""
    plain = unicodedata.normalize("NFKD", name or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()
    return [t for t in re.sub(r"[^0-9a-z]+", " ", plain).split() if not t.isdigit() and len(t) > 1]


def similar_names(a: Optional[str], b: Optional[str], km_a=None, km_b=None) -> Optional[str]:
    """Why two event names look like the same event, or None when they do not.

    Accent, case and punctuation do not matter, edition numbers and years are
    ignored, 'Capital Air' and 'Capitalair' count as the same. Two names that give clearly
    different distances (more than 12 % apart) are different events."""
    tokens_a, tokens_b = _name_tokens(a), _name_tokens(b)
    if not tokens_a or not tokens_b:
        return None
    if tokens_a == tokens_b:
        return "same name"
    if km_a and km_b and abs(km_a - km_b) > 0.12 * max(km_a, km_b):
        return None
    key_a = [t for t in tokens_a if t not in _GENERIC_WORDS]
    key_b = [t for t in tokens_b if t not in _GENERIC_WORDS]
    joined_a, joined_b = "".join(key_a), "".join(key_b)
    if min(len(joined_a), len(joined_b)) >= 6 and (joined_a in joined_b or joined_b in joined_a):
        return "same key words"
    shared = sorted(set(key_a) & set(key_b))
    if len(shared) >= 2 or (len(shared) == 1 and len(shared[0]) >= 5):
        return "shared words: " + ", ".join(shared)
    if difflib.SequenceMatcher(None, " ".join(tokens_a), " ".join(tokens_b)).ratio() >= 0.8:
        return "very similar wording"
    return None


def _target_km(target: Optional[dict]) -> Optional[float]:
    target = target or {}
    factor = _KM_PER_UNIT.get(target.get("unit"))
    return target.get("value") * factor if target.get("value") is not None and factor else None


def catalog_row(item: dict) -> dict:
    """One event from Garmin's catalog of organiser-published events."""
    area = item.get("administrativeArea") or {}
    km = _target_km(item.get("completionTarget"))
    return {
        "catalog_event_id": item.get("id"),
        "catalog_uuid": item.get("shareableEventUuid"),
        "title": item.get("eventName"),
        "date": item.get("date"),
        "start_time": (item.get("eventStartTime") or {}).get("startTimeHhMm"),
        "event_type": item.get("eventType"),
        "distance_km": round(km, 3) if km is not None else None,
        "city": area.get("cityEn") or area.get("cityNative"),
        "country": area.get("countryCode"),
        "provider": item.get("eventsProvider"),
        "subscribers": item.get("subscribersCount"),
        "official": item.get("official"),
        "url": item.get("url") or None,
    }


# What the Garmin apps call "Hivatalos esemény" (OFFICIAL), "Ellenőrzött forrás" (VERIFIED, e.g. a
# race published through a partner such as ahotu) and events added by Garmin Connect users (NONE).
_SOURCE_NAMES = {"official": "OFFICIAL", "verified": "VERIFIED", "unverified": "NONE"}
_EVENT_TYPE_ALIASES = {"triathlon": "multi_sport_triathlon", "motorcycling": "motorcycling_v2", "mtb": "mountain_biking"}
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def race_rows(item: dict) -> list:
    """Rows for one race-search result: one row per distance the race offers (the Garmin
    apps list each distance of a race separately)."""
    area = item.get("administrativeArea") or {}
    base = {
        "catalog_uuid": item.get("garminEventUuid"),
        "title": item.get("eventName"),
        "date": item.get("eventDate"),
        "start_time": (item.get("eventStartTime") or {}).get("startTimeHhMm"),
        "event_type": item.get("eventType"),
        "city": area.get("cityEn") or area.get("cityNative"),
        "country": area.get("countryCode"),
        "provider": item.get("provider"),
        "verified_status": item.get("verifiedStatus"),
        "official": item.get("isOfficial"),
        "has_course": item.get("hasCourse"),
        "url": item.get("eventUrl") or None,
    }
    rows = []
    for target in item.get("completionTargets") or [None]:
        km = _target_km(target)
        rows.append({**base, "distance_km": round(km, 3) if km is not None else None})
    return rows


def fetch_race_search(client, **params) -> list:
    """Raw results of Garmin's race search (race-search/events), the service behind the
    "search for an event" screens of Garmin Connect and the phone app."""
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return client.garth.get("connectapi", "race-search/events", params=params).json() or []


def fetch_catalog(client, **params) -> list:
    """Raw events from Garmin's catalog of organiser-published events
    (calendar-service/events/discover). Parameters are Garmin's own names: fromDate,
    toDate, searchPhrase, eventType, poiLat, poiLon, withinMeters, limit (max 1000)."""
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return client.garth.get("connectapi", "calendar-service/events/discover", params=params).json() or []


def _catalog_for_day(day: str, name: str) -> list:
    """Every catalog event on one date. Garmin returns at most 1000 per request; on a
    day that busy the list is topped up with searches for the words of the name."""
    found = {r["id"]: r for r in fetch_catalog(garmin_client, fromDate=day, toDate=day, limit=1000)}
    if len(found) >= 1000:
        for word in sorted({t for t in _name_tokens(name) if t not in _GENERIC_WORDS}):
            for r in fetch_catalog(garmin_client, fromDate=day, toDate=day, searchPhrase=word, limit=1000):
                found.setdefault(r["id"], r)
    return list(found.values())


def _similar_events(own_rows: list, catalog: list, day: str, name: str, km: Optional[float]):
    """(similar events on the user's calendar, similar catalog events) for one date.
    Exact same-name events on the calendar are handled before this."""
    own = []
    for row in own_rows:
        if row.get("date") != day or _same_name(row.get("eventName"), name):
            continue
        reason = similar_names(name, row.get("eventName"), km, _target_km(row.get("completionTarget")))
        if reason:
            own.append({**event_row(row), "match": reason})
    listed = []
    for item in catalog:
        if item.get("date") != day:
            continue
        reason = similar_names(name, item.get("eventName"), km, _target_km(item.get("completionTarget")))
        if reason:
            listed.append({**catalog_row(item), "match": reason})
    listed.sort(key=lambda r: r.get("subscribers") or 0, reverse=True)
    return own, listed


def _listed_by_uuid(rows: list, uuid: str):
    wanted = (uuid or "").lower()
    return next((r for r in rows if (r.get("shareableEventUuid") or "").lower() == wanted), None)


def _organiser_event(rows: list, event_id):
    """The calendar row of an event that belongs to an organiser (added from the catalog), or
    None. Those are addressed by their UUID and the numeric event id is not served by GET."""
    for row in rows:
        if row.get("id") == int(event_id) and row.get("shareableEventUuid") and row.get("eventOrganizer") is False:
            return row
    return None


def _set_goal_by_uuid(row: dict, goal_seconds):
    """Set (or, with None, clear) the goal time of an organiser event on the calendar."""
    custom = json.loads(json.dumps(row.get("eventCustomization") or {}))
    custom["customGoal"] = (
        {"value": float(goal_seconds), "unit": "second", "unitType": "time"} if goal_seconds else None
    )
    return _request("PUT", f"calendar-service/event/{row['shareableEventUuid']}/customization", json=custom)


def _update_organiser_goal(row: dict, goal_time, clear_goal_time: bool, other_fields_given: bool) -> str:
    """update_calendar_event for a race that came from the catalog: only the goal time is the
    user's to change."""
    before = event_row(row)
    if other_fields_given:
        return _dump({
            "status": "organiser_event",
            "message": "This race belongs to its organiser, so only goal_time (or clear_goal_time) can be changed. "
                       "Nothing was changed.",
            "event": before,
        })
    goal_seconds = parse_goal(goal_time) if goal_time else None
    put_status, put_body = _set_goal_by_uuid(row, goal_seconds)
    if put_status not in (200, 204):
        return _dump({
            "status": "failed",
            "http_status": put_status,
            "message": _problem(put_body),
            "note": "The event was not changed.",
        })
    after_row = _listed_by_uuid(_events_around_today(), row["shareableEventUuid"])
    if after_row is None:
        return _dump({
            "status": "updated_unverified",
            "message": "Garmin accepted the change but the event could not be read back.",
            "event_id": row.get("id"),
        })
    after = event_row(after_row)
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
    result = {"status": "updated", "event_id": row.get("id"), "changes": changes, "event": after}
    if after["goal_time"] != format_goal(goal_seconds):
        result["status"] = "updated_partly"
        result["warning"] = "Garmin did not keep the goal time as requested."
    return _dump(result)


def _remove_organiser_event(row: dict, confirm: bool) -> str:
    """delete_calendar_event for a race that came from the catalog: stop following it. The
    organiser's entry stays in the catalog and can be added again."""
    event = event_row(row)
    if not confirm:
        return _dump({
            "status": "confirmation_required",
            "message": "Nothing was deleted. This race comes from the organiser's catalog entry; deleting it takes "
                       "it off the user's calendar only (it can be added again with add_catalog_event_to_calendar). "
                       "Ask the user whether this exact event should go, then call again with confirm=true.",
            "event": event,
        })
    status, body = _request("DELETE", f"calendar-service/event/{row['shareableEventUuid']}/subscription")
    if status not in (200, 204):
        return _dump({"status": "failed", "http_status": status, "message": _problem(body), "event": event})
    gone = _listed_by_uuid(_events_around_today(), row["shareableEventUuid"]) is None
    return _dump({"status": "deleted" if gone else "delete_unverified", "event": event})


def _usual_timezone(rows: list) -> Optional[str]:
    zones = [(r.get("eventTimeLocal") or {}).get("timeZoneId") for r in rows]
    zones = [z for z in zones if z]
    return max(set(zones), key=zones.count) if zones else None


def _get_event(event_id: int):
    return _request("GET", f"calendar-service/event/{int(event_id)}")


def _dump(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ tools


def register_tools(app):
    """Register the calendar event write tools with the MCP server app"""

    @app.tool()
    async def create_calendar_event(
        name: str,
        date: str,
        start_time: str = "09:00",
        distance_km: Optional[float] = None,
        location: Optional[str] = None,
        goal_time: Optional[str] = None,
        event_type: str = "running",
        timezone_id: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        url: Optional[str] = None,
        note: Optional[str] = None,
        is_race: bool = False,
        create_anyway: bool = False,
    ) -> str:
        """Add ONE race / event to the Garmin Connect calendar (the Events feature)

        Only call this when the user asked for this event to be added. The event is
        always created PRIVATE (visible to the user only). Checks before anything is
        written: the date must be today or later and less than a year ahead (Garmin
        refuses anything further out). Organisers often publish their race in Garmin's
        event catalog beforehand, so the tool first looks for an event with a similar
        name on the same date, both on the user's calendar and in that catalog (see
        search_event_catalog). If it finds one it adds nothing and returns the matches:
        show them to the user, because adding the organiser's published event
        (add_catalog_event_to_calendar) is usually better than a private copy. Repeat with
        create_anyway=true only after the user said a separate private event is wanted.
        An event with exactly the same name on the same date is never added twice.
        Other events on that date are listed as a warning. The goal time and the race
        flag are set right after creation. Undo with delete_calendar_event.

        Args:
            name: Event title, e.g. "City Half Marathon"
            date: Event date, YYYY-MM-DD
            start_time: Start time HH:MM, 24 hour clock, local time (default 09:00)
            distance_km: Distance in kilometres, e.g. 21.1 (recommended)
            location: Place name, e.g. "Budapest, Hungary"
            goal_time: Goal finish time as h:mm:ss (1:40:00) or h:mm (3:50)
            event_type: Garmin event type, "running" (default) or e.g. "hiking"
            timezone_id: Time zone of the start time; by default the one the existing
                events on the calendar use. Required if the calendar has no events yet.
            latitude: Optional start point latitude (decimal degrees)
            longitude: Optional start point longitude (decimal degrees)
            url: Optional event web page
            note: Optional free text
            is_race: True marks the event as a race (the flag Garmin shows as "race" in
                the calendar). It does not make the event public.
            create_anyway: True skips the similar-event check (only after the user
                agreed to a separate private event)
        """
        try:
            title = " ".join((name or "").split())
            if not title:
                return "Error: name must not be empty"
            day = _check_date(date)
            start = _check_time(start_time)
            km = _check_distance(distance_km) if distance_km is not None else None
            goal_seconds = parse_goal(goal_time) if goal_time else None
            if (latitude is None) != (longitude is None):
                return "Error: give latitude and longitude together"

            rows = _events_around_today()
            duplicate, others = _same_day_report(rows, day, title)
            if duplicate:
                return _dump({
                    "status": "duplicate",
                    "message": "An event with this name already exists on this date; nothing was added. "
                               "Use update_calendar_event to change it.",
                    "existing_event": event_row(duplicate),
                })
            if not create_anyway:
                try:
                    own_similar, catalog_similar = _similar_events(
                        rows, _catalog_for_day(day, title), day, title, km
                    )
                except Exception as e:
                    return _dump({
                        "status": "check_failed",
                        "message": f"Could not check Garmin's event catalog ({str(e)[:200]}). Nothing was added. "
                                   "Try again, or repeat with create_anyway=true if the user wants to skip the check.",
                    })
                if own_similar or catalog_similar:
                    return _dump({
                        "status": "similar_event_found",
                        "message": "An event with a similar name is already on this date; nothing was added. "
                                   "Show the matches to the user. An event published by the organiser "
                                   "(catalog_matches) is usually better than a private copy: add it with "
                                   "add_catalog_event_to_calendar(catalog_uuid) if the user agrees. Repeat with "
                                   "create_anyway=true only if the user wants a separate private event anyway.",
                        "own_calendar_matches": own_similar,
                        "catalog_matches": catalog_similar[:10],
                    })
            zone = timezone_id or _usual_timezone(rows)
            if not zone:
                return "Error: no time zone known yet - pass timezone_id (e.g. the zone Garmin shows for your events)"

            body = {
                "eventName": title,
                "date": day,
                "eventTimeLocal": {"startTimeHhMm": start, "timeZoneId": zone},
                "eventType": event_type,
                "eventPrivacy": dict(_PRIVATE),
                "eventCustomization": {"customGoal": None, "isPrimaryEvent": False},
            }
            if km is not None:
                body["completionTarget"] = {"value": km, "unit": "kilometer", "unitType": "distance"}
            if location:
                body["location"] = location
            if latitude is not None:
                body["locationStartPoint"] = {"lat": latitude, "lon": longitude}
            if url:
                body["url"] = url
            if note:
                body["note"] = note

            status, created = _request("POST", "calendar-service/event", json=body)
            if status not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
                return _dump({
                    "status": "failed",
                    "http_status": status,
                    "message": _problem(created),
                    "note": "Nothing was added.",
                })
            event_id = created["id"]

            warnings = []
            if others:
                warnings.append(f"{len(others)} other event(s) are already on {day}")
            result = {"status": "created", "event_id": event_id}
            if goal_seconds or is_race:
                status, detail = _get_event(event_id)
                if status == 200 and isinstance(detail, dict):
                    if goal_seconds:
                        detail["eventCustomization"]["customGoal"] = {
                            "value": float(goal_seconds), "unit": "second", "unitType": "time",
                        }
                    if is_race:
                        detail["race"] = True
                    put_status, put_body = _request("PUT", f"calendar-service/event/{event_id}", json=detail)
                else:
                    put_status, put_body = status, detail
                if put_status not in (200, 204):
                    result["status"] = "created_partly"
                    warnings.append(
                        "The event was added but the goal time / race flag was not saved "
                        f"({_problem(put_body)}). Retry with update_calendar_event."
                    )
            status, final = _get_event(event_id)
            result["event"] = event_row(final if status == 200 and isinstance(final, dict) else created)
            if others:
                result["other_events_that_day"] = others
            if warnings:
                result["warnings"] = warnings
            return _dump(result)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error creating calendar event: {str(e)}"

    @app.tool()
    async def search_event_catalog(
        search_phrase: str = "",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_km: Optional[float] = None,
        max_km: Optional[float] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        within_km: Optional[float] = None,
        source: Optional[str] = None,
        provider: Optional[str] = None,
        event_type: Optional[str] = None,
        include_virtual: bool = False,
        limit: int = 50,
    ) -> str:
        """Search Garmin's catalog of races published by organisers (read-only)

        This is the same search as "Verseny keresése" / "search for an event" in the
        Garmin Connect app and website. Many races are already there before anyone adds
        them by hand, with the organiser's distance, start time and web page, so look
        here first when the user asks about a race, an event abroad, or races of a
        given distance near a place. Words match the event name and place (accents and
        capitals do not matter, all words must match). A race that offers several
        distances gets one row per distance. Nothing is added: put a result on the
        calendar with add_catalog_event_to_calendar(catalog_uuid).

        verified_status in the rows: OFFICIAL = "Hivatalos esemény" (official event),
        VERIFIED = "Ellenőrzött forrás" (published by a verified provider such as
        ahotu), NONE = added by Garmin Connect users. By default only OFFICIAL and
        VERIFIED events are returned, as in the app.

        Args:
            search_phrase: Words to look for, e.g. "springfield half marathon"
            from_date: First date, YYYY-MM-DD (default today)
            to_date: Last date, YYYY-MM-DD (default one year after from_date)
            min_km: Shortest distance in kilometres (e.g. 21 for half marathons and longer)
            max_km: Longest distance in kilometres (e.g. 22 together with min_km=21)
            latitude: Optional centre of a place search (give with longitude and within_km)
            longitude: Optional centre of a place search
            within_km: Optional radius around latitude/longitude, in kilometres
            source: Which events: "official", "verified", "unverified", a comma separated
                mix like "official,verified", or "all" (default "official,verified")
            provider: Optional provider key, e.g. "ahotu", "garmin-events", "active-events"
                ("gc-discoverable-events" = events added by Garmin Connect users)
            event_type: Optional event type as the app's filter offers it: running (all
                running), trail_running, cycling (all cycling), gravel_cycling,
                mountain_biking, swimming, multi_sport_triathlon (also accepted:
                triathlon), multi_sport, hiking, walking, fitness_equipment,
                motorcycling_v2, winter_sports, other; "all" or empty = any type
            include_virtual: True also returns virtual events (default: in-person only)
            limit: Most rows to return (1-200, default 50)
        """
        try:
            first = datetime.date.fromisoformat(from_date) if from_date else datetime.date.today()
            last = datetime.date.fromisoformat(to_date) if to_date else first + datetime.timedelta(days=365)
            if last < first:
                return "Error: to_date is before from_date"
            if (latitude is None) != (longitude is None) or (latitude is not None and not within_km):
                return "Error: a place search needs latitude, longitude and within_km together"
            if min_km is not None and max_km is not None and min_km > max_km:
                return "Error: min_km is larger than max_km"
            wanted = (source or "official,verified").replace(" ", "").casefold()
            names = list(_SOURCE_NAMES) if wanted == "all" else [n for n in wanted.split(",") if n]
            unknown = [n for n in names if n not in _SOURCE_NAMES]
            if unknown or not names:
                return "Error: source must be official, verified, unverified, a comma separated mix, or all"
            limit = max(1, min(int(limit), 200))
            kind = (event_type or "all").strip().casefold()
            kind = _EVENT_TYPE_ALIASES.get(kind, kind)
            raw = fetch_race_search(
                garmin_client,
                fromDate=first.isoformat(),
                toDate=last.isoformat(),
                searchPhrase=" ".join((search_phrase or "").split()),
                eventType=None if kind == "all" else kind,
                eventsProviders=provider,
                includeInPerson="true",
                includeVirtual="true" if include_virtual else "false",
                verifiedStatuses=",".join(_SOURCE_NAMES[n] for n in names),
                completionTargetDurationType="distance",
                completionTargetMinValue=int(min_km * 1000) if min_km else None,
                completionTargetMaxValue=int(max_km * 1000 + 0.999) if max_km else None,
                poiLat=latitude,
                poiLon=longitude,
                withinMeters=int(within_km * 1000) if within_km else None,
                limit=200,
            )
            rows = [row for item in raw for row in race_rows(item)]
            rows.sort(key=lambda r: (r.get("date") or "", r.get("title") or ""))
            if min_km or max_km:  # the service also lists a race when only one of its distances fits
                rows = [
                    r for r in rows
                    if r["distance_km"] is not None
                    and (not min_km or r["distance_km"] >= min_km - 0.001)
                    and (not max_km or r["distance_km"] <= max_km + 0.001)
                ]
            if not rows:
                return f"No catalog events found between {first} and {last} for that search."
            result = {"count": min(len(rows), limit), "events": rows[:limit]}
            if len(rows) > limit or len(raw) >= 200:
                result["note"] = "The list was cut; narrow the dates, the distance or the search words."
            return _dump(result)
        except ValueError:
            return "Error: dates must be YYYY-MM-DD"
        except Exception as e:
            return f"Error searching the event catalog: {str(e)}"

    @app.tool()
    async def add_catalog_event_to_calendar(catalog_uuid: str, goal_time: Optional[str] = None) -> str:
        """Add ONE organiser-published race from Garmin's catalog to the user's calendar

        Only call this when the user asked for this race to be added. Take catalog_uuid
        from search_event_catalog (or from the catalog_matches that create_calendar_event
        returns). This is the same as "Hozzáadás a naptárhoz" in the Garmin Connect app:
        the organiser's own entry (name, distance, start time, web page, race flag) goes
        onto the calendar and counts as one more follower of that race. Organiser events
        are public by nature; if the user wants a private event use create_calendar_event.
        An optional goal time is set right after. Nothing is added twice: if the race is
        already on the calendar the tool says so. A private event of the user's own with a
        similar name on the same date is reported as a warning (delete it with
        delete_calendar_event if it was only a stand-in).

        Args:
            catalog_uuid: The catalog_uuid of the race (a UUID such as 3a9e2cd2-c211-4c6d-bde8-2b61ce98331f)
            goal_time: Optional goal finish time as h:mm:ss (1:40:00) or h:mm (3:50)
        """
        try:
            uuid = (catalog_uuid or "").strip().lower()
            if not _UUID_RE.match(uuid):
                return "Error: catalog_uuid must be a UUID from search_event_catalog"
            goal_seconds = parse_goal(goal_time) if goal_time else None
            rows = _events_around_today()
            on_calendar = _listed_by_uuid(rows, uuid)
            if on_calendar:
                return _dump({
                    "status": "already_on_calendar",
                    "message": "This race is already on the calendar; nothing was added.",
                    "event": event_row(on_calendar),
                })
            status, body = _request("POST", f"calendar-service/event/{uuid}/subscription")
            if status not in (200, 201, 204):
                return _dump({
                    "status": "failed",
                    "http_status": status,
                    "message": _problem(body),
                    "note": "Nothing was added.",
                })
            rows = _events_around_today()
            added = _listed_by_uuid(rows, uuid)
            if not added:
                return _dump({
                    "status": "added_unverified",
                    "message": "Garmin accepted the request but the race is not in the calendar list yet.",
                })
            result = {"status": "added", "event_id": added.get("id")}
            warnings = []
            if goal_seconds:
                put_status, put_body = _set_goal_by_uuid(added, goal_seconds)
                if put_status not in (200, 204):
                    result["status"] = "added_without_goal_time"
                    warnings.append(
                        f"The race was added but the goal time was not saved ({_problem(put_body)}). "
                        "Retry with update_calendar_event."
                    )
                added = _listed_by_uuid(_events_around_today(), uuid) or added
            added_km = _target_km(added.get("completionTarget"))
            similar_own = []
            for other in rows:
                if other.get("id") == added.get("id") or other.get("date") != added.get("date"):
                    continue
                reason = similar_names(
                    added.get("eventName"), other.get("eventName"), added_km, _target_km(other.get("completionTarget"))
                )
                if reason:
                    similar_own.append({**event_row(other), "match": reason})
            result["event"] = event_row(added)
            if similar_own:
                warnings.append("Your calendar also has a similar event on this date; it may be a stand-in for this race.")
                result["similar_events_on_calendar"] = similar_own
            if warnings:
                result["warnings"] = warnings
            return _dump(result)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error adding the catalog event: {str(e)}"

    @app.tool()
    async def update_calendar_event(
        event_id: int,
        name: Optional[str] = None,
        date: Optional[str] = None,
        start_time: Optional[str] = None,
        distance_km: Optional[float] = None,
        location: Optional[str] = None,
        goal_time: Optional[str] = None,
        clear_goal_time: bool = False,
        event_type: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        url: Optional[str] = None,
        note: Optional[str] = None,
        is_race: Optional[bool] = None,
    ) -> str:
        """Change fields of ONE existing calendar event (race)

        Only call this when the user asked for the change. Pass only the fields to
        change; everything else stays as it is. Get event_id from get_calendar_events.
        A race that came from the organiser's catalog (added with
        add_catalog_event_to_calendar) only allows goal_time / clear_goal_time.
        The result lists each change as from -> to and the event as read back from
        Garmin afterwards. A new date must be today or later, less than a year ahead,
        and not collide with another event of the same name. Privacy cannot be changed
        here (use the Garmin app). Verified live on an event created through this
        server (including is_race on a private event); events added from Garmin's own
        event catalog are read back and checked the same way.

        Args:
            event_id: The event's id from get_calendar_events
            name: New title
            date: New date, YYYY-MM-DD
            start_time: New start time HH:MM, 24 hour clock
            distance_km: New distance in kilometres
            location: New place name
            goal_time: New goal finish time as h:mm:ss (1:40:00) or h:mm (3:50)
            clear_goal_time: True removes the goal time
            event_type: New Garmin event type, e.g. "running" or "hiking"
            latitude: New start point latitude (give with longitude)
            longitude: New start point longitude (give with latitude)
            url: New event web page
            note: New free text
            is_race: True marks the event as a race, False removes the mark. It does
                not change who can see the event.
        """
        try:
            changes_asked = [
                name, date, start_time, distance_km, location, goal_time, event_type, latitude, url, note,
                is_race,
            ]
            if not any(v is not None for v in changes_asked) and not clear_goal_time:
                return "Error: nothing to change - pass at least one field"
            if goal_time and clear_goal_time:
                return "Error: pass either goal_time or clear_goal_time, not both"
            if (latitude is None) != (longitude is None):
                return "Error: give latitude and longitude together"

            status, detail = _get_event(event_id)
            if status == 404:
                organiser = _organiser_event(_events_around_today(), event_id)
                if organiser:
                    return _update_organiser_goal(
                        organiser, goal_time, clear_goal_time,
                        any(v is not None for v in (
                            name, date, start_time, distance_km, location, event_type, latitude, url, note, is_race,
                        )),
                    )
                return _dump({"status": "not_found", "event_id": event_id})
            if status != 200 or not isinstance(detail, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(detail)})

            before = event_row(detail)
            updated = json.loads(json.dumps(detail))
            updated.setdefault("eventCustomization", {})
            updated.setdefault("eventTimeLocal", {})

            if name is not None:
                title = " ".join(name.split())
                if not title:
                    return "Error: name must not be empty"
                updated["eventName"] = title
            if date is not None:
                updated["date"] = _check_date(date)
            if start_time is not None:
                updated["eventTimeLocal"]["startTimeHhMm"] = _check_time(start_time)
            if distance_km is not None:
                updated["completionTarget"] = {
                    "value": _check_distance(distance_km), "unit": "kilometer", "unitType": "distance",
                }
            if location is not None:
                updated["location"] = location
            if latitude is not None:
                updated["locationStartPoint"] = {"lat": latitude, "lon": longitude}
            if event_type is not None:
                updated["eventType"] = event_type
            if url is not None:
                updated["url"] = url
            if note is not None:
                updated["note"] = note
            if is_race is not None:
                updated["race"] = bool(is_race)
            if goal_time:
                updated["eventCustomization"]["customGoal"] = {
                    "value": float(parse_goal(goal_time)), "unit": "second", "unitType": "time",
                }
            elif clear_goal_time:
                updated["eventCustomization"]["customGoal"] = None

            if date is not None or name is not None:
                duplicate, _ = _same_day_report(
                    _events_around_today(), updated["date"], updated["eventName"], skip_id=detail.get("id")
                )
                if duplicate:
                    return _dump({
                        "status": "duplicate",
                        "message": "Another event with this name is already on that date; nothing was changed.",
                        "existing_event": event_row(duplicate),
                    })

            put_status, put_body = _request("PUT", f"calendar-service/event/{int(event_id)}", json=updated)
            if put_status not in (200, 204):
                return _dump({
                    "status": "failed",
                    "http_status": put_status,
                    "message": _problem(put_body),
                    "note": "The event was not changed.",
                })

            status, after_raw = _get_event(event_id)
            if status != 200 or not isinstance(after_raw, dict):
                return _dump({
                    "status": "updated_unverified",
                    "message": "Garmin accepted the change but the event could not be read back.",
                    "event_id": event_id,
                })
            after = event_row(after_raw)
            changes = {k: {"from": before[k], "to": after[k]} for k in after if before.get(k) != after[k]}
            result = {"status": "updated", "event_id": event_id, "changes": changes, "event": after}
            expected = event_row(updated)
            not_kept = [k for k in expected if before.get(k) != expected[k] and after.get(k) != expected[k]]
            if not_kept:
                result["status"] = "updated_partly"
                result["warning"] = "Garmin did not keep these fields as requested: " + ", ".join(sorted(not_kept))
            return _dump(result)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error updating calendar event: {str(e)}"

    @app.tool()
    async def delete_calendar_event(event_id: int, confirm: bool = False) -> str:
        """Delete ONE event (race) from the Garmin Connect calendar

        Two steps. Without confirm=true nothing is deleted: the result shows which
        event would go. Show that to the user, and only after the user has explicitly
        agreed to deleting THIS event call again with confirm=true. Deleting cannot be
        undone, but the event can be created again with create_calendar_event (a race
        from the organiser's catalog with add_catalog_event_to_calendar). Only the
        calendar entry goes; activities and workouts are not touched.

        Args:
            event_id: The event's id from get_calendar_events
            confirm: True only after the user explicitly agreed to deleting this event
        """
        try:
            status, detail = _get_event(event_id)
            if status == 404:
                organiser = _organiser_event(_events_around_today(), event_id)
                if organiser:
                    return _remove_organiser_event(organiser, confirm)
                return _dump({
                    "status": "not_found",
                    "event_id": event_id,
                    "message": "No event with that id (already removed?)",
                })
            if status != 200 or not isinstance(detail, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(detail)})

            row = event_row(detail)
            if not confirm:
                preview = {
                    "status": "confirmation_required",
                    "message": "Nothing was deleted. Ask the user whether this exact event should be deleted, "
                               "then call again with confirm=true.",
                    "event": row,
                }
                if (detail.get("eventCustomization") or {}).get("associatedWithActivityId"):
                    preview["warning"] = "This event is linked to a recorded activity."
                return _dump(preview)

            del_status, del_body = _request("DELETE", f"calendar-service/event/{int(event_id)}")
            if del_status not in (200, 204):
                return _dump({
                    "status": "failed",
                    "http_status": del_status,
                    "message": _problem(del_body),
                    "event": row,
                })
            check, _ = _get_event(event_id)
            return _dump({
                "status": "deleted" if check == 404 else "delete_unverified",
                "event": row,
            })
        except Exception as e:
            return f"Error deleting calendar event: {str(e)}"

    return app
