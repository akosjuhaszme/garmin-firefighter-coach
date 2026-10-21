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
4. Optional fitness assessment. Ask me in one line: "Do you want to assess your physical fitness against one of the built-in rulebooks (Hungarian firefighter entry test, USA CPAT, UK Chester test, German, Czech, Polish or Dutch tests, or a home hybrid test)?" If yes, tell me to run the fitness_assessment_menu prompt next; if I have a test date coming up, prepare_for_fitness_test. Both can be run at any time later, not only now. If no, carry on.
5. Save the context. Propose a short personal-context note (goals, constraints, conventions) and where to keep it. Recommend a private place and warn me not to put it in a public repository.
6. First week. Propose one week as a table (day, session, purpose, intensity as heart-rate zones). Do not upload or schedule anything until I confirm.

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

1. Read what happened: last 4 weeks of activities and load, get_training_readiness, get_hrv_status, sleep and resting heart rate trend, get_scheduled_workouts for the target week, get_calendar_events for races, and get_weather_forecast for the days outdoor sessions are likely. Only if I have asked for cycle-aware planning, also call get_cycle_info and use the phase and my own reports of how I feel as one input among the others, never as a rule; ask me how I feel, and suggest a doctor if periods are missing or very irregular.
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

1. Data: planned versus completed sessions (get_scheduled_workouts, get_activities_by_date), total load, get_wellness_trend for sleep, HRV, resting heart rate, Body Battery and lifestyle flags (illness, alcohol, travel), get_body_weight for the trend, get_muscle_work for which muscle groups the strength sessions trained and which were left out, and, if connected, calories and macros from the food diary against the day's goals.
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

1. Find the event on my calendar (get_calendar_events): its date, distance and terrain. If it is not there, search Garmin's catalog of races published by the organisers (search_event_catalog, the same search as the app's race search; it takes words, dates, a distance range and a place, and returns official and verified sources first) and show me what you find. Add a race to my calendar only after I say so: add_catalog_event_to_calendar for a catalog race (it is public by nature), create_calendar_event for a private one (it first looks for an event with a similar name on the same date and stops if it finds one; use create_anyway only if I agree). Check the weather forecast when the date is within range.
2. Judge the goal against my predictions, recent long runs and personal records. Say plainly if it looks realistic, ambitious or out of reach, with the numbers.
3. Propose the remaining weeks as a table: build, taper and race week, with volume and intensity. Include the day-before and race-morning routine, pacing by heart-rate zone and by minutes per kilometre, and fuelling and hydration based on what the data says about my sweat loss (get_hydration).
4. List the logistics I should settle now (gear, route, travel, sleep).
5. For a flat distance offer a PacePro plan: show it first with create_pacepro_plan (even pace, or a slight negative split) and save it, and send it to my watch with send_pacepro_plan_to_watch, only when I ask. Remind me that a PacePro run replaces the heart-rate alerts of a structured workout and that the pace is only a guide next to my heart-rate zones.
Do not schedule, add, create or send anything until I confirm.

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

Read the exercise catalog resource workout://reference/exercise-catalog and the structure reference workout://reference/structure so every step uses a real Garmin category and exercise name. Think about where this fits against my running week (not before a key run) and my recent load, and use get_muscle_work to see which muscle groups the last week left untrained.

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

## `firefighter_fitness_test_hu`

Firefighter fitness test assessor (Hungarian entry test with scoring tables, plus USA, UK, German, Czech, Polish and Dutch benchmarks): scores results, gives the grade, the gap to the next level and targeted training.

Arguments: none

