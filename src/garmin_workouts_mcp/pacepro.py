"""
Garmin PacePro plans for Garmin Connect MCP Server

PacePro is Garmin's pacing plan: a goal time for a distance, split into km or mile
splits with a target pace for each, which the watch then follows during the race.
The plans live in course-service/pacebands. Tools here list and read the user's plans
and create or delete one for a flat distance (no course).

What is known and what is not: the list and the endpoints were checked against the
account, and the body of a new plan was learned from the server's own validation
messages (nothing was created while doing that). An even-pace plan made with
create_pacepro_plan was checked live: Garmin accepted it, read it back unchanged and the
Garmin Connect app showed it correctly (name, distance, goal time, target pace, the
splits and the strategy slider in the middle). A negative-split plan (5:03/km for the
first half, 4:57/km for the second, stored with manualPaceEdit) was saved, read back
unchanged and shown with exactly those splits and a stepped pace chart; the app then
shows an "edit" link in place of the strategy slider. The Garmin website computes the
split paces in the browser and the server stores what it is sent, so the splits are
computed here. send_pacepro_plan_to_watch uses the app's own "send to device" call
(POST course-service/pacebands/{id}/device/{deviceId}, no body); checked live, the plan
appeared on a fenix 7 after the next sync.
"""
import json
import re
from typing import Optional

from garth.exc import GarthHTTPError

# The garmin_client will be set by the main file
garmin_client = None

_PRESETS_M = {"5k": 5000.0, "10k": 10000.0, "half": 21097.5, "marathon": 42195.0}
_ALIASES = {
    "5": "5k", "5km": "5k", "10": "10k", "10km": "10k", "half marathon": "half", "halfmarathon": "half",
    "half_marathon": "half", "félmaraton": "half", "felmaraton": "half", "21.1": "half", "21.0975": "half",
    "full": "marathon", "42.2": "marathon", "42.195": "marathon", "maraton": "marathon",
}
_SPLIT_UNITS = {"km": ("DISTANCE_KILOMETER", 1000.0), "mile": ("DISTANCE_MILE", 1609.344)}
_MIN_KM, _MAX_KM = 1.5, 241.5  # the range the Garmin website accepts for a PacePro distance
_MIN_SPEED, _MAX_SPEED = 1.0, 8.5  # metres per second: about 16:40 to 1:57 per km
_MAX_SHIFT_PERCENT = 10.0


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


# ---------------------------------------------------------------- helpers


