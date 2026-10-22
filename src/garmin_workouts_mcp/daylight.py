"""
Sunrise, sunset and twilight for Garmin Connect MCP Server

Plain astronomy, no network call: the NOAA solar position formulas give sunrise, sunset, solar noon and civil twilight (sun 6
degrees below the horizon) for a place and a date, in the time zone of that place. Good to about a minute for latitudes where
the sun rises and sets. Use it to start a run at sunrise, to see whether a run starts in the dark, or to work out when to wake
up (set_watch_alarm takes the result).
"""
import datetime
import math
import os
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python older than 3.9
    ZoneInfo = None

_SUNRISE_ANGLE = 90.833  # the sun's centre below the horizon at sunrise and sunset: refraction and the sun's radius
_CIVIL_ANGLE = 96.0
_MAX_DAYS = 31


def _solar_terms(julian_day: float):
    t = (julian_day - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (math.sin(math.radians(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(math.radians(2 * m)) * (0.019993 - 0.000101 * t) + math.sin(math.radians(3 * m)) * 0.000289)
    omega = 125.04 - 1934.136 * t
    apparent = l0 + centre - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    declination = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(apparent))))
    y = math.tan(math.radians(eps / 2)) ** 2
    eq_time = 4 * math.degrees(
        y * math.sin(2 * math.radians(l0)) - 2 * e * math.sin(math.radians(m))
        + 4 * e * y * math.sin(math.radians(m)) * math.cos(2 * math.radians(l0))
        - 0.5 * y * y * math.sin(4 * math.radians(l0)) - 1.25 * e * e * math.sin(2 * math.radians(m))
    )
    return declination, eq_time


def _event_minutes_utc(day: datetime.date, lat: float, lon: float, angle: float, rising: bool) -> Optional[float]:
    """Minutes after 00:00 UTC of `day` when the sun is `angle` degrees from the zenith, or None (polar day/night)."""
    jd0 = day.toordinal() + 1721424.5
    minutes = 720.0 - 4 * lon  # first guess: solar noon
    for _ in range(3):  # refine with the sun's position at the estimated moment
        declination, eq_time = _solar_terms(jd0 + minutes / 1440.0)
        cos_ha = (math.cos(math.radians(angle)) / (math.cos(math.radians(lat)) * math.cos(math.radians(declination)))
                  - math.tan(math.radians(lat)) * math.tan(math.radians(declination)))
        if not -1.0 <= cos_ha <= 1.0:
            return None
        ha = math.degrees(math.acos(cos_ha))
        minutes = 720.0 - 4 * (lon + (ha if rising else -ha)) - eq_time
    return minutes


def _solar_noon_minutes_utc(day: datetime.date, lon: float) -> float:
    minutes = 720.0 - 4 * lon
    for _ in range(2):
        _, eq_time = _solar_terms(day.toordinal() + 1721424.5 + minutes / 1440.0)
        minutes = 720.0 - 4 * lon - eq_time
    return minutes


def _local(day: datetime.date, minutes_utc: Optional[float], tz) -> Optional[datetime.datetime]:
    if minutes_utc is None:
        return None
    utc = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc) + datetime.timedelta(minutes=minutes_utc)
    return utc.astimezone(tz)


def daylight_for_day(day: datetime.date, lat: float, lon: float, tz, minutes_before: int = 30) -> dict:
    """Sunrise, sunset, civil twilight, solar noon and day length for one day, as local times."""
    rise = _local(day, _event_minutes_utc(day, lat, lon, _SUNRISE_ANGLE, True), tz)
    sunset = _local(day, _event_minutes_utc(day, lat, lon, _SUNRISE_ANGLE, False), tz)
    dawn = _local(day, _event_minutes_utc(day, lat, lon, _CIVIL_ANGLE, True), tz)
    dusk = _local(day, _event_minutes_utc(day, lat, lon, _CIVIL_ANGLE, False), tz)
    noon = _local(day, _solar_noon_minutes_utc(day, lon), tz)

    def clock(moment):
        return moment.strftime("%H:%M") if moment else None

    result = {
        "date": day.isoformat(),
        "civil_dawn": clock(dawn),
        "sunrise": clock(rise),
        "solar_noon": clock(noon),
        "sunset": clock(sunset),
        "civil_dusk": clock(dusk),
        "daylight_hours": round((sunset - rise).total_seconds() / 3600, 2) if rise and sunset else None,
        "utc_offset_hours": rise.utcoffset().total_seconds() / 3600 if rise else (noon.utcoffset().total_seconds() / 3600),
    }
    if rise:
        result["wake_up_before_sunrise"] = clock(rise - datetime.timedelta(minutes=minutes_before))
    if rise is None:
        result["note"] = "The sun does not rise and set on this date at this latitude."
    return result


def register_tools(app):
    """Register the daylight tool with the MCP server app"""

    @app.tool()
    async def get_daylight(
        date: Optional[str] = None,
        days: int = 1,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        timezone: Optional[str] = None,
        minutes_before: int = 30,
    ) -> str:
        """Sunrise, sunset and civil twilight for a place and one or more days (calculated, no network)

        Use it to start a run at sunrise, to see whether a run starts before civil dawn (still dark), or to
        find the time for a wake-up alarm (wake_up_before_sunrise: sunrise minus minutes_before; set_watch_alarm
        can set it the evening before). Times are local clock times of the place, daylight saving time
        included. Good to about a minute. The place and the time zone come from the arguments or from the
        environment variables GARMIN_COACH_LATITUDE, GARMIN_COACH_LONGITUDE and GARMIN_COACH_TIMEZONE.

        Args:
            date: First day, YYYY-MM-DD (default today)
            days: How many days in a row (1-31, default 1)
            latitude: Latitude in degrees, north positive (e.g. 47.5)
            longitude: Longitude in degrees, east positive (e.g. 19.0)
            timezone: IANA time zone name of the place, e.g. "Europe/Budapest"
            minutes_before: Minutes before sunrise for wake_up_before_sunrise (default 30)
        """
        try:
            lat = latitude if latitude is not None else _env_float("GARMIN_COACH_LATITUDE")
            lon = longitude if longitude is not None else _env_float("GARMIN_COACH_LONGITUDE")
            zone = timezone or os.environ.get("GARMIN_COACH_TIMEZONE")
            if lat is None or lon is None or not zone:
                return ("Error: give latitude, longitude and timezone (for example 47.5, 19.0, Europe/Budapest), or set "
                        "GARMIN_COACH_LATITUDE, GARMIN_COACH_LONGITUDE and GARMIN_COACH_TIMEZONE")
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                return "Error: latitude must be between -90 and 90 and longitude between -180 and 180"
            if not 1 <= int(days) <= _MAX_DAYS:
                return f"Error: days must be between 1 and {_MAX_DAYS}"
            if not 0 <= int(minutes_before) <= 600:
                return "Error: minutes_before must be between 0 and 600"
            try:
                tz = ZoneInfo(zone)
            except Exception:
                return f"Error: unknown time zone {zone!r}; use an IANA name such as Europe/Budapest"
            first = datetime.date.fromisoformat(date) if date else datetime.date.today()
            rows = [daylight_for_day(first + datetime.timedelta(days=i), lat, lon, tz, int(minutes_before)) for i in range(int(days))]
            import json
            return json.dumps({"latitude": lat, "longitude": lon, "timezone": zone, "days": rows}, indent=2, ensure_ascii=False)
        except ValueError:
            return "Error: date must be YYYY-MM-DD"
        except Exception as e:
            return f"Error calculating daylight: {str(e)}"

    return app


def _env_float(name: str) -> Optional[float]:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return None
