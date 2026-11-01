"""
Unit tests for update_workout_step (workouts.py): plan_step_change, the preview, the confirmed write with backup and read-back,
and the restore when the read-back differs. A stateful fake of the Garmin client stands in.
"""
import copy
import json
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_workouts_mcp import workouts
from garmin_workouts_mcp.workouts import plan_step_change, workout_fingerprint

KG = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
WORKOUT = {
    "workoutId": 77, "workoutName": "Test body", "description": "5p warm-up, squat 3x10, lunge 2x10kg 3x12/leg, plank 30s",
    "workoutSegments": [{"segmentOrder": 1, "workoutSteps": [
        {"type": "ExecutableStepDTO", "stepOrder": 1, "stepType": {"stepTypeKey": "warmup"}, "endCondition": {"conditionTypeKey": "time"},
         "endConditionValue": 300.0, "description": "Warm-up"},
        {"type": "RepeatGroupDTO", "stepOrder": 2, "stepType": {"stepTypeKey": "repeat"}, "numberOfIterations": 3,
         "endCondition": {"conditionTypeKey": "iterations"}, "endConditionValue": 3.0, "workoutSteps": [
            {"type": "ExecutableStepDTO", "stepOrder": 3, "stepType": {"stepTypeKey": "interval"}, "endCondition": {"conditionTypeKey": "reps"},
             "endConditionValue": 12.0, "category": "LUNGE", "exerciseName": "ALTERNATING_DUMBBELL_LUNGE", "weightValue": 20.0,
             "weightUnit": KG, "description": "Lunge 2x10kg, 12/leg"},
            {"type": "ExecutableStepDTO", "stepOrder": 4, "stepType": {"stepTypeKey": "recovery"}, "endCondition": {"conditionTypeKey": "time"},
             "endConditionValue": 60.0, "description": "Rest"}]},
    ]}],
}


class FakeGarmin:
    def __init__(self):
        self.workout = copy.deepcopy(WORKOUT)
        self.puts = []
        self.status = 204
        self.sabotage = None  # callable(workout) applied after a PUT, to imitate a server that changes more than it should
        self.garth = SimpleNamespace(put=self._put)

    def get_workout_by_id(self, workout_id):
        return copy.deepcopy(self.workout)

    def _put(self, subdomain, url, json=None, api=False):
        self.puts.append((url, copy.deepcopy(json)))
        if self.status in (200, 204):
            self.workout = copy.deepcopy(json)
            if self.sabotage and len(self.puts) == 1:
                self.sabotage(self.workout)
        return SimpleNamespace(status_code=self.status, text="")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    client = FakeGarmin()
    workouts.configure(client)
    monkeypatch.setattr(workouts, "_WORKOUT_BACKUP_DIR", tmp_path / "backups")
    return client


@pytest.fixture
def app(fake):
    application = FastMCP("Test workout step")
    workouts.register_tools(application)
    return application


