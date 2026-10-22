"""
Unit tests for the watch alarm tools (watch_alarms.py)

A stateful fake of the device settings service stands in for Garmin. It copies what was seen live: the whole settings object is
read and written back, a new alarm (alarmId null, changeState NEW) gets an id and is stored as UNCHANGED, a value outside
VIBRATION / TONE / TONE_AND_VIBRATION for alarmSound refuses the whole write. Backups go to a temporary folder.
"""
import copy
import json
from types import SimpleNamespace

import pytest
from garth.exc import GarthHTTPError
from mcp.server.fastmcp import FastMCP
from requests import HTTPError

from garmin_workouts_mcp import watch_alarms

_SOUNDS = {"VIBRATION", "TONE", "TONE_AND_VIBRATION"}


def _response(status, body=None):
    text = "" if body is None else json.dumps(body)
    return SimpleNamespace(status_code=status, text=text, json=lambda: body)


def _alarm(alarm_id, minutes, mode="OFF", days=("ONCE",), sound="VIBRATION", label=None):
    return {"alarmId": alarm_id, "alarmMode": mode, "alarmTime": minutes, "alarmDays": list(days), "alarmSound": sound,
            "alarmMessage": label, "changeState": "UNCHANGED", "backlight": "ON", "enabled": None, "alarmImageId": None,
            "alarmIcon": None, "alarmType": None}


class FakeDeviceService:
    def __init__(self):
        self.settings = {"deviceId": 111, "timeFormat": "time_twenty_four_hr", "multipleAlarmEnabled": True,
                         "alarms": [_alarm(1000, 370)], "backlightTimeout": 15}
        self.devices = [{"deviceId": 111, "productDisplayName": "watch one", "primary": True}]
        self.calls = []
        self.next_id = 5000
        self.sabotage = None  # callable(settings) applied after a PUT, to imitate a server that changes more than it should
        self.put_status = 200

    def _fail(self, status, message):
        raise GarthHTTPError(msg="Error in request", error=HTTPError(response=_response(status, {"message": message})))

    def request(self, method, subdomain, path, api=False, json=None, **kw):
        self.calls.append((method, path))
        if path == "device-service/deviceregistration/devices":
            return _response(200, copy.deepcopy(self.devices))
        assert path == "device-service/deviceservice/device-info/settings/111", path
        if method == "GET":
            return _response(200, copy.deepcopy(self.settings))
        assert method == "PUT"
        if self.put_status >= 400:
            self._fail(self.put_status, "refused")
        for alarm in json["alarms"]:
            if alarm.get("alarmSound") not in _SOUNDS:
                self._fail(400, f"Invalid value '{alarm.get('alarmSound')}' for alarms.alarmSound")
        stored = copy.deepcopy(json)
        for alarm in stored["alarms"]:
            if alarm.get("alarmId") is None:
                alarm["alarmId"] = self.next_id
                self.next_id += 1
            alarm["changeState"] = "UNCHANGED"
        self.settings = stored
        if self.sabotage:
            self.sabotage(self.settings)
        return _response(200, copy.deepcopy(self.settings))

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(watch_alarms, "_BACKUP_DIR", tmp_path / "backups")
    return FakeDeviceService()


@pytest.fixture
def app(fake):
    watch_alarms.configure(SimpleNamespace(garth=fake))
    application = FastMCP("Test alarms")
    watch_alarms.register_tools(application)
    return application


async def call_json(app, name, args):
    return json.loads((await app.call_tool(name, args))[0][0].text)


async def call_text(app, name, args):
    return (await app.call_tool(name, args))[0][0].text


@pytest.mark.asyncio
async def test_list_alarms_shows_times_as_clock_times(app):
    data = await call_json(app, "get_watch_alarms", {})
    assert data["alarms"] == [{"alarm_id": 1000, "time": "06:10", "mode": "OFF", "days": ["ONCE"], "sound": "VIBRATION",
                               "label": None, "backlight": "ON"}]
    assert data["device"]["name"] == "watch one" and "set only on the watch" in data["note"]


