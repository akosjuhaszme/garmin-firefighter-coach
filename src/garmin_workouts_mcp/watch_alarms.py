"""
Watch alarms for Garmin Connect MCP Server

The alarms of a Garmin watch are part of its device settings
(device-service/deviceservice/device-info/settings/{deviceId}, GET and PUT; the Garmin
Connect Personal API has no such endpoint). The PUT takes the whole settings object, so every
write here is guarded: the settings are saved to ~/.garmin-coach/backups first, the new
settings are read back, and if anything other than the one intended alarm changed, the saved
copy is written back.

What was found out live (fenix 7): an alarm is {alarmId, alarmMode, alarmTime, alarmDays,
alarmSound, alarmMessage, backlight, changeState, ...}; a new alarm is sent with alarmId null and
changeState NEW and Garmin gives it an id; alarmSound accepts VIBRATION, TONE and
TONE_AND_VIBRATION (anything else is refused as a whole, nothing changes); alarmMessage and
backlight (ON/OFF) are kept; alarmMode accepts ON, OFF, ONCE, DAILY and WEEKDAYS; the day names
tried for a recurring alarm were all dropped, so only one-time alarms (alarmDays ["ONCE"]) are
created. alarmTime is treated as minutes after midnight (370 is 06:10); that unit follows from the one
alarm that was in the settings and still has to be confirmed on the watch itself.

WRITES ARE SWITCHED OFF unless the server environment has GARMIN_WATCH_ALARM_WRITES=1. Reason
(found 2026-10-22): the settings the API holds list ONE alarm, while the watch itself had three,
two of them recurring. No field of the settings object carries the recurring alarms (checked all
135 keys, with and without the mergeDefault parameters), so they exist only on the watch. A
settings write may make the watch replace its own alarms with Connect's list at the next sync;
that is not ruled out, and the backup and read-back checks here only protect what the API lists.
The experiments of that day wrote the list [06:10 off] (the list that was already there) a few
times between 15:13 and 15:18; the watch's last download from Connect before that was 14:31.
"""
import copy
import datetime
import json
import os
import pathlib
import re
from typing import Optional

from garth.exc import GarthHTTPError

from garmin_workouts_mcp.events import retry_once_on_401

# The garmin_client will be set by the main file
garmin_client = None

_WRITES_OFF = (
    "Alarm changes are switched off. Alarms that exist only on the watch (the recurring ones) do not appear in "
    "Garmin's settings, and a settings write may replace the watch's own alarms at its next sync; that is not ruled "
    "out. Nothing was changed. Switch writes on only after the user knows this and agreed: set the environment "
    "variable GARMIN_WATCH_ALARM_WRITES=1 for the server."
)
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_SOUNDS = ("VIBRATION", "TONE", "TONE_AND_VIBRATION")
_BACKUP_DIR = pathlib.Path.home() / ".garmin-coach" / "backups"
_KEEP_BACKUPS = 20
_MAX_LABEL = 30


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


# ---------------------------------------------------------------- helpers


def _request(method: str, path: str, **kwargs):
    """(status code, parsed body). garth raises on every HTTP error status, so unwrap that."""
    def send():
        return garmin_client.garth.request(method, "connectapi", path, api=True, **kwargs)

    try:
        response = retry_once_on_401(send) if method == "GET" else send()
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