```text
Dolgozz tűzoltó-alkalmasság értékelőként. Az alábbi szabályok és táblázatok alapján értékeld az eredményeimet. A táblázatokat és az összefoglalókat a felhasználó állította össze, nem ellenőriztük őket a hatályos szöveggel: ha eltérést találsz, a FORRÁSOK hivatalos leírásai a mérvadók.

ALAPELVEK
- Ha az értékeléshez adat hiányzik (életkor, nem, eredmények, választott gyakorlatok), előbb kérdezz rá.
- A végeredményeket két tizedesjegyre, tizedesvesszővel add meg.
- Ha egy szabály vagy határérték bizonytalan vagy elavult lehet, jelezd, és hivatkozz a forrásra (lásd a FORRÁSOK részt).

GARMIN-ADATOK (ha a Garmin-szerver csatlakoztatva van)
- Az életkort, a nemet és a testsúlyt a get_athlete_profile adja, ezekre ne kérdezz rá.
- A Cooper-teszthez keress egy kb. 12 perces, maximális erőkifejtésű futást (get_activities_by_date). Az erőgyakorlatokhoz a rögzített erőedzések (get_activity_exercise_sets) segíthetnek.
- A Garmin VO2max-értéke (get_athlete_profile) becslés, nem laboratóriumi vagy Chester-teszt eredmény. Ha a brit 42,3 ml/kg/perc küszöbhöz hasonlítod, jelezd ezt a különbséget.

========================================
1. MAGYARORSZÁG – hivatásos tűzoltó szakmai képzés előtti fizikai alkalmasságvizsgálat
Jogi alap: 45/2020. (XII. 16.) BM rendelet; 1/2021. (I. 21.) BM OKF utasítás.
A vizsgálat két részből áll, és MINDKETTŐT teljesíteni kell. Előfeltétel a háziorvosi igazolás.

1.1 Minimumfeltétel – Cooper-teszt (12 perc, kizárólag futással)
Korcsoport          | Férfi  | Nő
I.   (18–29 év)     | 2100 m | 1800 m
II.  (30–39 év)     | 1800 m | 1500 m
III. (40–49 év)     | 1500 m | 1200 m
IV.  (50 év felett) | 1250 m | 1050 m
Ha a minimum nem teljesül, a jelölt alkalmatlan.

1.2 Kiegészítő vizsgálat
A hat gyakorlatból négyet kell választani. Gyakorlatonként 1–15 pont adható, így a maximum 60 pont. Egy gyakorlat csak akkor érvényes, ha legalább 1 pontot ér.

Gyakorlatok és végrehajtási szabályok:
- Fekvőtámasz: 30 mp. Le kell menni addig, amíg a felkar párhuzamos a talajjal; a törzs egyenes.
- Húzódzkodás: vállszéles fogás. Az állnak a rúd fölé kell kerülnie, majd teljes karnyújtás következik. Max ismétlés számít.
- Guggolás: 1 perc, kéz csípőn. A térd 90°-ban hajlik, a comb párhuzamos a talajjal.
- Helyből távolugrás: páros lábról, karlendítéssel. A távot az ugróvonaltól a legközelebbi talajérintésig mérik, cm-ben.
- Félfelülés: 1 perc, hajlított lábbal, lábfej rögzítése nélkül. A lapockának el kell hagynia a talajt (kb. 30°).
- Plank: könyöktámasz, egyenes törzs. Maximális idő számít.

Pontozótáblázat (értékpárok: férfi/nő):
Pont | Fekvőt.(db) | Húzódz.(db) | Gugg.(db) | Távolugr.(cm) | Félfel.(db) | Plank
15 | 35/20 | 20/15 | 35/30 | 250/220 | 55/45 | 3:00/2:30
14 | 33/18 | 18/14 | 33/28 | 245/215 | 53/43 | 2:51/2:21
13 | 31/16 | 16/13 | 31/26 | 240/210 | 51/41 | 2:40/2:12
12 | 29/14 | 14/12 | 29/24 | 235/205 | 49/39 | 2:30/2:03
11 | 27/12 | 12/11 | 27/22 | 230/200 | 47/37 | 2:20/1:54
10 | 25/10 | 10/10 | 25/20 | 225/195 | 45/35 | 2:10/1:45
 9 | 23/9  |  9/9  | 23/18 | 220/190 | 43/33 | 2:00/1:36
 8 | 21/8  |  8/8  | 21/16 | 215/185 | 41/31 | 1:50/1:27
 7 | 19/7  |  7/7  | 19/14 | 210/180 | 39/29 | 1:40/1:18
 6 | 17/6  |  6/6  | 17/12 | 205/175 | 37/27 | 1:30/1:09
 5 | 15/5  |  5/5  | 16/11 | 200/170 | 35/25 | 1:20/1:00
 4 | 13/4  |  4/4  | 15/10 | 195/165 | 33/23 | 1:10/0:51
 3 | 11/3  |  3/3  | 14/9  | 190/160 | 31/21 | 1:00/0:42
 2 |  9/2  |  2/2  | 13/8  | 185/155 | 29/19 | 0:50/0:33
 1 |  7/1  |  1/1  | 12/7  | 180/150 | 27/17 | 0:40/0:24
A két szomszédos sor közé eső eredmény az alacsonyabb pontot kapja.

Minősítés (a 4 gyakorlat összpontszáma alapján):
Minősítés   | I.    | II.   | III.  | IV.
Kiváló      | 54–60 | 52–60 | 46–60 | 42–60
Jó          | 45–53 | 41–51 | 37–45 | 29–41
Megfelelt   | 40–44 | 32–40 | 28–36 | 20–28
Alkalmatlan | 0–39  | 0–31  | 0–27  | 0–19

========================================
2. NEMZETKÖZI FELMÉRŐK (viszonyítási alap)

2.1 USA – CPAT (Candidate Physical Ability Test)
- Megfelelt/nem felelt meg teszt, időlimit: 10:20. Nincs korcsoport.
- Végig 22,68 kg-os (50 lb) mellényt kell viselni.
- Nyolc állomás egymás után: lépcsőzés StepMill gépen, tömlőhúzás, felszerelés cipelése, létraemelés és -kitolás, erőszakos behatolás, kutatás (kúszás), mentés (bábuhúzás), plafonbontás és -húzás.
- Az állomások között 25,91 m gyaloglás következik (kb. 20 mp pihenő). Futni tilos.
- Esés, kapaszkodás vagy a gépről lelépés azonnali bukás.

2.2 Egyesült Királyság – Chester Treadmill Walk Test + NFST
- Egységes küszöb: VO2max ≥ 42,3 ml/kg/perc, életkortól és nemtől függetlenül.
- Protokoll: 6,2 km/h sebesség, 0%-os emelkedővel indul, kétpercenként +3%, a 12. percre eléri a 15%-ot. A 12 percet segítség nélkül kell végigcsinálni.
- Kiegészítő munkatesztek (NFST, London): létramászás; létraemelés-szimulátor (30 kg-os rúd 190 cm magasra); felszereléscipelés; felszerelés-összeszerelés; zárt tér.
- Egyes szolgálatok a hivatásos felvételinél 1,5 mérföldes futással mérik a VO2maxot.

2.3 Németország – Berufsfeuerwehr Sporttest
- A Kölni Sportfőiskola (DSHS Köln) tesztje, helyenként 9–10 versenyszámmal: állóképesség, erő, gyorsaság, reakció, koordináció, egyensúly.
- Nürnberg: kieséses rendszer. Egy nem teljesített szám után vége a tesztnek. Egy példa: akadálypálya-parcour ≤ 20 mp.
- München: hét feladat, köztük 30 m-es, 75°-os gépezetes létra mászása ≤ 60 mp alatt; wechselsprünge (oldalirányú ugrások 33 cm-es akadály fölött).

2.4 Csehország – HZS ČR (Pokyn GŘ HZS ČR 58/2008; 324/2001 Sb. vyhláška)
- Korcsoportos pontozás, az adott naptári évben betöltött életkor számít.
- Erő- és állóképességi tesztek, korcsoportonkénti ponthatárokkal.
- 51 év feletti férfiaknál csak a teljesítés számít, pontozás nélkül.
- Van szakirodalom önkéntes tűzoltók teszteléséről, TFA-szerű (Toughest Firefighter Alive) próbákkal.

2.5 Lengyelország – PSP (Dz.U. 2018/673)
- Felvételi: húzódzkodás, „boríték-futás" (ügyességi pálya) és beep-teszt.
- Éves ellenőrzés: két próba, nemenként és a beosztás jellege szerint eltérően.

2.6 Hollandia – PPMO (Periodiek Preventief Medisch Onderzoek)
- Hivatásos és önkéntes beosztott tűzoltókra egyaránt vonatkozik.
- Éves fizikai teszt, és javasoltan négyévente teljes PPMO.
- Validált funkcionális tesztek: emelés-cipelés, térdelés-guggolás, mászás-kúszás (létrateszt), tűzoltási szimuláció. Előtte PAR-Q kérdőív.
- A protokollt a Coronel Instituut (AMC Amszterdam) fejlesztette ki.

========================================
3. FELADATOK
1. Kérdezd meg, ha nem adtam meg és a Garminból nem olvasható ki: életkor, nem, testsúly, jelenlegi eredmények, és melyik rendszer szerint értékeljek (alapértelmezés: magyar).
2. Értékelés:
   - magyar rendszerben: korcsoport, Cooper-minimum, gyakorlatonkénti pontszám, összpontszám, minősítés (a táblázatkeresést ellenőrizd kétszer);
   - nemzetközi rendszerekben: teljesíti-e a küszöböt / hol áll hozzá képest.
3. Ha nem adtam meg a választott gyakorlatokat, javasold azt a 4-et, amellyel a legtöbb pontot szerezhetem.
4. Hiányelemzés: mennyi hiányzik a következő minősítési szintig, illetve az egyes nemzetközi küszöbökig.
5. Edzésjavaslat: célzott, periodizált javaslat. Vedd figyelembe a rendelkezésre álló eszközöket (pl. kettlebell, evezőgép) és az esetleges sérülési korlátokat. Jóváhagyásom nélkül ne ütemezz semmit.
6. Kérésre építs egy otthon is végrehajtható „hibrid" felmérőt a CPAT, a Chester-teszt és a PPMO elemeiből.

========================================
4. FORRÁSOK
Magyarország
- Békés VMKI – Tájékoztató a tűzoltó szakmai képzést megelőző fizikai alkalmasságvizsgálatról: https://bekes.katasztrofavedelem.hu/application/uploads/documents/2024-04/83662.pdf
- Heves VMKI – Hogyan lehetsz tűzoltó?: https://heves.katasztrofavedelem.hu/application/uploads/documents/2025-02/85130.pdf
- Védelem Tudomány – Tűzoltók fizikai állapotfelmérése (2021): https://ojs3.mtak.hu/index.php/vedelemtudomany/article/download/13455/10859
- Kanyó–Vásárhelyi-Nagy: Research for New Physical Ability Testing Method for Firefighters in the V4 Countries (MKK 2019): https://folyoirat.ludovika.hu/index.php/mkk/article/view/223

USA
- San Antonio FD – CPAT: https://www.sa.gov/Directory/Departments/SAFD/Recruiting/Become-a-Firefighter/Candidate/CPAT
- Seattle – CPAT Orientation Guide: https://seattle.gov/documents/departments/firejobs/cpatorientationguide.pdf
- Colorado Springs FD – CPAT: https://coloradosprings.gov/node/55121

Egyesült Királyság
- Cambridgeshire FRS – Chester treadmill test: https://www.cambsfire.gov.uk/media/3096/chester_fitness_test.pdf
- North Wales Fire – Firefighter Fitness Guide: https://www.northwalesfire.gov.wales/media/u43lysul/firefighters-fitness-booklet.pdf
- London Fire Brigade – Fitness tests: https://www.london-fire.gov.uk/careers/become-a-firefighter/fitness-tests
- LFB – Annual Fitness Testing (2024): https://www.london-fire.gov.uk/media/4zjngz5g/lfc-24-039-annual-fitness-testing-for-publication-signed.pdf
- Avon Fire – Practical physical tests: https://www.avonfire.gov.uk/careers/wholetime-firefighter/practical-physical-tests
- Topend Sports – Chester Treadmill Walk Test: https://www.topendsports.com/testing/tests/chester-treadmill-walk.htm

Németország
- Feuerwehr Wiesbaden – Auswahlverfahren: https://www.wiesbaden.de/leben-wohnen/feuerwehr-notfaelle/ehrenamt-beruf-karriere/informationen-zum-auswahlverfahren
- Stadt Dortmund – Einstellungstest: https://www.dortmund.de/themen/sicherheit-und-ordnung/helfer-und-retter/berufsfeuerwehr/karriere/ausbildung-zum-zur-brandmeister-in/der-einstellungstest/
- Nürnberg – Einstellungstest: https://www.nuernberg.de/internet/arbeitgeberin/einstellungstest.html
- BF München – Sporttest: https://www.hr6.tum.de/fileadmin/w00bjm/feuerwehr/Einstellung/Sporttest.pdf
- Feuerwehr Stuttgart – Informationen zur Bewerbung (a korábbi PDF-hivatkozás már nem érhető el): https://feuerwehr.stuttgart.de/karriere/informationen-zur-bewerbung/

Csehország
- HZS ČR – Pokyn GŘ 58/2008: https://hzscr.gov.cz/soubor/pokyn58-08-pdf.aspx
- Vyhláška 324/2001 Sb.: https://www.epravo.cz/top/zakony/sbirka-zakonu/sb/2001/324
- Önkéntes tűzoltók fizikai tesztje, TFA (VŠB, 2024): https://dspace.vsb.cz/handle/10084/155064

Lengyelország
- KG PSP – Sport w PSP: https://www.gov.pl/web/kgpsp/sport-w-psp
- Dz.U. 2018/673 – ocena sprawności fizycznej: https://api.sejm.gov.pl/eli/acts/DU/2018/673/text.html

Hollandia
- Keuringen brandweerpersoneel: https://lokaleregelgeving.overheid.nl/CVDR299668/1
- PPMO Bijlage VIIb: https://repository.officiele-overheidspublicaties.nl/CVDR/CVDR59711/2/xml/i41839.pdf
- NIPV – Waarom PPMO: https://archief.nipv.nl/documenten/waarom-ppmo
- PPMO testprotocol (Coronel Instituut): https://archief.nipv.nl/documenten/ppmo-periodiek-preventief-medisch-onderzoek-voor-repressief-brandweerpersoneel

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `fitness_assessment_menu`

Asks which rulebook to assess your physical fitness against (Hungarian firefighter entry test, CPAT, Chester, German, Czech, Polish, Dutch, home hybrid), then runs the assessment; can be repeated at any time.

Arguments: none

```text
FIZIKAI ÁLLAPOTFELMÉRÉS - VÁLASZTÓ

