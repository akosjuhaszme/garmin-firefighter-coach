"""
A small FIT reader and patcher (standard library only) for the few files a Garmin watch shows over USB.

Only what the watch tools need: reading data messages, the alarm slots of a Settings file (global
message 222, ten slots), the scheduled workouts of a Schedule file (global message 28), and adding ONE
alarm to an empty slot in place. A patched file keeps its size, every other byte stays as it was, and both CRCs are
checked before and after.

Alarm slot fields (fenix 7, read from a real Settings.fit; the day bits beyond Monday to Saturday are
assumed): 0 time in minutes after midnight (65535 = empty slot), 1 day bits (bit 0 Monday ... bit 6
Sunday, 128 = one-time), 2 and 3 and 4 and 7 sound and display options (copied from an existing
alarm), 5 created and 11 last changed (FIT timestamps), 8 on/off (1 = on), 254 slot number.
"""
import datetime
import struct
from collections import namedtuple

FIT_EPOCH_OFFSET = 631065600  # seconds from 1970-01-01 to the FIT epoch 1989-12-31
ALARM_MESSAGE = 222
SCHEDULE_MESSAGE = 28
ONCE_BIT = 128
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401, 0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
_BASE = {0: ("B", 1), 1: ("b", 1), 2: ("B", 1), 3: ("h", 2), 4: ("H", 2), 5: ("i", 4), 6: ("I", 4), 7: (None, 1), 8: ("f", 4),
         9: ("d", 8), 10: ("B", 1), 11: ("H", 2), 12: ("I", 4), 13: ("B", 1), 14: ("q", 8), 15: ("Q", 8), 16: ("Q", 8)}
Record = namedtuple("Record", "number layout endian start end")


class FitError(ValueError):
    pass