def _hms(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _ms(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _parse_goal(text: str) -> int:
    """'h:mm:ss' or 'h:mm' (hours:minutes) -> seconds."""
    parts = str(text).strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        raise ValueError("goal_time must look like 1:42:00 (h:mm:ss) or 3:30 (h:mm)")
    numbers = [int(p) for p in parts]
    hours, minutes, seconds = numbers[0], numbers[1], (numbers[2] if len(numbers) == 3 else 0)
    if minutes > 59 or seconds > 59:
        raise ValueError("goal_time minutes and seconds must be below 60")
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("goal_time must be longer than zero")
    return total


def _parse_distance(text) -> float:
    """'half', 'marathon', '5k', '10k' or a number of kilometres -> metres."""
    raw = str(text).strip().casefold().replace(",", ".")
    key = _ALIASES.get(raw, raw)
    if key in _PRESETS_M:
        return _PRESETS_M[key]
    try:
        km = float(raw.removesuffix("km").strip())
    except ValueError:
        raise ValueError("distance must be 5k, 10k, half, marathon or a number of kilometres such as 30")
    if not _MIN_KM <= km <= _MAX_KM:
        raise ValueError(f"distance must be between {_MIN_KM} and {_MAX_KM} km")
    return km * 1000.0


def build_splits(total_m: float, goal_s: float, split_m: float, second_half_faster_percent: float = 0.0) -> list:
    """Split paces for a flat distance. With 0 the pace is even. Otherwise the second half is that many
    percent faster in pace than the first (negative = slower), and the times still add up to the goal."""
    x = second_half_faster_percent / 100.0
    pace_first = 2.0 * goal_s / (total_m * (2.0 - x))  # seconds per metre
    pace_second = pace_first * (1.0 - x)
    half = total_m / 2.0

    def time_at(distance: float) -> float:
        if distance <= half:
            return distance * pace_first
        return half * pace_first + (distance - half) * pace_second

    bounds, at = [], split_m
    while at < total_m - 0.5:  # a last piece shorter than half a metre is float noise, not a split
        bounds.append(at)
        at += split_m
    bounds.append(total_m)

    splits, start = [], 0.0
    for end in bounds:
        split_time = time_at(end) - time_at(start)
        splits.append({
            "splitDistance": round(end - start, 3),
            "splitAvgSpeed": round((end - start) / split_time, 6),
            "cumulativeDistanceFromStart": round(end, 3),
            "cumulativeTimeFromStart": round(time_at(end), 3),
        })
        start = end
    return splits


def _summary_row(summary: dict, split_count=None) -> dict:
    split_type = summary.get("splitType")
    return {
        "plan_id": summary.get("paceBandPk"),
        "name": summary.get("name"),
        "distance_km": round(summary["totalDistance"] / 1000.0, 3) if summary.get("totalDistance") else None,
        "goal_time": _hms(summary["goalTime"]) if summary.get("goalTime") else None,
        "split_type": split_type,
        "course_id": summary.get("courseId"),
        "pacing_strategy": summary.get("pacingStrategy"),
        "hill_effort": summary.get("uphillEffort"),
        "manual_pace_edit": summary.get("manualPaceEdit"),
        "splits": split_count,
    }


def _split_rows(splits: list, split_type: Optional[str]) -> list:
    per_mile = split_type == "DISTANCE_MILE"
    unit_m = 1609.344 if per_mile else 1000.0
    rows, previous = [], 0.0
    for number, split in enumerate(splits, 1):
        elapsed = split["cumulativeTimeFromStart"] - previous
        previous = split["cumulativeTimeFromStart"]
        speed = split.get("splitAvgSpeed") or 0
        rows.append({
            "split": number,
            "distance_m": round(split["splitDistance"], 1),
            "pace": f"{_ms(unit_m / speed)}/{'mi' if per_mile else 'km'}" if speed else None,
            "split_time": _ms(elapsed),
            "elapsed": _hms(split["cumulativeTimeFromStart"]),
        })
    return rows


def _request(method: str, path: str, **kwargs):
    """(status code, parsed body). garth raises on every HTTP error status, so unwrap that."""
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
    if isinstance(body, dict):
        if body.get("errors"):
            return "; ".join(str(e) for e in body["errors"])[:500]
        if body.get("message"):
            return str(body["message"])
    return str(body)[:300] if body else "no details"


def _same_name(a: Optional[str], b: Optional[str]) -> bool:
    return " ".join((a or "").casefold().split()) == " ".join((b or "").casefold().split())


def _list_plans() -> list:
    status, body = _request("GET", "course-service/pacebands")
    if status != 200 or not isinstance(body, list):
        raise RuntimeError(f"could not read the PacePro plans (HTTP {status}: {_problem(body)})")
    return body


def _dump(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ tools


def register_tools(app):
    """Register the PacePro tools with the MCP server app"""

    @app.tool()
    async def get_pacepro_plans(plan_id: Optional[int] = None) -> str:
        """List the user's Garmin PacePro plans, or show one plan with all its splits (read-only)

        PacePro is Garmin's race pacing plan: a goal time for a distance with a target pace
        for every kilometre or mile split, which the watch follows during the race.

        Args:
            plan_id: Optional plan id from the list; with it the plan comes back with every split
        """
        try:
            if plan_id is not None:
                status, body = _request("GET", f"course-service/pacebands/{int(plan_id)}")
                if status == 404:
                    return _dump({"status": "not_found", "plan_id": plan_id})
                if status != 200 or not isinstance(body, dict):
                    return _dump({"status": "failed", "http_status": status, "message": _problem(body)})
                summary, splits = body.get("paceBandSummary") or {}, body.get("paceBandSplits") or []
                return _dump({
                    "plan": _summary_row(summary, len(splits)),
                    "splits": _split_rows(splits, summary.get("splitType")),
                })
            plans = _list_plans()
            if not plans:
                return "No PacePro plans found."
            rows = [_summary_row(p.get("paceBandSummary") or {}, len(p.get("paceBandSplits") or [])) for p in plans]
            return _dump({"count": len(rows), "plans": rows})
        except Exception as e:
            return f"Error retrieving PacePro plans: {str(e)}"

    @app.tool()
    async def create_pacepro_plan(
        name: str,
        distance: str,
        goal_time: str,
        split_unit: str = "km",
        second_half_faster_percent: float = 0.0,
        save: bool = False,
    ) -> str:
        """Plan a Garmin PacePro pacing strategy for a flat distance (no course)

        Without save=true nothing is written: the result is the plan the tool would store
        (the target pace and elapsed time for every split). Show that to the user, and call
        again with save=true only when the user agreed to saving it. A plan with the same
        name is never created twice. Not for courses with hills: the hill-adjusted paces of
        a course are computed by Garmin's own editor and are not reproduced here. Even-pace
        and negative-split plans were saved and shown correctly in Garmin Connect (a split
        plan is stored as manually edited, so the app shows an edit link instead of its
        strategy slider; editing the strategy there would replace these splits). If Garmin
        refuses the body its message is returned and nothing is stored. Putting the plan on
        the watch is a separate step (send_pacepro_plan_to_watch, only when the user asks).

        Args:
            name: Plan name, e.g. "City Half 1:42"
            distance: "5k", "10k", "half" (21.0975 km), "marathon" (42.195 km) or kilometres, e.g. "30"
            goal_time: Goal finish time as h:mm:ss (1:42:00) or h:mm (3:30)
            split_unit: "km" (default) or "mile": the length of each split
            second_half_faster_percent: 0 = even pace. Positive: the second half is that many percent
                faster in pace than the first half (negative split); negative: slower (positive split).
                The times still add up to the goal time. Range -10 to 10.
            save: True stores the plan on the Garmin account; the default only shows it
        """
        try:
            title = " ".join((name or "").split())
            if not title:
                return "Error: name must not be empty"
            if len(title) > 100:
                return "Error: name is too long (100 characters at most)"
            total_m = _parse_distance(distance)
            goal_s = _parse_goal(goal_time)
            unit = (split_unit or "km").strip().casefold()
            unit = {"kilometer": "km", "kilometre": "km", "miles": "mile", "mi": "mile"}.get(unit, unit)
            if unit not in _SPLIT_UNITS:
                return "Error: split_unit must be km or mile"
            if abs(second_half_faster_percent) > _MAX_SHIFT_PERCENT:
                return f"Error: second_half_faster_percent must be between -{_MAX_SHIFT_PERCENT:g} and {_MAX_SHIFT_PERCENT:g}"
            goal_speed = total_m / goal_s
            if not _MIN_SPEED <= goal_speed <= _MAX_SPEED:
                return "Error: that goal time is not realistic for that distance (check hours and minutes)"

            for plan in _list_plans():
                existing = plan.get("paceBandSummary") or {}
                if _same_name(existing.get("name"), title):
                    return _dump({
                        "status": "duplicate",
                        "message": "A PacePro plan with this name already exists; nothing was created.",
                        "existing_plan": _summary_row(existing, len(plan.get("paceBandSplits") or [])),
                    })

            split_type, split_m = _SPLIT_UNITS[unit]
            splits = build_splits(total_m, goal_s, split_m, second_half_faster_percent)
            body = {
                "paceBandSummary": {
                    "name": title,
                    "goalTime": float(goal_s),
                    "goalSpeed": round(goal_speed, 6),
                    "splitType": split_type,
                    "totalDistance": total_m,
                    "pacingStrategy": 0,
                    "uphillEffort": 0,
                    "manualPaceEdit": bool(second_half_faster_percent),
                },
                "paceBandSplits": splits,
            }
            plan_view = {
                "name": title,
                "distance_km": round(total_m / 1000.0, 3),
                "goal_time": _hms(goal_s),
                "split_unit": unit,
                "second_half_faster_percent": second_half_faster_percent,
                "splits": _split_rows(splits, split_type),
            }
            if not save:
                return _dump({
                    "status": "preview",
                    "message": "Nothing was saved. Show this plan to the user; call again with save=true to store it.",
                    "plan": plan_view,
                })

            status, created = _request("POST", "course-service/pacebands", json=body)
            if status not in (200, 201) or not isinstance(created, dict):
                return _dump({
                    "status": "failed",
                    "http_status": status,
                    "message": _problem(created),
                    "note": "Nothing was stored.",
                })
            summary = created.get("paceBandSummary") or {}
            return _dump({
                "status": "saved",
                "plan": _summary_row(summary, len(created.get("paceBandSplits") or splits)),
                "splits": plan_view["splits"],
            })
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error creating PacePro plan: {str(e)}"

    @app.tool()
    async def send_pacepro_plan_to_watch(plan_id: int, device_id: Optional[int] = None) -> str:
        """Send ONE saved PacePro plan to the user's Garmin watch

        Only call this when the user asked for the plan to go to the watch. This is the
        "send to device" of the Garmin Connect app: the plan is queued for the watch and
        arrives at its next sync (opening Garmin Connect on the phone starts one). Without
        device_id the primary device of the account is used. The plan stays on the Garmin
        account either way. Sending the same plan again is harmless.

        Args:
            plan_id: The plan id from get_pacepro_plans
            device_id: Optional device id; by default the primary device (the result lists the devices)
        """
        try:
            status, body = _request("GET", f"course-service/pacebands/{int(plan_id)}")
            if status == 404:
                return _dump({"status": "not_found", "plan_id": plan_id})
            if status != 200 or not isinstance(body, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(body)})
            plan = _summary_row(body.get("paceBandSummary") or {}, len(body.get("paceBandSplits") or []))

            status, devices = _request("GET", "device-service/deviceregistration/devices")
            if status != 200 or not isinstance(devices, list) or not devices:
                return _dump({"status": "failed", "http_status": status, "message": "No registered device found", "plan": plan})
            listed = [
                {"device_id": d.get("deviceId"), "name": d.get("productDisplayName") or d.get("displayName"),
                 "primary": bool(d.get("primary"))}
                for d in devices
            ]
            if device_id is not None:
                target = next((d for d in listed if d["device_id"] == int(device_id)), None)
                if target is None:
                    return _dump({"status": "unknown_device", "message": "That device id is not on the account.", "devices": listed})
            else:
                primary = [d for d in listed if d["primary"]]
                if len(primary) == 1:
                    target = primary[0]
                elif len(listed) == 1:
                    target = listed[0]
                else:
                    return _dump({"status": "device_needed", "message": "Pass device_id: no single primary device.", "devices": listed})

            send_status, send_body = _request(
                "POST", f"course-service/pacebands/{int(plan_id)}/device/{int(target['device_id'])}"
            )
            if send_status not in (200, 201, 202, 204):
                return _dump({
                    "status": "failed",
                    "http_status": send_status,
                    "message": _problem(send_body),
                    "plan": plan,
                    "device": target,
                })
            result = {
                "status": "sent",
                "message": "The plan is queued for the watch; it arrives at the next sync (open Garmin Connect on the phone).",
                "plan": plan,
                "device": target,
            }
            if send_body:
                result["garmin_response"] = send_body
            return _dump(result)
        except Exception as e:
            return f"Error sending the PacePro plan to the watch: {str(e)}"

    @app.tool()
    async def delete_pacepro_plan(plan_id: int, confirm: bool = False) -> str:
        """Delete ONE Garmin PacePro plan

        Two steps. Without confirm=true nothing is deleted: the result shows which plan would
        go. Show that to the user, and only after the user has explicitly agreed to deleting
        THIS plan call again with confirm=true. Deleting cannot be undone, but the plan can be
        made again with create_pacepro_plan.

        Args:
            plan_id: The plan id from get_pacepro_plans
            confirm: True only after the user explicitly agreed to deleting this plan
        """
        try:
            status, body = _request("GET", f"course-service/pacebands/{int(plan_id)}")
            if status == 404:
                return _dump({"status": "not_found", "plan_id": plan_id, "message": "No plan with that id (already removed?)"})
            if status != 200 or not isinstance(body, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(body)})
            row = _summary_row(body.get("paceBandSummary") or {}, len(body.get("paceBandSplits") or []))
            if not confirm:
                return _dump({
                    "status": "confirmation_required",
                    "message": "Nothing was deleted. Ask the user whether this exact plan should be deleted, "
                               "then call again with confirm=true.",
                    "plan": row,
                })
            del_status, del_body = _request("DELETE", f"course-service/pacebands/{int(plan_id)}")
            if del_status not in (200, 204):
                return _dump({"status": "failed", "http_status": del_status, "message": _problem(del_body), "plan": row})
            check, _ = _request("GET", f"course-service/pacebands/{int(plan_id)}")
            return _dump({"status": "deleted" if check == 404 else "delete_unverified", "plan": row})
        except Exception as e:
            return f"Error deleting PacePro plan: {str(e)}"

    return app
