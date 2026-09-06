"""
Workout template resources for Garmin MCP Server

Provides MCP resources with valid workout JSON structures that clients can
read and use as templates for creating custom workouts via upload_workout.
"""
import json
from pathlib import Path

# Full exercise_category -> [exerciseName, ...] catalog (33 categories, 1207
# names), extracted from a "GARMIN CONNECT EXERCICES.xlsx" export of Garmin's
# own exercise database. This is the authoritative source for the strength
# ExecutableStepDTO "category"/"exerciseName" fields - see
# workout://reference/exercise-catalog.
_EXERCISE_CATALOG_PATH = Path(__file__).parent / "data" / "exercise_catalog.json"


def _load_exercise_catalog() -> dict:
    with open(_EXERCISE_CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# WORKOUT TEMPLATES
# =============================================================================

SIMPLE_RUN_TEMPLATE = {
    "workoutName": "Simple Run",
    "description": "Basic run workout: warmup, run, cooldown",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [{
        "segmentOrder": 1,
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSteps": [
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 1,
                "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup"},
                "description": "Warmup 5 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 300.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 2,
                "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                "description": "Run 20 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 1200.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 3,
                "stepType": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
                "description": "Cooldown 5 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 300.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            }
        ]
    }]
}

INTERVAL_RUNNING_TEMPLATE = {
    "workoutName": "Interval Run",
    "description": "Interval workout with repeat groups: warmup, 6x(400m fast + 2min recovery), cooldown",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [{
        "segmentOrder": 1,
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSteps": [
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 1,
                "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup"},
                "description": "Warmup 10 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 600.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            },
            {
                "type": "RepeatGroupDTO",
                "stepOrder": 2,
                "numberOfIterations": 6,
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                        "description": "Fast 400m",
                        "endCondition": {"conditionTypeId": 3, "conditionTypeKey": "distance"},
                        "endConditionValue": 400.0,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
                    },
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 2,
                        "stepType": {"stepTypeId": 4, "stepTypeKey": "recovery"},
                        "description": "Recovery 2 min",
                        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                        "endConditionValue": 120.0,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
                    }
                ]
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 3,
                "stepType": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
                "description": "Cooldown 10 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 600.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            }
        ]
    }]
}

TEMPO_RUN_TEMPLATE = {
    "workoutName": "Tempo Run",
    "description": "Tempo workout: warmup, 20min at tempo pace (HR zone 4), cooldown",
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSegments": [{
        "segmentOrder": 1,
        "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
        "workoutSteps": [
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 1,
                "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup"},
                "description": "Warmup 10 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 600.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 2,
                "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                "description": "Tempo 20 min - HR Zone 4",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 1200.0,
                "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
                "zoneNumber": 4
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 3,
                "stepType": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
                "description": "Cooldown 10 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 600.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            }
        ]
    }]
}

STRENGTH_CIRCUIT_TEMPLATE = {
    "workoutName": "Strength Circuit",
    "description": "Strength training circuit: warmup, 3x circuit (exercise + rest), cooldown",
    "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    "workoutSegments": [{
        "segmentOrder": 1,
        "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
        "workoutSteps": [
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 1,
                "stepType": {"stepTypeId": 1, "stepTypeKey": "warmup"},
                "description": "Warmup 5 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 300.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            },
            {
                "type": "RepeatGroupDTO",
                "stepOrder": 2,
                "numberOfIterations": 3,
                "workoutSteps": [
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 1,
                        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                        "description": "Squat x12 @ 20kg",
                        "category": "SQUAT",
                        "exerciseName": "GOBLET_SQUAT",
                        "weightValue": 20.0,
                        "weightUnit": {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0},
                        "endCondition": {"conditionTypeId": 10, "conditionTypeKey": "reps"},
                        "endConditionValue": 12,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
                    },
                    {
                        "type": "ExecutableStepDTO",
                        "stepOrder": 2,
                        "stepType": {"stepTypeId": 4, "stepTypeKey": "recovery"},
                        "description": "Rest 30 sec",
                        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                        "endConditionValue": 30.0,
                        "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
                    }
                ]
            },
            {
                "type": "ExecutableStepDTO",
                "stepOrder": 3,
                "stepType": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
                "description": "Cooldown stretch 5 min",
                "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                "endConditionValue": 300.0,
                "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
            }
        ]
    }]
}