def crc16(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC[crc & 0xF] ^ _CRC[b & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ _CRC[crc & 0xF] ^ _CRC[(b >> 4) & 0xF]
    return crc


def check_crc(data: bytes) -> bool:
    """True when the file CRC (and the header CRC, if the header has one) match"""
    if len(data) < 16 or data[8:12] != b".FIT":
        return False
    if crc16(data[:-2]) != struct.unpack_from("<H", data, len(data) - 2)[0]:
        return False
    stored = struct.unpack_from("<H", data, 12)[0] if data[0] >= 14 else 0
    return data[0] < 14 or stored == 0 or crc16(data[:12]) == stored


def records(data: bytes):
    """Every data message as a Record: global number, {field: (offset, size, base type)}, endianness, byte range"""
    header = data[0]
    pos, end = header, header + struct.unpack_from("<I", data, 4)[0]
    definitions = {}
    while pos < end:
        start = pos
        h = data[pos]
        pos += 1
        if h & 0x80:
            definition = definitions[(h >> 5) & 3]
        elif h & 0x40:
            endian = ">" if data[pos + 1] else "<"
            number = struct.unpack_from(endian + "H", data, pos + 2)[0]
            count = data[pos + 4]
            pos += 5
            fields = [tuple(data[pos + 3 * i:pos + 3 * i + 3]) for i in range(count)]
            pos += 3 * count
            developer = []
            if h & 0x20:
                n = data[pos]
                developer = [tuple(data[pos + 1 + 3 * i:pos + 4 + 3 * i]) for i in range(n)]
                pos += 1 + 3 * n
            definitions[h & 0x0F] = (endian, number, fields, developer)
            continue
        else:
            definition = definitions[h & 0x0F]
        endian, number, fields, developer = definition
        layout = {}
        for field, size, base in fields:
            layout[field] = (pos, size, base & 0x1F)
            pos += size
        pos += sum(size for _, size, _ in developer)
        yield Record(number, layout, endian, start, pos)


def _get(data, record, field):
    if field not in record.layout:
        return None
    offset, size, base = record.layout[field]
    code, width = _BASE.get(base, (None, 1))
    if code and size == width:
        return struct.unpack_from(record.endian + code, data, offset)[0]
    return bytes(data[offset:offset + size])


def _put(buf, record, field, value):
    offset, size, base = record.layout[field]
    code, width = _BASE.get(base, (None, 1))
    if not code or size != width:
        raise FitError(f"field {field} is not a plain number")
    struct.pack_into(record.endian + code, buf, offset, value)


# ---------------------------------------------------------------- days

def days_mask(spec: str) -> int:
    """'once', 'daily', 'weekdays', 'weekend' or a list/range such as 'mon,wed,fri' or 'mon-sat' to the day bits"""
    text = spec.strip().lower().replace(" ", "")
    if text == "once":
        return ONCE_BIT
    if text == "daily":
        return 127
    if text == "weekdays":
        return 31
    if text == "weekend":
        return 96
    mask = 0
    for part in text.split(","):
        names = part.split("-")
        if not all(n[:3] in DAY_NAMES for n in names) or len(names) > 2:
            raise FitError(f"unknown day in {spec!r}: use once, daily, weekdays, weekend, or days such as mon,wed or mon-sat")
        first = DAY_NAMES.index(names[0][:3])
        last = DAY_NAMES.index(names[-1][:3])
        mask |= sum(1 << ((first + i) % 7) for i in range(((last - first) % 7) + 1))
    return mask


def day_names(mask: int) -> list:
    return ["once"] if mask & ONCE_BIT else [DAY_NAMES[i] for i in range(7) if mask & (1 << i)]


# ---------------------------------------------------------------- alarms

def alarm_slots(data: bytes) -> list:
    out = []
    for r in (r for r in records(data) if r.number == ALARM_MESSAGE):
        minutes = _get(data, r, 0)
        used = minutes is not None and minutes != 0xFFFF
        created, changed = _get(data, r, 5), _get(data, r, 11)
        out.append({
            "slot": len(out),
            "time": f"{minutes // 60:02d}:{minutes % 60:02d}" if used else None,
            "days": day_names(_get(data, r, 1) or 0) if used else None,
            "enabled": (_get(data, r, 8) == 1) if used else None,
            "created": fit_time(created) if used else None,
            "changed": fit_time(changed) if used else None,
        })
    return out


def fit_time(seconds):
    if not isinstance(seconds, int) or seconds >= 0xFFFFFFF0:
        return None
    moment = datetime.datetime.fromtimestamp(seconds + FIT_EPOCH_OFFSET, datetime.timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def _patch(data: bytes, slot: int, values: dict, must_be_empty: bool) -> bytes:
    if not check_crc(data):
        raise FitError("the file does not pass its own CRC check, nothing was changed")
    rows = [r for r in records(data) if r.number == ALARM_MESSAGE]
    if not 0 <= slot < len(rows):
        raise FitError(f"slot {slot} does not exist (the file has {len(rows)})")
    record = rows[slot]
    if must_be_empty and _get(data, record, 0) != 0xFFFF:
        raise FitError(f"slot {slot} is not empty, refusing to overwrite it")
    buf = bytearray(data)
    for field, value in values.items():
        _put(buf, record, field, value)
    struct.pack_into("<H", buf, len(buf) - 2, crc16(bytes(buf[:-2])))
    changed = [i for i in range(len(buf)) if buf[i] != data[i]]
    if any(not (record.start <= i < record.end or i >= len(buf) - 2) for i in changed):
        raise FitError("bytes outside the slot would change, refusing")
    result = bytes(buf)
    if not check_crc(result):
        raise FitError("the patched file fails its CRC check, refusing")
    return result


def set_alarm(data: bytes, slot: int, minutes: int, mask: int, enabled: bool, now: int = None) -> bytes:
    """Fill the EMPTY slot with an alarm; the sound/display fields are those of a normal one-time alarm"""
    stamp = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) - FIT_EPOCH_OFFSET if now is None else now
    return _patch(data, slot, {0: minutes, 1: mask, 2: 0, 3: 2, 4: 1, 5: stamp, 7: 0, 8: 1 if enabled else 0, 11: stamp}, True)


# There is no clear_alarm on purpose: the watch ignores a slot that holds only invalid (empty) values, so an alarm
# cannot be removed by importing a file (checked live, 2026-10-22).


# ---------------------------------------------------------------- schedule

def schedule_rows(data: bytes) -> list:
    """Scheduled workouts on the watch: date, whether it is done, and the workout's number"""
    out = []
    for r in (r for r in records(data) if r.number == SCHEDULE_MESSAGE):
        day = _get(data, r, 6)
        date = datetime.datetime.fromtimestamp(day + FIT_EPOCH_OFFSET, datetime.timezone.utc).strftime("%Y-%m-%d") \
            if isinstance(day, int) and day < 0xFFFFFFF0 else None
        out.append({"date": date, "completed": bool(_get(data, r, 4)), "workout_id": _get(data, r, 2)})
    return sorted(out, key=lambda row: row["date"] or "")
