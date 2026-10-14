"""
Strength-training analysis: which muscle groups worked, and a body map picture.

Garmin does not expose its own muscle map or muscle load through the API, and its
set totals include phantom sets (the watch stores movement during rests as extra
ACTIVE sets). So this module works from the raw exercise sets: it drops the
phantoms, maps every exercise to muscle groups with a small mapping of its own
(by category, with name-based exceptions) and counts weighted sets per muscle.

The mapping is an estimate made from exercise names, NOT Garmin's muscle map, and
this is record-keeping and training analysis, not medical advice.
"""
import datetime
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from garmin_workouts_mcp.strength_render import render_svg

# The garmin_client will be set by the main file
garmin_client = None


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


NOTE = (
    "Estimated from exercise names with this server's own category-to-muscle mapping, "
    "not Garmin's muscle map. Primary muscles count 1.0 per set, secondary 0.5. "
    "Training analysis only, not medical advice."
)

MUSCLE_LABELS = {
    "chest": "Chest",
    "shoulders": "Shoulders",
    "biceps": "Biceps",
    "triceps": "Triceps",
    "forearms": "Forearms / grip",
    "traps": "Traps",
    "lats": "Lats / upper back",
    "lower_back": "Lower back",
    "abs": "Abs",
    "obliques": "Obliques",
    "glutes": "Glutes",
    "hip_stabilizers": "Hip stabilizers",
    "quads": "Quads",
    "hamstrings": "Hamstrings",
    "calves": "Calves",
}

# category -> (primary muscles, secondary muscles). None = not strength work, ignored.
_BY_CATEGORY: Dict[str, Optional[Tuple[List[str], List[str]]]] = {
    "BENCH_PRESS": (["chest"], ["triceps", "shoulders"]),
    "CALF_RAISE": (["calves"], []),
    "CARDIO": None,
    "CARRY": (["traps", "abs"], ["shoulders"]),
    "CHOP": (["obliques", "abs"], ["shoulders", "glutes"]),
    "CORE": (["abs"], ["obliques", "lower_back"]),
    "CRUNCH": (["abs"], ["obliques"]),
    "CURL": (["biceps"], ["forearms"]),
    "DEADLIFT": (["hamstrings", "glutes", "lower_back"], ["traps", "forearms", "quads"]),
    "FLYE": (["chest"], ["shoulders"]),
    "HIP_RAISE": (["glutes"], ["hamstrings", "lower_back"]),
    "HIP_STABILITY": (["hip_stabilizers", "glutes"], ["abs"]),
    "HIP_SWING": (["glutes", "hamstrings"], ["lower_back", "shoulders", "forearms"]),
    "HYPEREXTENSION": (["lower_back"], ["glutes", "hamstrings"]),
    "LATERAL_RAISE": (["shoulders"], ["traps"]),
    "LEG_CURL": (["hamstrings"], ["glutes", "calves"]),
    "LEG_RAISE": (["abs"], ["obliques"]),
    "LUNGE": (["quads", "glutes", "hip_stabilizers"], ["hamstrings", "calves"]),
    "OLYMPIC_LIFT": (["glutes", "quads", "hamstrings", "traps"], ["shoulders", "lower_back", "forearms"]),
    "PLANK": (["abs"], ["shoulders", "obliques", "glutes", "lower_back"]),
    "PLYO": (["quads", "glutes", "calves"], ["hamstrings"]),
    "PULL_UP": (["lats"], ["biceps", "forearms", "shoulders"]),
    "PUSH_UP": (["chest", "shoulders"], ["triceps", "abs"]),
    "ROW": (["lats"], ["biceps", "traps", "shoulders"]),
    "RUN": None,
    "SHOULDER_PRESS": (["shoulders"], ["triceps", "traps"]),
    "SHOULDER_STABILITY": (["shoulders"], ["traps"]),
    "SHRUG": (["traps"], ["shoulders", "forearms"]),
    "SIT_UP": (["abs"], ["obliques"]),
    "SQUAT": (["quads", "glutes"], ["hamstrings", "lower_back", "calves", "abs", "hip_stabilizers"]),
    "TOTAL_BODY": (["quads", "glutes", "chest"], ["shoulders", "triceps", "abs"]),
    "TRICEPS_EXTENSION": (["triceps"], []),
    "WARM_UP": None,
}

