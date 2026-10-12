# Ready-made prompts

Prompts for the coaching workflow: a first-run routine for after installing, a weekly
rhythm, and single-purpose checks. They contain no personal data. They tell the assistant
which tools to use to read your real data (so it does not ask for numbers Garmin already
has), and they require your explicit yes before anything is uploaded, scheduled or deleted.

*This file is generated from `src/garmin_workouts_mcp/prompts.py`
(`python scripts/gen_prompt_docs.py`); a Hungarian version is in
[PROMPTS.hu.md](PROMPTS.hu.md).*

## Getting started after installing

1. Install and authenticate the Garmin server (see Setup in the README) and register it in your
   MCP client. Optional: the food diary (README, "Food diary: MyFitnessPal").
2. Restart the client so the tools and prompts load.
3. Run **`first_run_setup`**. It checks the connections, reads your history, asks only what
   Garmin cannot know (goal, available days, equipment, injuries, constraints) and proposes a
   first week. Nothing is written to Garmin before you confirm.
4. Keep what it learns about you in a **private** place, never in a public repository.

A weekly rhythm that works: `weekly_review` on the last day of the week, then
`plan_training_week` for the next one; `recovery_check` on the mornings you doubt a session;
`nutrition_check` when a food diary is connected; `race_prep` once a race is on the calendar.

## How to run them

- In an MCP client that supports prompts they are listed by name (Claude Code shows them as
  slash commands such as `/mcp__garmin-workouts__first_run_setup`). Prompts with arguments
  ask for them.
- Otherwise paste the text below into the chat and fill the values in.


## `first_run_setup`

Start here after installing: checks the connections, reads the history, asks only what Garmin cannot know, proposes a first week.

Arguments: none

```text
You are setting up a personal training and recovery coach for this user. Work through these steps and report briefly after each one.

1. Connections. Call get_athlete_profile and get_daily_summary. If a 'mfp-readonly' server is connected, also call fitness_get_day. Tell me what works and what is missing, for example: consumed_kcal empty (a food diary is not linked to Garmin), no recent weigh-ins, a MyFitnessPal session notice, an expired login.
2. What Garmin already knows. Summarise the last 8 weeks: get_activities_by_date, weekly distance and sessions, get_personal_records, get_race_predictions, get_training_status, resting heart rate, HRV and sleep (get_wellness_trend), weight trend (get_body_weight), and any races on the calendar (get_calendar_events).
3. What Garmin cannot know. Ask me only these, all at once: my goal and target date, how many days a week I can train and which days are fixed or off, equipment available, injuries or limitations, work or shift constraints, and anything I never want in a plan.
4. Save the context. Propose a short personal-context note (goals, constraints, conventions) and where to keep it. Recommend a private place and warn me not to put it in a public repository.
5. First week. Propose one week as a table (day, session, purpose, intensity as heart-rate zones). Do not upload or schedule anything until I confirm.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `plan_training_week`

Build next week's plan from recent load, recovery, calendar and weather; show it first, schedule only after a yes.

Arguments: `week_start`, `constraints`

```text
Plan my training week starting next Monday. Extra constraints for this week: none.

1. Read what happened: last 4 weeks of activities and load, get_training_readiness, get_hrv_status, sleep and resting heart rate trend, get_scheduled_workouts for the target week, get_calendar_events for races, and get_weather_forecast for the days outdoor sessions are likely.
2. Decide the week's purpose in one sentence (build, hold, deload, return from a break) and justify it from the data.
3. Propose the week as a table: day, session, duration or distance, intensity as heart-rate zones, purpose. Keep at least one full rest day and respect my fixed days. Avoid stacking hard sessions.
4. Flag risks (weather, a hard session close to a race, poor recovery) and what you would change if recovery is worse on the day.
5. Ask for my confirmation. Only then upload and schedule the sessions with upload_workouts and schedule_workouts (short descriptive names, structured heart-rate zone targets, a real warm-up and cool-down on structured runs).

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `weekly_review`

End-of-week review: what worked, what limited progress, what to change next week.

Arguments: `days`

