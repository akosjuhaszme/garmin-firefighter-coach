"""
Compare Garmin's official Personal API with the unofficial route this server normally uses (read-only).

Needs a Personal API key (see src/garmin_workouts_mcp/personal_api.py: environment variable
GARMIN_PERSONAL_API_KEY or a key file) and the usual Garmin login tokens in ~/.garminconnect. About a
dozen GET requests are made on each side. The key and the access token are never printed.

    python scripts/check_personal_api.py            # yesterday
    python scripts/check_personal_api.py --date 2026-10-20
"""
import argparse
import datetime
import socket
import sys

import urllib3.util.connection as _urllib3_connection

from garmin_workouts_mcp.personal_api import PersonalApiClient, PersonalApiError, find_values

_urllib3_connection.allowed_gai_family = lambda: socket.AF_INET  # same IPv4 preference as the server


def _keys(obj, limit=10):
    if isinstance(obj, dict):
        names = sorted(obj)
        return ", ".join(names[:limit]) + (" ..." if len(names) > limit else "")
    if isinstance(obj, list):
        return f"list of {len(obj)}"
    return type(obj).__name__


def _activity_ids(obj):
    rows = obj if isinstance(obj, list) else (obj or {}).get("activityList") or []
    return [row.get("activityId") for row in rows if isinstance(row, dict)]


def _weights(obj):
    return find_values(obj, "weight", limit=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", help="day to compare, YYYY-MM-DD (default yesterday)")
    parser.add_argument("--token-dir", default="~/.garminconnect", help="unofficial login tokens")
    args = parser.parse_args()
    day = args.date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    start = (datetime.date.fromisoformat(day) - datetime.timedelta(days=30)).isoformat()

    official = PersonalApiClient()
    if not official.configured:
        print("No Personal API key found. Set GARMIN_PERSONAL_API_KEY or save the key in the key file.")
        return 2
    print("Personal API key: found (not shown)")
    try:
        official.token()
    except PersonalApiError as e:
        print("Token exchange failed:", e)
        return 1
    print("Access token: obtained (not shown); answer fields:", official.token_shape)

    from garminconnect import Garmin

    unofficial = Garmin()
    unofficial.login(args.token_dir)
    print(f"Unofficial login: ok. Comparing the day {day}\n")

    # (label, official path, official params, unofficial call, fields to compare)
    checks = [
        ("profile settings", "/userprofile-service/userprofile/settings", None,
         lambda: unofficial.garth.connectapi("/userprofile-service/userprofile/settings"),
         ["measurementSystem", "preferredLocale"]),
        ("sleep", "/sleep-service/sleep/dailySleep", {"date": day},
         lambda: unofficial.get_sleep_data(day),
         ["sleepTimeSeconds", "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds"]),
        ("HRV", f"/hrv-service/hrv/{day}", None,
         lambda: unofficial.get_hrv_data(day), ["lastNightAvg", "weeklyAvg", "status"]),
        ("daily summary", "/usersummary-service/usersummary/daily", {"calendarDate": day},
         lambda: unofficial.get_user_summary(day),
         ["totalSteps", "restingHeartRate", "totalKilocalories", "bodyBatteryHighestValue", "bodyBatteryLowestValue"]),
        ("heart rate", "/wellness-service/wellness/dailyHeartRate", {"date": day},
         lambda: unofficial.get_heart_rates(day), ["restingHeartRate", "maxHeartRate", "minHeartRate"]),
        ("hydration", f"/usersummary-service/stats/hydration/daily/{day}/{day}", None,
         lambda: unofficial.get_hydration_data(day), ["valueInML", "goalInML"]),
        ("stress", f"/usersummary-service/stats/stress/daily/{day}/{day}", None,
         lambda: unofficial.get_stress_data(day), ["overallStressLevel", "avgStressLevel"]),
        ("body battery", "/wellness-service/wellness/bodyBattery/reports/daily", {"startDate": day, "endDate": day},
         lambda: unofficial.get_body_battery(day), []),
        ("weight (30 days)", f"/weight-service/weight/range/{start}/{day}", {"includeAll": "true"},
         lambda: unofficial.get_weigh_ins(start, day), ["__weights__"]),
        ("last 5 activities", "/activitylist-service/activities/search/activities", {"start": 0, "limit": 5},
         lambda: unofficial.get_activities(0, 5), ["__activity_ids__"]),
        ("food log (official only)", f"/nutrition-service/food/logs/{day}", None, None, []),
    ]

    same = different = failed = 0
    for label, path, params, unofficial_call, fields in checks:
        print(f"== {label}")
        try:
            status, body = official.get(path, params)
        except Exception as e:  # keep going: one broken endpoint must not hide the others
            print(f"  official:   request failed: {type(e).__name__}")
            failed += 1
            continue
        if status != 200:
            print(f"  official:   HTTP {status} {str(body)[:200]}")
            failed += 1
            continue
        print(f"  official:   HTTP 200, {_keys(body)}")
        if unofficial_call is None:
            continue
        try:
            other = unofficial_call()
        except Exception as e:
            print(f"  unofficial: failed: {type(e).__name__}: {str(e)[:120]}")
            failed += 1
            continue
        print(f"  unofficial: ok, {_keys(other)}")
        for field in fields:
            if field == "__weights__":
                a, b = _weights(body), _weights(other)
                name = "latest weight"
            elif field == "__activity_ids__":
                a, b = _activity_ids(body), _activity_ids(other)
                name = "activity ids"
            else:
                a, b = find_values(body, field), find_values(other, field)
                name = field
            if not a and not b:
                continue
            verdict = "same" if a == b else "DIFFERENT"
            same += verdict == "same"
            different += verdict != "same"
            print(f"  {name}: official={a} | unofficial={b} | {verdict}")
    print(f"\nSummary: {same} fields the same, {different} different, {failed} endpoints failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
