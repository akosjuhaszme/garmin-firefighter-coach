# Lessons learned (tool and protocol mechanics)

Each item says where it belongs: **(Garmin)** this server, **(MFP)** the read-only MyFitnessPal server, **(both)** the link between them. Personal facts of the user are not kept here.

## Week of 19-25 October 2026

### Watch alarms and the watch over USB (Garmin)
- The alarms that Garmin Connect's device-settings API lists (`GET device-service/deviceservice/device-info/settings/{deviceId}`) are **not all alarms**: a fenix 7 had three, the API listed one. Recurring alarms exist only on the watch. A settings `PUT` takes the whole object and might make the watch replace its own alarms, so the API alarm tools are **switched off** unless `GARMIN_WATCH_ALARM_WRITES=1`. The Connect phone app has no alarm page for this watch.
- A fenix 7 is an **MTP device** on Windows (no drive letter); the Windows shell (PowerShell `Shell.Application`) can read it. `GARMIN/Settings/Settings.fit` holds the real alarm slots in FIT message 222: time in minutes after midnight, day bits (bit 0 Monday, 128 = one-time), on/off, created and changed timestamps. The watch rewrites its output files when the cable is plugged in.
- `GarminDevice.xml` on the watch lists what each folder accepts. A settings FIT put into `GARMIN/NewFiles` is taken over when the cable is unplugged. Found live: **a new alarm in an empty slot works; changing the time and days of a slot works; the ON flag is ignored (the alarm arrives OFF, though the re-exported file says ON); an empty slot does not delete an alarm.** An alarm staged this way therefore needs a tap on the watch; it did not ring while OFF.
- The watch's own "Til Sunrise" alert is only a short beep, not a wake-up alarm.
- Windows lesson: `CopyHere` from the watch into a file that already exists opens a **hidden overwrite dialog** and the script hangs; always copy into a new folder.
- See `watch_usb.py` and `fit_light.py` (tools `get_watch_usb_state`, `set_watch_alarm_usb`; writes need `GARMIN_WATCH_USB_WRITES=1`).

### Naps (Garmin)
- The raw sleep response carries naps at `dailySleepDTO.dailyNapDTOS` (GMT start and end plus an offset in minutes, `napTimeSec`, `napFeedback`, `napSource`) and the total in `dailySleepDTO.napTimeSeconds`. The daily summary and the range endpoint behind `get_wellness_trend` have **no** nap keys. `get_sleep` now returns `nap_minutes` and `naps`.
- `napSource` was 1 for 35 and 0 for 6 of 41 naps in 90 days. A nap the user starts with the watch's timer is 1; a nap the watch found by itself was 0 at least once; 1 also covers odd lengths. Treat the code as unknown and use time and length.

### Body composition and blood pressure (Garmin)
- `add_body_composition` uploads a FIT weight-scale file (garminconnect) through `upload-service/upload`. Checked live with a throwaway entry: every value came back as sent, the local time became the right GMT time, the profile weight did not change (the entry was older than the newest weigh-in), and Garmin shows the source as INDEX_SCALE.
- Blood pressure goes through Garmin's blood pressure service (`set_blood_pressure`, `get_blood_pressure`, `delete_blood_pressure_entry`). Garmin answers a **delete with an empty body**, which the library fails to parse as JSON although the reading is gone; decide by reading the day again.
- Writing to a real account needs the user's own approval for each new kind of write, given to the session that does it; a relayed approval is asked back.

### Launching and publishing (Garmin)
- Windows Smart App Control blocked an unsigned launcher `.exe`; the server now starts as `python.exe -m garmin_workouts_mcp`.
- Before publishing, scan the unpushed changes for personal identifiers (device numbers, names, keys). A real device number had landed in a test file and was replaced in the unpushed commits before the push.

