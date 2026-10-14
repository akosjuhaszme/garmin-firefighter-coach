# Kész promptok (magyarul)

Promptok az edzői munkafolyamathoz: egy első indítási rutin telepítés után, egy heti ritmus és
egyedi ellenőrzések. Nem tartalmaznak személyes adatot. Megmondják az asszisztensnek, mely
eszközökkel olvassa ki a valódi adataidat (hogy ne kérdezze meg azt, amit a Garmin már tud), és
kérik a kifejezett jóváhagyásodat, mielőtt bármit feltöltene, ütemezne vagy törölne.

*Az angol, kódból generált változat: [PROMPTS.md](PROMPTS.md). Az MCP-promptok angolul vannak
beépítve; az asszisztens a te nyelveden válaszol. Itt bemásolható magyar szövegek vannak.*

## Első lépések telepítés után

1. Telepítsd és hitelesítsd a Garmin-szervert (README, "Setup"), és vedd fel az MCP-kliensedbe.
   Opcionális: az étkezésnapló (README, "Food diary: MyFitnessPal").
2. Indítsd újra a klienst, hogy az eszközök és a promptok betöltődjenek.
3. Futtasd az **`első indítás`** promptot (lent). Ellenőrzi a kapcsolatokat, elolvassa az
   előzményeidet, és csak azt kérdezi meg, amit a Garmin nem tudhat (cél, szabad napok, felszerelés,
   sérülések, kötöttségek), majd javasol egy első hetet. A jóváhagyásod előtt semmi nem kerül a Garminba.
4. Amit rólad megtanul, azt **privát** helyen tárold, soha ne nyilvános tárolóban.

Heti ritmus: a hét utolsó napján heti értékelés, utána a következő hét megtervezése. Reggel,
ha kétséged van egy edzésről, regenerációs ellenőrzés. Étkezésnapló mellett táplálkozás-ellenőrzés.
Versenynaptár-bejegyzés után versenyfelkészítés.

## Alapszabályok (minden prompt végére)

- A valódi adataimat a csatlakoztatott eszközökkel olvasd ki, ne kérdezz rá arra, amit a Garmin tud.
- Semmit ne tölts fel, ne ütemezz, ne törölj, és ne naplózz, amíg nem mutattad meg a tervet és nem mondok egyértelmű igent.
- Ez edzéstervezés és nyilvántartás, nem orvosi tanács: fájdalomnál, betegségnél, étrend-kiegészítőnél vagy egészségi kérdésnél orvoshoz vagy laborvizsgálathoz irányíts.
- Ha csatlakoztatva van az `mfp-readonly` szerver (`fitness_*` eszközök), az étkezésekhez és makrókhoz azt használd. A saját kalória- és makrócéljaimat ne kérdőjelezd meg és ne változtasd, hacsak nem kérem.
- Azon a nyelven válaszolj, amelyen írok. Legyél rövid és konkrét.
- A személyes háttér (sérülések, időbeosztás, célok) a saját privát jegyzeteimbe tartozik, soha nem nyilvános tárolóba.

## Első indítás

```text
Személyes edzői és regenerációs rendszert állítasz be nekem. Menj végig a lépéseken, és mindegyik után röviden számolj be.

1. Kapcsolatok. Hívd a get_athlete_profile és a get_daily_summary eszközt. Ha csatlakoztatva van az mfp-readonly, a fitness_get_day-t is. Mondd meg, mi működik és mi hiányzik (pl. üres consumed_kcal, mert nincs étkezésnapló a Garminhoz kötve, nincs friss mérés, lejárt bejelentkezés).
2. Amit a Garmin már tud. Foglald össze az elmúlt 8 hetet: get_activities_by_date, heti kilométer és edzésszám, get_personal_records, get_race_predictions, get_training_status, nyugalmi pulzus, HRV és alvás (get_wellness_trend), a súly trendje (get_body_weight), és a naptárban lévő versenyek (get_calendar_events).
3. Amit a Garmin nem tudhat. Egyszerre kérdezd meg: a célomat és a dátumát, heti hány napon edzhetek és melyek a fix vagy szabad napok, milyen felszerelésem van, sérüléseim és korlátaim, munka- vagy műszakbeosztás, és mi az, amit soha nem szeretnék a tervben.
4. A háttér elmentése. Javasolj egy rövid személyes háttérjegyzetet (célok, kötöttségek, szokások) és hol tároljam. Privát helyet javasolj, és figyelmeztess, hogy ne kerüljön nyilvános tárolóba.
5. Az első hét. Javasolj egy hetet táblázatban (nap, edzés, cél, intenzitás pulzuszónában). Amíg nem hagyom jóvá, semmit ne tölts fel és ne ütemezz.
```

## Heti edzésterv

