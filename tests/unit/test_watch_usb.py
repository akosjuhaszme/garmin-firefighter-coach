"""
Unit tests for the FIT helper (fit_light.py) and the watch-over-USB tools (watch_usb.py)

A small FIT file is built here with the same message layout as a real Settings.fit (ten alarm slots in global message 222)
and Schedule.fit (global message 28). The Windows side (PowerShell and the watch) is replaced by two fake bridge functions.
"""
import json
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import fit_light, watch_usb

EMPTY = (0xFFFF, 0, 0, 255, 255, 0xFFFFFFFF, 0, 255, 255, 0xFFFFFFFF)  # fields 0 1 2 3 4 5 6(skipped) 7 8 11
STAMP = 1161000000  # a FIT timestamp in 2026


def _definition(local, number, fields):
    body = struct.pack("<BBBHB", 0x40 | local, 0, 0, number, len(fields))
    return body + b"".join(struct.pack("<BBB", f, size, base) for f, size, base in fields)


def _finish(body):
    header = struct.pack("<BBHI4s", 14, 0x10, 21195, len(body), b".FIT")
    header += struct.pack("<H", fit_light.crc16(header))
    data = header + body
    return data + struct.pack("<H", fit_light.crc16(data))


def settings_fit(alarms):
    """alarms: [(minutes, day bits, on)] for the first slots; the rest of the ten slots stay empty"""
    body = _definition(0, 0, [(0, 1, 0x00), (3, 4, 0x8C)]) + bytes([0]) + struct.pack("<BI", 2, 1234567890)
    body += _definition(1, 222, [(0, 2, 0x84), (1, 1, 0x02), (2, 1, 0x02), (3, 1, 0x02), (4, 1, 0x02), (5, 4, 0x86), (6, 32, 0x07),
                                 (7, 1, 0x02), (8, 1, 0x02), (11, 4, 0x86), (254, 2, 0x84)])
    for slot in range(10):
        if slot < len(alarms):
            minutes, bits, on = alarms[slot]
            row = (minutes, bits, 0, 2, 1, STAMP, 0, 1 if on else 0, STAMP + 5)
        else:
            row = (0xFFFF, 0, 0, 255, 255, 0xFFFFFFFF, 255, 255, 0xFFFFFFFF)
        body += bytes([1]) + struct.pack("<HBBBBI", *row[:6]) + bytes(32) + struct.pack("<BBI", row[6], row[7], row[8]) + struct.pack("<H", slot)
    return _finish(body)


def schedule_fit(rows):
    """rows: [(day as FIT seconds, done, workout id)]"""
    body = _definition(2, 28, [(2, 4, 0x86), (3, 4, 0x86), (4, 1, 0x02), (5, 1, 0x00), (6, 4, 0x86)])
    for day, done, workout in rows:
        body += bytes([2]) + struct.pack("<IIBBI", workout, STAMP, done, 0, day)
    return _finish(body)


MON_SAT = 63


@pytest.fixture
def settings():
    return settings_fit([(300, MON_SAT, True), (370, 128, False), (540, 30, False)])


# ---------------------------------------------------------------- fit_light

def test_crc_check_and_alarm_slots(settings):
    assert fit_light.check_crc(settings)
    assert not fit_light.check_crc(settings[:-3] + b"\x00\x00\x00")
    slots = fit_light.alarm_slots(settings)
    assert len(slots) == 10
    assert [(s["time"], s["days"], s["enabled"]) for s in slots[:3]] == [
        ("05:00", ["mon", "tue", "wed", "thu", "fri", "sat"], True), ("06:10", ["once"], False), ("09:00", ["tue", "wed", "thu", "fri"], False)]
    assert all(s["time"] is None for s in slots[3:])


def test_days_mask_round_trips():
    assert fit_light.days_mask("once") == 128 and fit_light.days_mask("mon-sat") == 63 and fit_light.days_mask("weekdays") == 31
    assert fit_light.days_mask("mon, wed,fri") == 0b10101 and fit_light.days_mask("sat-mon") == 0b1100001
    assert fit_light.day_names(fit_light.days_mask("weekend")) == ["sat", "sun"]
    with pytest.raises(fit_light.FitError):
        fit_light.days_mask("someday")


def test_set_alarm_changes_only_its_slot_and_keeps_the_crc(settings):
    new = fit_light.set_alarm(settings, 3, 13 * 60 + 37, 128, False, now=STAMP + 100)
    assert fit_light.check_crc(new) and len(new) == len(settings)
    before, after = fit_light.alarm_slots(settings), fit_light.alarm_slots(new)
    assert after[:3] == before[:3] and after[4:] == before[4:]
    assert (after[3]["time"], after[3]["days"], after[3]["enabled"]) == ("13:37", ["once"], False)
    changed = [i for i in range(len(new)) if new[i] != settings[i]]
    record = [r for r in fit_light.records(settings) if r.number == 222][3]
    assert all(record.start <= i < record.end or i >= len(new) - 2 for i in changed)


def test_set_alarm_refuses_a_used_slot_a_missing_slot_and_a_bad_crc(settings):
    with pytest.raises(fit_light.FitError, match="not empty"):
        fit_light.set_alarm(settings, 0, 360, 128, True)
    with pytest.raises(fit_light.FitError, match="does not exist"):
        fit_light.set_alarm(settings, 10, 360, 128, True)
    with pytest.raises(fit_light.FitError, match="CRC"):
        fit_light.set_alarm(settings[:-3] + b"\x00\x00\x00", 3, 360, 128, True)