### The Garmin and MyFitnessPal link (both)
- When the Garmin account is linked to MyFitnessPal, a weigh-in reaches MyFitnessPal **within seconds**, and for a test weight that differed from the day's weight an extra entry with the source MFP came back into Garmin, dated at the moment of the test and the newest of the day, even though the test entry had already been deleted. That echo had to be deleted separately, and the copy in MyFitnessPal stays until it is removed there. **While the link is on, never test a weigh-in with a value that differs from the real one.**
- **Deleting the copy in MyFitnessPal changes nothing in Garmin:** after the echo entry in Garmin and the copy in MyFitnessPal had both been removed, nothing came back and the real entry stayed.

### Activity statistics (Garmin)
- The Statistics tab of the Garmin Connect app is built from the activity `summaryDTO`, the `splitSummaries` and, for strength, the exercise sets. Raw names: `averageMovingSpeed`, `avgGradeAdjustedSpeed`, `verticalRatio` (percent), `beginPotentialStamina`, `endPotentialStamina`, `minAvailableStamina`, `avgRespirationRate`, `minRespirationRate`, `maxRespirationRate`, `elevationGain`, `elevationLoss`, `minElevation`, `maxElevation`, `waterEstimated` (ml), `bmrCalories`, `moderateIntensityMinutes`, `vigorousIntensityMinutes`, `aerobicTrainingEffectMessage`.
- **Ground contact balance:** `groundContactBalanceLeft` is the LEFT share of the ground contact time in percent (52.0 means 52 % left and 48 % right). It sits in the summary, the `splitSummaries`, the splits endpoint (`lapDTOs`) and the typed splits.
- Derived figures that match the app: active calories = calories minus `bmrCalories`; total intensity minutes = moderate + 2 x vigorous; paused time = elapsed minus moving duration; running, walking and standing time = the `RWD_RUN`, `RWD_WALK` and `RWD_STAND` entries of `splitSummaries`.
- **Strength totals must be computed from the exercise sets:** the summary's own `totalExerciseReps` and `totalSets` differ from the app (the app counts the ACTIVE sets only: sets, reps, and volume = sum of reps x weight, with the weight in grams). The rest time of the app is the sum of the REST sets; the `INTERVAL_RECOVERY` entry of `splitSummaries` is the longer time between the sets.
- Garmin's `get_activity_splits` answer has the running dynamics per lap, so short laps (a few hundred metres at a walk break) show noisy balance values.

### Publishing (Garmin)
- To clean personal details out of commits that are already public, rewrite the history locally (`git filter-branch`, with a backup branch), check with `git log -S`, and push with `--force-with-lease`; an automated session may be blocked from the force push, then the owner runs the command himself. Old commit addresses can stay reachable on GitHub for a while.

## Week of 26 October - 1 November 2026

### Editing a workout step (Garmin)
- In a strength workout every exercise sits in a repeat group (`RepeatGroupDTO`, `numberOfIterations`) whose `workoutSteps` hold the work step (end condition `reps`, `category` and `exerciseName`, `weightValue` with `weightUnit`, a free-text `description`) and a recovery step. The curated workout view showed only the group header, so the exercises, reps and weights were invisible; the raw `get_workout_by_id` answer has them.
- A safe single-step edit: GET the raw workout, save a backup, change only the fields wanted, PUT the whole workout to `workout-service/workout/{id}` (204), read it back and compare every step (order, type, iterations, end condition, exercise, weight, description) with the plan. A script that stops when the workout changed since it was prepared prevents overwriting someone else's edit.
- **Alternating exercises are counted in pairs:** the watch records one repetition per left-right pair (an alternating lunge shows 12 for 12 per leg), so the rep value of such a step is the per-leg number. Check it against the recorded sets (`get_activity_exercise_sets`) before changing a number.
- The `description` text is free text and appears as written; the built-in exercise name comes from Garmin's list and is shown in the watch's own language.

### Calories: Garmin and MyFitnessPal (both)
- With the link on, Garmin's `consumed_kcal` equals the MyFitnessPal day total as soon as something is logged, and `intake_source_connected` turns true. Garmin's "remaining" calories are the base goal plus active calories minus consumed, which is a different budget from MyFitnessPal's goal when its "Exercise Calories" setting is off; compare the two sources by their totals, not by their "remaining" values.