Első lépésként egyetlen kérdésben kérdezd meg tőlem: "Szeretnéd felmérni a fizikai állapotodat valamelyik szabályzat alapján?" Mutasd be az alábbi választékot (rövid leírással), és kérdezd meg, melyiket választom:

1. Magyar hivatásos tűzoltó szakmai képzés előtti alkalmasságvizsgálat: Cooper-minimum és négy választott gyakorlat, pontozással és minősítéssel (a teljes pontozású rendszer, ez az alapértelmezés).
2. USA - CPAT: megfelelt / nem felelt meg, 10:20 időlimit, mellényben; eszközök nélkül csak közelíteni lehet.
3. Egyesült Királyság - Chester-teszt és az NFST munkatesztek (VO2max-küszöb).
4. Németország - berufsfeuerwehr sporttest (kieséses rendszerek).
5. Csehország - HZS ČR, korcsoportos pontozás.
6. Lengyelország - PSP (húzódzkodás, ügyességi pálya, beep-teszt).
7. Hollandia - PPMO (funkcionális tesztek).
8. Otthon elvégezhető "hibrid" felmérő a CPAT, a Chester-teszt és a PPMO elemeiből.
9. Most nem kérek felmérést.

Ha a 9-est választom, köszönd meg, és mondd el, hogy a felmérő bármikor újra indítható, nem csak most.

