"""
Unit tests for the extra statistics in get_activity and get_activity_splits (activity_management.py): the fields of the
Garmin Connect app's Statistics tab that the summary carries, and the strength totals computed from the active sets.
"""
import json

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import activity_management
from garmin_workouts_mcp.activity_management import extra_summary_fields, strength_totals

RUN = {
    "activityId": 1, "activityName": "Run", "activityTypeDTO": {"typeKey": "running"}, "metadataDTO": {},
    "summaryDTO": {"distance": 8123.1, "duration": 3486.4, "movingDuration": 3325.9, "elapsedDuration": 3488.5, "averageMovingSpeed": 2.4423377,
                   "avgGradeAdjustedSpeed": 2.339, "verticalRatio": 9.19, "beginPotentialStamina": 95.0, "endPotentialStamina": 49.0,
                   "minAvailableStamina": 49.0, "avgRespirationRate": 32.91, "minRespirationRate": 19.81, "maxRespirationRate": 37.21,
                   "elevationGain": 45.59, "elevationLoss": 45.7, "minElevation": 175.8, "maxElevation": 206.0, "avgElevation": 192.29,
                   "waterEstimated": 504.0, "calories": 690.0, "bmrCalories": 90.0, "moderateIntensityMinutes": 43,
                   "vigorousIntensityMinutes": 6, "aerobicTrainingEffectMessage": "IMPROVING_AEROBIC_BASE_8"},
    "splitSummaries": [{"splitType": "INTERVAL_ACTIVE", "noOfSplits": 1, "duration": 3256.094, "distance": 8052.31},
                       {"splitType": "RWD_STAND", "noOfSplits": 6, "duration": 60.799, "distance": 9.56},
                       {"splitType": "RWD_WALK", "noOfSplits": 14, "duration": 153.117, "distance": 64.15},
                       {"splitType": "RWD_RUN", "noOfSplits": 8, "duration": 3272.303, "distance": 8049.42}],
}
STRENGTH = {
    "activityId": 2, "activityName": "Strength", "activityTypeDTO": {"typeKey": "strength_training"}, "metadataDTO": {},
    "summaryDTO": {"duration": 2766.3, "movingDuration": 2759.2, "elapsedDuration": 2766.3, "calories": 309.0, "bmrCalories": 71.0,
                   "moderateIntensityMinutes": 1, "vigorousIntensityMinutes": 1, "waterEstimated": 538.0, "totalExerciseReps": 373, "totalSets": 124},
}
SETS = {"exerciseSets": [
    {"setType": "ACTIVE", "repetitionCount": 10, "weight": 20000.0, "duration": 30.0},
    {"setType": "REST", "duration": 60.0},
    {"setType": "ACTIVE", "repetitionCount": 12, "weight": 10000.0, "duration": 60.0},
    {"setType": "REST", "duration": 45.0},
    {"setType": "ACTIVE", "repetitionCount": 15, "weight": None, "duration": 45.0},  # bodyweight
]}


class FakeGarmin:
    def __init__(self):
        self.sets_fail = False

    def get_activity(self, activity_id):
        return RUN if activity_id == 1 else STRENGTH

    def get_activity_exercise_sets(self, activity_id):
        if self.sets_fail:
            raise RuntimeError("boom")
        return SETS

    def get_activity_splits(self, activity_id):
        return {"activityId": activity_id, "lapDTOs": [
            {"lapIndex": 1, "distance": 1000.0, "movingDuration": 330.04, "averageMovingSpeed": 3.0303, "avgGradeAdjustedSpeed": 3.05,
             "maxRunCadence": 176.0, "groundContactTime": 258.6, "verticalOscillation": 7.86, "strideLength": 83.6, "verticalRatio": 9.16,
             "avgRespirationRate": 31.5, "maxRespirationRate": 35.2, "minElevation": 180.2, "maxElevation": 190.4}]}


@pytest.fixture
def fake():
    client = FakeGarmin()
    activity_management.configure(client)
    return client


@pytest.fixture
def app(fake):
    application = FastMCP("Test activity extras")
    activity_management.register_tools(application)
    return application


async def call(app, name, args):
    return json.loads((await app.call_tool(name, args))[0][0].text)


def test_the_summary_fields_match_the_connect_app_numbers():
    f = extra_summary_fields(RUN["summaryDTO"], RUN["splitSummaries"])
    assert f["stamina"] == {"start_percent": 95.0, "end_percent": 49.0, "min_percent": 49.0}
    assert f["respiration_bpm"] == {"avg": 32.9, "min": 19.8, "max": 37.2}
    assert f["elevation"] == {"gain_m": 45.6, "loss_m": 45.7, "min_m": 175.8, "max_m": 206.0, "avg_m": 192.3}
    assert f["estimated_sweat_loss_ml"] == 504.0 and f["active_calories"] == 600 and f["intensity_minutes_total"] == 55  # 43 + 2 x 6
    assert f["run_walk_stand_seconds"] == {"running": 3272, "walking": 153, "standing": 61}  # 54:32, 2:33, 1:01 in the app
    assert f["paused_seconds"] == 162.6 and f["vertical_ratio_percent"] == 9.2 and f["avg_grade_adjusted_speed_mps"] == 2.339
    assert f["split_summaries"][0] == {"type": "INTERVAL_ACTIVE", "count": 1, "seconds": 3256, "distance_m": 8052.3}


def test_missing_data_leaves_the_fields_out():
    f = extra_summary_fields({"calories": 100.0}, None)
    assert f["active_calories"] is None and f["stamina"] is None and f["elevation"] is None and f["split_summaries"] is None
    assert f["intensity_minutes_total"] is None and f["run_walk_stand_seconds"] is None


def test_strength_totals_come_from_the_active_sets():
    assert strength_totals(SETS) == {"sets": 3, "reps": 37, "volume_kg": 320.0, "avg_seconds_per_set": 45, "rest_sets": 2,
                                     "rest_between_sets_seconds": 105}
    assert strength_totals({"exerciseSets": []}) is None and strength_totals(None) is None


@pytest.mark.asyncio
async def test_get_activity_returns_the_extras_for_a_run_and_totals_for_strength(app, fake):
    run = await call(app, "get_activity", {"activity_id": 1})
    assert run["stamina"]["start_percent"] == 95.0 and run["run_walk_stand_seconds"]["running"] == 3272 and "strength_totals" not in run
    strength = await call(app, "get_activity", {"activity_id": 2})
    assert strength["strength_totals"]["reps"] == 37 and strength["active_calories"] == 238 and strength["intensity_minutes_total"] == 3
    assert strength["estimated_sweat_loss_ml"] == 538.0 and strength["paused_seconds"] == 7.1
    fake.sets_fail = True  # the totals are a bonus: a failing sets call must not break the activity
    again = await call(app, "get_activity", {"activity_id": 2})
    assert "strength_totals" not in again and again["calories"] == 309.0


@pytest.mark.asyncio
async def test_each_lap_carries_the_running_dynamics(app):
    lap = (await call(app, "get_activity_splits", {"activity_id": 1}))["laps"][0]
    assert lap["avg_ground_contact_time_ms"] == 258.6 and lap["avg_vertical_oscillation_cm"] == 7.9 and lap["avg_stride_length_cm"] == 83.6
    assert lap["vertical_ratio_percent"] == 9.2 and lap["avg_respiration_bpm"] == 31.5 and lap["max_cadence"] == 176.0
    assert lap["avg_moving_speed_mps"] == 3.03 and lap["min_elevation_m"] == 180.2 and lap["moving_duration_seconds"] == 330.0