```text
Tervezd meg az edzéshetemet, kezdés: [HÉT KEZDETE, pl. jövő hétfő]. Különleges kötöttségek ezen a héten: [KÖTÖTTSÉGEK vagy "nincs"].

1. Olvasd ki, mi történt: az utolsó 4 hét edzései és terhelése, get_training_readiness, get_hrv_status, az alvás és a nyugalmi pulzus trendje, get_scheduled_workouts a célhétre, get_calendar_events a versenyekhez, get_weather_forecast a szabadtéri napokra.
2. Egy mondatban döntsd el a hét célját (építés, szinten tartás, tehermentesítés, visszatérés szünet után), és indokold az adatokkal.
3. Javasold a hetet táblázatban: nap, edzés, időtartam vagy távolság, intenzitás pulzuszónában, cél. Legyen legalább egy teljes pihenőnap, tartsd tiszteletben a fix napjaimat, és ne halmozz nehéz edzéseket.
4. Jelezd a kockázatokat (időjárás, nehéz edzés a verseny közelében, rossz regeneráció), és mit változtatnál, ha aznap rosszabb a regenerációm.
5. Kérd a jóváhagyásomat. Csak utána tölts fel és ütemezz az upload_workouts és a schedule_workouts eszközzel (rövid, leíró nevek, szerkezeti pulzuszóna-célok, valódi bemelegítés és levezetés a szerkezeti futásokon).
```

## Heti értékelés

```text
Értékeld az elmúlt [7] napomat edzőként.

1. Adatok: tervezett és teljesített edzések (get_scheduled_workouts, get_activities_by_date), összterhelés, get_wellness_trend az alváshoz, HRV-hez, nyugalmi pulzushoz, Body Batteryhez és az életmód-jelölésekhez (betegség, alkohol, utazás), get_body_weight a súlytrendhez, és ha van étkezésnapló, a kalória és a makrók a napi célok mellett.
2. Hogy éreztem magam: tegyél fel egy rövid kérdést az energiaszintemről és a fájdalmakról, és használd a válaszomat.
3. Ítélet: három pont arról, mi működött, egy pont a legnagyobb akadályozó tényezőről, bizonyítékkal. Különítsd el a valódi jelzéseket (magas pulzus ugyanazon a tempón, több rossz éjszaka, alapszint alatti HRV) a zajtól (egy furcsa érték, szenzorhiba).
4. Jövő hét: legfeljebb három konkrét változtatás, mindegyikhez mérhető céllal. Jóváhagyásom nélkül semmit ne ütemezz.
```

## Regenerációs ellenőrzés (ma)

```text
Mondd meg, hogy a terv szerint edzek-e ma.

Olvasd ki: get_training_readiness, get_hrv_status, az éjszakai alvás (get_sleep), get_body_battery, get_stress, a nyugalmi pulzus az alapszinthez képest, az utolsó három nap terhelése, a mai tervezett edzés (get_scheduled_workouts), és az életmódnapló a betegséghez vagy sérüléshez (get_lifestyle_logging).

Válaszolj az egyikkel: a terv szerint, módosítva (pontosan mondd meg hogyan: rövidebb, alacsonyabb zóna, mobilitásra cserélve), vagy pihenj. Add meg a két-három adatot, ami eldöntötte. Ha betegségre vagy sérülésre utal valami, mondd ki egyenesen és orvost javasolj, ne diagnosztizálj.
```

## Táplálkozás-ellenőrzés

```text
Nézd meg az elmúlt [7] napom étkezését a saját céljaim és az edzéseim mellett.

Ha csatlakoztatva van az étkezésnapló-szerver, használd a fitness_get_day vagy a fitness_bulk_export és a fitness_get_trends eszközt (calories_in, protein, carbs, fat), és a get_daily_summary-t az elégetett kalóriához és a consumed_kcal-hoz. Ha nincs étkezésnapló, mondd meg, hogyan kössem össze, és állj meg.

Jelentsd: az átlagos bevitel a céljaimhoz képest, a nagyon eltérő napok és mi követte őket edzésben, a fehérje eloszlása a napok között, és hogy a nehéz edzések előtti és utáni bevitel megfelelőnek látszik-e. A céljaimat úgy használd, ahogy vannak, ne javasolj változtatást, hacsak nem kérem. Orvosit ne mondj; hiányállapotnál és étrend-kiegészítőnél orvoshoz vagy laborvizsgálathoz irányíts.
```

## Versenyfelkészítés

