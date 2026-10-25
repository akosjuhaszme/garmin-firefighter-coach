"""
Body composition upload for Garmin Connect MCP Server

log_body_weight (tracking.py) records the weight only. add_body_composition sends a weigh-in with fat, muscle,
water, bone, visceral fat and BMI, the way a smart scale does: the garminconnect library builds a FIT weight-scale
file and posts it to the upload service (upload-service/upload), so Garmin Connect shows the values and charts them.

WRITES to the user's real Garmin account. Guards: value ranges, no future time, a jump of more than 5 kg against the
previous weigh-in needs force=True, and the entry is read back afterwards and compared. A wrong entry is undone with
delete_body_weight_entry (sample_pk from the result). An existing weigh-in of the same day is never touched: it is
reported, because the upload adds a second entry (for example a weight-only one that was logged earlier).

Not known until it has been run against the account: how Garmin treats the time zone of the FIT timestamp, and whether
Garmin takes the muscle mass given in kilograms as it is (a scale such as the Omron shows skeletal muscle in percent, and
Garmin's own muscle mass definition can differ), and whether the profile weight changes. The read-back shows what Garmin
stored.
"""
import asyncio
import json
from datetime import datetime, time as _time, timedelta
from typing import Optional

from garmin_workouts_mcp import tracking

# The garmin_client will be set by the main file
garmin_client = None

_POLL_TRIES = 4
_POLL_SECONDS = 2.0
_RANGES = {
    "weight_kg": (30.0, 300.0),
    "body_fat_percent": (3.0, 60.0),
    "body_water_percent": (30.0, 80.0),
    "muscle_mass_kg": (10.0, 100.0),
    "bone_mass_kg": (0.5, 8.0),
    "visceral_fat_rating": (1, 59),
    "bmi": (10.0, 60.0),
}


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def _out_of_range(values: dict):
    for name, value in values.items():
        if value is None:
            continue
        low, high = _RANGES[name]
        if not (low <= value <= high):
            return f"Refusing: {name} {value} is outside the plausible range {low}-{high}."
    return None


def _metrics_of_day(day: str) -> list:
    data = garmin_client.get_weigh_ins(day, day) or {}
    out = []
    for summary in data.get("dailyWeightSummaries") or []:
        metrics = summary.get("allWeightMetrics") or ([summary["latestWeight"]] if summary.get("latestWeight") else [])
        out.extend(m for m in metrics if m.get("weight"))
    return out


def _view(metric: dict) -> dict:
    """What Garmin stored, in the units this tool takes (kg, percent)"""
    return tracking._drop_none({
        "sample_pk": metric.get("samplePk"),
        "kg": tracking._grams_to_kg(metric.get("weight")),
        "body_fat_percent": metric.get("bodyFat"),
        "body_water_percent": metric.get("bodyWater"),
        "muscle_mass_kg": tracking._mass_to_kg(metric.get("muscleMass")),
        "bone_mass_kg": tracking._mass_to_kg(metric.get("boneMass")),
        "visceral_fat_rating": metric.get("visceralFat"),
        "bmi": metric.get("bmi"),
        "source": metric.get("sourceType"),
    })


def _differences(sent: dict, stored: dict) -> dict:
    """Fields that were sent but come back different (or missing); percent and kg values to 0.05, BMI to 0.1"""
    out = {}
    for name, value in sent.items():
        if value is None:
            continue
        got = stored.get(name)
        tolerance = 0.1 if name == "bmi" else 0.05
        if got is None or abs(float(got) - float(value)) > tolerance:
            out[name] = {"sent": value, "stored": got}
    return out


