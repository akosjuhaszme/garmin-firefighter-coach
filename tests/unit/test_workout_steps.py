"""Unit tests for the curated workout steps (workouts._curate_workout_step): repeat groups keep their steps, strength steps show exercise and weight."""
from garmin_workouts_mcp.workouts import _curate_workout_step

LUNGE_GROUP = {
    "type": "RepeatGroupDTO", "stepOrder": 5, "stepType": {"stepTypeKey": "repeat"}, "numberOfIterations": 3.0,
    "endCondition": {"conditionTypeKey": "iterations"}, "endConditionValue": 3.0,
    "workoutSteps": [
        {"type": "ExecutableStepDTO", "stepOrder": 6, "stepType": {"stepTypeKey": "interval"}, "endCondition": {"conditionTypeKey": "reps"},
         "endConditionValue": 6.0, "category": "LUNGE", "exerciseName": "ALTERNATING_DUMBBELL_LUNGE", "weightValue": 20.0,
         "weightUnit": {"unitKey": "kilogram"}, "description": "Kitörés 2x10kg, 6/láb"},
        {"type": "ExecutableStepDTO", "stepOrder": 7, "stepType": {"stepTypeKey": "recovery"}, "endCondition": {"conditionTypeKey": "time"},
         "endConditionValue": 60.0, "description": "Pihenés"},
    ],
}


def test_a_repeat_group_keeps_the_steps_inside_it():
    group = _curate_workout_step(LUNGE_GROUP)
    assert group["type"] == "repeat" and group["repeat_count"] == 3.0 and len(group["steps"]) == 2
    work, rest = group["steps"]
    assert work == {"order": 6, "type": "interval", "description": "Kitörés 2x10kg, 6/láb", "end_condition": "reps", "end_condition_value": 6.0,
                    "exercise": {"category": "LUNGE", "name": "ALTERNATING_DUMBBELL_LUNGE"}, "weight": {"value": 20.0, "unit": "kilogram"}}
    assert rest == {"order": 7, "type": "recovery", "description": "Pihenés", "end_condition": "time", "end_condition_value": 60.0}


def test_a_plain_running_step_looks_as_before():
    step = {"stepOrder": 1, "stepType": {"stepTypeKey": "interval"}, "endCondition": {"conditionTypeKey": "distance"}, "endConditionValue": 1000.0,
            "targetType": {"workoutTargetTypeKey": "heart.rate.zone"}, "zoneNumber": 2}
    assert _curate_workout_step(step) == {"order": 1, "type": "interval", "end_condition": "distance", "end_condition_value": 1000.0,
                                          "target_type": "heart.rate.zone", "target_zone": 2}


def test_missing_parts_do_not_break_it():
    assert _curate_workout_step({"stepOrder": 2}) == {"order": 2}
    assert _curate_workout_step({"stepOrder": 3, "stepType": None, "endCondition": None, "weightValue": 5.0}) == {"order": 3, "weight": {"value": 5.0, "unit": None}}
