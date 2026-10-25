"""
Blood pressure for Garmin Connect MCP Server

The user measures at home with a cuff that has no Bluetooth and types the values in. get_blood_pressure reads the
readings of a date range (curated: a short list, averages, weekly averages) and set_blood_pressure writes one reading
(Garmin's bloodpressure-service through the garminconnect library); delete_blood_pressure_entry undoes one.

Record-keeping and trends only, not medical advice: whether a value is a problem is for a doctor. Garmin's own category
label of a reading is passed on as garmin_category without any interpretation here. set_blood_pressure WRITES to the
user's real Garmin account: ranges are checked, systolic must be above diastolic, no future time, the new entry is read
back and compared, and the result carries the version needed to delete it.
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
_MAX_NOTES = 200
_MAX_READINGS_LISTED = 60


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def _readings(raw) -> list:
    """Every reading found in a bloodpressure-service answer, oldest first, without duplicates"""
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            if "systolic" in obj and "diastolic" in obj and ("measurementTimestampLocal" in obj or "version" in obj):
                found.append(obj)
                return
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(raw)
    seen, out = set(), []
    for m in found:
        stamp = str(m.get("measurementTimestampLocal") or "")[:19]
        key = (m.get("version"), stamp, m.get("systolic"), m.get("diastolic"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "date": stamp[:10] or None,
            "time": stamp[11:16] or None,
            "systolic": m.get("systolic"),
            "diastolic": m.get("diastolic"),
            "pulse": m.get("pulse"),
            "notes": m.get("notes") or None,
            "version": m.get("version"),
            "source": m.get("sourceType"),
            "garmin_category": m.get("categoryName") or m.get("category"),
        })
    out.sort(key=lambda r: ((r["date"] or ""), (r["time"] or "")))
    return out


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _summary(rows: list) -> dict:
    weeks = {}
    for r in rows:
        if r["date"]:
            year, week, _ = datetime.fromisoformat(r["date"]).isocalendar()
            weeks.setdefault(f"{year}-W{week:02d}", []).append(r)
    top = max(rows, key=lambda r: (r["systolic"] or 0, r["diastolic"] or 0))
    low = min(rows, key=lambda r: (r["systolic"] or 999, r["diastolic"] or 999))
    return {
        "readings": len(rows),
        "days_with_readings": len({r["date"] for r in rows}),
        "avg_systolic": _mean([r["systolic"] for r in rows]),
        "avg_diastolic": _mean([r["diastolic"] for r in rows]),
        "avg_pulse": _mean([r["pulse"] for r in rows]),
        "highest": {k: top[k] for k in ("date", "time", "systolic", "diastolic")},
        "lowest": {k: low[k] for k in ("date", "time", "systolic", "diastolic")},
        "weekly_averages": [{"week": w, "readings": len(rs), "avg_systolic": _mean([r["systolic"] for r in rs]),
                             "avg_diastolic": _mean([r["diastolic"] for r in rs]), "avg_pulse": _mean([r["pulse"] for r in rs])}
                            for w, rs in sorted(weeks.items())],
    }


def register_tools(app):
    @app.tool()
    async def get_blood_pressure(start_date: str = "", end_date: str = "") -> str:
        """Get the blood pressure readings of a date range from Garmin Connect (read-only)

        Returns the readings (newest 60 at most: date, time, systolic, diastolic, pulse, notes, version, source, Garmin's
        own category label) and a summary: count, averages, highest and lowest reading, and weekly averages for the trend.
        Record-keeping only, not medical advice: what a value means is for a doctor.

        Args:
            start_date: YYYY-MM-DD (default: 28 days before end_date)
            end_date: YYYY-MM-DD (default: today)
        """
        try:
            end = tracking._parse_date(end_date, "end_date") if end_date else tracking._today()
            start = tracking._parse_date(start_date, "start_date") if start_date else end - timedelta(days=28)
            if start > end:
                return "start_date is after end_date."
            rows = _readings(garmin_client.get_blood_pressure(start.isoformat(), end.isoformat()))
            if not rows:
                return f"No blood pressure readings between {start} and {end}."
            return json.dumps({"from": start.isoformat(), "to": end.isoformat(), "summary": _summary(rows),
                               "readings": rows[-_MAX_READINGS_LISTED:], "note": tracking._NOT_MEDICAL}, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error retrieving blood pressure: {e}"

    @app.tool()
    async def set_blood_pressure(systolic: int, diastolic: int, pulse: int, date: str = "", time: str = "", notes: str = "") -> str:
        """Record ONE blood pressure reading in Garmin Connect

        WRITES to the user's real Garmin account - only call this with values the user actually read from the cuff.
        Guards: systolic 70-260, diastolic 40-150 and below the systolic, pulse 20-250, no future time, notes up to 200
        characters, an identical reading at the same minute is refused. The new reading is read back and compared.
        Undo it with delete_blood_pressure_entry (version and date from the result). Record-keeping only, not medical advice.

        Args:
            systolic: Upper value in mmHg, e.g. 128
            diastolic: Lower value in mmHg, e.g. 82
            pulse: Pulse in beats per minute, e.g. 64
            date: YYYY-MM-DD of the reading (default: today)
            time: HH:MM or HH:MM:SS local time (default: now if date is today, else 07:00)
            notes: Optional short text, e.g. "morning, after waking"
        """
        try:
            for name, value, low, high in (("systolic", systolic, 70, 260), ("diastolic", diastolic, 40, 150), ("pulse", pulse, 20, 250)):
                if not isinstance(value, int) or isinstance(value, bool) or not (low <= value <= high):
                    return f"Refusing: {name} must be a whole number between {low} and {high}, got {value!r}."
            if diastolic >= systolic:
                return f"Refusing: diastolic {diastolic} is not below systolic {systolic} - the two values are probably swapped."
            if len(notes) > _MAX_NOTES:
                return f"Refusing: notes are {len(notes)} characters, the limit is {_MAX_NOTES}."
            day = tracking._parse_date(date, "date") if date else tracking._today()
            if time:
                at = _time(*[int(p) for p in time.split(":")])
            elif day == tracking._today():
                at = datetime.now().time().replace(microsecond=0)
            else:
                at = _time(7, 0)
            when = datetime.combine(day, at)
            if when > datetime.now() + timedelta(minutes=5):
                return f"Refusing to record a reading in the future ({when.isoformat(timespec='minutes')})."

            before = _readings(garmin_client.get_blood_pressure(day.isoformat(), day.isoformat()))
            minute = when.strftime("%H:%M")
            for r in before:
                if r["time"] == minute and r["systolic"] == systolic and r["diastolic"] == diastolic and r["pulse"] == pulse:
                    return json.dumps({"status": "duplicate", "message": "An identical reading exists at that minute; nothing was added.", "existing": r}, indent=2)
            known = {(r["version"], r["time"], r["systolic"], r["diastolic"]) for r in before}

            garmin_client.set_blood_pressure(systolic, diastolic, pulse, when.isoformat(timespec="seconds"), notes)

            new = []
            for _ in range(_POLL_TRIES):
                after = _readings(garmin_client.get_blood_pressure(day.isoformat(), day.isoformat()))
                new = [r for r in after if (r["version"], r["time"], r["systolic"], r["diastolic"]) not in known]
                if new:
                    break
                await asyncio.sleep(_POLL_SECONDS)
            if not new:
                return json.dumps({"status": "sent_not_seen_yet", "message": "Garmin accepted the reading but it is not visible yet. Check get_blood_pressure in a minute; do not send it again before that."}, indent=2)
            stored = new[-1]
            differences = {k: {"sent": v, "stored": stored.get(k)} for k, v in (("systolic", systolic), ("diastolic", diastolic), ("pulse", pulse))
                           if stored.get(k) != v}
            return json.dumps(tracking._drop_none({
                "status": "success" if not differences else "stored_with_differences",
                "date": day.isoformat(), "stored": stored, "differences": differences or None,
                "undo": f"delete_blood_pressure_entry(version={stored.get('version')!r}, date={day.isoformat()!r})",
                "note": tracking._NOT_MEDICAL}), indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error recording blood pressure: {e}"

    @app.tool()
    async def delete_blood_pressure_entry(version: str, date: str) -> str:
        """Delete one blood pressure reading from Garmin Connect (undo a wrong set_blood_pressure)

        Args:
            version: The reading's version (from set_blood_pressure or get_blood_pressure)
            date: YYYY-MM-DD the reading belongs to
        """
        try:
            day = tracking._parse_date(date).isoformat()
            before = {str(r["version"]) for r in _readings(garmin_client.get_blood_pressure(day, day))}
            if str(version) not in before:
                return json.dumps({"status": "not_found", "message": f"No reading with version {version} on {day}; nothing was deleted."}, indent=2)
            garmin_client.delete_blood_pressure(str(version), day)
            after = {str(r["version"]) for r in _readings(garmin_client.get_blood_pressure(day, day))}
            return json.dumps({"status": "success" if str(version) not in after else "still_there", "version": str(version), "date": day}, indent=2)
        except Exception as e:
            return f"Error deleting blood pressure reading: {e}"

    return app