# (category, substring of the exercise name) -> muscles; checked before the category.
_BY_NAME: List[Tuple[Optional[str], str, Tuple[List[str], List[str]]]] = [
    (None, "DEAD_BUG", (["abs"], ["hip_stabilizers", "obliques"])),
    (None, "QUADRUPED", (["glutes"], ["lower_back", "abs", "hamstrings"])),
    (None, "BIRD_DOG", (["glutes"], ["lower_back", "abs", "hamstrings"])),
    ("HIP_STABILITY", "FIRE_HYDRANT", (["hip_stabilizers"], ["glutes"])),
    ("HIP_STABILITY", "SIDE_LYING", (["hip_stabilizers"], ["glutes"])),
    ("HIP_STABILITY", "CLAM", (["hip_stabilizers"], ["glutes"])),
    ("HIP_STABILITY", "ABDUCTION", (["hip_stabilizers"], ["glutes"])),
    ("HIP_STABILITY", "ADDUCTION", (["hip_stabilizers"], ["abs"])),
    ("PLANK", "SIDE_PLANK", (["obliques"], ["abs", "hip_stabilizers", "shoulders"])),
    ("PLANK", "MOUNTAIN_CLIMBER", (["abs"], ["quads", "shoulders"])),
    ("LATERAL_RAISE", "MUSCLE_UP", (["lats"], ["biceps", "triceps", "chest"])),
    ("LATERAL_RAISE", "BENT_OVER", (["shoulders", "traps"], ["lats"])),
    ("LATERAL_RAISE", "REAR", (["shoulders", "traps"], ["lats"])),
    ("ROW", "FACE_PULL", (["shoulders", "traps"], ["lats"])),
    ("LEG_CURL", "GOOD_MORNING", (["hamstrings", "lower_back"], ["glutes"])),
    ("PUSH_UP", "PIKE", (["shoulders"], ["triceps", "chest"])),
    ("PUSH_UP", "DIAMOND", (["triceps", "chest"], ["shoulders"])),
    ("PUSH_UP", "CLOSE_GRIP", (["triceps", "chest"], ["shoulders"])),
    ("BENCH_PRESS", "CLOSE_GRIP", (["triceps", "chest"], ["shoulders"])),
    ("HIP_RAISE", "KETTLEBELL_SWING", (["glutes", "hamstrings"], ["lower_back", "shoulders", "forearms"])),
    ("LUNGE", "SIDE_LUNGE", (["quads", "glutes", "hip_stabilizers"], ["hamstrings"])),
]


def muscles_for(category: Optional[str], name: Optional[str]) -> Optional[Tuple[List[str], List[str]]]:
    """(primary, secondary) muscles for an exercise, or None when it is not
    strength work or unknown."""
    if not category or category == "UNKNOWN":
        return None
    upper = (name or "").upper()
    for cat, fragment, muscles in _BY_NAME:
        if (cat is None or cat == category) and fragment in upper:
            return muscles
    return _BY_CATEGORY.get(category)


# ----------------------------------------------------------------------------- #
# analysis
# ----------------------------------------------------------------------------- #

def _set_label(s: dict) -> Tuple[Optional[str], Optional[str]]:
    ex = (s.get("exercises") or [{}])
    ex = ex[0] if ex else {}
    return ex.get("category"), ex.get("name")


def _is_countable(s: dict) -> bool:
    reps = s.get("repetitionCount") or 0
    duration = s.get("duration") or 0
    return reps >= 3 or duration >= 20


