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