async def call(app, args):
    text = (await app.call_tool("update_workout_step", args))[0][0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


def test_plan_changes_only_the_named_step_and_keeps_the_original_untouched():
    new = plan_step_change(WORKOUT, 3, {"reps": 6, "description": "Lunge 2x10kg, 6/leg"}, {"old": "3x12/leg", "new": "3x6/leg"})
    before, after = workout_fingerprint(WORKOUT), workout_fingerprint(new)
    assert [i for i, (b, a) in enumerate(zip(before, after)) if b != a] == [2]
    assert after[2]["end_condition_value"] == 6.0 and after[2]["weight"] == 20.0 and after[2]["exercise"] == "ALTERNATING_DUMBBELL_LUNGE"
    assert new["description"].endswith("lunge 2x10kg 3x6/leg, plank 30s") and WORKOUT["description"].count("3x12/leg") == 1
    assert WORKOUT["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]["endConditionValue"] == 12.0


def test_a_repeat_group_count_is_kept_in_both_places_and_weight_changes_keep_the_unit():
    group = plan_step_change(WORKOUT, 2, {"repeat_count": 4})["workoutSegments"][0]["workoutSteps"][1]
    assert group["numberOfIterations"] == 4 and group["endConditionValue"] == 4.0
    step = plan_step_change(WORKOUT, 3, {"weight_kg": 22.5})["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]
    assert step["weightValue"] == 22.5 and step["weightUnit"] == KG


@pytest.mark.parametrize("step_order, changes, fragment", [
    (3, {"sets": 4}, "unknown change"), (3, {}, "nothing to change"), (99, {"reps": 6}, "exactly one step"),
    (1, {"reps": 6}, "repetitions"), (2, {"reps": 6}, "repetitions"), (3, {"repeat_count": 2}, "repeat group"),
    (3, {"reps": 0}, "above 0"), (3, {"reps": True}, "above 0"), (3, {"description": "x" * 513}, "512"),
    (4, {"weight_kg": 10}, "strength step"), (3, {"weight_kg": 900}, "at most"), (2, {"repeat_count": 2.5}, "whole number"),
    (2, {"end_condition_value": 5}, "reps, time or distance"),
])
def test_changes_that_do_not_fit_are_refused(step_order, changes, fragment):
    with pytest.raises(ValueError, match=fragment):
        plan_step_change(WORKOUT, step_order, changes)


def test_the_description_phrase_must_appear_exactly_once():
    with pytest.raises(ValueError, match="exactly once"):
        plan_step_change(WORKOUT, 3, {"reps": 6}, {"old": "no such phrase", "new": "x"})
    with pytest.raises(ValueError, match="exactly once"):
        plan_step_change(WORKOUT, 3, {"reps": 6}, {"old": "3x", "new": "4x"})  # appears twice


@pytest.mark.asyncio
async def test_without_confirm_nothing_is_written_and_the_differences_are_shown(app, fake):
    data = await call(app, {"workout_id": 77, "step_order": 3, "changes": {"reps": 6}})
    assert data["status"] == "confirmation_required" and fake.puts == []
    assert len(data["steps_that_change"]) == 1 and data["steps_that_change"][0]["before"]["end_condition_value"] == 12.0
    assert data["steps_that_change"][0]["after"]["end_condition_value"] == 6.0 and data["steps_compared"] == 4


@pytest.mark.asyncio
async def test_confirmed_edit_saves_a_backup_writes_and_reads_back(app, fake, tmp_path):
    data = await call(app, {"workout_id": 77, "step_order": 3, "changes": {"reps": 6, "description": "Lunge 2x10kg, 6/leg"},
                            "workout_description_replace": {"old": "3x12/leg", "new": "3x6/leg"}, "confirm": True})
    assert data["status"] == "success" and data["read_back_matches_plan"] is True
    assert len(fake.puts) == 1 and fake.puts[0][0] == "workout-service/workout/77"
    saved = json.loads(pathlib_read(data["backup"]))
    assert saved["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]["endConditionValue"] == 12.0  # the backup holds the ORIGINAL
    assert fake.workout["workoutSegments"][0]["workoutSteps"][1]["workoutSteps"][0]["endConditionValue"] == 6.0


def pathlib_read(path):
    import pathlib
    return pathlib.Path(path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_server_that_changes_more_than_planned_gets_the_original_put_back(app, fake):
    def sabotage(workout):
        workout["workoutSegments"][0]["workoutSteps"][0]["endConditionValue"] = 999.0  # another step changed

    fake.sabotage = sabotage
    data = await call(app, {"workout_id": 77, "step_order": 3, "changes": {"reps": 6}, "confirm": True})
    assert data["status"] == "failed_restored" and len(fake.puts) == 2
    assert fake.workout == WORKOUT  # the original is back


@pytest.mark.asyncio
async def test_a_refusal_by_garmin_and_bad_input_change_nothing(app, fake):
    fake.status = 400
    assert (await call(app, {"workout_id": 77, "step_order": 3, "changes": {"reps": 6}, "confirm": True}))["status"] == "failed"
    fake.puts.clear()
    assert "Refusing" in await call(app, {"workout_id": 77, "step_order": 1, "changes": {"reps": 6}, "confirm": True})
    assert fake.puts == []
