"""
Garmin watch over USB for Garmin Connect MCP Server (Windows)

A fenix 7 shows up on Windows as an MTP device (no drive letter). This module reads it through the
Windows shell (PowerShell, Shell.Application) and, with the user's agreement, writes ONE file into
GARMIN/NewFiles, the folder the watch declares in GarminDevice.xml as its input folder for FIT files.

What was found out live (fenix 7, firmware 27.18, 2026-10-22):
 - GARMIN/Settings/Settings.fit is output-only; its message 222 holds the ten alarm slots, including the
   recurring ones that the Garmin Connect settings API never lists (see fit_light.py).
 - A copy of that file with one empty alarm slot filled in (everything else byte for byte the same, CRC fixed),
   put into GARMIN/NewFiles, was taken over by the watch when the cable was pulled: NewFiles was empty
   afterwards and the next export of Settings.fit held the new alarm, the other alarms unchanged.
 - GARMIN/Schedule/Schedule.fit lists the scheduled workouts (date, done or not, workout number).

Everything here is read-only except set_watch_alarm_usb / delete_watch_alarm_usb, which are switched off unless
the server environment has GARMIN_WATCH_USB_WRITES=1, ask for confirm=true, keep a copy of the watch's
Settings.fit in ~/.garmin-coach/backups, change only the one slot, and stage the file; the watch applies it
when the cable is unplugged. Verify afterwards with get_watch_usb_state.
"""
import base64
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Optional

from garmin_workouts_mcp import fit_light

_DEFAULT_NAME = r"^(fenix|forerunner|enduro|epix|venu|vivoactive|instinct|marq|tactix)"
_BACKUP_DIR = pathlib.Path.home() / ".garmin-coach" / "backups"
_KEEP_BACKUPS = 20
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_WRITES_OFF = (
    "Writing to the watch over USB is switched off. Nothing was changed. Set the environment variable "
    "GARMIN_WATCH_USB_WRITES=1 for the server to allow it."
)