A választás után:
1. Kérdezd meg, van-e friss eredményem, vagy előbb el kell végeznem a tesztet. Ha előbb el kell végeznem: add meg a protokollt lépésről lépésre, a bemelegítést és a biztonsági tudnivalókat (a hivatalos vizsgálat előtt háziorvosi igazolás kell, ahol a szabályzat előírja), és várd meg az eredményeket. Fájdalomnál vagy rosszullétnél állj le, és orvoshoz irányíts.
2. Ha korábbi felmérésemet mentettem a privát jegyzeteimbe, vesd össze vele, és mutasd a változást. Ha nincs, javasold, hogy az eredményt privát helyen tároljam, hogy később összevethessük.
3. Értékelj a lent mellékelt szabályzat szerint (az alapelvek és a feladatok ott vannak).
4. A végén kérdezd meg, szeretnék-e a következő tesztre készülni (ha igen, ajánld a prepare_for_fitness_test promptot), és emlékeztess, hogy a felmérés bármikor megismételhető, például 6-8 hetente.

[=== SZABÁLYZAT ÉS FORRÁSOK (az értékelés alapja) ===
 the full rulebook text, identical to the one in `firefighter_fitness_test_hu`]

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```

## `prepare_for_fitness_test`

Training plan counted back from the date of the next fitness test: baseline, weakest components, periodised weeks with mini-tests, taper; can be started at any time.

Arguments: `test`, `test_date`

```text
Készíts fel a következő fizikai alkalmassági tesztre.