```text
Készíts fel erre a versenyre: [VERSENY NEVE vagy "a naptáram következő versenye"]. A célom: [CÉL vagy "kérdezz rá, és vesd össze a get_race_predictions-szel"].

1. Keresd meg a versenyt, a dátumát, távját és terepét. Ha közel a dátum, nézd meg az időjárás-előrejelzést.
2. Mérd a célt az előrejelzéseimhez, a friss hosszú futásaimhoz és a személyes rekordjaimhoz. Mondd ki egyenesen, hogy reális, ambiciózus vagy elérhetetlen, számokkal.
3. Javasold a hátralévő heteket táblázatban: építés, tapering és versenyhét, terheléssel és intenzitással. Legyen benne a verseny előtti nap és a verseny reggelének rutinja, a tempó pulzuszóna és perc/km szerint, és a folyadék- és energiapótlás az izzadásveszteségem adatai alapján (get_hydration).
4. Sorold fel a logisztikát, amit most kell elintézni (felszerelés, útvonal, utazás, alvás).
Jóváhagyásom nélkül semmit ne ütemezz.
```

## Terhelésnövelési szabályok

```text
Írd meg a személyes terhelésnövelési szabályaimat a valódi előzményeim alapján, ne általános tanácsokból.

Nézd át az elmúlt 6 hónapot: a heti terhelés és mennyire nőtt gyorsan, mely hetek mentek jól és melyek végződtek betegséggel, fájdalommal vagy rossz regenerációval (get_wellness_trend és az életmódnapló), és hogyan viselkedik a pulzusom könnyű tempón.

Készíts egyoldalas szabályrendszert: mikor és mennyivel növeljek mennyiséget vagy intenzitást, mikor tartsam a szintet, milyen jelzések váltanak ki tehermentesítést (nevezd meg a mutatókat és a határokat), hogyan térjek vissza betegség vagy szünet után, és melyik az a szabály, amit a legvalószínűbb, hogy megszegek. Minden szabály legyen mérhető. Ajánld fel, hogy elmented a privát jegyzeteimbe.
```

## Erő- és funkcionális edzés

```text
Tervezz egy [40] perces erő- vagy funkcionális edzést. Felszerelés: [FELSZERELÉS vagy "kérdezz rá"]. Fókusz: [FÓKUSZ vagy "kérdezz rá, vagy válaszd a gyenge pontjaimból és a futóigényekből"].

Olvasd el a workout://reference/exercise-catalog gyakorlatkatalógust és a workout://reference/structure leírást, hogy minden lépés valódi Garmin-kategóriát és gyakorlatnevet használjon. Gondold végig, hová illik a futóhetemben (ne egy kulcsfutás előtt) és a friss terhelésemhez.

Mutasd táblázatban (gyakorlat, sorozat, ismétlés vagy idő, pihenő, intenzitás vagy súly). Jelezd, ha egy gyakorlatot az óra más néven jelenít meg. Az igenem után tölts fel erőedzésként (ismétlődő szerkezet a sorozatokhoz), és ajánld fel az ütemezést.
```

## Gyenge pontok

```text
Találd meg, mi korlátozza a fejlődésemet [TERÜLET, ha van], és készíts célzott tervet.

Nézd meg: a tempó és a pulzus elcsúszása a hosszú futásokban (get_activity_hr_in_timezones, get_activity_splits), a lépésszám és talajkontaktus trendje, ahol van, a személyes rekordok az előrejelzésekhez képest, milyen gyakran maradnak rövidek az edzések, az erőedzések jegyzetei, és az ismétlődő fájdalmak említései.

Add meg a két fő korlátozót bizonyítékkal, majd mindegyikhez: két-három konkrét gyakorlatot, milyen gyakran, mennyi ideig próbáljam mielőtt ítélek, és milyen mérhető változás jelezné a működését. Ajánld fel, hogy beépíted a heti tervbe, de jóváhagyásom nélkül semmit ne ütemezz.
```

## Tűzoltó alkalmasságvizsgálat (minta felmérő)

Mintaként egy konkrét szabályzatokra épülő felmérő: a hivatásos tűzoltó szakmai képzést megelőző
magyar fizikai alkalmasságvizsgálat (Cooper-minimum és négy választott gyakorlat) pontozótáblákkal,
és nemzetközi viszonyítási alapok (USA CPAT, brit Chester-teszt, német, cseh, lengyel, holland
rendszer) forráslistával. A táblázatokat és az összefoglalókat a felhasználó állította össze, nem
ellenőriztük őket a hatályos szöveggel: használat előtt vesd össze a forrásokkal. A beépített
MCP-prompt neve `firefighter_fitness_test_hu`. A korodat, nemedet és testsúlyodat a profilból
olvassa ki, a Cooper-futást és az erőgyakorlatokat az edzéseid között keresi, és figyelmeztet, hogy
a Garmin VO2max becslés, nem laboreredmény. Ugyanez a minta bármilyen más pontozótáblás felmérőhöz
használható: a szabályzat szövege a promptban van, a számolás az asszisztensé, ezért kéri a
táblázatkeresés dupla ellenőrzését.

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
```
