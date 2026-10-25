"""
Unit tests for add_body_composition (body_composition.py)

A stateful fake of the Garmin client stands in: add_body_composition stores a weigh-in (masses in grams, as Garmin reports
them) and get_weigh_ins returns the stored ones grouped by day.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import body_composition, tracking


class FakeGarmin:
    def __init__(self):
        self.entries = []  # weight metrics as Garmin returns them
        self.uploads = []
        self.response = {"detailedImportResult": {"successes": [{"internalId": 1}], "failures": []}}
        self.store_it = True
        self.alter = {}  # fields the fake "Garmin" stores differently from what was sent
        self._pk = 1000

    def seed(self, day, kg, source="MANUAL", **extra):
        self._pk += 1
        self.entries.append({"samplePk": self._pk, "calendarDate": day, "weight": int(kg * 1000), "sourceType": source, **extra})

    def get_weigh_ins(self, start, end):
        days = {}
        for m in self.entries:
            if start <= m["calendarDate"] <= end:
                days.setdefault(m["calendarDate"], []).append(m)
        return {"dailyWeightSummaries": [{"summaryDate": d, "allWeightMetrics": ms} for d, ms in sorted(days.items())]}

    def add_body_composition(self, timestamp, weight, percent_fat=None, percent_hydration=None, bone_mass=None, muscle_mass=None,
                             visceral_fat_rating=None, bmi=None):
        self.uploads.append(dict(timestamp=timestamp, weight=weight, percent_fat=percent_fat, percent_hydration=percent_hydration,
                                 bone_mass=bone_mass, muscle_mass=muscle_mass, visceral_fat_rating=visceral_fat_rating, bmi=bmi))
        if self.store_it:
            self._pk += 1
            entry = {"samplePk": self._pk, "calendarDate": timestamp[:10], "weight": int(weight * 1000), "bodyFat": percent_fat,
                     "bodyWater": percent_hydration, "boneMass": None if bone_mass is None else int(bone_mass * 1000),
                     "muscleMass": None if muscle_mass is None else int(muscle_mass * 1000), "visceralFat": visceral_fat_rating,
                     "bmi": bmi, "sourceType": "INDEX_SCALE"}
            entry.update(self.alter)
            self.entries.append(entry)
        return self.response


@pytest.fixture
def fake(monkeypatch):
    client = FakeGarmin()
    tracking.configure(client)
    body_composition.configure(client)
    monkeypatch.setattr(body_composition, "_POLL_SECONDS", 0)
    return client


@pytest.fixture
def app(fake):
    application = FastMCP("Test body composition")
    body_composition.register_tools(application)
    return application


async def call(app, args):
    text = (await app.call_tool("add_body_composition", args))[0][0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
FULL = {"weight_kg": 82.4, "body_fat_percent": 24.1, "muscle_mass_kg": 34.0, "visceral_fat_rating": 9, "bmi": 25.6}


@pytest.mark.asyncio
async def test_a_full_entry_is_uploaded_and_read_back(app, fake):
    data = await call(app, {**FULL, "date": YESTERDAY, "time": "07:05"})
    assert data["status"] == "success" and "differences" not in data
    assert data["stored"]["kg"] == 82.4 and data["stored"]["body_fat_percent"] == 24.1 and data["stored"]["muscle_mass_kg"] == 34.0
    assert data["stored"]["visceral_fat_rating"] == 9 and data["stored"]["bmi"] == 25.6 and data["stored"]["sample_pk"]
    sent = fake.uploads[0]
    assert sent["timestamp"] == f"{YESTERDAY}T07:05:00" and sent["weight"] == 82.4 and sent["percent_fat"] == 24.1
    assert sent["muscle_mass"] == 34.0 and sent["visceral_fat_rating"] == 9 and sent["bmi"] == 25.6


@pytest.mark.asyncio
async def test_an_existing_weight_only_entry_is_reported_and_kept(app, fake):
    fake.seed(YESTERDAY, 82.4)
    data = await call(app, {**FULL, "date": YESTERDAY, "time": "06:20"})
    assert data["status"] == "success" and len(fake.entries) == 2  # nothing was removed
    assert data["same_day_entries_before"] == [{"sample_pk": 1001, "kg": 82.4, "source": "MANUAL"}]
    assert "delete_body_weight_entry" in data["note"]


@pytest.mark.asyncio
async def test_bad_values_are_refused_before_anything_is_sent(app, fake):
    for args, fragment in (
        ({"weight_kg": 20}, "weight_kg"), ({**FULL, "body_fat_percent": 70}, "body_fat_percent"),
        ({**FULL, "muscle_mass_kg": 120}, "muscle_mass_kg"), ({**FULL, "visceral_fat_rating": 0}, "visceral_fat_rating"),
        ({**FULL, "bmi": 3}, "bmi"), ({**FULL, "body_water_percent": 10}, "body_water_percent"),
        ({"weight_kg": 60, "muscle_mass_kg": 61}, "not below the weight"),
    ):
        assert fragment in await call(app, args)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert "future" in await call(app, {**FULL, "date": tomorrow, "time": "08:00"})
    assert "YYYY-MM-DD" in await call(app, {**FULL, "date": "yesterday"})
    assert fake.uploads == []


@pytest.mark.asyncio
async def test_a_jump_of_more_than_5_kg_needs_force(app, fake):
    fake.seed((date.today() - timedelta(days=10)).isoformat(), 75.0)
    refused = await call(app, {**FULL, "date": YESTERDAY, "time": "07:00"})
    assert "more than 5 kg" in refused and fake.uploads == []
    assert (await call(app, {**FULL, "date": YESTERDAY, "time": "07:00", "force": True}))["status"] == "success"


@pytest.mark.asyncio
async def test_a_refusal_by_garmin_is_reported(app, fake):
    fake.response = {"detailedImportResult": {"successes": [], "failures": [{"messages": [{"content": "Duplicate upload"}]}]}}
    fake.store_it = False
    assert "Garmin refused" in await call(app, {**FULL, "date": YESTERDAY, "time": "07:00"})


@pytest.mark.asyncio
async def test_an_entry_that_does_not_show_up_is_not_called_a_success(app, fake):
    fake.store_it = False
    data = await call(app, {**FULL, "date": YESTERDAY, "time": "07:00"})
    assert data["status"] == "uploaded_not_seen_yet" and "do not upload again" in data["message"]


@pytest.mark.asyncio
async def test_values_that_come_back_different_are_listed(app, fake):
    fake.alter = {"muscleMass": 25000, "bodyFat": None}
    data = await call(app, {**FULL, "date": YESTERDAY, "time": "07:00"})
    assert data["status"] == "stored_with_differences"
    assert data["differences"] == {"body_fat_percent": {"sent": 24.1, "stored": None}, "muscle_mass_kg": {"sent": 34.0, "stored": 25.0}}