Teszt: kérdezz rá a fitness_assessment_menu választéka szerint.
Időpont: kérdezz rá: mikor lesz? Nézd meg a naptáramat is (get_calendar_events).

1. Hiányzó adatnál előbb kérdezz (teszt, időpont, jelenlegi eredmények, korlátok, felszerelés).
2. Kiindulás: ha nincs 4 hétnél újabb felmérésem, készíts egyet az adataimból és az eredményeimből a lent mellékelt szabályzat szerint, különben használd a legutóbbit. Pontszám nélküli rendszernél a küszöbhöz viszonyíts.
3. Idő: számold ki, hány hét van a tesztig, és hogy a cél minősítés reális-e. Ha túl kevés az idő, mondd ki, és mondd meg, mi érhető el.
4. Prioritás: sorold fel, hol veszítek a legtöbb pontot vagy hol hiányzik a küszöb. Pontozásos rendszernél válaszd ki azt a négy gyakorlatot, amelyikkel a legkönnyebben javítható az összpontszám.
5. Terv: periodizált, hetekre bontva (építés, specifikus fázis, tapering és a teszt hete), mini-tesztekkel (pl. 4 és 1 héttel a teszt előtt), a futóedzéseimhez és a regenerációmhoz igazítva (get_training_readiness, get_hrv_status, get_scheduled_workouts). Ne halmozz nehéz edzéseket, és tartsd a pihenőnapokat.
6. Mutasd táblázatban (hét, fókusz, főbb edzések, mini-teszt). Jóváhagyásom után tölts fel és ütemezz (upload_workouts, schedule_workouts).
7. Ha a teszt időpontja nincs a naptáramban, javasold, hogy vegyem fel (te nem tudsz eseményt létrehozni).
8. Mondd meg, mikor ismételjük meg a felmérést (a fitness_assessment_menu bármikor újra futtatható), és hogyan követjük a fejlődést a heti értékelésben (weekly_review).

[=== SZABÁLYZAT ÉS FORRÁSOK (az értékelés alapja) ===
 the full rulebook text, identical to the one in `firefighter_fitness_test_hu`]

Ground rules:
- Read the user's real data with the connected tools instead of asking for numbers Garmin already has (age, height, weight, zones, history).
- Never upload, schedule, delete or log anything before showing the plan and getting a clear yes.
- This is training planning and record-keeping, not medical advice: for pain, illness, supplements or health conditions point to a doctor or a lab test.
- If a companion 'mfp-readonly' server (fitness_* tools) is connected, use it for meals and macros. Never question or change the user's own calorie or macro targets unless they ask.
- Reply in the language the user writes in. Keep answers short and concrete.
- Personal context (injuries, schedule, goals) belongs in the user's own private notes, never in a public repository.
```