def _dump(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _pick_device(device_id: Optional[int]):
    """(device dict, None) or (None, error payload)."""
    status, devices = _request("GET", "device-service/deviceregistration/devices")
    if status != 200 or not isinstance(devices, list) or not devices:
        return None, {"status": "failed", "http_status": status, "message": "No registered device found"}
    listed = [
        {"device_id": d.get("deviceId"), "name": d.get("productDisplayName") or d.get("displayName"),
         "primary": bool(d.get("primary"))}
        for d in devices
    ]
    if device_id is not None:
        target = next((d for d in listed if d["device_id"] == int(device_id)), None)
        if target is None:
            return None, {"status": "unknown_device", "message": "That device id is not on the account.", "devices": listed}
        return target, None
    primary = [d for d in listed if d["primary"]]
    if len(primary) == 1:
        return primary[0], None
    if len(listed) == 1:
        return listed[0], None
    return None, {"status": "device_needed", "message": "Pass device_id: no single primary device.", "devices": listed}


def _settings_path(device_id) -> str:
    return f"device-service/deviceservice/device-info/settings/{int(device_id)}"


def _writes_allowed() -> bool:
    return os.environ.get("GARMIN_WATCH_ALARM_WRITES", "").strip().lower() in ("1", "true", "yes")


def _alarm_row(alarm: dict) -> dict:
    minutes = alarm.get("alarmTime")
    return {
        "alarm_id": alarm.get("alarmId"),
        "time": f"{minutes // 60:02d}:{minutes % 60:02d}" if isinstance(minutes, int) else None,
        "mode": alarm.get("alarmMode"),
        "days": alarm.get("alarmDays"),
        "sound": alarm.get("alarmSound"),
        "label": alarm.get("alarmMessage"),
        "backlight": alarm.get("backlight"),
    }


def _save_backup(device_id, settings: dict) -> pathlib.Path:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = _BACKUP_DIR / f"device-settings-{int(device_id)}-{stamp}.json"
    path.write_text(json.dumps(settings, indent=1, ensure_ascii=False), encoding="utf-8")
    old = sorted(_BACKUP_DIR.glob(f"device-settings-{int(device_id)}-*.json"))[:-_KEEP_BACKUPS]
    for stale in old:
        try:
            stale.unlink()
        except OSError:
            pass
    return path


def _without_alarms(settings: dict) -> dict:
    return {k: v for k, v in settings.items() if k != "alarms"}


def _write_checked(device_id, before: dict, new_alarms: list, expected_ok):
    """PUT the settings with a new alarm list; read back; run expected_ok(after_alarms) and check that nothing else
    changed; restore the saved copy on any mismatch. Returns (status, details)."""
    backup = _save_backup(device_id, before)
    path = _settings_path(device_id)
    wanted = copy.deepcopy(before)
    wanted["alarms"] = new_alarms
    put_status, put_body = _request("PUT", path, json=wanted)
    if put_status not in (200, 204):
        return "failed", {"http_status": put_status, "message": _problem(put_body), "note": "Nothing was changed.", "backup": str(backup)}
    read_status, after = _request("GET", path)
    problems = []
    if read_status != 200 or not isinstance(after, dict):
        problems.append("the settings could not be read back")
    else:
        if _without_alarms(after) != _without_alarms(before):
            problems.append("other device settings changed")
        reason = expected_ok(after.get("alarms") or [])
        if reason:
            problems.append(reason)
    if not problems:
        return "ok", {"alarms": after.get("alarms") or [], "backup": str(backup)}
    restore_status, _ = _request("PUT", path, json=before)
    check_status, again = _request("GET", path)
    restored = check_status == 200 and isinstance(again, dict) and again == before
    return ("failed_restored" if restored else "failed_restore_unverified"), {
        "problems": problems, "restore_http_status": restore_status, "backup": str(backup),
    }


# ------------------------------------------------------------------ tools


def register_tools(app):
    """Register the watch alarm tools with the MCP server app"""

    @app.tool()
    async def get_watch_alarms(device_id: Optional[int] = None) -> str:
        """List the alarms in the Garmin settings of the user's watch (read-only)

        Shows what Garmin Connect holds for the watch: id, time, mode, days, sound, label. An
        alarm that was only set on the watch itself may not be listed here, so this is not
        always the full list of what rings. Without device_id the primary device is used.

        Args:
            device_id: Optional device id (the result of the other watch tools lists the devices)
        """
        try:
            device, error = _pick_device(device_id)
            if error:
                return _dump(error)
            status, settings = _request("GET", _settings_path(device["device_id"]))
            if status != 200 or not isinstance(settings, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(settings)})
            return _dump({
                "device": device,
                "multiple_alarms_supported": settings.get("multipleAlarmEnabled"),
                "alarms": [_alarm_row(a) for a in settings.get("alarms") or []],
                "note": "Alarms set only on the watch may not appear in this list.",
            })
        except Exception as e:
            return f"Error reading the watch alarms: {str(e)}"

    @app.tool()
    async def set_watch_alarm(
        time: str,
        sound: str = "VIBRATION",
        label: Optional[str] = None,
        device_id: Optional[int] = None,
    ) -> str:
        """Add ONE new one-time alarm to the Garmin settings of the user's watch

        SWITCHED OFF by default (see the module note: a settings write may replace alarms that exist only on the
        watch); it works only when the server runs with GARMIN_WATCH_ALARM_WRITES=1, which the user must agree to.
        Only call this when the user asked for the alarm. The alarm is a one-time alarm: it rings the
        next time the clock shows that time (within 24 hours), so set it the evening before the
        morning it is meant for. It reaches the watch at the next sync (open Garmin Connect on the phone
        to start one). Existing alarms are never changed or removed by this tool. Before the write the
        device settings are saved to a backup file; afterwards they are read back, and if anything but
        the new alarm differs the saved copy is written back and the tool says so. An alarm at the same
        time that already exists is reported instead of added twice. Remove it again with
        delete_watch_alarm.

        Args:
            time: Local time of the alarm, HH:MM on the 24 hour clock, e.g. "05:45"
            sound: "VIBRATION" (default), "TONE" or "TONE_AND_VIBRATION"
            label: Optional short text (up to 30 characters); the watch may not show it
            device_id: Optional device id; by default the primary device
        """
        try:
            if not _writes_allowed():
                return _dump({"status": "switched_off", "message": _WRITES_OFF})
            match = _TIME_RE.match(str(time).strip())
            if not match:
                return "Error: time must be HH:MM on the 24 hour clock"
            minutes = int(match.group(1)) * 60 + int(match.group(2))
            sound = (sound or "VIBRATION").strip().upper()
            if sound not in _SOUNDS:
                return f"Error: sound must be one of {', '.join(_SOUNDS)}"
            text = " ".join(label.split()) if label else None
            if text and len(text) > _MAX_LABEL:
                return f"Error: label is too long ({_MAX_LABEL} characters at most)"

            device, error = _pick_device(device_id)
            if error:
                return _dump(error)
            path = _settings_path(device["device_id"])
            status, before = _request("GET", path)
            if status != 200 or not isinstance(before, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(before)})
            existing = before.get("alarms") or []
            duplicate = next((a for a in existing if a.get("alarmTime") == minutes and a.get("alarmMode") != "OFF"), None)
            if duplicate:
                return _dump({
                    "status": "duplicate",
                    "message": "An active alarm at this time is already in the settings; nothing was added.",
                    "existing_alarm": _alarm_row(duplicate),
                })
            if existing and before.get("multipleAlarmEnabled") is False:
                return _dump({"status": "not_supported", "message": "This watch holds only one alarm; nothing was added.",
                              "alarms": [_alarm_row(a) for a in existing]})

            template = copy.deepcopy(existing[0]) if existing else {"backlight": "ON", "enabled": None}
            new = {**template, "alarmId": None, "changeState": "NEW", "alarmMode": "ON", "alarmTime": minutes,
                   "alarmDays": ["ONCE"], "alarmSound": sound, "alarmMessage": text}
            known_ids = {a.get("alarmId") for a in existing}

            def expected_ok(after_alarms):
                added = [a for a in after_alarms if a.get("alarmId") not in known_ids]
                if len(added) != 1:
                    return f"expected exactly one new alarm, found {len(added)}"
                got = added[0]
                for field, want in (("alarmTime", minutes), ("alarmMode", "ON"), ("alarmDays", ["ONCE"]), ("alarmSound", sound)):
                    if got.get(field) != want:
                        return f"the new alarm was stored with {field} = {got.get(field)!r}, not {want!r}"
                kept = {a.get("alarmId"): a for a in after_alarms}
                for old in existing:
                    if kept.get(old.get("alarmId")) != old:
                        return "an existing alarm changed"
                return None

            outcome, details = _write_checked(device["device_id"], before, copy.deepcopy(existing) + [new], expected_ok)
            if outcome != "ok":
                return _dump({"status": outcome, "device": device, **details})
            added = next(a for a in details["alarms"] if a.get("alarmId") not in known_ids)
            return _dump({
                "status": "set",
                "device": device,
                "alarm": _alarm_row(added),
                "message": "The alarm is in the settings and reaches the watch at the next sync. It rings the next time the "
                           "clock shows this time.",
                "backup": details["backup"],
            })
        except Exception as e:
            return f"Error setting the watch alarm: {str(e)}"

    @app.tool()
    async def delete_watch_alarm(alarm_id: int, confirm: bool = False, device_id: Optional[int] = None) -> str:
        """Delete ONE alarm from the Garmin settings of the user's watch

        SWITCHED OFF by default like set_watch_alarm (GARMIN_WATCH_ALARM_WRITES=1 needed).
        Two steps. Without confirm=true nothing is deleted: the result shows which alarm would go. Show
        that to the user and call again with confirm=true only after the user agreed to deleting THIS
        alarm (an alarm this tool created for a test may be deleted without asking again). The settings
        are saved to a backup file first and read back afterwards; if anything but that alarm differs the
        saved copy is written back. The removal reaches the watch at the next sync.

        Args:
            alarm_id: The alarm id from get_watch_alarms
            confirm: True only after the user agreed to deleting this alarm
            device_id: Optional device id; by default the primary device
        """
        try:
            if not _writes_allowed():
                return _dump({"status": "switched_off", "message": _WRITES_OFF})
            device, error = _pick_device(device_id)
            if error:
                return _dump(error)
            path = _settings_path(device["device_id"])
            status, before = _request("GET", path)
            if status != 200 or not isinstance(before, dict):
                return _dump({"status": "failed", "http_status": status, "message": _problem(before)})
            existing = before.get("alarms") or []
            target = next((a for a in existing if a.get("alarmId") == int(alarm_id)), None)
            if target is None:
                return _dump({"status": "not_found", "alarm_id": alarm_id, "alarms": [_alarm_row(a) for a in existing]})
            if not confirm:
                return _dump({
                    "status": "confirmation_required",
                    "message": "Nothing was deleted. Ask the user whether this exact alarm should be deleted, then call "
                               "again with confirm=true.",
                    "alarm": _alarm_row(target),
                })
            remaining = [copy.deepcopy(a) for a in existing if a.get("alarmId") != int(alarm_id)]

            def expected_ok(after_alarms):
                if any(a.get("alarmId") == int(alarm_id) for a in after_alarms):
                    return "the alarm is still in the settings"
                if len(after_alarms) != len(remaining) or any(a not in remaining for a in after_alarms):
                    return "the other alarms are not as they were"
                return None

            outcome, details = _write_checked(device["device_id"], before, remaining, expected_ok)
            if outcome != "ok":
                return _dump({"status": outcome, "device": device, **details})
            return _dump({"status": "deleted", "alarm": _alarm_row(target), "backup": details["backup"]})
        except Exception as e:
            return f"Error deleting the watch alarm: {str(e)}"

    return app
