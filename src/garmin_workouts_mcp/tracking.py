"""
Body-weight, athlete-profile, daily-summary, supplement and trend tools.

Everything here returns small, curated JSON (the raw Garmin payloads for weight,
sleep and the daily summary are large and mostly null). Personal data stays out of
this repo: the supplement log and plan are written to a LOCAL data directory
(default ~/.garmin-coach/, override with GARMIN_COACH_DATA_DIR) and are never
sent to Garmin.

These are record-keeping and trend tools, not medical advice. For anything about
supplements, deficiencies or health conditions the right authority is a doctor /
a lab test, not a trend line.
"""
import json
import os
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date as _date
from datetime import datetime, time as _time, timedelta
from pathlib import Path
from typing import Optional

# The garmin_client will be set by the main file
garmin_client = None

_NOT_MEDICAL = (
    "Record-keeping and trend analysis only - not medical advice. For supplement, "
    "deficiency or health questions, a doctor / lab test is the authority."
)


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _today() -> _date:
    return datetime.now().date()


def _parse_date(value: str, name: str = "date") -> _date:
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}")


def _mean(values, ndigits=1):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), ndigits) if vals else None


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _data_dir() -> Path:
    return Path(os.environ.get("GARMIN_COACH_DATA_DIR") or (Path.home() / ".garmin-coach"))


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _supplement_log_path() -> Path:
    return _data_dir() / "supplements.jsonl"


def _supplement_plan_path() -> Path:
    return _data_dir() / "supplement_plan.json"


def _norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _grams_to_kg(value):
    return None if value is None else round(value / 1000.0, 2)


def _mass_to_kg(value):
    """Garmin reports body-composition masses in grams; tolerate kg-sized values."""
    if value is None:
        return None
    return round(value / 1000.0, 2) if value > 1000 else round(float(value), 2)


def _collect_weights(start: str, end: str) -> list:
    """One entry per weighed day (the latest weigh-in of that day), oldest first."""
    data = garmin_client.get_weigh_ins(start, end) or {}
    days = []
    for day in data.get("dailyWeightSummaries") or []:
        metrics = day.get("allWeightMetrics") or (
            [day["latestWeight"]] if day.get("latestWeight") else []
        )
        metrics = [m for m in metrics if m.get("weight")]
        if not metrics:
            continue
        metrics.sort(key=lambda m: m.get("timestampGMT") or 0)
        latest = metrics[-1]
        days.append({
            "date": day.get("summaryDate") or latest.get("calendarDate"),
            "latest": latest,
            "count": len(metrics),
            "min": min(m["weight"] for m in metrics),
            "max": max(m["weight"] for m in metrics),
        })
    days.sort(key=lambda d: d["date"])
    return days


def _slope_kg_per_week(points: list):
    """Least-squares slope in kg/week over [(date, kg), ...]; None if the data
    is too thin (fewer than 2 points or spanning under 5 days)."""
    if len(points) < 2:
        return None
    origin = points[0][0]
    span = (points[-1][0] - origin).days
    if span < 5:
        return None
    xs = [(d - origin).days for d, _ in points]
    ys = [kg for _, kg in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope_per_day = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return round(slope_per_day * 7, 2)


def _parse_when(taken_at: str) -> datetime:
    if not taken_at:
        return datetime.now().replace(microsecond=0)
    text = taken_at.strip().replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"taken_at must be ISO like 2026-10-11T08:30 or 2026-10-11, got {taken_at!r}")