```text
Review my last 7 days as my coach.

1. Data: planned versus completed sessions (get_scheduled_workouts, get_activities_by_date), total load, get_wellness_trend for sleep, HRV, resting heart rate, Body Battery and lifestyle flags (illness, alcohol, travel), get_body_weight for the trend, and, if connected, calories and macros from the food diary against the day's goals.
2. How it felt: ask me one short question about energy and any pain, and use my answers.
3. Verdict: three bullets on what worked, one bullet on the single biggest limiting factor, with the evidence for it. Separate real signals (heart rate high at the same pace, several nights of poor sleep, HRV below baseline) from noise (one odd reading, a sensor artefact).
4. Next week: at most three concrete changes with a measurable target each. Do not schedule anything without my yes.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `recovery_check`

Today's go / modify / rest call from readiness, HRV, sleep, Body Battery and recent load.

Arguments: none

```text
Tell me whether to train as planned today.

Read get_training_readiness, get_hrv_status, last night's sleep (get_sleep), get_body_battery, get_stress, resting heart rate against my baseline, the last three days of load, today's planned session (get_scheduled_workouts) and the lifestyle log for illness or injury (get_lifestyle_logging).

Answer with one of: go as planned, modify (say exactly how: shorter, lower zone, swap for mobility) or rest. Give the two or three data points that decided it. If something looks like illness or an injury, say so plainly and suggest seeing a doctor rather than diagnosing.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `nutrition_check`

Compare food intake with the user's own targets and with training load; reports, does not re-set targets.

Arguments: `days`

```text
Look at my last 7 days of food against my own targets and my training.

Use fitness_get_day or fitness_bulk_export and fitness_get_trends (calories_in, protein, carbs, fat) if the food diary server is connected, and get_daily_summary for calories burned and consumed_kcal. If no food diary is connected, say how to link one and stop.

Report: average intake against my targets, the days that missed by a lot and what training they followed, protein spread across the days, and whether intake before and after hard sessions looks adequate. Use my targets as given. Do not suggest changing them unless I ask. Mention nothing medical; for deficiencies or supplements point to a doctor or a lab test.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `race_prep`

Taper and race-week plan for an event on the Garmin calendar.

Arguments: `event_name`, `goal`

```text
Prepare me for the race: the next race on my calendar (get_calendar_events). My goal: ask me, and compare with get_race_predictions.

1. Find the event, its date, distance and terrain. Check the weather forecast when the date is within range.
2. Judge the goal against my predictions, recent long runs and personal records. Say plainly if it looks realistic, ambitious or out of reach, with the numbers.
3. Propose the remaining weeks as a table: build, taper and race week, with volume and intensity. Include the day-before and race-morning routine, pacing by heart-rate zone and by minutes per kilometre, and fuelling and hydration based on what the data says about my sweat loss (get_hydration).
4. List the logistics I should settle now (gear, route, travel, sleep).
Do not schedule anything until I confirm.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `progression_rules`

Explicit rules for adding load, holding, deloading and returning after a break.

Arguments: none

```text
Write my personal progression rules, based on my real history rather than generic advice.

Look at the last 6 months: weekly volume and how fast it grew, which weeks went well and which ended in illness, pain or poor recovery (use get_wellness_trend and the lifestyle log), and how my heart rate behaves at easy pace.

Produce a one-page rule set: when to add volume or intensity and by how much, when to hold, the signals that trigger a deload (name the metrics and thresholds), how to return after illness or a break, and the one rule you think I am most likely to break. Keep each rule measurable. Offer to save the result in my private notes.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `strength_session`

Design a cross-training or functional strength session that runs on the watch.

Arguments: `equipment`, `focus`, `minutes`

```text
Design a 40-minute strength / functional session. Equipment: ask me. Focus: ask me, or pick from my weak points and running needs.

Read the exercise catalog resource workout://reference/exercise-catalog and the structure reference workout://reference/structure so every step uses a real Garmin category and exercise name. Think about where this fits against my running week (not before a key run) and my recent load.

Show the session as a table (exercise, sets, reps or time, rest, intensity or weight). Warn me about any exercise that the watch will display under a different name. After my yes, upload it as a strength workout (a repeat structure for the sets) and offer to schedule it.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `weak_points`

Find what limits progress (from the data) and choose drills and strength work for it.

Arguments: `focus`

```text
Find what is limiting my progress and build a targeted plan.

Evidence to look at: pace and heart-rate drift in long runs (get_activity_hr_in_timezones, get_activity_splits), cadence and ground-contact trends where available, personal records versus predictions, how often sessions are cut short, strength-session notes, and recurring pain mentions.

Give me the top two limiters with the evidence for each, then for each: two or three specific drills or exercises, how often, how long to try before judging the result, and what measurable change would show it worked. Offer to add the drills into the weekly plan, without scheduling anything until I confirm.

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```