# Reference documentation for workout structure
WORKOUT_STRUCTURE_REFERENCE = {
    "description": "Reference guide for Garmin workout JSON structure",
    "step_types": {
        "ExecutableStepDTO": "Regular workout step (warmup, interval, cooldown, recovery, rest)",
        "RepeatGroupDTO": "Repeat group containing nested steps with numberOfIterations"
    },
    "stepType_values": {
        "1": {"stepTypeKey": "warmup", "description": "Warmup phase"},
        "2": {"stepTypeKey": "cooldown", "description": "Cooldown phase"},
        "3": {"stepTypeKey": "interval", "description": "Work/effort interval"},
        "4": {"stepTypeKey": "recovery", "description": "Recovery between intervals"},
        "5": {"stepTypeKey": "rest", "description": "Complete rest"}
    },
    "endCondition_values": {
        "1": {"conditionTypeKey": "lap.button", "description": "Manual lap press"},
        "2": {"conditionTypeKey": "time", "description": "Duration in seconds"},
        "3": {"conditionTypeKey": "distance", "description": "Distance in meters"},
        "10": {"conditionTypeKey": "reps", "description": "Rep count (use for strength ExecutableStepDTO steps: endConditionValue = number of reps). Not returned by get_workout_by_id's curated view, but confirmed working on upload - renders in the Garmin app as e.g. 'Cel: N ismetles'."}
    },
    "targetType_values": {
        "1": {"workoutTargetTypeKey": "no.target", "description": "No specific target"},
        "4": {"workoutTargetTypeKey": "heart.rate.zone", "description": "Heart rate zone (use zoneNumber 1-5)"},
        "6": {"workoutTargetTypeKey": "pace.zone", "description": "Pace zone (use zoneNumber)"}
    },
    "sportType_values": {
        "1": {"sportTypeKey": "running"},
        "2": {"sportTypeKey": "cycling"},
        "4": {"sportTypeKey": "swimming", "description": "NOT strength_training - using id 4 with sportTypeKey strength_training silently creates the workout as swimming. This is a SEPARATE enum from get_activity_types' activityType IDs; do not reuse those here (e.g. activityType 13 for strength_training produces sport 'rucking' as a workout sportType, also wrong)."},
        "5": {"sportTypeKey": "strength_training", "description": "Confirmed by live upload + get_workouts round-trip on a real account. cardio's correct sportTypeId is not yet confirmed - do not assume 5 (that's strength_training) or 4 (that's swimming)."},
        "11": {"sportTypeKey": "walking"}
    },
    "strength_step_fields": {
        "category": "String - one of Garmin's 33 real exercise categories (BENCH_PRESS, CALF_RAISE, CARDIO, CARRY, CHOP, CORE, CRUNCH, CURL, DEADLIFT, FLYE, HIP_RAISE, HIP_STABILITY, HIP_SWING, HYPEREXTENSION, LATERAL_RAISE, LEG_CURL, LEG_RAISE, LUNGE, OLYMPIC_LIFT, PLANK, PLYO, PULL_UP, PUSH_UP, ROW, RUN, SHOULDER_PRESS, SHOULDER_STABILITY, SHRUG, SIT_UP, SQUAT, TOTAL_BODY, TRICEPS_EXTENSION, WARM_UP). Optional field on a strength ExecutableStepDTO. Confirmed working - drives the exercise name shown in the Garmin app (e.g. SQUAT -> 'Guggolas'). For the exact valid exerciseName values within each category (1207 total), read workout://reference/exercise-catalog rather than guessing - a plausible-sounding category/name that isn't in Garmin's real catalog fails silently, same failure mode as sportTypeId 4.",
        "exerciseName": "String. Accepted alongside category but NOT confirmed to affect the displayed name - the app showed the generic category-derived name regardless. Possibly requires a specific enum value; treat as unreliable until confirmed.",
        "bird_dog_example": "Worked example of the 'looks obvious but isn't' trap this catalog exists for: 'bird dog' has NO literal BIRD_DOG entry anywhere in Garmin's catalog. The real pairing is category='HIP_STABILITY', exerciseName='QUADRUPED_WITH_LEG_LIFT' (or 'QUADRUPED_HIP_EXTENSION' for the arm-less variant) - confirmed directly from Garmin's own exercise database export (see workout://reference/exercise-catalog's source note), not a third-party guess. Two superficially similar names sit in DIFFERENT categories despite both being 'quadruped' exercises: QUADRUPED_LEG_RAISE is under LEG_RAISE, and QUADRUPED_ROCKING is under WARM_UP - don't assume same-sounding names share a category.",
        "weight": "CONFIRMED (live, via the Garmin app showing 'Suly: 20,0 kg' instead of the bodyweight default, on two separate steps/categories). weightValue (number, plain kg - e.g. 20.0 for 20kg, NOT grams) + weightUnit: {unitId: 8, unitKey: 'kilogram', factor: 1000.0}, both required together - omitting weightUnit, or using the wrong key 'weightDisplayUnit', silently leaves the step at bodyweight default. Source: github.com/n1t3k/garmin-strength-api. Note get_workout_by_id's curated view still strips category/exerciseName/weight from its output even though the fields ARE saved - the app UI is the only way to verify these, not this MCP server's own read tools."
    },
    "coaching_platform_conventions": {
        "_context": "Garmin acquired TrainingPeaks and TrainHeroic in July 2026 - these conventions are worth following since they're likely the direction Garmin's own tooling converges on, not just external inspiration.",
        "one_warmup_one_cooldown": "TrainingPeaks best practice, and already how every template in this file is built: exactly one warmup block as the FIRST step and exactly one cooldown block as the LAST step. Never more than one of each, never in the middle - some devices/platforms handle that incorrectly. (source: help.trainingpeaks.com Structured Workout Builder FAQ)",
        "plain_language_input": "TrainingPeaks' workout generator accepts natural-language descriptions like '20min warmup, 6x3m @ threshold w/ 2min recovery, 10 min cooldown' and builds the structured workout from that. Treat that phrasing style as the expected shorthand a user/coach will describe a workout in when asking for one to be built here.",
        "exercise_vs_circuit_blocks": "TrainHeroic distinguishes Exercise Blocks (a single named movement, sets/reps/load individually tracked - maps to a strength ExecutableStepDTO with 'category' set, e.g. SQUAT) from Circuit Blocks (several movements described in one untracked block, completed as a unit - maps to a plain ExecutableStepDTO with only a free-text 'description', no category). Use 'category' when the step should read back as one specific, trackable exercise; skip it for a generic multi-movement circuit segment."
    }
}