def test_schedule_rows():
    day = lambda d: (d - 631065600) // 1  # noqa: E731 - FIT seconds from Unix seconds
    data = schedule_fit([(day(1792411200), 0, 1720628796), (day(1792238400), 1, 1700039876)])
    assert fit_light.schedule_rows(data) == [{"date": "2026-10-17", "completed": True, "workout_id": 1700039876},
                                             {"date": "2026-10-19", "completed": False, "workout_id": 1720628796}]


# ---------------------------------------------------------------- tools

class FakeWatch:
    def __init__(self, settings, schedule=b"", new_files=()):
        self.settings, self.schedule, self.new_files = settings, schedule, list(new_files)
        self.found, self.put_files = True, []

    def state(self, pattern):
        if not self.found:
            return {"found": False}
        import pathlib
        import tempfile
        folder = pathlib.Path(tempfile.mkdtemp())
        (folder / "Settings.fit").write_bytes(self.settings)
        (folder / "Schedule.fit").write_bytes(self.schedule)
        return {"found": True, "device": "fenix 7", "folder": str(folder), "storage_total": "14,3 GB", "storage_free": "2,4 GB",
                "workouts": ["Alap_5k_workout.fit"], "dated_workouts": ["2026-10-24.fit"], "pacebands": ["Alap_5k_7_24_band1.fit"],
                "activities": ["2026-10-20-17-52-27", "2026-10-22-15-15-23", "2026-10-20-16-52-11", "2026-10-18-07-29-39"],
                "new_files": list(self.new_files), "files": ["Settings.fit", "Schedule.fit"]}

    def put(self, pattern, local):
        import pathlib
        self.put_files.append(pathlib.Path(local).read_bytes())
        return {"found": True, "new_files": ["ALARM"]}


@pytest.fixture
def fake(monkeypatch, settings, tmp_path):
    watch = FakeWatch(settings, schedule_fit([(1161864000, 0, 1700039876)]))
    monkeypatch.setattr(watch_usb, "_bridge_state", watch.state)
    monkeypatch.setattr(watch_usb, "_bridge_put", watch.put)
    monkeypatch.setattr(watch_usb, "_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setenv("GARMIN_WATCH_USB_WRITES", "1")
    return watch


@pytest.fixture
def app(fake):
    application = FastMCP("Test watch usb")
    watch_usb.register_tools(application)
    return application


async def call(app, name, args=None):
    text = (await app.call_tool(name, args or {}))[0][0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


@pytest.mark.asyncio
async def test_state_shows_alarms_schedule_and_files(app):
    data = await call(app, "get_watch_usb_state")
    assert data["status"] == "ok" and data["device"] == "fenix 7"
    assert [a["time"] for a in data["alarms"]] == ["05:00", "06:10", "09:00"] and data["free_alarm_slots"] == 7
    assert data["scheduled_workouts"] == [{"date": "2026-10-25", "completed": False, "workout_id": 1700039876}]
    assert data["activities"]["count"] == 4 and data["activities"]["newest"][-1] == "2026-10-22-15-15-23" and data["files_waiting_in_new_files"] == []


@pytest.mark.asyncio
async def test_state_without_a_watch(app, fake):
    fake.found = False
    assert (await call(app, "get_watch_usb_state"))["status"] == "watch_not_connected"


@pytest.mark.asyncio
async def test_writes_are_off_by_default(app, monkeypatch, fake):
    monkeypatch.delenv("GARMIN_WATCH_USB_WRITES")
    assert (await call(app, "set_watch_alarm_usb", {"time": "05:45", "confirm": True}))["status"] == "switched_off"
    assert fake.put_files == []


@pytest.mark.asyncio
async def test_set_needs_confirmation_then_stages_one_file(app, fake, tmp_path):
    plan = await call(app, "set_watch_alarm_usb", {"time": "5:45", "days": "once", "enabled": False})
    assert plan["status"] == "confirmation_required" and plan["plan"] == {"slot": 3, "time": "05:45", "days": ["once"], "enabled": False}
    assert fake.put_files == []
    done = await call(app, "set_watch_alarm_usb", {"time": "5:45", "days": "once", "enabled": False, "confirm": True})
    assert done["status"] == "staged" and len(fake.put_files) == 1
    staged = fit_light.alarm_slots(fake.put_files[0])
    assert [s["time"] for s in staged if s["time"]] == ["05:00", "06:10", "09:00", "05:45"]
    assert len(list((tmp_path / "backups").glob("watch-settings-*.fit"))) == 1  # the watch's own file, saved first


@pytest.mark.asyncio
async def test_set_refuses_bad_input_duplicates_pending_files_and_full_slots(app, fake):
    assert "HH:MM" in await call(app, "set_watch_alarm_usb", {"time": "25:00"})
    assert "unknown day" in await call(app, "set_watch_alarm_usb", {"time": "05:45", "days": "someday"})
    dup = await call(app, "set_watch_alarm_usb", {"time": "06:10", "days": "once", "enabled": False, "confirm": True})
    assert dup["status"] == "duplicate"
    fake.new_files = ["SOMETHING"]
    assert (await call(app, "set_watch_alarm_usb", {"time": "05:45", "confirm": True}))["status"] == "import_pending"
    fake.new_files = []
    fake.settings = settings_fit([(60 + i, 128, False) for i in range(10)])
    assert (await call(app, "set_watch_alarm_usb", {"time": "05:45", "confirm": True}))["status"] == "no_free_slot"
    assert fake.put_files == []


@pytest.mark.asyncio
async def test_set_refuses_a_file_that_fails_its_crc(app, fake):
    fake.settings = fake.settings[:-3] + b"\x00\x00\x00"
    assert (await call(app, "set_watch_alarm_usb", {"time": "05:45", "confirm": True}))["status"] == "unreadable_settings"