def classify_sets(exercise_sets: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Split the ACTIVE sets of one activity into real sets and flagged ones.

    Flagged: an unknown exercise (the watch's rest detections) or a short set of a
    different exercise sitting between two sets of the same exercise (the phantom
    "squat" the watch sometimes invents in a rest). Rest rows are ignored.
    """
    active = [s for s in exercise_sets if s.get("setType") == "ACTIVE"]
    real, flagged = [], []
    labelled = [s for s in active if _set_label(s)[0] not in (None, "UNKNOWN")]
    for s in active:
        category, name = _set_label(s)
        if category in (None, "UNKNOWN"):
            flagged.append({**s, "_reason": "unknown exercise (rest-period movement detected by the watch)"})
    for i, s in enumerate(labelled):
        category, name = _set_label(s)
        reps = s.get("repetitionCount") or 0
        prev_label = _set_label(labelled[i - 1]) if i > 0 else None
        next_label = _set_label(labelled[i + 1]) if i + 1 < len(labelled) else None
        if (prev_label and next_label and prev_label == next_label
                and prev_label != (category, name) and reps <= 5):
            flagged.append({**s, "_reason": "short set of a different exercise between two sets of the same exercise"})
        else:
            real.append(s)
    return real, flagged


def _status(m: dict) -> str:
    """worked = at least one set with the muscle as a primary mover (Garmin's
    "primary"); assisted = it took part only as a secondary muscle (Garmin's
    "secondary"); else not worked ("not targeted")."""
    if m["primary_sets"] >= 1:
        return "worked"
    if m["weighted_sets"] > 0:
        return "assisted"
    return "not worked"


def _tally(activities: List[dict], today: datetime.date) -> dict:
    muscles = {
        key: {"muscle": key, "label": label, "weighted_sets": 0.0, "primary_sets": 0, "secondary_sets": 0,
              "reps": 0, "tonnage_kg": 0.0, "last_worked": None, "exercises": {}}
        for key, label in MUSCLE_LABELS.items()
    }
    unmapped = {}
    flagged_out = []
    activity_rows = []
    for act in activities:
        day = act["date"]
        real, flagged = classify_sets(act["sets"])
        counted = 0
        for s in real:
            if not _is_countable(s):
                continue
            category, name = _set_label(s)
            mapping = muscles_for(category, name)
            if mapping is None:
                unmapped[f"{category}/{name or '-'}"] = unmapped.get(f"{category}/{name or '-'}", 0) + 1
                continue
            counted += 1
            reps = s.get("repetitionCount") or 0
            weight_kg = (s.get("weight") or 0) / 1000.0
            tonnage = reps * weight_kg if weight_kg > 0 else 0.0
            for group, weight in [(m, 1.0) for m in mapping[0]] + [(m, 0.5) for m in mapping[1]]:
                m = muscles[group]
                m["weighted_sets"] += weight
                m["primary_sets" if weight == 1.0 else "secondary_sets"] += 1
                m["reps"] += reps
                m["tonnage_kg"] += tonnage * weight
                if m["last_worked"] is None or day > m["last_worked"]:
                    m["last_worked"] = day
                label = (name or category).replace("_", " ").lower()
                m["exercises"][label] = m["exercises"].get(label, 0) + 1
        for s in flagged:
            category, name = _set_label(s)
            flagged_out.append({
                "date": day, "activity_id": act["id"], "exercise": f"{category}/{name or '-'}",
                "reps": s.get("repetitionCount"), "duration_s": round(s.get("duration") or 0),
                "reason": s["_reason"],
            })
        activity_rows.append({
            "activity_id": act["id"], "date": day, "name": act.get("name"),
            "real_sets": counted, "flagged_sets": len(flagged),
            "garmin_total_sets": act.get("garmin_total_sets"), "garmin_active_sets": act.get("garmin_active_sets"),
            "garmin_total_reps": act.get("garmin_total_reps"),
        })
    rows = []
    for m in muscles.values():
        last = m["last_worked"]
        rows.append({
            "muscle": m["muscle"], "label": m["label"],
            "status": _status(m),
            "worked": _status(m) == "worked",
            "weighted_sets": round(m["weighted_sets"], 1),
            "primary_sets": m["primary_sets"], "secondary_sets": m["secondary_sets"],
            "reps": m["reps"], "tonnage_kg": round(m["tonnage_kg"]),
            "last_worked": last,
            "days_since": (today - datetime.date.fromisoformat(last)).days if last else None,
            "exercises": [e for e, _ in sorted(m["exercises"].items(), key=lambda kv: -kv[1])[:3]],
        })
    rows.sort(key=lambda r: (-r["weighted_sets"], r["label"]))
    return {"muscles": rows, "activities": activity_rows, "flagged_sets": flagged_out, "unmapped": unmapped}


def _load_activities(start: str, end: str, activity_id: str = "") -> List[dict]:
    if activity_id:
        listed = [{"activityId": int(activity_id)}]
    else:
        listing = garmin_client.get_activities_by_date(start, end) or []
        listed = [
            a for a in listing
            if (a.get("activityType") or {}).get("typeKey") == "strength_training"
        ]
    out = []
    for item in listed:
        aid = item["activityId"]
        sets = (garmin_client.get_activity_exercise_sets(aid) or {}).get("exerciseSets") or []
        if not sets:
            continue
        info = garmin_client.get_activity(aid) or {}
        dto = info.get("summaryDTO") or {}
        local = (item.get("startTimeLocal") or dto.get("startTimeLocal") or "")[:10]
        out.append({
            "id": aid, "date": local, "name": item.get("activityName") or info.get("activityName"), "sets": sets,
            "garmin_total_sets": dto.get("totalSets"),
            "garmin_active_sets": dto.get("activeSets"),
            "garmin_total_reps": dto.get("totalExerciseReps"),
        })
    return out


def _window(start_date: str, end_date: str) -> Tuple[str, str]:
    end = datetime.date.fromisoformat(end_date) if end_date else datetime.date.today()
    start = datetime.date.fromisoformat(start_date) if start_date else end - datetime.timedelta(days=6)
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if (end - start).days > 120:
        raise ValueError("date range is limited to 120 days")
    return start.isoformat(), end.isoformat()


def analyse(start_date: str = "", end_date: str = "", activity_id: str = "") -> dict:
    start, end = _window(start_date, end_date)
    if activity_id:
        activities = _load_activities(start, end, activity_id)
        start = end = activities[0]["date"] if activities else start
    else:
        activities = _load_activities(start, end)
    result = _tally(activities, datetime.date.today())
    result["window"] = {"start": start, "end": end}
    return result


def default_output_path(result: dict) -> Path:
    base = Path(os.environ.get("GARMIN_COACH_DATA_DIR") or (Path.home() / ".garmin-coach"))
    base.mkdir(parents=True, exist_ok=True)
    w = result["window"]
    return base / f'muscle-map-{w["start"]}_{w["end"]}.svg'


# ----------------------------------------------------------------------------- #
# tools
# ----------------------------------------------------------------------------- #

def _count_by(rows: List[dict], key: str) -> dict:
    counts: dict = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return counts


def _compact(result: dict) -> dict:
    muscles = result["muscles"]
    return {
        "window": result["window"],
        "worked": [m["label"] for m in muscles if m["status"] == "worked"],
        "assisted_only": [m["label"] for m in muscles if m["status"] == "assisted"],
        "not_worked": [m["label"] for m in muscles if m["status"] == "not worked"],
        "muscles": muscles,
        "activities": result["activities"],
        "flagged_total": len(result["flagged_sets"]),
        "flagged_by_reason": _count_by(result["flagged_sets"], "reason"),
        "flagged_examples": result["flagged_sets"][:4],
        "unmapped_exercises": result["unmapped"] or None,
        "note": NOTE,
    }


def register_tools(app):
    """Register strength analysis tools with the MCP server app"""

    @app.tool()
    async def get_muscle_work(start_date: str = "", end_date: str = "", activity_id: str = "") -> str:
        """Which muscle groups did the strength workouts train, and how much

        Answers "did muscle group X work in this period?" from the raw exercise
        sets of the strength workouts in the window (default: the last 7 days),
        or of one activity (activity_id). For each of 15 muscle groups: a status
        (worked = at least one set with it as a primary mover; assisted = it only
        took part as a secondary muscle; not worked), weighted sets (a set counts 1.0 for a primary and 0.5 for a
        secondary muscle), reps, tonnage in kg (reps x weight, where a weight was
        recorded), the date it was last worked and the days since. Also lists
        the muscles that did not work, the workouts included (with Garmin's own
        set totals for comparison) and the flagged sets that were left out.

        Garmin's own set totals are inflated: the watch stores movement during
        rests as extra ACTIVE sets (unknown exercise) and sometimes invents a short
        set of another exercise. Those are excluded here. The muscle assignment is
        an estimate from exercise names using this server's own mapping, NOT
        Garmin's muscle map (the API does not expose it). Training analysis only,
        not medical advice.

        Args:
            start_date: YYYY-MM-DD (default: 6 days before end_date)
            end_date: YYYY-MM-DD (default: today; range limited to 120 days)
            activity_id: Analyse just this activity instead of a date range
        """
        try:
            result = analyse(start_date, end_date, activity_id)
            if not result["activities"]:
                return f'No strength workouts with recorded sets between {result["window"]["start"]} and {result["window"]["end"]}.'
            return json.dumps(_compact(result), indent=1, ensure_ascii=False)
        except Exception as e:
            return f"Error analysing muscle work: {e}"

    @app.tool()
    async def render_muscle_map(start_date: str = "", end_date: str = "", activity_id: str = "", path: str = "", theme: str = "auto") -> str:
        """Draw a front/back body map of the muscles trained (SVG file)

        Same analysis as get_muscle_work, drawn like Garmin's own map: a front and
        a back figure with primary muscles in red, secondary in yellow and the
        rest grey (not targeted), and the weighted sets listed underneath. Writes an SVG file and
        returns its path (default: the local data directory, ~/.garmin-coach/,
        named after the window) together with a short summary. Open the file in
        a browser, or attach it so the user can look at it. A stylised figure, not
        Garmin's own muscle map; the muscle assignment is an estimate from exercise
        names. Training analysis only, not medical advice.

        Args:
            start_date: YYYY-MM-DD (default: 6 days before end_date)
            end_date: YYYY-MM-DD (default: today)
            activity_id: Draw just this activity
            path: Optional output file path (.svg)
            theme: auto (follows the viewer's light/dark setting), light or dark
        """
        try:
            result = analyse(start_date, end_date, activity_id)
            if not result["activities"]:
                return f'No strength workouts with recorded sets between {result["window"]["start"]} and {result["window"]["end"]}.'
            out = Path(path) if path else default_output_path(result)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_svg(result, theme), encoding="utf-8")
            return json.dumps({
                "status": "success", "file": str(out), "window": result["window"],
                "worked": [m["label"] for m in result["muscles"] if m["status"] == "worked"],
                "assisted_only": [m["label"] for m in result["muscles"] if m["status"] == "assisted"],
                "not_worked": [m["label"] for m in result["muscles"] if m["status"] == "not worked"],
                "flagged_sets_excluded": len(result["flagged_sets"]), "note": NOTE,
            }, indent=1, ensure_ascii=False)
        except Exception as e:
            return f"Error rendering muscle map: {e}"

    return app