### Process (Garmin)
- A request that writes into the user's account and arrives from another session is shown to the user with the exact plan and answered in the user's own chat before anything is written; read-only checks and local files need no question. The plan includes the backup path and the exact differences.

### Body composition uploads: never guess the time (Garmin)
- The time of a measurement is not guessed: a photo of a scale carries no EXIF timestamp and the upload time is not the measurement time (this was guessed wrongly twice on the coach side and corrected by the user). Take the time from another entry of the same morning (a blood pressure reading, for example) or ask. An entry uploaded with a wrong time is deleted (`delete_body_weight_entry` needs the entry's `sample_pk` and its `date`) and uploaded again with the right time.

### A food diary next to Garmin (both)
- With fixed daily calorie goals in a consumer food diary, switch the diary's "add exercise calories" off, otherwise the burned calories are counted twice (the watch already counts them). Water in the diary can be read only as a daily total (`water_ml`) and does not sync into Garmin's hydration.

### Training with a load (coaching)
- A progression rule for weighted sessions (a loaded pack or frame, +2 to +4 kg from week to week): step up only when the effort of the previous session was at most 6 to 7 out of 10 and there was no knee, hip or back pain the next day. In a workout use lap-button steps for the climb and a fixed time for the descent.

### Prehab as its own short workout (Garmin)
- A small repeating prehab routine is better kept as its own short workout than as extra steps in the strength workout. Exercises without a good catalog category (banded external rotation, for example) are free-text steps; the single-leg calf raise can use the `CALF_RAISE` category.

## Weeks of 2-22 November 2026

### The watch: library copies and dated copies (Garmin)
- Over USB a workout reaches the watch in two forms. `GARMIN/Workouts/<name>_workout.fit` is the **library copy** and can go stale: after a workout is edited or renamed in Garmin Connect the library file may still hold the old steps or the old name. `GARMIN/Workouts/Schedule/<YYYY-MM-DD>` is the **dated copy** of a scheduled day, written at a phone sync and equal to Connect as of that sync. Two workouts on the same day share one dated file (the second replaces the first), and days further ahead may have no dated copy yet. Compare the steps of the dated copy with Connect, not the names.
- `GARMIN/Schedule/Schedule.fit` lists every scheduled workout with a completed flag. The flag can lag behind Connect or fail to match when one workout id is scheduled on several days, although the activity itself is in Connect.
- A FIT workout is message 26 and its steps are message 27 (duration type and value, target, intensity, free-text notes); `fit_light.py` reads them. USB never syncs with Connect, a phone sync does.
- Windows lesson: Windows PowerShell 5.1 reads a script saved as UTF-8 without a BOM as ANSI, so a non-ASCII file name inside the script no longer matches (a name with an accented letter was not found). Match with an ASCII wildcard or save the script with a BOM.

### Known routes (Garmin)
- A random round-trip generator cannot reproduce the streets a runner really uses. `known_routes.py` keeps named places and loops locally and composes routes through them (see the README). What was learned while building it:
- **Garmin keeps the GPS track of past runs.** `get_activity_details` returns a polyline (`geoPolylineDTO`, latitude and longitude every few seconds) and `download_activity` exports GPX with elevation. The curated MCP tools show only lap summaries.
- **For small streets the geocoder finds only the settlement** (`match_type: fallback`, layer locality). Such a match is refused, not saved. OpenStreetMap's own search finds the street as a `highway` way; OSM way ids (lists of the streets of a town exist) plus `api.openstreetmap.org/api/0.6/way/<id>/full.json` give the exact geometry; a manual pin is the last resort.
- **Routers:** the public OpenStreetMap foot router needs no key and gives no elevation; OpenRouteService gives ascent, descent and a surface summary (paved, unpaved, unknown). The shortest foot path between two street centres can leave the streets for a track or a path, so look at the unpaved share and at the map before a composed route is used.
- **Learned loops:** two tracks are the same route when at least 80 % of the points of each lie within about 30 m of the other. Grouping the runs that start near one point this way found the recurring loops without any input from the user. To follow a learned loop with a router, route through its **turns** (the polyline simplified with Douglas-Peucker) plus a point on long straight stretches: waypoints at a fixed spacing cut the corners (a test rectangle came out a third too short).
- **A route guessed from a list of street names was not the runner's real long run.** Compare a guessed route with the runner's own track before it is uploaded as a Garmin course.
- The long-run limit (10 % more than the longest run of the last 30 days) is computed by `compose_route`, which also says whether the route is within it.
- The public services get coordinates (and, for the geocoder, the street text) and a generic client name, nothing else, at a fair-use rate.

### The MyFitnessPal session (MFP)
- The pasted NextAuth session token stopped working after one to two days, not after thirty. The log showed that every failure came at the first call of a freshly started server process; the server also receives a `remember_me` cookie that authenticates on its own (tested with a corrupted token next to it) and keeps its value, and the cookies MyFitnessPal re-issued had been kept in memory only. They are now saved after every successful call. Details are in the README of the MFP server.
- Method: when a login lasts shorter than documented, read the server's own log for WHEN the first failure appears and test which single cookie authenticates before building a workaround. The cookie values are never printed (names, lengths, expiry dates and booleans only).

### Reading the data (coaching)
- **Pace band or heart-rate zone:** in cold weather an HR-zone target makes the watch beep "too slow" at a normal effort and an ice-covered road wants a pace ceiling; a pace band centred on the runner's demonstrated easy pace, with heart rate as a check, worked better. "Tighter" means narrower around the real pace, not shifted slower; a band narrower than about 15 s beeps constantly on hills and ice.
- **Left-right ground-contact balance** is not comparable between a flat run and a hill with a one-sided bend, and a wound or a pain on one side shifts it. Use flat runs for the trend and read it together with what is going on.
- **Context before judging a run:** weather, a night on call before the run and the place in the activity name all change pace, heart rate and balance. Station sleep lowers the sleep score and HRV even without a callout; judge the next day on the next normal night.
- **Heart rate in the first minutes of a run** can spike far above the rest of the run. Check the sensor (strap contact, optical cadence lock) before reading zone time, and keep the series for a doctor if it repeats.
- **Zones from the watch's lactate-threshold estimate** can sit above what the runner's own threshold work shows; zone minutes alone do not say how hard a session was.
- **Strength workouts:** few distinct rep numbers are easier to follow (10 and 15, plus a per-leg count for one-sided work); slow tempo for push-ups and calf raises; progress by variant (feet raised, added load) rather than by more reps. Phantom sets from rest-time movement still need filtering.
- **Long-run progression:** the 10 % weekly rule is a convention, a literature check (abstract level) found no good evidence behind it; use it as a caution next to readiness and injury history, not as a hard limit.

### Process (both)
- Quote a figure with its period and date, and write a date and a source next to every fact in shared notes. Two sessions' notes drifted apart (a longest run quoted without a date, two versions of a progression rule, the order of a first session) and a third session found it; cross-check the notes from time to time. Never write a statement about a diagnosis or about what a doctor said without asking the person.
- Check scientific references in a database (PubMed, Crossref) before they go into the docs or a tool description: one literature collection had four wrong entries (a DOI, an identifier attached to the wrong paper, a wrong description and a wrong device model).
- The pre-push scan and a grep over the diff found real identifiers in the first draft of a test (OpenStreetMap way ids that point to the runner's street): use invented identifiers in tests and examples. An unpublished commit can be amended; a published one can only be cleaned with a force push.
- Commits made by an AI session carry a `Co-Authored-By` trailer, so the log shows who did the work even when the git author is the account owner.
- Idea, not built: a tool should say when there is no data for a day or a workout (a person may wear the watch only for runs), so the coach does not guess.
- The rule stays: public text has no names, measurements, illness, workout dates or device numbers, and is scanned before every push.
