"""
Unit tests for the blood pressure tools (blood_pressure.py)

A stateful fake of the Garmin client stands in: set_blood_pressure stores a reading, get_blood_pressure returns the stored
ones in the shape of Garmin's bloodpressure-service (summaries per day with a list of measurements), delete removes one.
"""
import json
from datetime import date, timedelta

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import blood_pressure, tracking


class FakeGarmin:
    def __init__(self):
        self.readings = []
        self.sent = []
        self.store_it = True
        self.alter = {}
        self._version = 5000

    def seed(self, day, hhmm, sys_, dia, pulse=60, notes=""):
        self._version += 1
        self.readings.append({"version": self._version, "measurementTimestampLocal": f"{day}T{hhmm}:00.0", "systolic": sys_,
                              "diastolic": dia, "pulse": pulse, "sourceType": "MANUAL", "notes": notes, "categoryName": "NORMAL"})

    def get_blood_pressure(self, start, end=None):
        end = end or start
        days = {}
        for r in self.readings:
            d = r["measurementTimestampLocal"][:10]
            if start <= d <= end:
                days.setdefault(d, []).append(r)
        # the same readings appear twice in Garmin's answer (summaries and categorized summaries): duplicates must be ignored
        return {"measurementSummaries": [{"startDate": d, "measurements": ms} for d, ms in sorted(days.items())],
                "categorizedMeasurementSummaries": [{"measurements": ms} for _, ms in sorted(days.items())]}

    def set_blood_pressure(self, systolic, diastolic, pulse, timestamp="", notes=""):
        self.sent.append((systolic, diastolic, pulse, timestamp, notes))
        if self.store_it:
            self._version += 1
            entry = {"version": self._version, "measurementTimestampLocal": timestamp + ".0", "systolic": systolic, "diastolic": diastolic,
                     "pulse": pulse, "sourceType": "MANUAL", "notes": notes, "categoryName": "NORMAL"}
            entry.update(self.alter)
            self.readings.append(entry)
        return {}

    def delete_blood_pressure(self, version, cdate):
        self.readings = [r for r in self.readings if str(r["version"]) != str(version)]
        return {}


@pytest.fixture
def fake(monkeypatch):
    client = FakeGarmin()
    blood_pressure.configure(client)
    tracking.configure(client)
    monkeypatch.setattr(blood_pressure, "_POLL_SECONDS", 0)
    return client


@pytest.fixture
def app(fake):
    application = FastMCP("Test blood pressure")
    blood_pressure.register_tools(application)
    return application


async def call(app, name, args=None):
    text = (await app.call_tool(name, args or {}))[0][0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.mark.asyncio
async def test_get_gives_readings_averages_and_weekly_trend(app, fake):
    fake.seed(days_ago(10), "07:00", 130, 84, 66)
    fake.seed(days_ago(3), "07:10", 120, 80, 62)
    fake.seed(days_ago(3), "20:00", 126, 82, 70, notes="evening")
    data = await call(app, "get_blood_pressure", {"start_date": days_ago(14), "end_date": days_ago(0)})
    assert data["summary"]["readings"] == 3 and data["summary"]["days_with_readings"] == 2  # no double counting
    assert data["summary"]["avg_systolic"] == 125.3 and data["summary"]["avg_diastolic"] == 82.0 and data["summary"]["avg_pulse"] == 66.0
    assert data["summary"]["highest"]["systolic"] == 130 and data["summary"]["lowest"]["systolic"] == 120
    assert [r["time"] for r in data["readings"]] == ["07:00", "07:10", "20:00"] and data["readings"][2]["notes"] == "evening"
    assert sum(w["readings"] for w in data["summary"]["weekly_averages"]) == 3 and "not medical advice" in data["note"].lower()


@pytest.mark.asyncio
async def test_get_with_nothing_and_with_a_bad_range(app, fake):
    assert "No blood pressure readings" in await call(app, "get_blood_pressure", {"start_date": days_ago(5)})
    assert "after end_date" in await call(app, "get_blood_pressure", {"start_date": days_ago(1), "end_date": days_ago(5)})


@pytest.mark.asyncio
async def test_set_records_reads_back_and_offers_the_undo(app, fake):
    data = await call(app, "set_blood_pressure", {"systolic": 128, "diastolic": 82, "pulse": 64, "date": days_ago(1), "time": "06:30", "notes": "ZZ TEST"})
    assert data["status"] == "success" and data["stored"]["systolic"] == 128 and data["stored"]["time"] == "06:30"
    assert data["stored"]["notes"] == "ZZ TEST" and "delete_blood_pressure_entry" in data["undo"]
    assert fake.sent == [(128, 82, 64, f"{days_ago(1)}T06:30:00", "ZZ TEST")]


@pytest.mark.asyncio
async def test_bad_values_future_times_and_duplicates_are_refused(app, fake):
    for args, fragment in (
        ({"systolic": 300, "diastolic": 80, "pulse": 60}, "systolic"), ({"systolic": 120, "diastolic": 20, "pulse": 60}, "diastolic"),
        ({"systolic": 120, "diastolic": 80, "pulse": 10}, "pulse"), ({"systolic": 80, "diastolic": 120, "pulse": 60}, "swapped"),
        ({"systolic": 120, "diastolic": 80, "pulse": 60, "notes": "x" * 201}, "notes"),
        ({"systolic": 120, "diastolic": 80, "pulse": 60, "date": (date.today() + timedelta(days=1)).isoformat(), "time": "08:00"}, "future"),
        ({"systolic": 120, "diastolic": 80, "pulse": 60, "date": "yesterday"}, "YYYY-MM-DD"),
    ):
        assert fragment in await call(app, "set_blood_pressure", args)
    assert fake.sent == []
    fake.seed(days_ago(1), "06:30", 128, 82, 64)
    dup = await call(app, "set_blood_pressure", {"systolic": 128, "diastolic": 82, "pulse": 64, "date": days_ago(1), "time": "06:30"})
    assert dup["status"] == "duplicate" and fake.sent == []


@pytest.mark.asyncio
async def test_a_reading_that_does_not_show_up_or_comes_back_different(app, fake):
    fake.store_it = False
    assert (await call(app, "set_blood_pressure", {"systolic": 128, "diastolic": 82, "pulse": 64, "date": days_ago(1), "time": "06:30"}))["status"] == "sent_not_seen_yet"
    fake.store_it = True
    fake.alter = {"pulse": 99}
    data = await call(app, "set_blood_pressure", {"systolic": 118, "diastolic": 76, "pulse": 60, "date": days_ago(1), "time": "07:30"})
    assert data["status"] == "stored_with_differences" and data["differences"] == {"pulse": {"sent": 60, "stored": 99}}


@pytest.mark.asyncio
async def test_delete_removes_only_the_named_reading(app, fake):
    fake.seed(days_ago(1), "06:30", 128, 82, 64)
    fake.seed(days_ago(1), "20:30", 122, 80, 66)
    assert (await call(app, "delete_blood_pressure_entry", {"version": "9999", "date": days_ago(1)}))["status"] == "not_found"
    done = await call(app, "delete_blood_pressure_entry", {"version": "5001", "date": days_ago(1)})
    assert done["status"] == "success" and [r["version"] for r in fake.readings] == [5002]
    assert "YYYY-MM-DD" in await call(app, "delete_blood_pressure_entry", {"version": "5002", "date": "x"})
