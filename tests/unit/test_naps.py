"""Unit tests for the nap list in get_sleep (recovery.naps_of)"""
from garmin_workouts_mcp.recovery import naps_of

NAP = {"napTimeSec": 1800, "napStartTimestampGMT": "2026-01-15T09:20:00", "napEndTimestampGMT": "2026-01-15T09:50:00",
       "napFeedback": "LATE_TIMING_IDEAL_DURATION_LOW_NEED", "napSource": 1, "napStartTimeOffset": 60, "napEndTimeOffset": 60}


def test_a_nap_gets_local_clock_times_and_minutes():
    assert naps_of({"dailyNapDTOS": [NAP]}) == [{"start": "10:20", "end": "10:50", "minutes": 30,
                                                 "feedback": "LATE_TIMING_IDEAL_DURATION_LOW_NEED", "source_code": 1}]


def test_no_naps_or_broken_entries_give_an_empty_list():
    assert naps_of({}) == [] and naps_of({"dailyNapDTOS": None}) == [] and naps_of(None) == []
    assert naps_of({"dailyNapDTOS": [{"napTimeSec": 600}]}) == []  # no timestamps: skipped, no crash