@pytest.mark.asyncio
async def test_set_adds_one_alarm_and_leaves_the_rest_alone(app, fake, tmp_path):
    before = copy.deepcopy(fake.settings)
    data = await call_json(app, "set_watch_alarm", {"time": "5:45", "sound": "tone", "label": "  Futas   napkelte "})
    assert data["status"] == "set"
    alarm = data["alarm"]
    assert alarm["time"] == "05:45" and alarm["mode"] == "ON" and alarm["days"] == ["ONCE"] and alarm["sound"] == "TONE"
    assert alarm["label"] == "Futas napkelte" and alarm["alarm_id"] == 5000
    assert fake.settings["alarms"][0] == before["alarms"][0]  # the existing alarm is untouched
    assert {k: v for k, v in fake.settings.items() if k != "alarms"} == {k: v for k, v in before.items() if k != "alarms"}
    backups = list((tmp_path / "backups").glob("device-settings-111-*.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == before  # saved BEFORE the write


@pytest.mark.asyncio
async def test_set_refuses_duplicates_and_bad_input_without_writing(app, fake):
    fake.settings["alarms"].append(_alarm(1001, 345, mode="ON"))
    dup = await call_json(app, "set_watch_alarm", {"time": "05:45"})
    assert dup["status"] == "duplicate" and dup["existing_alarm"]["alarm_id"] == 1001
    for args, fragment in (
        ({"time": "25:00"}, "HH:MM"), ({"time": "soon"}, "HH:MM"), ({"time": "06:00", "sound": "LOUD"}, "sound must be"),
        ({"time": "06:00", "label": "x" * 31}, "too long"),
    ):
        assert fragment in await call_text(app, "set_watch_alarm", args)
    assert fake.puts() == []


@pytest.mark.asyncio
async def test_an_alarm_that_is_off_does_not_count_as_a_duplicate(app, fake):
    data = await call_json(app, "set_watch_alarm", {"time": "06:10"})  # the existing 06:10 alarm is OFF
    assert data["status"] == "set" and len(fake.settings["alarms"]) == 2


@pytest.mark.asyncio
async def test_a_server_that_changes_other_settings_gets_the_saved_copy_written_back(app, fake):
    before = copy.deepcopy(fake.settings)

    def sabotage(settings):
        settings["backlightTimeout"] = 99  # the write changed something it should not have

    fake.sabotage = sabotage
    first_put = {}
    original_request = fake.request

    def request(method, subdomain, path, api=False, json=None, **kw):
        if method == "PUT" and not first_put:
            first_put["done"] = True
        elif method == "PUT":
            fake.sabotage = None  # the restore write behaves
        return original_request(method, subdomain, path, api=api, json=json, **kw)

    fake.request = request
    data = await call_json(app, "set_watch_alarm", {"time": "05:45"})
    assert data["status"] == "failed_restored"
    assert "other device settings changed" in data["problems"]
    assert fake.settings == before  # restored
    assert len(fake.puts()) == 2


@pytest.mark.asyncio
async def test_a_refused_write_changes_nothing(app, fake):
    before = copy.deepcopy(fake.settings)
    fake.put_status = 400
    data = await call_json(app, "set_watch_alarm", {"time": "05:45"})
    assert data["status"] == "failed" and data["http_status"] == 400 and "Nothing was changed" in data["note"]
    assert fake.settings == before


@pytest.mark.asyncio
async def test_delete_needs_confirmation_and_keeps_the_others(app, fake):
    await call_json(app, "set_watch_alarm", {"time": "05:45"})
    await call_json(app, "set_watch_alarm", {"time": "05:50"})
    preview = await call_json(app, "delete_watch_alarm", {"alarm_id": 5000})
    assert preview["status"] == "confirmation_required" and preview["alarm"]["time"] == "05:45"
    assert len(fake.settings["alarms"]) == 3
    done = await call_json(app, "delete_watch_alarm", {"alarm_id": 5000, "confirm": True})
    assert done["status"] == "deleted"
    assert [a["alarmId"] for a in fake.settings["alarms"]] == [1000, 5001]
    missing = await call_json(app, "delete_watch_alarm", {"alarm_id": 424242, "confirm": True})
    assert missing["status"] == "not_found"


@pytest.mark.asyncio
async def test_device_choice_is_checked(app, fake):
    fake.devices = [{"deviceId": 111, "productDisplayName": "a"}, {"deviceId": 222, "productDisplayName": "b"}]
    assert (await call_json(app, "set_watch_alarm", {"time": "05:45"}))["status"] == "device_needed"
    assert (await call_json(app, "get_watch_alarms", {"device_id": 999}))["status"] == "unknown_device"
    assert fake.puts() == []