def register_tools(app):
    @app.tool()
    async def add_body_composition(
        weight_kg: float,
        body_fat_percent: Optional[float] = None,
        muscle_mass_kg: Optional[float] = None,
        visceral_fat_rating: Optional[int] = None,
        bmi: Optional[float] = None,
        body_water_percent: Optional[float] = None,
        bone_mass_kg: Optional[float] = None,
        date: str = "",
        time: str = "",
        force: bool = False,
    ) -> str:
        """Record a weigh-in WITH body composition in Garmin Connect (FIT weight-scale upload)

        WRITES to the user's real Garmin account - only call this with values the user actually read from the
        scale. Use it instead of log_body_weight when fat, muscle, visceral fat or BMI are known; Connect then shows
        them and charts them. Guards: plausible ranges, no future time, a jump of more than 5 kg against the previous
        weigh-in (last 90 days) needs force=True. The entry is read back and compared with what was sent. It is an
        ADDITIONAL entry: an existing weigh-in of that day (for example a weight-only one) is reported but not
        removed; undo any entry with delete_body_weight_entry (sample_pk from the result). Garmin may use the newest
        weigh-in as the profile weight behind its VO2max and zone estimates.

        Args:
            weight_kg: Weight in kilograms, e.g. 82.4
            body_fat_percent: Body fat in percent, e.g. 24.1
            muscle_mass_kg: Muscle mass in kilograms (convert a percent value yourself; Garmin's definition of muscle
                mass can differ from a scale's skeletal muscle)
            visceral_fat_rating: Visceral fat rating, e.g. 9
            bmi: Body mass index, e.g. 25.6
            body_water_percent: Optional body water in percent
            bone_mass_kg: Optional bone mass in kilograms
            date: YYYY-MM-DD of the weigh-in (default: today)
            time: HH:MM or HH:MM:SS local time (default: now if date is today, else 07:00)
            force: True to accept a jump of more than 5 kg versus the previous weigh-in
        """
        try:
            values = {"weight_kg": weight_kg, "body_fat_percent": body_fat_percent, "muscle_mass_kg": muscle_mass_kg,
                      "visceral_fat_rating": visceral_fat_rating, "bmi": bmi, "body_water_percent": body_water_percent,
                      "bone_mass_kg": bone_mass_kg}
            problem = _out_of_range(values)
            if problem:
                return problem
            if muscle_mass_kg is not None and muscle_mass_kg >= weight_kg:
                return f"Refusing: muscle mass {muscle_mass_kg} kg is not below the weight {weight_kg} kg."

            day = tracking._parse_date(date, "date") if date else tracking._today()
            if time:
                at = _time(*[int(p) for p in time.split(":")])
            elif day == tracking._today():
                at = datetime.now().time().replace(microsecond=0)
            else:
                at = _time(7, 0)
            when = datetime.combine(day, at)
            if when > datetime.now() + timedelta(minutes=5):
                return f"Refusing to upload a weigh-in in the future ({when.isoformat(timespec='minutes')})."

            earlier = [d for d in tracking._collect_weights((day - timedelta(days=90)).isoformat(), day.isoformat())
                       if d["date"] <= day.isoformat()]
            previous_kg = tracking._grams_to_kg(earlier[-1]["latest"]["weight"]) if earlier else None
            if previous_kg is not None and abs(weight_kg - previous_kg) > 5.0 and not force:
                return (f"Refusing: {weight_kg} kg differs from the previous weigh-in ({previous_kg} kg) by more than 5 kg - "
                        "likely a typo. Repeat with force=True if it is correct.")

            before = {m.get("samplePk") for m in _metrics_of_day(day.isoformat())}
            sent_to_garmin = dict(timestamp=when.isoformat(timespec="seconds"), weight=weight_kg, percent_fat=body_fat_percent,
                                  percent_hydration=body_water_percent, bone_mass=bone_mass_kg, muscle_mass=muscle_mass_kg,
                                  visceral_fat_rating=visceral_fat_rating, bmi=bmi)
            response = garmin_client.add_body_composition(**sent_to_garmin) or {}
            failures = (response.get("detailedImportResult") or {}).get("failures") or []
            if failures:
                return f"Garmin refused the upload, nothing was stored: {json.dumps(failures, ensure_ascii=False)[:400]}"

            new = []
            for attempt in range(_POLL_TRIES):
                new = [m for m in _metrics_of_day(day.isoformat()) if m.get("samplePk") not in before]
                if new:
                    break
                await asyncio.sleep(_POLL_SECONDS)
            existing = [_view(m) for m in _metrics_of_day(day.isoformat()) if m.get("samplePk") in before]
            if not new:
                return json.dumps(tracking._drop_none({
                    "status": "uploaded_not_seen_yet",
                    "message": "Garmin accepted the file but no new entry is visible yet. Check get_body_weight in a minute; do not upload again before that.",
                    "same_day_entries_before": existing or None}), indent=2)

            stored = _view(new[-1])
            sent = {"kg": weight_kg, "body_fat_percent": body_fat_percent, "muscle_mass_kg": muscle_mass_kg,
                    "visceral_fat_rating": visceral_fat_rating, "bmi": bmi, "body_water_percent": body_water_percent,
                    "bone_mass_kg": bone_mass_kg}
            differences = _differences(sent, stored)
            return json.dumps(tracking._drop_none({
                "status": "success" if not differences else "stored_with_differences",
                "date": day.isoformat(),
                "time_sent": at.isoformat(timespec="minutes"),
                "stored": stored,
                "differences": differences or None,
                "previous_kg": previous_kg,
                "same_day_entries_before": existing or None,
                "note": "An earlier entry of the same day was not touched. Undo any entry with delete_body_weight_entry."
                        if existing else None,
            }), indent=2)
        except Exception as e:
            return f"Error uploading body composition: {e}"

    return app