def register_resources(app):
    """Register workout template resources with the MCP server app"""

    @app.resource("workout://templates/simple-run")
    async def get_simple_run_template() -> str:
        """Simple run workout template (warmup, run, cooldown)

        A basic running workout structure suitable for easy runs.
        Modify the endConditionValue to adjust durations.
        """
        return json.dumps(SIMPLE_RUN_TEMPLATE, indent=2)

    @app.resource("workout://templates/interval-running")
    async def get_interval_template() -> str:
        """Interval running workout template with repeat groups

        Demonstrates RepeatGroupDTO for interval training.
        Includes 6x400m intervals with 2min recovery.
        """
        return json.dumps(INTERVAL_RUNNING_TEMPLATE, indent=2)

    @app.resource("workout://templates/tempo-run")
    async def get_tempo_template() -> str:
        """Tempo run workout template with heart rate zone target

        Demonstrates targeting a specific heart rate zone.
        20min tempo block at HR zone 4.
        """
        return json.dumps(TEMPO_RUN_TEMPLATE, indent=2)

    @app.resource("workout://templates/strength-circuit")
    async def get_strength_template() -> str:
        """Strength training circuit template

        Circuit-style strength workout with repeat groups. Uses sportTypeId 5
        (NOT 4 - that silently creates a swimming workout instead), the
        "reps" endCondition (id 10), the "category" field for exercise
        naming (e.g. SQUAT), and weightValue/weightUnit for a per-step
        target weight in kg - see workout://reference/structure for the
        confirmed field details.
        3 rounds of squat x12 @ 20kg + 30s rest.
        """
        return json.dumps(STRENGTH_CIRCUIT_TEMPLATE, indent=2)

    @app.resource("workout://reference/structure")
    async def get_structure_reference() -> str:
        """Reference guide for workout JSON structure

        Documents valid values for step types, conditions, targets, and sports.
        Use this to understand what values are valid in workout definitions.
        """
        return json.dumps(WORKOUT_STRUCTURE_REFERENCE, indent=2)

    @app.resource("workout://reference/exercise-catalog")
    async def get_exercise_catalog() -> str:
        """Full Garmin exercise category/name catalog (33 categories, 1207 names)

        The authoritative source for the strength ExecutableStepDTO "category"
        and "exerciseName" fields - extracted directly from Garmin's own
        exercise database (a "GARMIN CONNECT EXERCICES.xlsx" export), not a
        third-party guess. Structure: {"CATEGORY": ["EXERCISE_NAME", ...], ...}.

        Use this before assuming a common exercise name (e.g. "bird dog",
        which is actually category=HIP_STABILITY, exerciseName=
        QUADRUPED_WITH_LEG_LIFT - Garmin has no literal BIRD_DOG entry)
        doesn't exist - it's usually filed under a less obvious category.
        """
        catalog = _load_exercise_catalog()
        return json.dumps({
            "category_count": len(catalog),
            "exercise_count": sum(len(v) for v in catalog.values()),
            "catalog": catalog,
        }, indent=2)

    return app
