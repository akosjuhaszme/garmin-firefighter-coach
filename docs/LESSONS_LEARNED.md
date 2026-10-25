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