_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$shell = New-Object -ComObject Shell.Application
$dev = $shell.NameSpace(17).Items() | Where-Object { $_.Name -match '__PATTERN__' } | Select-Object -First 1
if (-not $dev) { '{"found": false}'; exit 0 }
$storage = $dev.GetFolder.Items() | Select-Object -First 1
function Get-Mtp($root, [string]$path) {
  $cur = $root
  foreach ($part in $path.Split('/')) {
    if ($part -eq '') { continue }
    $next = $cur.GetFolder.Items() | Where-Object { $_.Name -eq $part } | Select-Object -First 1
    if (-not $next) { return $null }
    $cur = $next
  }
  return $cur
}
function Get-Names([string]$path, [bool]$files) {
  $f = Get-Mtp $storage $path
  if (-not $f) { return @() }
  @($f.GetFolder.Items() | Where-Object { $files -eq (-not $_.IsFolder) } | ForEach-Object { $_.Name })
}
"""

_STATE = _PRELUDE + r"""
$dest = '__DEST__'
foreach ($p in 'GARMIN/Settings', 'GARMIN/Schedule') {
  $f = Get-Mtp $storage $p
  if ($f) { $item = $f.GetFolder.Items() | Select-Object -First 1; if ($item) { $shell.NameSpace($dest).CopyHere($item, 0x414) } }
}
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline -and @(Get-ChildItem $dest -File).Count -lt 2) { Start-Sleep -Milliseconds 300 }
$out = [ordered]@{
  found = $true
  device = $dev.Name
  storage_total = $dev.GetFolder.GetDetailsOf($storage, 2)
  storage_free = $dev.GetFolder.GetDetailsOf($storage, 3)
  workouts = @(Get-Names 'GARMIN/Workouts' $true)
  dated_workouts = @(Get-Names 'GARMIN/Workouts/Schedule' $true)
  pacebands = @(Get-Names 'GARMIN/PaceBands' $true)
  activities = @(Get-Names 'GARMIN/Activity' $true)
  new_files = @(Get-Names 'GARMIN/NewFiles' $true)
  files = @(Get-ChildItem $dest -File | ForEach-Object { $_.Name })
}
$out | ConvertTo-Json -Depth 4 -Compress
"""

_PUT = _PRELUDE + r"""
$nf = Get-Mtp $storage 'GARMIN/NewFiles'
if (-not $nf) { throw 'GARMIN/NewFiles not found on the watch' }
$nf.GetFolder.CopyHere('__LOCAL__', 0x414)
Start-Sleep -Seconds 4
@{ found = $true; new_files = @(Get-Names 'GARMIN/NewFiles' $true) } | ConvertTo-Json -Depth 3 -Compress
"""


def _quote(text: str) -> str:
    return text.replace("'", "''")


def _powershell(script: str, timeout: int = 120) -> dict:
    if sys.platform != "win32":
        return {"error": "USB access to the watch is implemented for Windows only"}
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        done = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-EncodedCommand", encoded], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "the watch did not answer in time (is it unlocked and showing the USB screen?)"}
    out = done.stdout.decode("utf-8-sig", "replace").strip()
    lines = [line for line in out.splitlines() if line.lstrip().startswith("{")]
    if done.returncode != 0 or not lines:
        return {"error": (done.stderr.decode("utf-8", "replace").strip() or out or "no answer")[:400]}
    return json.loads(lines[-1])


def _bridge_state(pattern: str) -> dict:
    """Find the watch, list a few folders, and copy Settings.fit and Schedule.fit into a temporary folder"""
    dest = tempfile.mkdtemp(prefix="garmin-watch-")
    script = _STATE.replace("__PATTERN__", _quote(pattern)).replace("__DEST__", _quote(dest))
    result = _powershell(script)
    result["folder"] = dest
    return result


def _bridge_put(pattern: str, local: str) -> dict:
    return _powershell(_PUT.replace("__PATTERN__", _quote(pattern)).replace("__LOCAL__", _quote(local)))


def _writes_allowed() -> bool:
    return os.environ.get("GARMIN_WATCH_USB_WRITES", "").strip().lower() in ("1", "true", "yes")


def _dump(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _pattern(device_name: Optional[str]) -> str:
    return device_name or os.environ.get("GARMIN_WATCH_USB_NAME") or _DEFAULT_NAME


def _read(device_name: Optional[str]):
    """(problem payload or None, state dict, Settings.fit bytes, Schedule.fit bytes)"""
    state = _bridge_state(_pattern(device_name))
    if state.get("error"):
        return {"status": "usb_error", "message": state["error"]}, state, b"", b""
    if not state.get("found"):
        return {"status": "watch_not_connected",
                "message": "No watch found. Plug it into the PC with its cable and wake the screen; it shows up as a "
                           "portable device (MTP) in Explorer."}, state, b"", b""
    folder = pathlib.Path(state["folder"])
    settings = (folder / "Settings.fit")
    schedule = (folder / "Schedule.fit")
    return None, state, settings.read_bytes() if settings.exists() else b"", schedule.read_bytes() if schedule.exists() else b""


def _backup(data: bytes) -> str:
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _BACKUP_DIR / f"watch-settings-{datetime.datetime.now():%Y%m%d-%H%M%S}.fit"
    path.write_bytes(data)
    for old in sorted(_BACKUP_DIR.glob("watch-settings-*.fit"))[:-_KEEP_BACKUPS]:
        old.unlink()
    return str(path)


def _stage(data: bytes, pattern: str, name_hint: str) -> dict:
    folder = tempfile.mkdtemp(prefix="garmin-watch-out-")
    local = pathlib.Path(folder) / f"{name_hint}{datetime.datetime.now():%y%m%d%H%M%S}.FIT"
    local.write_bytes(data)
    return _bridge_put(pattern, str(local))


_NEXT = ("The file is waiting in the watch's NewFiles folder. The watch takes it over when the cable is unplugged "
         "(wait a minute, plug it in again), then call get_watch_usb_state to check the result.")


def register_tools(app):
    @app.tool()
    async def get_watch_usb_state(device_name: Optional[str] = None) -> str:
        """
        Read what is on a Garmin watch that is plugged into this Windows PC (read-only).

        Shows the alarm slots as the watch really holds them (including recurring alarms that Garmin Connect's
        settings never list), the scheduled workouts, the workout and PaceBands (PacePro) files, the newest
        activity files, free space, and whether a file is still waiting in NewFiles. Needs the cable; the watch
        shows up as a portable device.

        Args:
            device_name: Part of the device's name in Explorer (default: any fenix, Forerunner, Venu, ... or the
                environment variable GARMIN_WATCH_USB_NAME).
        """
        problem, state, settings, schedule = _read(device_name)
        if problem:
            return _dump(problem)
        alarms = fit_light.alarm_slots(settings) if settings and fit_light.check_crc(settings) else None
        activities = sorted(state.get("activities") or [])
        return _dump({
            "status": "ok",
            "device": state.get("device"),
            "storage": {"total": state.get("storage_total"), "free": state.get("storage_free")},
            "alarms": None if alarms is None else [a for a in alarms if a["time"]],
            "free_alarm_slots": None if alarms is None else sum(1 for a in alarms if not a["time"]),
            "scheduled_workouts": fit_light.schedule_rows(schedule) if schedule and fit_light.check_crc(schedule) else None,
            "workout_files": state.get("workouts"),
            "dated_workout_copies": state.get("dated_workouts"),
            "pacepro_files": state.get("pacebands"),
            "activities": {"count": len(activities), "newest": activities[-3:]},
            "files_waiting_in_new_files": state.get("new_files"),
            "note": "Day names of alarms assume bit 0 = Monday (checked only for a Monday to Saturday alarm). Times are the "
                    "watch's own clock times.",
        })

    @app.tool()
    async def set_watch_alarm_usb(time: str, days: str = "once", enabled: bool = True, confirm: bool = False,
                                  device_name: Optional[str] = None) -> str:
        """
        Add ONE alarm to the watch over USB (needs the cable; switched off unless GARMIN_WATCH_USB_WRITES=1).

        Fills the first empty alarm slot; existing alarms are never touched. The watch applies the change when the
        cable is unplugged. Without confirm=true only the plan is shown.

        Args:
            time: HH:MM on the watch's clock.
            days: once, daily, weekdays, weekend, or days such as mon,wed,fri or mon-sat. Only "once" and
                Monday-to-Saturday have been checked against the watch.
            enabled: false stores the alarm switched off.
            confirm: must be true to stage the file.
            device_name: Part of the device's name in Explorer.
        """
        if not _writes_allowed():
            return _dump({"status": "switched_off", "message": _WRITES_OFF})
        match = _TIME_RE.match(time.strip())
        if not match:
            return "time must be HH:MM, for example 05:45"
        try:
            mask = fit_light.days_mask(days)
        except fit_light.FitError as e:
            return str(e)
        minutes = int(match.group(1)) * 60 + int(match.group(2))
        problem, state, settings, _ = _read(device_name)
        if problem:
            return _dump(problem)
        if not settings or not fit_light.check_crc(settings):
            return _dump({"status": "unreadable_settings", "message": "Settings.fit could not be read or fails its CRC check. Nothing was changed."})
        if state.get("new_files"):
            return _dump({"status": "import_pending", "files_waiting": state["new_files"],
                          "message": "A file is still waiting in NewFiles. Unplug the cable so the watch takes it over, then try again."})
        slots = fit_light.alarm_slots(settings)
        wanted = fit_light.day_names(mask)
        for a in slots:
            if a["time"] == f"{minutes // 60:02d}:{minutes % 60:02d}" and a["days"] == wanted and a["enabled"] == enabled:
                return _dump({"status": "duplicate", "existing_alarm": a})
        free = next((a["slot"] for a in slots if not a["time"]), None)
        if free is None:
            return _dump({"status": "no_free_slot", "message": "All alarm slots are in use; delete one first."})
        plan = {"slot": free, "time": f"{minutes // 60:02d}:{minutes % 60:02d}", "days": wanted, "enabled": enabled}
        if not confirm:
            return _dump({"status": "confirmation_required", "plan": plan, "message": "Call again with confirm=true to stage it."})
        try:
            patched = fit_light.set_alarm(settings, free, minutes, mask, enabled)
        except fit_light.FitError as e:
            return _dump({"status": "refused", "message": str(e)})
        expected = [dict(a) for a in slots]
        after = fit_light.alarm_slots(patched)
        if [a for a in after if a["slot"] != free] != [a for a in expected if a["slot"] != free]:
            return _dump({"status": "refused", "message": "The other alarm slots would change. Nothing was staged."})
        backup = _backup(settings)
        result = _stage(patched, _pattern(device_name), "ALARM")
        if result.get("error"):
            return _dump({"status": "usb_error", "message": result["error"], "backup": backup})
        return _dump({"status": "staged", "alarm": plan, "backup": backup, "files_waiting_in_new_files": result.get("new_files"),
                      "next": _NEXT})

    @app.tool()
    async def delete_watch_alarm_usb(slot: int, confirm: bool = False, device_name: Optional[str] = None) -> str:
        """
        Remove ONE alarm from the watch over USB (needs the cable; switched off unless GARMIN_WATCH_USB_WRITES=1).

        The slot number is the one get_watch_usb_state shows. Without confirm=true only the alarm is shown. The watch
        applies the change when the cable is unplugged.
        """
        if not _writes_allowed():
            return _dump({"status": "switched_off", "message": _WRITES_OFF})
        problem, state, settings, _ = _read(device_name)
        if problem:
            return _dump(problem)
        if not settings or not fit_light.check_crc(settings):
            return _dump({"status": "unreadable_settings", "message": "Settings.fit could not be read or fails its CRC check. Nothing was changed."})
        if state.get("new_files"):
            return _dump({"status": "import_pending", "files_waiting": state["new_files"],
                          "message": "A file is still waiting in NewFiles. Unplug the cable so the watch takes it over, then try again."})
        slots = fit_light.alarm_slots(settings)
        target = next((a for a in slots if a["slot"] == slot), None)
        if target is None or not target["time"]:
            return _dump({"status": "not_found", "message": f"Slot {slot} holds no alarm.", "alarms": [a for a in slots if a["time"]]})
        if not confirm:
            return _dump({"status": "confirmation_required", "alarm": target, "message": "Call again with confirm=true to remove it."})
        try:
            patched = fit_light.clear_alarm(settings, slot)
        except fit_light.FitError as e:
            return _dump({"status": "refused", "message": str(e)})
        if [a for a in fit_light.alarm_slots(patched) if a["slot"] != slot] != [a for a in slots if a["slot"] != slot]:
            return _dump({"status": "refused", "message": "The other alarm slots would change. Nothing was staged."})
        backup = _backup(settings)
        result = _stage(patched, _pattern(device_name), "ALARM")
        if result.get("error"):
            return _dump({"status": "usb_error", "message": result["error"], "backup": backup})
        return _dump({"status": "staged", "removed": target, "backup": backup, "files_waiting_in_new_files": result.get("new_files"),
                      "next": _NEXT})

    return app