def _load_plan() -> dict:
    path = _supplement_plan_path()
    if not path.exists():
        return {"items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        plan.setdefault("items", [])
        return plan
    except (json.JSONDecodeError, OSError):
        return {"items": []}


def _dose_label(entry: dict) -> str:
    dose, unit = entry.get("dose"), entry.get("unit") or ""
    if dose is None:
        return entry["name"]
    dose_txt = f"{dose:g}"
    return f"{entry['name']} {dose_txt}{unit}".strip()


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #

def register_tools(app):
    """Register body/nutrition/supplement/trend tools with the MCP server app"""

    # ---- 1. weight ------------------------------------------------------- #

    @app.tool()
    async def get_body_weight(start_date: str = "", end_date: str = "") -> str:
        """Get curated body-weight history and trend (kg), one value per weighed day

        Replaces the raw Garmin payload (grams, a dozen always-null fields) with:
        per-day weight in kg (plus body fat %, body water %, muscle/bone mass in
        kg, BMI, visceral fat, metabolic age ONLY when the weigh-in actually has
        them - a manual weigh-in has none), the change vs the previous weigh-in,
        and a summary: latest value, 3-week moving average (mean of weigh-ins in
        the 21 days up to the latest), weekly_change_kg (least-squares slope over
        the last 28 days, negative = losing; null when there are <2 weigh-ins
        spanning at least 5 days), change since the first weigh-in in range, and
        days since the last weigh-in. With weekly weigh-ins the slope needs ~3+
        weeks of data to mean much. Record-keeping and trend analysis only - not
        medical advice.

        Args:
            start_date: YYYY-MM-DD (default: 56 days before end_date)
            end_date: YYYY-MM-DD (default: today)
        """
        try:
            end = _parse_date(end_date, "end_date") if end_date else _today()
            start = _parse_date(start_date, "start_date") if start_date else end - timedelta(days=56)
            days = _collect_weights(start.isoformat(), end.isoformat())
            if not days:
                return f"No weigh-ins between {start} and {end}."

            series, prev_kg = [], None
            for d in days:
                m = d["latest"]
                kg = _grams_to_kg(m["weight"])
                point = _drop_none({
                    "date": d["date"],
                    "kg": kg,
                    "change_vs_prev_kg": round(kg - prev_kg, 2) if prev_kg is not None else None,
                    "weigh_ins_that_day": d["count"] if d["count"] > 1 else None,
                    "bmi": m.get("bmi"),
                    "body_fat_pct": m.get("bodyFat"),
                    "body_water_pct": m.get("bodyWater"),
                    "muscle_mass_kg": _mass_to_kg(m.get("muscleMass")),
                    "bone_mass_kg": _mass_to_kg(m.get("boneMass")),
                    "visceral_fat": m.get("visceralFat"),
                    "metabolic_age": m.get("metabolicAge"),
                    "source": m.get("sourceType"),
                    "sample_pk": m.get("samplePk"),
                })
                series.append(point)
                prev_kg = kg

            pairs = [(_date.fromisoformat(p["date"]), p["kg"]) for p in series]
            last_date, last_kg = pairs[-1]
            window_21 = [kg for d, kg in pairs if (last_date - d).days <= 20]
            window_28 = [(d, kg) for d, kg in pairs if (last_date - d).days <= 28]
            summary = _drop_none({
                "latest_kg": last_kg,
                "latest_date": last_date.isoformat(),
                "moving_avg_3w_kg": round(statistics.fmean(window_21), 2),
                "weigh_ins_in_3w_window": len(window_21),
                "weekly_change_kg": _slope_kg_per_week(window_28),
                "change_since_first_kg": round(last_kg - pairs[0][1], 2) if len(pairs) > 1 else None,
                "first_date_in_range": pairs[0][0].isoformat() if len(pairs) > 1 else None,
                "days_since_last_weigh_in": (_today() - last_date).days,
            })
            return json.dumps({"summary": summary, "weigh_ins": series[-60:]}, indent=2)
        except Exception as e:
            return f"Error retrieving body weight: {e}"

    @app.tool()
    async def log_body_weight(
        weight_kg: float, date: str = "", time: str = "", force: bool = False
    ) -> str:
        """Record a manual weigh-in in Garmin Connect (weight-service upload)

        WRITES to the user's real Garmin account - only call this with a value the
        user actually told you. Guards against typos: rejects values outside
        30-300 kg, future timestamps, and a jump of more than 5 kg versus the
        previous weigh-in in the last 90 days unless force=True. Note Garmin may
        use the newest weigh-in as the profile weight behind its VO2max / zone
        estimates, so a wrong value does have knock-on effects. Use
        delete_body_weight_entry (sample_pk from the result or get_body_weight)
        to undo a wrong entry.

        Args:
            weight_kg: Weight in kilograms, e.g. 94.2
            date: YYYY-MM-DD of the weigh-in (default: today)
            time: HH:MM or HH:MM:SS local time (default: now if date is today,
                else 07:00)
            force: Set True to accept a >5 kg jump versus the previous weigh-in
        """
        try:
            if not (30.0 <= weight_kg <= 300.0):
                return f"Refusing to log {weight_kg} kg - outside the plausible 30-300 kg range."
            day = _parse_date(date, "date") if date else _today()
            if time:
                parts = [int(p) for p in time.split(":")]
                at = _time(*parts)
            elif day == _today():
                at = datetime.now().time().replace(microsecond=0)
            else:
                at = _time(7, 0)
            when = datetime.combine(day, at)
            if when > datetime.now() + timedelta(minutes=5):
                return f"Refusing to log a weigh-in in the future ({when.isoformat(timespec='minutes')})."

            earlier = [
                d for d in _collect_weights((day - timedelta(days=90)).isoformat(), day.isoformat())
                if d["date"] <= day.isoformat()
            ]
            previous_kg = _grams_to_kg(earlier[-1]["latest"]["weight"]) if earlier else None
            if previous_kg is not None and abs(weight_kg - previous_kg) > 5.0 and not force:
                return (
                    f"Refusing: {weight_kg} kg differs from the previous weigh-in "
                    f"({previous_kg} kg) by more than 5 kg - likely a typo. "
                    "Repeat with force=True if it is correct."
                )

            garmin_client.add_weigh_in(weight_kg, "kg", when.isoformat(timespec="seconds"))

            sample_pk = None
            for d in reversed(_collect_weights(day.isoformat(), day.isoformat())):
                for m in [d["latest"]]:
                    if abs((m["weight"] or 0) / 1000.0 - weight_kg) < 0.01:
                        sample_pk = m.get("samplePk")
            return json.dumps(_drop_none({
                "status": "success",
                "date": day.isoformat(),
                "time": at.isoformat(timespec="minutes"),
                "kg": weight_kg,
                "previous_kg": previous_kg,
                "change_vs_previous_kg": round(weight_kg - previous_kg, 2) if previous_kg is not None else None,
                "sample_pk": sample_pk,
            }), indent=2)
        except Exception as e:
            return f"Error logging weight: {e}"

    @app.tool()
    async def delete_body_weight_entry(sample_pk: str, date: str) -> str:
        """Delete one weigh-in from Garmin Connect (undo a wrong log_body_weight)

        Args:
            sample_pk: The entry's sample_pk (from log_body_weight / get_body_weight)
            date: YYYY-MM-DD the entry belongs to
        """
        try:
            _parse_date(date)
            response = garmin_client.delete_weigh_in(str(sample_pk), date)
            code = getattr(response, "status_code", None)
            if code in (200, 204, None):
                return json.dumps({"status": "success", "sample_pk": str(sample_pk), "date": date})
            return f"Delete failed: HTTP {code}"
        except Exception as e:
            return f"Error deleting weigh-in: {e}"

    # ---- 2. profile ------------------------------------------------------ #

    @app.tool()
    async def get_athlete_profile() -> str:
        """Read the user's Garmin profile so nobody has to ask for what Garmin already knows

        Returns birth date + computed age, gender, height, profile weight, VO2max
        (running/cycling), max HR, lactate-threshold HR and speed, and the heart-rate
        zone boundaries Garmin currently uses (per sport entry, zone floors/ceilings
        in bpm, with the method - e.g. LACTATE_THRESHOLD vs %MAX_HR), plus the
        training-day preferences. Read-only.

        Caveats: the lactate threshold speed is returned as the raw Garmin number
        (its unit is undocumented); the *_unverified pace is computed assuming the
        raw value is m/s divided by 10 and must be checked against the Garmin app
        before anyone relies on it. The profile weight is Garmin's own stored value
        and can lag the latest weigh-in (see get_body_weight).
        """
        try:
            profile = garmin_client.get_user_profile() or {}
            ud = profile.get("userData") or {}
            out = {}

            birth = ud.get("birthDate")
            if birth:
                b = _parse_date(birth, "birthDate")
                today = _today()
                age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
                out["birth_date"] = birth
                out["age_years"] = age
            out.update(_drop_none({
                "gender": ud.get("gender"),
                "height_cm": ud.get("height"),
                "profile_weight_kg": _grams_to_kg(ud.get("weight")),
                "vo2max_running": ud.get("vo2MaxRunning"),
                "vo2max_cycling": ud.get("vo2MaxCycling"),
                "measurement_system": ud.get("measurementSystem"),
            }))

            errors = []
            lt = {}
            try:
                rows = garmin_client.garth.get(
                    "connectapi", "biometric-service/biometric/latestLactateThreshold"
                ).json()
                for row in rows if isinstance(rows, list) else []:
                    if row.get("speed") is not None:
                        lt["speed_raw"] = row["speed"]
                        lt["updated"] = (row.get("calendarDate") or "")[:10] or None
                    if row.get("hearRate") is not None:  # sic - Garmin's own field spelling
                        lt["heart_rate_bpm"] = row["hearRate"]
            except Exception as e:
                errors.append(f"lactate threshold: {e}")
            if "speed_raw" not in lt and ud.get("lactateThresholdSpeed") is not None:
                lt["speed_raw"] = ud["lactateThresholdSpeed"]
            if "heart_rate_bpm" not in lt and ud.get("lactateThresholdHeartRate") is not None:
                lt["heart_rate_bpm"] = ud["lactateThresholdHeartRate"]
            if lt.get("speed_raw"):
                ms = lt["speed_raw"] * 10.0
                pace_s = 1000.0 / ms
                lt["pace_min_per_km_unverified"] = f"{int(pace_s // 60)}:{int(round(pace_s % 60)):02d}"
                lt["speed_note"] = "unit undocumented; pace assumes raw*10 = m/s - verify in the Garmin app"
            if lt:
                out["lactate_threshold"] = lt

            try:
                zones = garmin_client.garth.get("connectapi", "biometric-service/heartRateZones").json()
                zone_rows = []
                for z in zones if isinstance(zones, list) else []:
                    floors = [z.get(f"zone{i}Floor") for i in range(1, 6)]
                    mx = z.get("maxHeartRateUsed")
                    if None in floors or mx is None:
                        continue
                    ceilings = [floors[i + 1] - 1 for i in range(4)] + [mx]
                    zone_rows.append(_drop_none({
                        "sport": z.get("sport"),
                        "method": z.get("trainingMethod"),
                        "max_hr_bpm": mx,
                        "lactate_threshold_hr_bpm": z.get("lactateThresholdHeartRateUsed"),
                        "resting_hr_used": z.get("restingHeartRateUsed"),
                        "zones_bpm": {f"Z{i + 1}": f"{floors[i]}-{ceilings[i]}" for i in range(5)},
                    }))
                if zone_rows:
                    out["hr_zones"] = zone_rows
                    out["max_hr_bpm"] = zone_rows[0]["max_hr_bpm"]
            except Exception as e:
                errors.append(f"hr zones: {e}")

            try:
                settings = garmin_client.get_userprofile_settings() or {}
                out.update(_drop_none({
                    "available_training_days": settings.get("availableTrainingDays"),
                    "preferred_long_training_days": settings.get("preferredLongTrainingDays"),
                }))
            except Exception as e:
                errors.append(f"settings: {e}")

            if errors:
                out["partial_errors"] = errors
            return json.dumps(out, indent=2, default=str)
        except Exception as e:
            return f"Error retrieving athlete profile: {e}"

    # ---- 3. daily summary ------------------------------------------------ #

    @app.tool()
    async def get_daily_summary(cdate: str = "") -> str:
        """Curated Garmin daily summary: calories, steps, floors, intensity minutes, hydration

        Calories: total / active / BMR burned, plus consumed and remaining. Consumed
        is null (and listed under not_available) unless something feeds it: a
        calorie-intake service such as MyFitnessPal linked to Garmin Connect, or
        the paid Garmin Connect+ Nutrition log (whether that populates this field
        is unverified). Macros (protein/carbs/fat) are not part of this summary; for
        meals and macros use the companion mfp-readonly server (fitness_get_day)
        when it is connected.
        Intensity minutes are moderate + vigorous (Garmin counts vigorous double
        toward the weekly goal). Hydration: intake logged (in the app or via
        log_hydration), the daily goal, Garmin's sweat-loss estimate from the day's
        workouts, and the base goal (Garmin adds the sweat-loss estimate on top of
        a base goal to get the daily goal). Record-keeping and trend analysis only -
        not medical or dietary advice; questions about nutrition or deficiencies
        belong with a doctor / lab test.

        Args:
            cdate: YYYY-MM-DD (default: today; today's totals are partial)
        """
        try:
            day = _parse_date(cdate, "cdate") if cdate else _today()
            s = garmin_client.get_user_summary(day.isoformat()) or {}
            out = {"date": day.isoformat()}
            out["calories"] = _drop_none({
                "total_kcal": s.get("totalKilocalories"),
                "active_kcal": s.get("activeKilocalories"),
                "bmr_kcal": s.get("bmrKilocalories"),
                "consumed_kcal": s.get("consumedKilocalories"),
                "remaining_kcal": s.get("remainingKilocalories"),
                "net_goal_kcal": s.get("netCalorieGoal"),
                "intake_source_connected": bool(s.get("includesCalorieConsumedData")),
            })
            out["steps"] = _drop_none({
                "total": s.get("totalSteps"),
                "goal": s.get("dailyStepGoal"),
                "distance_km": round(s["totalDistanceMeters"] / 1000, 2) if s.get("totalDistanceMeters") is not None else None,
            })
            out["floors"] = _drop_none({
                "ascended": round(s["floorsAscended"], 1) if s.get("floorsAscended") is not None else None,
                "goal": s.get("userFloorsAscendedGoal"),
            })
            out["intensity_minutes"] = _drop_none({
                "moderate": s.get("moderateIntensityMinutes"),
                "vigorous": s.get("vigorousIntensityMinutes"),
                "weekly_goal": s.get("intensityMinutesGoal"),
            })
            try:
                hyd = garmin_client.get_hydration_data(day.isoformat()) or {}
                intake, goal = hyd.get("valueInML"), hyd.get("goalInML")
                sweat = hyd.get("sweatLossInML")
                out["hydration"] = _drop_none({
                    "intake_ml": intake,
                    "goal_ml": goal,
                    "base_goal_ml": round(goal - sweat) if goal is not None and sweat is not None else None,
                    "sweat_loss_est_ml": sweat,
                    "remaining_ml": round(max(goal - intake, 0)) if goal is not None and intake is not None else None,
                })
            except Exception:
                pass
            if s.get("restingHeartRate") is not None:
                out["resting_hr_bpm"] = s["restingHeartRate"]

            missing = []
            if s.get("consumedKilocalories") is None:
                missing.append(
                    "consumed_kcal: nothing feeds it - link e.g. MyFitnessPal to "
                    "Garmin Connect, or use the paid Connect+ Nutrition log"
                )
            missing.append("macros (protein/carbs/fat): not in this summary")
            out["not_available"] = missing
            return json.dumps(out, indent=2)
        except Exception as e:
            return f"Error retrieving daily summary: {e}"

    @app.tool()
    async def log_hydration(amount_ml: float, date: str = "", time: str = "") -> str:
        """Log (or correct) water intake in Garmin Connect's hydration tracker

        WRITES to the user's real Garmin account - only log amounts the user
        actually reported. Adds amount_ml to the day's intake; a negative amount
        subtracts (to undo a mistaken entry) but never takes the total below zero.
        Accepts 1-2000 ml per call. The result shows the day's new total, the daily
        goal, and Garmin's sweat-loss estimate: the goal is a base goal plus the
        sweat-loss estimate from that day's workouts (activity "waterEstimated"),
        so a hard session raises it.

        Args:
            amount_ml: Millilitres to add (negative to subtract), e.g. 500
            date: YYYY-MM-DD (default: today)
            time: HH:MM local time of the intake (default: now)
        """
        try:
            if amount_ml == 0 or abs(amount_ml) > 2000:
                return "Refusing: amount_ml must be non-zero and at most 2000 ml per call."
            day = _parse_date(date, "date") if date else _today()
            if time:
                at = _time(*[int(p) for p in time.split(":")])
            elif day == _today():
                at = datetime.now().time().replace(microsecond=0)
            else:
                at = _time(12, 0)
            when = datetime.combine(day, at)
            if when > datetime.now() + timedelta(minutes=5):
                return f"Refusing to log hydration in the future ({when.isoformat(timespec='minutes')})."

            before = garmin_client.get_hydration_data(day.isoformat()) or {}
            current = before.get("valueInML") or 0.0
            if amount_ml < 0 and current + amount_ml < 0:
                return f"Refusing: only {current:g} ml logged on {day}, cannot subtract {abs(amount_ml):g} ml."

            garmin_client.add_hydration_data(
                value_in_ml=amount_ml,
                timestamp=when.isoformat(timespec="milliseconds"),
                cdate=day.isoformat(),
            )
            after = garmin_client.get_hydration_data(day.isoformat()) or {}
            return json.dumps(_drop_none({
                "status": "success",
                "date": day.isoformat(),
                "added_ml": amount_ml,
                "intake_ml": after.get("valueInML"),
                "goal_ml": after.get("goalInML"),
                "sweat_loss_est_ml": after.get("sweatLossInML"),
            }), indent=2)
        except Exception as e:
            return f"Error logging hydration: {e}"

    # ---- 4. supplements (local log) -------------------------------------- #

    @app.tool()
    async def log_supplement(
        name: str,
        dose: Optional[float] = None,
        unit: str = "",
        taken_at: str = "",
        note: str = "",
    ) -> str:
        """Log a supplement/vitamin intake in the LOCAL supplement log (not Garmin)

        Garmin's Lifestyle Logging can't be relied on for this: its habit catalogue
        (lifestyle, self-care, treatments, sleep, life status, custom) has no
        vitamin/supplement entry, there is no catalogue endpoint, and the write
        endpoint is undocumented. So intakes are stored in a local file in the
        user's data directory (~/.garmin-coach/supplements.jsonl, override with
        GARMIN_COACH_DATA_DIR) that is never committed or uploaded.

        Record-keeping and trend analysis only - not medical advice. For
        supplement, deficiency or health questions, a doctor / lab test is the
        authority.

        Args:
            name: Supplement name, e.g. "magnesium"
            dose: Amount per intake (optional)
            unit: Unit of the dose, e.g. "mg", "IU", "g", "capsule"
            taken_at: ISO local time like 2026-10-11T08:30 or a date (default: now)
            note: Free text (e.g. "with breakfast")
        """
        try:
            if not name.strip():
                return "name is required."
            when = _parse_when(taken_at)
            if when > datetime.now() + timedelta(days=1):
                return "Refusing to log an intake more than a day in the future."
            entry = _drop_none({
                "id": uuid.uuid4().hex[:8],
                "name": name.strip(),
                "dose": dose,
                "unit": unit or None,
                "taken_at": when.isoformat(timespec="minutes"),
                "date": when.date().isoformat(),
                "note": note or None,
            })
            path = _supplement_log_path()
            rows = _read_jsonl(path)
            rows.append(entry)
            _write_jsonl(path, rows)
            return json.dumps({"status": "success", "entry": entry}, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error logging supplement: {e}"

    @app.tool()
    async def list_supplements(days: int = 7, name: str = "") -> str:
        """List logged supplement intakes (local log) for the last N days, newest first

        Args:
            days: How many days back, counting today (1-120, default 7)
            name: Optional case-insensitive name filter
        """
        try:
            days = max(1, min(days, 120))
            since = (_today() - timedelta(days=days - 1)).isoformat()
            rows = [
                r for r in _read_jsonl(_supplement_log_path())
                if r.get("date", "") >= since and (not name or _norm(name) == _norm(r.get("name", "")))
            ]
            rows.sort(key=lambda r: r.get("taken_at", ""), reverse=True)
            totals = {}
            for r in rows:
                t = totals.setdefault(_norm(r["name"]), {"name": r["name"], "doses": 0, "total_dose": 0.0, "unit": r.get("unit")})
                t["doses"] += 1
                t["total_dose"] += r.get("dose") or 0.0
            for t in totals.values():
                t["total_dose"] = round(t["total_dose"], 2) if t["total_dose"] else None
            return json.dumps({
                "window_days": days,
                "count": len(rows),
                "totals_by_name": [_drop_none(t) for t in totals.values()],
                "entries": rows[:100],
                "note": _NOT_MEDICAL,
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error listing supplements: {e}"

    @app.tool()
    async def delete_supplement_entry(entry_id: str) -> str:
        """Delete one entry from the local supplement log by its id (fix a mistaken log)

        Args:
            entry_id: The id returned by log_supplement / list_supplements
        """
        try:
            path = _supplement_log_path()
            rows = _read_jsonl(path)
            kept = [r for r in rows if r.get("id") != entry_id]
            if len(kept) == len(rows):
                return f"No supplement entry with id {entry_id!r}."
            _write_jsonl(path, kept)
            return json.dumps({"status": "success", "deleted": entry_id})
        except Exception as e:
            return f"Error deleting supplement entry: {e}"

    @app.tool()
    async def set_supplement_plan(
        name: str,
        dose: Optional[float] = None,
        unit: str = "",
        times_per_day: int = 1,
        days_per_week: int = 7,
        active: bool = True,
        note: str = "",
    ) -> str:
        """Create/update one item of the supplement PLAN (what should be taken), local file

        The plan is what get_supplement_adherence compares the log against. Calling
        this again for the same name replaces that item; active=False retires it.
        Stored locally (~/.garmin-coach/supplement_plan.json), never uploaded.

        Record-keeping only - not medical advice. What to take, and whether it is
        needed, is for a doctor / lab test to decide.

        Args:
            name: Supplement name (matched case-insensitively against the log)
            dose: Planned amount per intake
            unit: Unit of the dose
            times_per_day: Intakes per planned day (default 1)
            days_per_week: Planned days per week, 1-7 (default 7 = daily)
            active: False to retire the item without deleting the history
            note: Free text
        """
        try:
            if not name.strip():
                return "name is required."
            times_per_day = max(1, min(times_per_day, 10))
            days_per_week = max(1, min(days_per_week, 7))
            plan = _load_plan()
            item = _drop_none({
                "name": name.strip(),
                "dose": dose,
                "unit": unit or None,
                "times_per_day": times_per_day,
                "days_per_week": days_per_week,
                "active": active,
                "note": note or None,
            })
            plan["items"] = [i for i in plan["items"] if _norm(i.get("name")) != _norm(name)] + [item]
            path = _supplement_plan_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            return json.dumps({"status": "success", "plan": plan["items"]}, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error saving supplement plan: {e}"

    @app.tool()
    async def get_supplement_adherence(days: int = 7) -> str:
        """Daily/weekly adherence of the logged supplements against the plan

        For each active plan item: doses taken vs expected over the window
        (expected = times_per_day x days x days_per_week/7), adherence %, and for
        daily plans the exact days with a missed dose (today counts as missed until
        a dose is logged). Also lists anything logged that has no plan item. Local
        data only.

        Record-keeping and trend analysis only - not medical advice. For
        supplement, deficiency or health questions, a doctor / lab test is the
        authority.

        Args:
            days: Window length ending today (1-90, default 7)
        """
        try:
            days = max(1, min(days, 90))
            today = _today()
            window = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
            log = [r for r in _read_jsonl(_supplement_log_path()) if r.get("date") in set(window)]
            plan = [i for i in _load_plan()["items"] if i.get("active", True)]

            report = []
            planned = set()
            for item in plan:
                key = _norm(item["name"])
                planned.add(key)
                taken = [r for r in log if _norm(r.get("name")) == key]
                per_day = {}
                for r in taken:
                    per_day[r["date"]] = per_day.get(r["date"], 0) + 1
                tpd, dpw = item.get("times_per_day", 1), item.get("days_per_week", 7)
                expected = tpd * days * dpw / 7.0
                row = _drop_none({
                    "name": item["name"],
                    "plan": _dose_label(item) + f" x{tpd}/day, {dpw} days/week",
                    "doses_taken": len(taken),
                    "doses_expected": round(expected, 1),
                    "adherence_pct": round(min(len(taken) / expected, 1.0) * 100) if expected else None,
                    "days_with_dose": len(per_day),
                })
                if dpw == 7:
                    row["missed_days"] = [d for d in window if per_day.get(d, 0) < tpd]
                report.append(row)

            unplanned = sorted({r["name"] for r in log if _norm(r.get("name")) not in planned})
            return json.dumps({
                "window": {"start": window[0], "end": window[-1], "days": days},
                "items": report,
                "logged_without_plan": unplanned,
                "note": _NOT_MEDICAL,
            }, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Error computing supplement adherence: {e}"

    # ---- 5. trend -------------------------------------------------------- #

    @app.tool()
    async def get_wellness_trend(
        days: int = 14, end_date: str = "", include_sleep_context_flags: bool = False
    ) -> str:
        """Compact day-by-day trend table for pattern spotting (small output)

        One row per day for the last N days: weight (kg, weigh-in days only),
        sleep score + hours, overnight HRV + status, resting HR, Body Battery
        change over the night, training load (sum of that day's activities) and
        workout count, Lifestyle Logging flags that were YES (e.g. Illness,
        Massage Therapy) and QUANTITY behaviours such as caffeine, and the
        supplements logged locally. A summary block gives window averages and the
        weight change. Missing data is simply omitted from a row.

        Lifestyle flags are whatever habits the user tracks in the Garmin Connect
        app (a custom habit added there under "Custom" should appear here too,
        but that is untested). Sleep-context flags (pet in bedroom, shared bed)
        are left out unless include_sleep_context_flags=True. Fetches use Garmin's range endpoints
        (1 call each for sleep/RHR/weight/activities) plus 1 lifestyle call per
        day, in parallel. This shows correlations in logged data - it can't
        establish causes and isn't medical advice (doctor / lab test for that).

        Args:
            days: Window length, 1-42 (default 14)
            end_date: Last day, YYYY-MM-DD (default: today)
            include_sleep_context_flags: Include sleepRelated lifestyle flags
        """
        try:
            days = max(1, min(days, 42))
            end = _parse_date(end_date, "end_date") if end_date else _today()
            start = end - timedelta(days=days - 1)
            s_iso, e_iso = start.isoformat(), end.isoformat()
            errors = []

            def fetch_sleep():
                d = garmin_client.garth.get(
                    "connectapi", f"sleep-service/stats/sleep/daily/{s_iso}/{e_iso}"
                ).json()
                return {r["calendarDate"]: r.get("values") or {} for r in d.get("individualStats", [])}

            def fetch_rhr():
                d = garmin_client.garth.get(
                    "connectapi",
                    f"userstats-service/wellness/daily/{garmin_client.display_name}",
                    params={"fromDate": s_iso, "untilDate": e_iso, "metricId": 60},
                ).json()
                rows = (d.get("allMetrics", {}).get("metricsMap", {}) or {}).get("WELLNESS_RESTING_HEART_RATE", [])
                return {r["calendarDate"]: r.get("value") for r in rows}

            def fetch_weight():
                return {d["date"]: _grams_to_kg(d["latest"]["weight"]) for d in _collect_weights(s_iso, e_iso)}

            def fetch_load():
                per_day = {}
                for a in garmin_client.get_activities_by_date(s_iso, e_iso) or []:
                    day = (a.get("startTimeLocal") or "")[:10]
                    if not day:
                        continue
                    row = per_day.setdefault(day, {"load": 0.0, "n": 0, "sweat": 0.0})
                    row["load"] += a.get("activityTrainingLoad") or 0.0
                    row["sweat"] += a.get("waterEstimated") or 0.0
                    row["n"] += 1
                return per_day

            def fetch_lifestyle(day_iso):
                data = garmin_client.get_lifestyle_logging_data(day_iso) or {}
                flags, quantities, logged = [], {}, False
                for r in data.get("dailyLogsReport") or []:
                    status = r.get("logStatus")
                    if status in ("YES", "NO"):
                        logged = True
                    if r.get("measurementType") == "QUANTITY":
                        amount = sum(x.get("amount") or 0 for x in r.get("details") or [])
                        if amount:
                            quantities[r.get("name")] = amount
                    elif status == "YES" and (include_sleep_context_flags or not r.get("sleepRelated")):
                        flags.append(r.get("name"))
                return {"flags": flags, "quantities": quantities, "logged": logged}

            day_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = {
                    "sleep": pool.submit(fetch_sleep),
                    "rhr": pool.submit(fetch_rhr),
                    "weight": pool.submit(fetch_weight),
                    "load": pool.submit(fetch_load),
                }
                lifestyle_futures = {d: pool.submit(fetch_lifestyle, d) for d in day_list}
                results = {}
                for key, fut in futures.items():
                    try:
                        results[key] = fut.result()
                    except Exception as e:
                        results[key] = {}
                        errors.append(f"{key}: {e}")
                lifestyle = {}
                for d, fut in lifestyle_futures.items():
                    try:
                        lifestyle[d] = fut.result()
                    except Exception as e:
                        lifestyle[d] = {}
                        errors.append(f"lifestyle {d}: {e}")

            supplements = {}
            for r in _read_jsonl(_supplement_log_path()):
                if s_iso <= r.get("date", "") <= e_iso:
                    supplements.setdefault(r["date"], []).append(_dose_label(r))

            rows = []
            for d in day_list:
                sl = results["sleep"].get(d, {})
                ld = results["load"].get(d)
                lf = lifestyle.get(d, {})
                row = _drop_none({
                    "date": d,
                    "weight_kg": results["weight"].get(d),
                    "sleep_score": sl.get("sleepScore"),
                    "sleep_h": round(sl["totalSleepTimeInSeconds"] / 3600, 1) if sl.get("totalSleepTimeInSeconds") else None,
                    "hrv_ms": sl.get("avgOvernightHrv"),
                    "hrv_status": sl.get("hrvStatus"),
                    "rhr": results["rhr"].get(d),
                    "bb_change": sl.get("bodyBatteryChange"),
                    "training_load": round(ld["load"], 1) if ld else None,
                    "workouts": ld["n"] if ld else None,
                    "sweat_est_ml": round(ld["sweat"]) if ld and ld["sweat"] else None,
                    "flags": lf.get("flags") or None,
                    "quantities": lf.get("quantities") or None,
                    "supplements": supplements.get(d),
                })
                if not lf.get("logged"):
                    row["lifestyle_logged"] = False
                rows.append(row)

            weights = [r["weight_kg"] for r in rows if "weight_kg" in r]
            quantity_totals = {}
            for r in rows:
                for k, v in (r.get("quantities") or {}).items():
                    q = quantity_totals.setdefault(k, [])
                    q.append(v)
            summary = _drop_none({
                "avg_sleep_score": _mean([r.get("sleep_score") for r in rows]),
                "avg_sleep_h": _mean([r.get("sleep_h") for r in rows]),
                "avg_hrv_ms": _mean([r.get("hrv_ms") for r in rows]),
                "avg_rhr": _mean([r.get("rhr") for r in rows]),
                "total_training_load": round(sum(r.get("training_load", 0) for r in rows), 1) or None,
                "lifestyle_logged_days": sum(1 for r in rows if r.get("lifestyle_logged", True)),
                "weight_first_last_kg": [weights[0], weights[-1]] if len(weights) >= 2 else None,
                "weight_change_kg": round(weights[-1] - weights[0], 2) if len(weights) >= 2 else None,
                "avg_per_logged_day": {k: _mean(v, 2) for k, v in quantity_totals.items()} or None,
                "supplement_doses": {
                    n: sum(1 for lst in supplements.values() for x in lst if x == n) for n in sorted({x for lst in supplements.values() for x in lst})
                } or None,
            })
            out = {"window": {"start": s_iso, "end": e_iso, "days": days}, "summary": summary, "days": rows}
            if errors:
                out["partial_errors"] = errors[:5]
            out["note"] = _NOT_MEDICAL
            return json.dumps(out, indent=1, ensure_ascii=False)
        except Exception as e:
            return f"Error building wellness trend: {e}"

    return app
