# Garmin Firefighter Coach

A fork of [brunosantos/garmin-workouts-mcp](https://github.com/brunosantos/garmin-workouts-mcp) that adds the read-only recovery/wellness and race-calendar tools the upstream project deliberately leaves out, so a single MCP server (single Garmin auth, single token file) can both **plan** training and **push structured workouts straight to a Garmin watch** — no phone taps needed mid-session.

Built for a firefighter's functional-training and running-race prep: 5-6 running sessions + 1-2 cross-training sessions a week, periodized around real races pulled from the Garmin Connect calendar, and adjusted against real recovery data instead of a fixed template.

This repo documents the *server* (mechanics, API quirks, bug fixes) - it's public and account-agnostic on purpose. Person-specific coaching context (injury history, race results, equipment, HR zones) for the account this was built for lives in a private companion repo instead, kept out of public view; ask the account owner for access if you need it.

## What's different here vs. other Garmin+Claude coach projects

A survey of the existing Garmin+Claude/MCP ecosystem (Claude4Garmin, garmin-coach-mcp, claude-garmin, garmin-skill, claude-trail-running, claude-running-coach) showed a consistent split: projects either expose **broad read access** (activities, HRV, sleep, body battery, training status - sometimes 90+ tools) *or* they expose **workout write access** (upload/schedule structured workouts to the calendar), rarely both in one minimal-scope server. The trade-off is deliberate on the upstream project's side: least-privilege by design.

This fork closes that gap without widening the attack surface or adding a second server/auth flow:

- **`recovery.py`** (new) - training readiness, HRV status, Body Battery, sleep, stress, resting HR, training status, race-time predictions, body weight, Endurance Score, Hill Score, floors climbed, intensity minutes, personal records, hydration, gear (shoe/bike mileage + retirement-threshold tracking), and lifestyle logging (the app's manual Massage Therapy/Illness/Injured/self-care day checklist). Read-only, same `garth` client and `~/.garminconnect` token as everything else - no extra login, no extra scopes beyond what `garminconnect` already grants.
- **`get_calendar_events`** (new) - reads the Garmin Connect **Events** calendar (`calendar-service/events`), which is where manually-entered races live and which no other surveyed project exposes at all. Each event comes back with its `event_id`, date, start time, distance, location, goal time, privacy, URL and note. This is what lets the coach periodize against real race dates/distances/goal times instead of a date typed into a prompt. `create_calendar_event`, `update_calendar_event` and `delete_calendar_event` add, change and remove one event (see below).
- **Workout push stays intact** - `upload_workout(s)` / `schedule_workout(s)` from upstream, covering `running`, `strength_training`, and `cardio` sport types, so a functional-training/cross-training session is scheduled to the watch exactly like a running session.
- **`weather.py`** (new) - `get_weather_forecast`, a non-Garmin tool backed by OpenWeatherMap's free forecast API, flagging ICE_RISK / EXTREME_HEAT / POSSIBLE_STORM_HAIL for the days a week's outdoor sessions are about to be scheduled on. Requires an `OPENWEATHER_API_KEY` env var (see Setup below); everything else in this fork needs no keys beyond the Garmin token.
- **`workout://reference/exercise-catalog`** (new) - the full Garmin exercise `category`/`exerciseName` catalog (33 categories, 1207 names), bundled as data rather than left for the caller to guess. Upstream's own template only demonstrates a handful of categories (SQUAT, LUNGE, PUSH_UP, ROW, PLANK, CALF_RAISE); this resource is the authoritative rest of it, sourced from Garmin's own exercise database export.
- **`routes.py`** (new) - `generate_running_route`: given a start point (coordinates or a free-text address, via the bundled `geocode_address`) and target distance, generates a real-streets loop route via OpenRouteService's free round-trip routing (requires `OPENROUTESERVICE_API_KEY` - Garmin itself has no public route-generation API at all, the official Courses API is business-gated). Then **`create_garmin_course` / `list_garmin_courses` / `delete_garmin_course`** push that route onto the watch as a real, navigable Garmin Course - reverse-engineered from Garmin's undocumented course-service API (no course support exists anywhere in `python-garminconnect`), live-verified end to end (create -> real courseId assigned -> delete -> no residue) against a real account. Same Garmin auth as everything else, no extra login for this half either.
- **`rename_workout` / `update_workout`** (new) - update an existing workout's name or full structure in place via Garmin's workout-service PUT endpoint (reverse-engineered the same way as the course update endpoints), instead of the delete+reupload upstream requires, which churned the `workout_id` and broke any `schedule_workout` calls already pointing at it. Live-verified end to end against a real account.
- **`tracking.py`** (new) - body weight, athlete profile, daily summary, supplement log and a compact multi-day wellness trend, all as small curated output (see "Body, nutrition and supplement tracking" below). Includes `log_body_weight`, which writes a manual weigh-in to Garmin's weight-service, and a local-only supplement log (Garmin has no supplement tracking to build on).

Net effect: one MCP server, one auth step, that can answer "am I recovered enough for the hard session today, what's on my race calendar, will the weather let me run it, here's a route for an unfamiliar location pushed straight to my watch as a navigable course, and here's this week's plan pushed to my watch" - what a human coach would actually check, in one place.

The original repo's own history traces back to [garmin_mcp](https://github.com/Taxuspt/garmin_mcp) by Taxuspt; this fork keeps that lineage (MIT license, see `LICENSE`) and layers the above on top.

### Bug fixes found while using this fork against a real account

- `get_activity_weather` was returning Fahrenheit/mph mislabeled as Celsius/m-per-s (Garmin's weather sub-API always replies in imperial units regardless of account preference). Confirmed via a January activity coming back as "32°C" - actually 32°F, i.e. 0°C. Now converted.
- The workout reference resource had `strength_training` mapped to the wrong `sportTypeId` (4, which actually creates a **swimming** workout - confirmed via live upload + readback). Correct id is 5. Also documents the `reps` end-condition and the `category`/`weightValue`/`weightUnit` fields needed for a real strength-training step, none of which are in Garmin's own public docs (there isn't a public API for this at all - see [n1t3k/garmin-strength-api](https://github.com/n1t3k/garmin-strength-api)).
- `get_calendar_events` was filtering on Garmin's `isRace` flag, which turns out to be inconsistently set (`true` for some registered road races, `false` for an equally-real 100km registered trail ultra on the same calendar). Now filters on the Events feature's own `itemType` instead.
- A physio-prescribed "bird dog" exercise couldn't be set up: there is no `BIRD_DOG` category in Garmin's catalog at all. The real pairing is `category="HIP_STABILITY"`, `exerciseName="QUADRUPED_WITH_LEG_LIFT"` - confirmed directly from Garmin's own exercise database (see `workout://reference/exercise-catalog` above), which also caught two look-alike traps: `QUADRUPED_LEG_RAISE` and `QUADRUPED_ROCKING` sit in different categories (`LEG_RAISE` and `WARM_UP`) despite both being "quadruped" exercises too.
- OpenRouteService's round-trip `length` parameter is only a weak preference, not a target: for a fixed seed, changing the requested length often changed nothing at all (6.0km, 4.5km, and 4.32km requests all returned the identical 8.28km route), and across seeds at a fixed length, actual distance ranged from -2% to +100%+ of target in testing. `generate_running_route` works around this by trying up to 15 seeds internally and returning the closest match rather than trusting length alone.
- `get_sleep` and `get_activity_exercise_sets` were raw passthrough dumps that routinely exceeded 100k-300k characters (per-epoch sleep time series; ~25 always-null barbell-velocity-tracker fields per strength set), blowing past typical MCP tool-result size limits and forcing a fallback to file+grep just to read one day's data. Both now return curated summaries instead - confirmed live: 317,889 → 2,160 characters for a night's sleep, 109,646 → 9,170 for a 92-set strength session.
- `generate_running_route`'s `prefer="hilly"/"flat"` elevation feature had two bugs only visible once live-tested against a real OpenRouteService response: `ascent`/`descent` come back as top-level `properties` fields, not nested under `properties.summary` as first assumed (the code silently fell back to computing them from coordinates every time); and with no distance tolerance, "hilly" would pick whichever of the 15 tried seeds had the most climbing regardless of distance - a 6km request came back as 13.44km once. Fixed both: correct field path, plus a 25% distance-tolerance filter before ranking by elevation.
- `get_activities_by_date`'s `activity_type` filter uses a different vocabulary than the `sportTypeKey` used everywhere else in this server: valid values are `cycling`, `running`, `swimming`, `multi_sport`, `fitness_equipment`, `hiking`, `walking`, `other` - `"strength_training"` (the natural guess, and what's used for workouts) returns HTTP 400. The closest match, `"fitness_equipment"`, is a broader gym-activities bucket that also returns yoga sessions, not a strength-only filter.
- Renaming or restructuring an existing workout required delete + re-upload, which churned the `workout_id` and broke any `schedule_workout` calls already pointing at it. `rename_workout`/`update_workout` now do this in place via Garmin's workout-service PUT endpoint (reverse-engineered the same way as the course update endpoints), live-verified end to end.
- Multi-day mystery, finally solved: `generate_running_route`/`geocode_address` kept returning 403 "Quota exceeded" even right after the OpenRouteService dashboard showed full quota. Turns out `api.openrouteservice.org` was deprecated 2026-04-28 in favor of `api.heigit.org` (unified HeiGIT API domain), and the deprecated host answers every request with that same 403 regardless of actual usage - confirmed by testing both domains side by side with the same key: old host 403, new host 200. Migrated both tools to `api.heigit.org` (new paths: `/openrouteservice/v2/directions/...`, `/pelias/v1/search` - same API key/auth header, no other changes).

### Known failure mode: `CONNECT_TIMEOUT` on startup (fixed - kept here as a diagnosis recipe)

If the MCP client reports the server "connection timed out after 30000ms" and running the exe by hand shows only `Trying to login to Garmin Connect using token data...`, the login is slow, not broken. Debug-log it (`logging.basicConfig(level=logging.DEBUG)` around `Garmin().login('~/.garminconnect')`) and look for a ~50s gap before the first `connectapi.garmin.com` response. Cause found live: an unusable IPv6 route to Cloudflare - the host resolves to 5 AAAA + 5 A records, urllib3 waits out the OS connect timeout on every AAAA address before falling back to IPv4 (51s vs 0.43s IPv4-only). The server now prefers IPv4 (set `GARMIN_MCP_ALLOW_IPV6=1` to opt out), logs in on a background thread so the MCP handshake never waits on Garmin (tool calls wait for the login, or return the real login error), and writes refreshed OAuth2 tokens back to disk.

### Known failure mode: interrupted bulk workout-schedule calls

If a client interrupts a `schedule_workouts` call mid-flight, the server-side work can still complete - leaving real orphaned workouts in the Garmin workout library/calendar - while the client-side interrupt produces a "response for unknown message ID" error that poisons the stdio connection for the rest of that session (it won't recover without a restart). This isn't fixable from this server's side (it's an artifact of interrupting a long-running tool call over stdio), but it's worth knowing: after any interrupted bulk call, check `get_workouts`/`get_scheduled_workouts` for orphans before doing anything else, and expect to need a session restart.

### Calendar, zones and exercise names: things verified live

- **Two calendar views that disagree.** `get_scheduled_workouts` used to read Garmin's GraphQL schedule summary, which is eventually consistent: it can leave out an entry that was just scheduled and keep listing one that was removed long ago (checked live: a removed entry was still listed more than half an hour later). It now reads the real-time calendar (`calendar-service`) and uses the GraphQL data only to add the completed flag, linked activity and training-plan details. Entries only the GraphQL view still knows about are dropped as stale (reported as `ignored_stale_entries`) unless they are training-plan, rest or race entries.
- **Scheduling the same workout twice on a day creates two entries**, it does not overwrite. `schedule_workout` now returns the new `schedule_id` and warns when the same workout is already on that day. `unschedule_workout(schedule_id)` removes just one calendar entry and leaves the workout in the library (`delete_workout` removes the library template and every entry that uses it).
- **Races on the calendar can be added, changed and removed.** `create_calendar_event(name, date, start_time, distance_km, location, goal_time, ...)`, `update_calendar_event(event_id, ...)` and `delete_calendar_event(event_id, confirm)` work on Garmin's Events feature. They were checked live with one throwaway event that was created, given a goal time, deleted and confirmed gone. What that showed: the goal time lives in `eventCustomization.customGoal` (seconds) and is set with a second request after the event exists (`create_calendar_event` does that for you); a `PUT` takes the whole event object back; `PUT` and `DELETE` answer `204`; a deleted id answers `404`; and Garmin refuses a new event that is a year or more ahead (`400`, "Event date must be less than a year in the future"). Safeguards in the tools: new events are always created **private**; the date must be today or later and less than a year ahead; an event with the same name on the same date is reported instead of added twice; **before anything is added the tool looks for a similar name on the same date, on the calendar and in Garmin's catalog of organiser-published events** (organisers often have their race there already, usually under a slightly different name: one real half marathon turned up three times under three different spellings; accents, case, edition numbers and joined or split words ("Capital Air"/"Capitalair") do not matter, and two names with clearly different distances are not treated as the same event) and, if it finds one, adds nothing and returns the matches, so the user can add the organiser's event instead (`add_catalog_event_to_calendar`, below); `create_anyway=true` skips that check once the user wants a separate private event; other events on that date come back as a warning; `update_calendar_event` reads the event back and says if Garmin did not keep a field; `delete_calendar_event` only shows the event until it is called again with `confirm=true`, so ask the user first. Privacy of existing events cannot be changed through the tools (events added from Garmin's own event list are usually public in the app). Goal times are written as `h:mm:ss`, or `h:mm` for hours and minutes. `is_race=true` sets Garmin's `race` flag, the one the calendar uses to show an event as a race: a `PUT` with `race: true` on a private event is accepted, changes nothing else and the event stays private (checked live on a real event; the flag is independent of who can see the event). `get_calendar_events` reports it as `is_race`. The time zone defaults to the one the existing events use (Garmin names the Central European zone `Europe/Paris`).
- **Races are often already there: search Garmin's organiser catalog first.** The Garmin Connect app and website have a race search ("Verseny keresése" / "search for an event"), exposed here as `search_event_catalog`: words in the name or place, dates, distance range (`min_km` / `max_km`), a radius around a place (`latitude` / `longitude` / `within_km`), event type (the app's list: `running`, `trail_running`, `cycling`, `gravel_cycling`, `mountain_biking`, `swimming`, `multi_sport_triathlon`, `multi_sport`, `hiking`, `walking`, `fitness_equipment`, `motorcycling_v2`, `winter_sports`, `other`), provider, and the app's source filter: official ("Hivatalos esemény", `OFFICIAL`), verified source ("Ellenőrzött forrás", `VERIFIED`, for example races published through ahotu) and events added by Garmin Connect users (`NONE`; the default is official + verified, as in the app). It calls the same `race-search/events` service the app uses (`verifiedStatuses`, `completionTargetMinValue` / `completionTargetMaxValue` in metres together with `completionTargetDurationType=distance`, `poiLat` / `poiLon` / `withinMeters`, `eventsProviders`, `limit` up to 200); a race that offers several distances comes back as one row per distance, and `calendar-service/race-events/providers` lists the providers. `add_catalog_event_to_calendar(catalog_uuid)` is the app's "add to calendar": `POST calendar-service/event/{uuid}/subscription` with the race's UUID (the numeric id answers `404`; checked live, `201`). The organiser's entry then sits on the calendar with the race flag and counts as one more follower, so such an event is public by nature. It is addressed by its UUID: the goal time is set with `PUT calendar-service/event/{uuid}/customization` (checked live, `204`), while `GET`/`PUT`/`DELETE` on the numeric event id answer `404`. So `update_calendar_event` only changes the goal time of such a race, and `delete_calendar_event` removes it with `DELETE calendar-service/event/{uuid}/subscription`, a call taken from the Garmin web app's own code. The whole round trip was checked live through the tools with a race that had two followers: added with a goal time, goal time changed, a rename refused, goal time cleared, removed again; the calendar and the follower count were back to what they were before. `create_calendar_event` checks the catalog through `calendar-service/events/discover`, which also lists the entries added by users and the follower counts.
- **PacePro plans: `get_pacepro_plans`, `create_pacepro_plan`, `send_pacepro_plan_to_watch`, `delete_pacepro_plan`.** PacePro is Garmin's race pacing plan (a goal time for a distance with a target pace for every kilometre or mile split, which the watch follows). The plans live in `course-service/pacebands` (`GET` list, `POST` create, `GET`/`PUT`/`DELETE` by id, `POST .../{id}/device/{deviceId}` to send one to a watch). The body of a new plan was learned from the server's own validation messages, sent deliberately invalid bodies that cannot create anything: `paceBandSummary` needs `name`, `goalTime` (seconds), `goalSpeed` (m/s), `splitType` (`DISTANCE_KILOMETER`, `DISTANCE_MILE` or `ELEVATION`) and `totalDistance` (metres); `paceBandSplits` needs at least one split with `splitDistance`, `splitAvgSpeed`, `cumulativeDistanceFromStart` and `cumulativeTimeFromStart`. The Garmin website computes the split paces in the browser and the server stores whatever it is sent, so `create_pacepro_plan` computes them itself for a flat distance (5k, 10k, half, marathon or any distance from 1.5 to 241.5 km): even pace, or a negative or positive split where the second half is up to 10 % faster or slower and the times still add up to the goal time. Plans for a course with hills are not computed (Garmin's elevation algorithm is not reproduced). Without `save=true` the tool only shows the plan; a plan with the same name is never created twice; `delete_pacepro_plan` needs `confirm=true`. Checked live: the tool's real request body, sent with one required field removed, made the server complain about that field only, and then an even-pace plan (10 km, 50:00) was saved and read back unchanged; the Garmin Connect app showed it correctly (name, distance, goal time, target pace, per-kilometre splits, and the pacing strategy slider in the middle, with "positive" on its left end and "negative" on its right end). A negative-split plan (5:03/km for the first half, 4:57/km for the second) is stored as manually edited (`manualPaceEdit: true`, `pacingStrategy` 0): it was also saved, read back unchanged and shown by the app with exactly those splits and a stepped pace chart (slowest 5:03, fastest 4:57). The app then shows an "edit" link in place of the strategy slider and warns that editing the strategy there removes earlier changes to the splits, so such a plan is a fixed list of splits, not a strategy Garmin recomputes. Both test plans were deleted again with `delete_pacepro_plan` and the plan list was empty afterwards. If Garmin refuses a body, its message comes back and nothing is stored.
- **Garmin's official Personal API (experimental, read-only, not used by any tool yet).** Since October 2026 Garmin lets anyone create a personal API key on the Garmin Connect website (the key is shown once and expires after 30 days to a year) and read their own data through `https://personal.connectapi.garmin.com`: 26 `GET` endpoints with the same service paths as the unofficial route (activities and FIT files, sleep, HRV, hydration, steps, stress, weight and weight goal, body battery, daily heart rate and summaries, heart-rate zones, fitness age, food log, menstrual cycle). It is pull-only, so any date range can be asked for on demand; there is no write endpoint at all, and calendar events, PacePro, workouts, gear, training status and race predictions are not in it. The key is exchanged for an OAuth2 access token that lives 24 hours (no refresh token; ask again with the key). Garmin's supplementary terms say the key is personal, may only be used with applications you built or run for your own use, must not be shared with anyone, and that Garmin may limit and change request limits at any time and suspend access. `personal_api.py` is a small client (key from `GARMIN_PERSONAL_API_KEY` or `~/.garmin-coach/personal_api_key.txt`; the key and token are never printed or put into an error message) and `scripts/check_personal_api.py` compares the official answers with the unofficial route for one day, about a dozen requests each side. Garmin also publishes its own Python client for this API ([garmin/connect-personal-api-python](https://github.com/garmin/connect-personal-api-python), Apache-2.0, `gc-personal` command line and library): it expects the token to be a JWT with an `exp` claim, caches it and renews it when less than an hour is left, does not retry a `401`, and returns activity downloads as a ZIP file; the helper here is a smaller read-only version written from the public documentation.
- **Watch alarms: `get_watch_alarms`, `set_watch_alarm`, `delete_watch_alarm`, and `get_daylight` for sunrise-based times.** A watch's alarms are part of its device settings (`GET`/`PUT device-service/deviceservice/device-info/settings/{deviceId}`; the official Personal API has no such endpoint). The `PUT` takes the whole settings object, so every write here saves the settings to `~/.garmin-coach/backups` first, reads them back, and writes the saved copy back if anything other than the one intended alarm changed. Checked live on a fenix 7 with throwaway alarms that were added, read back and removed again (the settings equalled the backup afterwards): a new alarm goes in with `alarmId` null and `changeState` `NEW` and Garmin assigns the id; `alarmSound` accepts `VIBRATION`, `TONE` and `TONE_AND_VIBRATION` and refuses anything else as a whole; `alarmMessage` and `backlight` are kept; `alarmMode` accepted `ON`, `OFF`, `ONCE`, `DAILY` and `WEEKDAYS`; every day name tried for a recurring alarm was dropped (stored as an empty list), so the tool only creates one-time alarms (`alarmDays` `["ONCE"]`), which ring the next time the clock shows that time, so set them the evening before. Not known yet: that `alarmTime` is minutes after midnight (the one alarm in the settings, 370, would be 06:10) has to be confirmed on the watch, and an alarm that was set only on the watch itself did not show up in the settings list at all, so what rings and what the API lists can differ. **That second point turned out to matter:** the watch the tests were run on holds three alarms (two of them recurring), the settings object holds one, and none of its 135 fields, with or without the `mergeDefault` parameters, carries the recurring ones, so they exist only on the watch. The Garmin Connect phone app shows no alarm page at all for this watch, so nothing in the app can confirm what the API lists, and it was never verified that an alarm set through the API reaches the watch. A settings write may make the watch replace its own alarms with Connect's list at the next sync; that is not ruled out, and the backup and read-back checks only protect what the API lists. **`set_watch_alarm` and `delete_watch_alarm` are therefore switched off unless the server environment has `GARMIN_WATCH_ALARM_WRITES=1`**, which should only be set by someone who knows this; `get_watch_alarms` and `get_daylight` are not affected. The tool never changes an alarm that the settings list. `get_daylight` calculates sunrise, sunset and civil twilight for a place and days (NOAA formulas, no network, local time with daylight saving; compared with the `astral` library for five places and seven dates: at most two minutes apart, usually within one) and the time `minutes_before` sunrise to wake up. It needs latitude, longitude and an IANA time zone, as arguments or from `GARMIN_COACH_LATITUDE`, `GARMIN_COACH_LONGITUDE` and `GARMIN_COACH_TIMEZONE`; `tzdata` is a dependency on Windows.
- **Heart-rate zone drift.** `get_activity_hr_in_timezones` returns each zone's `zoneLowBoundary` as it was for *that activity*, so comparing runs shows when Garmin moved your zones (for instance after a lactate-threshold update). A workout step that targets a zone *number* silently follows the new boundaries; a step with explicit bpm values does not. `get_athlete_profile` returns the zones currently in force.
- **Exercise names in the app depend on the app language.** Observed in the Hungarian app (the step description is shown under the name, so put the name you want in the description): `FLYE` -> "Tárogatás"; `SHRUG` / `SCAPULAR_RETRACTION` -> "Emelés és kitartás V-alakban" (misleading); `LATERAL_RAISE` / `SEATED_REAR_LATERAL_RAISE` -> "Oldalemelés ülő pozícióban"; `ROW` / `FACE_PULL` -> "Archoz húzás"; `SHOULDER_STABILITY` / `BAND_EXTERNAL_ROTATION` -> "Kifelé forgatás gumiszalaggal". A `FLYE` step without `exerciseName` is what the Hungarian app shows as "Tárogatás".
- **Which muscles did the strength workouts train?** Since Garmin exposes no muscle map, `get_muscle_work(start_date, end_date, activity_id)` works it out from the raw exercise sets: it drops the phantom sets, maps each exercise to muscle groups with its own category-based mapping (with name-based exceptions, compared once against Garmin's own map for the same workout) and reports, for 15 muscle groups, a status like Garmin's map (`worked` = at least one set with the muscle as a primary mover, `assisted` = secondary muscle only, `not worked`), weighted sets (primary 1.0, secondary 0.5), reps, tonnage, last-worked date and the flagged sets, next to Garmin's own totals. `render_muscle_map` draws the same result as a front and back body figure (male or female drawing, `body` = auto uses the sex in the Garmin profile; hair shown from both sides) in the same three states (primary red, secondary yellow, not targeted grey) with the numbers listed underneath, as an SVG file in the local data directory; the colours follow the viewer's light or dark setting (`theme` = auto, light or dark) and every muscle has a hover title. The mapping is an estimate from exercise names, not Garmin's muscle map. The anatomical shapes in `data/body_parts.json` come from [react-native-body-highlighter](https://github.com/HichamELBSI/react-native-body-highlighter) (MIT, copyright 2022 ELABBASSI Hicham; the licence text and a provenance note are in `data/BODY_PARTS_NOTICE.txt`).
- **Strength-activity totals are inflated by phantom sets, and there is no muscle map in the API.** In a recorded strength activity the watch also detects movement during the rests and stores it as extra ACTIVE sets (category `UNKNOWN`, rest-length duration, a handful of reps), and now and then it labels one as a real exercise (for example a 3-rep `SQUAT` between two sets of another exercise, 45 s long). `summaryDTO.activeSets` counts every ACTIVE row, so in one checked activity Garmin reported 42 active sets while only 21 were real; its `totalExerciseReps` (190) did not match any simple sum of the set list (all active rows 275, known exercises 227, without the phantom squats 220), so how it is composed is unknown. `get_activity_exercise_sets` only returns the raw rows (category, name, reps, weight in grams, duration) with no muscle fields, and the muscle-map / muscle-load endpoints we tried through the API host all returned 404 (the app probably computes the map itself). `OPTIONS` on the exercise-sets endpoint lists `PUT`, so editing sets is likely possible, but it has not been tried and this server does not do it.
- **Dropped connections.** Garmin occasionally drops a connection (`RemoteDisconnected`, seen right after a restart). Read-only client calls (`get_*`, `count_*`, `download_*`) are retried once automatically; writes never are, because a retried upload or schedule could create a duplicate.

### Food diary: MyFitnessPal (optional)

Garmin has no free food log, but it can show calories eaten if a diary app feeds it. MyFitnessPal is the one with a working link to Garmin Connect (the others tried, Cronometer, Lose It! and MyNetDiary, only pull Garmin activity *into* their own app). Garmin's own Connect+ Nutrition log is a paid subscription; reportedly, opening it disconnects an existing MyFitnessPal link.

1. **Calories into Garmin (no code needed).** Link your MyFitnessPal account in Garmin Connect (in the app's settings, under connected apps) and log food in MyFitnessPal. `get_daily_summary` then shows `consumed_kcal` and `intake_source_connected: true` (verified live: one logged item arrived within hours). Only the total calories reach Garmin, no macros.
2. **Meals and macros (optional, separate server).** MyFitnessPal has no public API for individuals (its partner API is closed to new applicants), so reading the diary means reverse-engineering the website with a logged-in browser session cookie. The community project [myfitnesspal-mcp](https://github.com/Mason-Levyy/myfitnesspal-mcp) does that, and [mfp-readonly-mcp](https://github.com/akosjuhaszme/mfp-readonly-mcp) is a fork of it with every write/delete tool removed (the default branch is `readonly`); both are unofficial and can break whenever the site changes. A free account's diary exposes, per food entry and per day, calories, protein, carbs, fat, sodium and sugar, plus the day's goals; fibre, saturated fat, cholesterol and vitamins were not in the data. With "Exercise Calories" on, the day's goal is the base goal plus calories burned in synced exercise.
3. **Treat the cookie like a password.** The `__Secure-next-auth.session-token` cookie gives full access to the account (it can log and delete entries) and lasts about 30 days. Enter it only at a hidden prompt on your own machine, never in a chat, an issue or a file in a repo. The upstream server has no read-only mode (7 of its 18 tools write or delete diary data), so the read-only fork is the safer thing to hand to an assistant.
5. **Run both servers side by side.** Register this server and the read-only MyFitnessPal one in the same MCP config, for example:

   ```json
   {
     "mcpServers": {
       "garmin-workouts": { "command": "C:\path\to\garmin-workouts-mcp\.venv\Scripts\garmin-workouts-mcp.exe", "args": [] },
       "mfp-readonly":    { "command": "C:\path\to\mfp-readonly-mcp\.venv\Scripts\myfitnesspal-mcp.exe", "args": [] }
     }
   }
   ```

   With the two accounts linked, data flows both ways (checked on a real account): calories eaten, and a weight logged in MyFitnessPal, reach Garmin (`consumed_kcal` in `get_daily_summary`; the weigh-in is tagged with the source `MFP`); synced Garmin workouts appear in MyFitnessPal's exercise diary and, with "Exercise Calories" on, raise that day's calorie goal. Not everything is synced: **water logged in MyFitnessPal does not reach Garmin's hydration tracker** (checked live: 1000 ml in MyFitnessPal, empty intake in Garmin), so hydration has to be logged in Garmin (`log_hydration`) or mirrored by hand. Garmin's `net_goal_kcal` followed the MyFitnessPal calorie goal when that was changed. Garmin's hydration base goal is a user setting and can change from one day to the next, so read `base_goal_ml` instead of assuming a value.

4. **Sharing the diary publicly does not help.** Making the diary Public or "Locked with a key" does not give scripts access: anonymous requests get a bot-protection challenge (HTTP 403, verified live), and a public diary would only expose your food log. Keep it Private.

### Setup for the weather and route tools

```
$env:OPENWEATHER_API_KEY = "your-key-here"        # PowerShell, current session only
$env:OPENROUTESERVICE_API_KEY = "your-key-here"   # PowerShell, current session only
```

Free keys: [openweathermap.org/api](https://openweathermap.org/api) (5-day/3-hour forecast endpoint, free tier, no card) and [openrouteservice.org/dev](https://openrouteservice.org/dev/#/signup) (Directions API, free tier, no card). For either to persist across restarts, add it to the `env` block of this server's entry in your MCP client config instead of setting it ad hoc each session.

### Body, nutrition and supplement tracking

All of these return small, curated JSON (Garmin's raw weigh-in, sleep and daily-summary payloads are large and mostly null). They are record-keeping and trend tools, **not medical advice** - questions about supplements, deficiencies or health conditions belong with a doctor / lab test, and the tool descriptions say so.

| Tool | What it does |
|---|---|
| `get_body_weight` | Per-day weight in kg, change vs the previous weigh-in, and a summary: latest value, 3-week moving average, weekly change (least-squares slope over 28 days, negative = losing), days since the last weigh-in. Body fat / water / muscle / bone / BMI appear only when the weigh-in has them (a manual one has none). Replaces the earlier raw passthrough (grams, a dozen null fields). |
| `log_body_weight` / `delete_body_weight_entry` | Write / undo a manual weigh-in via the weight-service upload. Guards against typos: rejects values outside 30-300 kg, future timestamps and a jump of more than 5 kg versus the previous weigh-in unless `force=True`. The result includes the `sample_pk` needed for deletion. |
| `get_athlete_profile` | Birth date and computed age, gender, height, profile weight, VO2max, max HR, lactate-threshold HR and speed, and the HR-zone boundaries Garmin currently uses (zone floors/ceilings in bpm, plus whether they are LACTATE_THRESHOLD- or %max-based), and the goals currently in force with their source: weight goal in kg (and kilograms to go), calorie goal (`MYFITNESSPAL` when pushed by a linked MyFitnessPal), hydration base goal (`MANUAL` or auto) and steps goal. Read-only. |
| `get_daily_summary` | Calories (total / active / BMR, consumed and remaining), steps, floors, intensity minutes, hydration (intake, goal, base goal, sweat-loss estimate, remaining). Fields that really are empty are listed under `not_available` instead of being silently dropped. |
| `log_hydration` | Add (or, with a negative amount, subtract) water intake in Garmin's hydration tracker; 1-2000 ml per call, never below zero. Garmin's daily goal is a base goal plus a sweat-loss estimate summed from the day's activities (`waterEstimated`, verified: the daily `sweatLossInML` equals that sum), so a hard workout raises the goal; `get_wellness_trend` shows the per-day estimate as `sweat_est_ml`. |
| `log_supplement` / `list_supplements` / `delete_supplement_entry` | Local supplement log: name, dose, unit, time, note. |
| `set_supplement_plan` / `get_supplement_adherence` | Local plan (dose, times/day, days/week) and daily/weekly adherence against it, including the exact missed days for daily plans. |
| `get_cycle_info` | Optional, read-only: menstrual-cycle tracking from Garmin Connect (cycle day / phase and similar fields when present, recent cycle summaries, dates with logged symptoms or ovulation, no free text). Sensitive data: only for users who ask for cycle-aware planning, never in the default trend. Checked against an account without cycle tracking (empty results handled); the layout of a filled-in cycle has not been seen, so fields are passed through as found and the obvious ones are lifted into `highlights`. A planning input only, not medical advice: the evidence for strict phase-based training is mixed, so symptoms, sleep and recovery decide. |
| `get_wellness_trend` | One compact row per day for N days (1-42): weight, sleep score/hours, HRV + status, resting HR, Body Battery change, training load and workout count, Lifestyle Logging flags (e.g. illness, massage) and quantities (e.g. caffeine), and logged supplements, plus window averages. Uses Garmin's range endpoints (one call each for sleep, resting HR, weight and activities) and one lifestyle call per day, in parallel. |

**What Garmin does not provide** (verified against a real account):

- **Consumed calories and macros.** On an account with nothing feeding it, `consumedKilocalories` stays empty (and `includesCalorieConsumedData` is false). Two things can feed it: a calorie-intake service linked to Garmin Connect (MyFitnessPal is the one with a documented two-way link; Cronometer, Lose It! and MyNetDiary only pull Garmin activity *into* their own app and do not send food calories back), or Garmin's own **Connect+ Nutrition** log (paid subscription, launched 2026). Whether Connect+ Nutrition entries populate `consumedKilocalories` has not been verified here, and no macro fields are read by this server. `get_daily_summary` reports the empty case explicitly.
- **Supplement / vitamin tracking.** The Lifestyle Logging habit catalogue (lifestyle, self-care, treatments, sleep-related, life status, custom) contains no vitamin or supplement habit, there is no catalogue endpoint, and the write endpoint is undocumented. Supplements are therefore stored **locally** in `~/.garmin-coach/` (`supplements.jsonl`, `supplement_plan.json`; override with `GARMIN_COACH_DATA_DIR`). Nothing is uploaded to Garmin, and the directory is git-ignored. Habits you track in the Garmin app (including, untested, ones you add under "Custom") are read by `get_lifestyle_logging` and flow into `get_wellness_trend`.
- **Lactate-threshold pace.** Garmin returns a raw speed number whose unit is undocumented. `get_athlete_profile` returns the raw value plus a clearly labelled *unverified* pace estimate (assuming raw x 10 = m/s) - check it against the Garmin app before relying on it.

`log_body_weight` was live-verified end to end (upload -> read back -> delete -> read back: gone), and every tool above was exercised against a real account.

Garmin's API is accessed via the [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library and also the garth 

## Features

- List recent activities with pagination support
- Get detailed activity information
- Access workouts and training plans
- Browse workout templates

## Usage Examples

Once connected in Claude Desktop/VS Code Copilot, you can ask questions like:

### Basic queries:
- "Show me the details of my latest run"
- "Create a workout plan for next week based on my recent activities"
- "When is my next scheduled workout?"
- "Create a workout plan with 30min easy run at conversational pace"
- "Create a workout plan with 5km tempo run at 5:15 min/km pace"
- "Create a workout plan with intervals: 6×400 m @ 4:10–4:20/km, 90s recovery (include 15 min warm-up/cool-down)"

### AI Coach assisted queries:
- "What are some workout templates I can use to improve my 5k time?"
- "Based on my recent activities, what workouts should I do this week to prepare for a half marathon?"
- "Create a workout plan for the next Hackney Half Marathon based on my recent activities, with a goal to run it in under 1h45."
- "Upload a structured 45-minute threshold run workout and schedule it for next Tuesday"
- "Look at my last 4 weeks of running and tell me if I'm overtraining or ready to increase mileage"
- "How much time did I spend in each heart rate zone during my run last Sunday?"
- "Compare my pace and HR across my last 5 runs — am I getting fitter?"
- "I have a race in 6 weeks — build me a progressive weekly workout schedule and add each session to my calendar"

### Ready-made prompts and a first-run routine

The server ships twelve coaching prompts as MCP prompts (clients that support them list them by name; Claude Code shows them as slash commands such as `/mcp__garmin-workouts__first_run_setup`). Start with **`first_run_setup`** after installing: it checks the connections, reads your history, asks only what Garmin cannot know and proposes a first week, without writing anything before you confirm. The others: `plan_training_week`, `weekly_review`, `recovery_check`, `nutrition_check`, `race_prep`, `progression_rules`, `strength_session`, `weak_points`, plus a fitness-assessment pair that can be run at any time: `fitness_assessment_menu` (asks which rulebook to assess your physical fitness against, then runs it; `first_run_setup` offers it as an optional step) and `prepare_for_fitness_test` (asks for the test and its date, then plans backwards from it with mini-tests and a taper). Both are built on a concrete rulebook: `firefighter_fitness_test_hu` (the Hungarian professional firefighter entry fitness test, Cooper minimum plus four chosen exercises, scored against tables, with benchmarks from the USA, UK, Germany, Czechia, Poland and the Netherlands and a source list; the tables and summaries were supplied by the user and are not verified, so check them against the current texts before relying on them). They hold no personal data and always ask for your yes before uploading or scheduling. Full texts, copy-paste versions and a suggested weekly rhythm: [docs/PROMPTS.md](docs/PROMPTS.md), in Hungarian [docs/PROMPTS.hu.md](docs/PROMPTS.hu.md).

### Tool Coverage

This MCP server implements tools for the following domains:

- ✅ **Activity Management** — 13 read-only tools 🏃
  - 📋 `get_activities` — list activities with pagination support (newest first)
  - 📅 `get_activities_by_date` — list activities between two dates, optionally filtered by type
  - 📅 `get_activities_fordate` — list activities recorded on a specific date
  - 🔍 `get_activity` — get detailed information for a single activity
  - 📊 `get_activity_splits` — get lap/split data for an activity
  - 📊 `get_activity_typed_splits` — get typed splits (run/walk/etc.) for an activity
  - 📊 `get_activity_split_summaries` — get split summary statistics for an activity
  - 🌤️ `get_activity_weather` — get weather conditions recorded during an activity
  - ❤️ `get_activity_hr_in_timezones` — get heart rate distribution across HR zones for an activity
  - 👟 `get_activity_gear` — get gear (shoes, bike, etc.) used for an activity
  - 🏋️ `get_activity_exercise_sets` — get exercise sets for strength training activities
  - 🏷️ `get_activity_types` — list all activity types supported by Garmin Connect
  - 🔢 `count_activities` — get the total number of activities in the account

- ✅ **Workouts** — 12 read/write tools 💪
  - 📋 `get_workouts` — list all workouts in the Garmin Connect workout library
  - 🔍 `get_workout_by_id` — get full details for a workout by numeric ID or UUID
  - ⬆️ `upload_workout` — create a new workout from structured JSON data
  - ⬆️ `upload_workouts` — create multiple workouts from structured JSON data in a single call
  - 🗑️ `delete_workout` — permanently delete a workout from the library
  - 🗑️ `delete_workouts` — permanently delete multiple workouts from the library in a single call
  - 📅 `schedule_workout` — schedule a workout to a specific calendar date
  - 📅 `schedule_workouts` — schedule multiple workouts (or upload-and-schedule inline) in a single call
  - 📅 `get_scheduled_workouts` — list workouts scheduled on the calendar between two dates (real-time calendar, each entry has a `schedule_id`)
  - 🧹 `unschedule_workout` — remove one calendar entry by `schedule_id` without deleting the workout from the library
  - 🗓️ `get_training_plan_workouts` — get Garmin Coach / training plan workouts for a given week
  - ⬇️ `download_workout` — download a workout in FIT file format

- ✅ **Calendar events (races)** — 2 read and 4 write tools 🏁
  - 📋 `get_calendar_events` — list the races/events on the calendar with `event_id`, distance, goal time, privacy
  - 🔎 `search_event_catalog` — the app's race search: words, dates, distance range, radius around a place, event type, official / verified / user-created source; read-only
  - 📥 `add_catalog_event_to_calendar` — add an organiser-published race to the calendar (the app's "add to calendar"), optional goal time
  - ➕ `create_calendar_event` — add one event (always private; date check; stops when a similar event is already on the calendar or in the catalog; goal time as `h:mm:ss`; optional `is_race`)
  - ✏️ `update_calendar_event` — change fields of one event, read back to confirm
  - 🗑️ `delete_calendar_event` — delete one event, only after an explicit `confirm=true`

- ✅ **PacePro** — 1 read and 3 write tools 🎯
  - 📋 `get_pacepro_plans` — list the PacePro plans, or one plan with every split
  - ⌚ `send_pacepro_plan_to_watch` — queue a saved plan for the primary watch (the app's own "send to device", `POST course-service/pacebands/{id}/device/{deviceId}`, no body); it arrives at the next sync. Checked live: the plan showed up on a fenix 7 after the sync
  - ➕ `create_pacepro_plan` — plan a flat distance: goal time, km or mile splits, even or negative/positive split; preview first, `save=true` to store
  - 🗑️ `delete_pacepro_plan` — delete one plan, only after an explicit `confirm=true`

- ✅ **Watch alarms and daylight** — 2 read and 2 write tools ⏰
  - 📋 `get_watch_alarms` — the alarms in the watch's Garmin settings (an alarm set only on the watch may not be listed)
  - ➕ `set_watch_alarm` — add ONE new one-time alarm (backup first, read back, restore on any other change); switched off unless `GARMIN_WATCH_ALARM_WRITES=1`, see above
  - 🗑️ `delete_watch_alarm` — remove ONE alarm, only with `confirm=true`; switched off like `set_watch_alarm`
  - 🌅 `get_daylight` — sunrise, sunset, civil twilight and a wake-up time for a place and days (calculated, no network)

- ✅ **Watch over USB (Windows)** — 1 read and 1 write tool 🔌
  - 🔎 `get_watch_usb_state` — read-only: the alarm slots as the watch really holds them (including recurring ones that Garmin Connect's settings never list), the scheduled workouts, workout and PacePro files, newest activity files, free space, and whether a file still waits in `NewFiles`
  - ➕ `set_watch_alarm_usb` — add ONE alarm to the first empty slot (one-time alarms and Monday-to-Saturday were checked on a fenix 7); the watch's own `Settings.fit` is saved first, only that slot's bytes and the CRC change, `confirm=true` is needed, and nothing is written unless the server environment has `GARMIN_WATCH_USB_WRITES=1`
  - How it works: the watch is an MTP device (no drive letter); it is read through the Windows shell (PowerShell). A changed settings file is put into `GARMIN/NewFiles`, which the watch's `GarminDevice.xml` lists as its input folder for settings FIT files, and the watch takes it over when the cable is pulled. Checked live on a fenix 7 (firmware 27.18): a test alarm went in that way, the other alarms stayed unchanged. The new alarm showed up on the watch's own alarm list as a one-time alarm; that it rings is not checked yet. Removing an alarm does not work this way: a file whose slot holds only empty values was taken from `NewFiles` and then ignored, so an alarm added here has to be deleted on the watch itself

- ✅ **Workout Templates** — 5 MCP resources 📂
  - 🏃 `workout://templates/simple-run` — basic warmup / run / cooldown structure
  - ⚡ `workout://templates/interval-running` — interval training with repeat groups (6×400 m)
  - 🎯 `workout://templates/tempo-run` — tempo run targeting a heart rate zone
  - 🏋️ `workout://templates/strength-circuit` — strength training circuit with repeat groups
  - 📖 `workout://reference/structure` — complete JSON structure reference for building workouts

### OAuth Scope Notes

This server uses the [garminconnect](https://github.com/cyberjunky/python-garminconnect) and [garth](https://github.com/matin/garth) libraries for authentication, which relies on Garmin's SSO OAuth tokens. The access token grants access to the Garmin Connect API with read and write permissions. The token scopes are not user-configurable in the auth library (`garth`). For that reason least-privilege access has been applied by design at the MCP Tool level as follows:

- **Activity Management** — read-only operations to list and retrieve activities. No write operations are implemented for activities (e.g. creating, updating, or deleting activities). No access to user profile or other sensitive data like GPS coordinates.
- **Workouts** — read and write operations required (listing, uploading, scheduling, deleting workouts)

## Setup

### Security considerations
> [!NOTE] 
> [Garmin’s official API program](https://developer.garmin.com/gc-developer-program/program-faq/) is available for Enterprise use only and not for individual developers to access. I tried to get access to the official API but was denied because I'm doing this as a Open Source individual project. For that reason I turner to other existing open source libraries. The `garminconnect` library uses reverse-engineered API endpoints and relies on OAuth tokens obtained through the Garmin Connect web/mobile login flow. The `garmin-mcp-auth` tool is a workaround to obtain these tokens for use with the MCP server, but it is not an official or long-term solution.

The Garmin Workouts MCP depends on the [Garmin connect library](https://github.com/cyberjunky/python-garminconnect) and that uses the [Garth library](https://github.com/matin/garth) for authentication, which relies on long lived OAuth tokens.
The Garth library uses Garmin Connect’s mobile-app SSO flow to obtain and persist long-lived (one year) session tokens, which python-garminconnect (API Wrapper) then uses to call Garmin Connect API endpoints.
The `garmin-mcp-auth` tool is a one-time setup utility that prompts you for your Garmin Connect credentials and MFA code (if enabled) to obtain these tokens. The tokens are then saved locally and used by the MCP server for authentication when making API requests to Garmin Connect.

The secret management in this solution can be considered insecure specially the use of long lived OAuth access tokens. We are working on alternatives such as short lived tokens with automatic refresh or integration with external secret managers or keyvaults. In the meantime, you must pre-authenticate to obtain the necessary tokens for the server to function. Use this tool at your own discretion and be aware of the security implications of storing credentials and tokens on your machine. However the scopes of the MCP tools are limited to read-only access for activities and read-write access for workouts, which minimizes potential risks.

#### Prerequisites

- Python 3.12+
- Garmin Connect account
- MFA may be required if enabled on your account

#### Step 1: Pre-authenticate (One-time)
Before adding to Claude Desktop or VS Code Copilot, authenticate once in your terminal:

```bash

# Install and run authentication tool
uvx --python 3.12 --from git+https://github.com/brunosantos/garmin-workouts-mcp garmin-mcp-auth

# You'll be prompted for:
# - Email (or set GARMIN_EMAIL env var)
# - Password (or set GARMIN_PASSWORD env var)
# - MFA code (if enabled on your account)

# OAuth tokens will be saved to ~/.garminconnect
```

You can verify your credentials at any time with
```bash
uv run garmin-mcp-auth --verify
```

**Note:** This will create a local file at `~/.garminconnect` with your Garmin Connect long lived tokens (one year). The MCP server will read from this file to authenticate API requests. These tokens will have a one year lifespan. 


> [!WARNING]  
> Here be dragons 🐉. 
> Long Lived Tokens are a security risk and against OAuth's best practices, but is a limitation of the underlying `garminconnect` library. Use with caution and be aware of the security implications.
> For this reason I've restricted the scope of the MCP server to only the necessary API endpoints (read-only for activities and workout templates, read-write for workouts) to minimize potential risks.
> I'm working on an alternative using short lived tokens with automatic refresh.

### Usage with Claude Desktop
#### Step 2: Configure Claude Desktop

> **Prerequisite:** Complete [Step 1: Pre-authenticate](#step-1-pre-authenticate-one-time) before configuring Claude Desktop.

Add to your Claude Desktop MCP settings **WITHOUT** credentials:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "garmin-workouts": {
      "command": "uvx",
      "args": [
        "--python",
        "3.12",
        "--from",
        "git+https://github.com/brunosantos/garmin-workouts-mcp",
        "garmin-workouts-mcp"
      ]
    }
  }
}
```

**Important:** No `GARMIN_EMAIL` or `GARMIN_PASSWORD` needed in config! The server uses your saved tokens.

#### Step 3: Restart Claude Desktop
Your Garmin data is now available in Claude Desktop !

---

### Usage with VS Code

> **Prerequisite:** Complete [Step 1: Pre-authenticate](#step-1-pre-authenticate-one-time) before configuring VS Code.

For quick installation, use one of the one-click install buttons below:

[![Install with UV in VS Code](https://img.shields.io/badge/VS_Code-UV-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=garmin-workouts&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--python%22%2C%223.12%22%2C%22--from%22%2C%22git%2Bhttps%3A//github.com/brunosantos/garmin-workouts-mcp%22%2C%22garmin-workouts-mcp%22%5D%7D) [![Install with UV in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-UV-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=garmin-workouts&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--python%22%2C%223.12%22%2C%22--from%22%2C%22git%2Bhttps%3A//github.com/brunosantos/garmin_workouts_mcp%22%2C%22garmin-workouts-mcp%22%5D%7D&quality=insiders)

For manual installation, you can configure the MCP server using one of these methods:

**Method 1: User Configuration (Recommended)** Add the configuration to your user-level MCP configuration file. Open the Command Palette (`Ctrl + Shift + P`) and run `MCP: Open User Configuration`. This will open your user `mcp.json` file where you can add the server configuration.

**Method 2: Workspace Configuration** Alternatively, you can add the configuration to a file called `.vscode/mcp.json` in your workspace. This will allow you to share the configuration with others.

> For more details about MCP configuration in VS Code, see the [official VS Code MCP documentation](https://code.visualstudio.com/docs/copilot/customization/mcp-servers).

```json
{
  "servers": {
    "garmin-workouts": {
      "command": "uvx",
      "args": [
        "--python",
        "3.12",
        "--from",
        "git+https://github.com/brunosantos/garmin-workouts-mcp",
        "garmin-workouts-mcp"
      ]
    }
  }
}
```

**Important:** No `GARMIN_EMAIL` or `GARMIN_PASSWORD` needed in config! The server uses your saved tokens from the pre-authentication step.

---

### Development Setup

#### Directly from your local copy of the repository:

1. Add this server configuration:

```
{
  "mcpServers": {
    "garmin-workouts-local": {
      "command": "uv",
      "args": [
        "--directory",
        "<full path to your local repository>/garmin-workouts-mcp",
        "run",
        "garmin-workouts-mcp"
      ]
    }
  }
}
```

## Running the Server

### Testing the server locally with MCP Inspector

The Inspector runs directly through npx without requiring installation. Run from the project root:

```bash
npx @modelcontextprotocol/inspector uv run garmin--workouts-mcp
```

You'll be able to inspect and test the tools.


### The server does not start on Windows ("EUNKNOWN ... uv_spawn", "an application control policy blocked this file")

The `garmin-workouts-mcp.exe` in `.venv\Scripts` is a small launcher that pip generates at install time. It is not signed, and Windows Smart App Control (a Windows 11 feature, on by default on clean installs) can block unsigned programs it has no reputation for, with the message that an application control policy blocked the file. The Windows event log shows it as Code Integrity event 3077 (Event Viewer, Applications and Services Logs, Microsoft, Windows, CodeIntegrity, Operational). The Python interpreter itself is signed and Smart App Control does not restrict the code it runs, so start the server through it instead of through the launcher:

```json
"garmin-workouts": {
  "command": "C:\\path\\to\\garmin-workouts-mcp\\.venv\\Scripts\\python.exe",
  "args": ["-m", "garmin_workouts_mcp"]
}
```

`python -m garmin_workouts_mcp` runs the same entry point as the launcher. Turning Smart App Control off is not recommended: Microsoft documents that it cannot be switched back on without reinstalling Windows.

### Login Issues

If you encounter login issues:

1. Verify your credentials are correct
2. Check if Garmin Connect requires additional verification
3. Ensure the garminconnect package is up to date

## Testing

This project includes comprehensive tests for all MCP tools. **All tests are currently passing (100%)**.

### Running Tests

```bash
# Run all integration tests (default - uses mocked Garmin API)
uv run pytest tests/integration/

# Run tests with verbose output
uv run pytest tests/integration/ -v

# Run a specific test module
uv run pytest tests/integration/test_activity_management_tools.py -v

# Run end-to-end tests (requires real Garmin credentials)
uv run pytest tests/e2e/ -m e2e -v
```

### Test Structure

- **Integration tests** (49 tests): Test all MCP tools using FastMCP integration with mocked Garmin API responses
- **End-to-end tests** (9 tests): Test with real MCP server and Garmin API (requires valid credentials)