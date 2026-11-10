# Dnevnik rada

Kronološki zapis važnih radnji i odluka. Najnovije na dnu.

## 10.11.2026.

### Repozitorij
- Napravljen repozitorij na GitHubu (`AceTep/okom`). Glavna grana je `main`, a rad ide na granama nazvanim po temi (npr. `screen-switch`), bez imena osoba, jer oboje radimo na svemu.
- `.gitignore` izostavlja `data/` (snimke lica, kalibracije, logovi), `models/` (MediaPipe datoteke koje se preuzimaju skriptom) i `.venv/`.

### Podjela posla
- Mateo radi većinu posla u svim mapama, pa podjela vlasništva po mapama iz početnog plana ne vrijedi strogo.
- Arhitektura ostaje ista: dva procesa (`gaze/` i `app/`) koji komuniciraju samo preko UDP-a.

### Cilj za Napredak I (17.11.)
- Prebacivanje fokusa između dva ekrana pogledom. Postav: laptop dolje, monitor gore. Ekrani su razmaknuti okomito, pa se razlikuju po nagibu glave i položaju šarenice.
- Odluka: kad pogled prijeđe na drugi ekran, fokus dobiva **zadnji aktivni prozor na tom ekranu**, odnosno najviši u redoslijedu slaganja prozora. Tako se korisnik vraća točno tamo gdje je zadnji put radio.

### Okruženje
- Fedora 44, KDE Plasma 6.8.2, Wayland, dvije kamere (`/dev/video0`, `/dev/video1`).
- `uv` je instaliran u `~/.local` (`pip install --user uv`). Python 3.11 povlači `uv` jer MediaPipe nema wheel za Python 3.14.

### Protokol (`shared/protocol.py`)
- `GazeMessage` dataclass s `to_json()` i `from_json()`, a validacija se radi pri stvaranju objekta.
- Odluke:
  - Nepoznata polja se pri čitanju **ignoriraju**, tako da noviji pošiljatelj radi sa starijim primateljem. To je u skladu s pravilom da se polja smiju samo dodavati.
  - Cijeli brojevi se prihvaćaju za float polja (`t`, `x`, `y`, `conf`) jer JSON ne razlikuje `1` i `1.0`.
  - `bool` se ne prihvaća kao `int` i obrnuto (u Pythonu je `True` podtip `int`, pa se to mora eksplicitno provjeriti).
  - NaN i beskonačnost se odbijaju.
- Zadani port `5555` i adresa `127.0.0.1` su konstante u `shared/protocol.py` jer su dio protokola.

### Numeriranje ekrana (`shared/screens.py`)
- Protokol šalje indeks ekrana, pa obje strane moraju brojati ekrane jednako.
- Pravilo: ekrani se sortiraju po gornjem lijevom kutu u globalnom rasporedu, prvo odozgo prema dolje, zatim slijeva nadesno.
- Na demo postavu to daje: **0 = monitor (HDMI-A-1, gore)**, **1 = laptop (eDP-1, dolje)**.

### KDE Wayland backend (`app/backends/kde_wayland.py`)
- Na Waylandu obična aplikacija ne može vidjeti ni aktivirati tuđe prozore, pa posao radi sam KWin.
- Način rada: preko D-Bus-a (`org.kde.KWin /Scripting`) učita se kratka KWin JavaScript skripta i pokrene. Ona napravi popis prozora ili aktivira prozor, a rezultat vrati pozivom `callDBus()` na našu D-Bus vezu. Nakon toga se skripta ukloni.
- Za D-Bus se koristi `jeepney`: čisti Python, bez sistemskih biblioteka, sinkroni API.
- Popis sadrži samo normalne, neminimizirane prozore na trenutnoj virtualnoj radnoj površini, uz ekran, geometriju i položaj u slaganju.
- Izmjereno: jedan dohvat popisa traje oko **3 ms**, što je dovoljno brzo da se zove pri svakoj odluci.
- Ručno provjereno na Fedori 44: popis prozora je točan, prebacivanje fokusa radi u oba smjera, a nepostojeći ID vraća `False`.
- Ručna provjera: `python -m app.backends.kde_wayland` (popis) i `python -m app.backends.kde_wayland --focus <ID>`.

### Odabir backenda (`app/backends/detect.py`)
- `choose_backend(platform, env)` je čista funkcija s redoslijedom iz plana: Windows, Hyprland, Sway, X11, KDE, GNOME, dummy. Testirana je s lažnim varijablama okoline.
- `create_backend()` stvori backend i provjeri vidi li barem jedan prozor. Ako ne vidi, ili ako backend još nije napravljen, prelazi na `dummy` i ispisuje razlog.
- Na ovom računalu: `detected platform backend: kde_wayland`, `sees 4 windows`.

### Sljedeće
- `app/receiver.py`, `app/decision.py` (dwell i histereza na razini ekrana), `app/mock_gaze.py`, `app/main.py`.
- Zatim gaze engine: kamera, MediaPipe, značajke, kalibracija, klasifikator ekrana.

### Aplikacijska strana za prebacivanje ekrana

**Lažni izvor pogleda (`app/mock_gaze.py`)**
- Pozicija miša glumi pogled. Šalju se iste UDP poruke kao iz pravog gaze enginea, pa `app/main.py` ne zna razliku.
- Na Waylandu obična aplikacija ne vidi poziciju miša, pa je javlja KWin skripta (`workspace.cursorPos`).
- **Mjerenje koje je odlučilo pristup:** jednokratna skripta učitana 30 puta u sekundi traje oko 6 ms po upitu, ali KWinu uzima **oko 15 % jezgre**. To je previše za proces koji crta cijeli ekran.
- **Odluka:** jedna skripta ostaje učitana (`okom_cursor`). Ima tajmer od 33 ms i javlja poziciju samo kad se miš pomaknuo, pa miran miš ne troši ništa. Izmjereno uz cijeli sustav: KWin troši isto kao bez nas (oko 10 % jezgre, što je normalni rad), dakle naš trošak je zanemariv.
- Ako se proces sruši (provjereno s `kill -9`), skripta ostaje u KWinu. Zato ima stalno ime i uklanja se pri sljedećem pokretanju (provjereno).
- Šum: Gaussov, σ = 4 cm (preračunato grubo s 40 px/cm). Kašnjenje je 100 ms. Točka izvan svih ekrana pridružuje se najbližem ekranu, kao što bi to napravio klasifikator.
- Kursor se u backendu daje kao `open_cursor_stream()`, tako da je kod ovisan o platformi samo u `app/backends/`.

**Odluka o prebacivanju (`app/decision.py`)** je čista logika: vrijeme se uzima iz `t` u porukama.
- Novi ekran mora držati pogled **dwell = 0,4 s**.
- Nakon prebacivanja slijedi **pauza od 0,8 s** prije sljedećeg.
- Uzorci s treptajem, bez lica, sa `screen = null` ili s `conf < 0,6` se **preskaču**: ne pomiču dwell, ali ga ni ne poništavaju. Tako treptaj ne prekida odluku.
- Ako između upotrebljivih uzoraka prođe više od **0,5 s** (npr. korisnik je otišao), dwell kreće ispočetka. Bez toga bi stari početak dwella odmah okinuo prebacivanje.

**Koji prozor dobiva fokus (`app/mapping.py`)**
- Dobiva ga najviši prozor na ciljnom ekranu.
- Ako je aktivni prozor već na tom ekranu, ne radi se ništa, tako da se ne poništi ručni Alt+Tab.

**Ostale datoteke**
- `app/receiver.py`: UDP primanje. Neispravne poruke se broje i javljaju najviše svakih 5 s.
- `app/config.yaml` i `app/config.py`: sve vrijednosti iznad. Nepoznati ili nedostajući ključ je greška, da se tipfeler ne izgubi tiho.
- `app/main.py`: povezuje sve. Pri pokretanju pita KWin na kojem je ekranu aktivni prozor. U logu ispisuje svako prebacivanje i vrijeme od uzorka koji je odlučio.

**Testovi:** 56 testova prolazi (odluka, mapiranje, config, geometrija mocka, UDP na localhostu).

**Poznato ograničenje:** `app/main.py` zna aktivni ekran samo pri pokretanju i nakon vlastitog prebacivanja. Ako korisnik ručno klikne prozor na drugom ekranu, aplikacija to ne zna dok pogled ne prijeđe na drugi ekran i natrag. Moguće rješenje: KWin skripta javlja promjenu aktivnog prozora (`workspace.windowActivated`).

**Ručna proba (Mateo, Fedora 44, KDE Wayland)**
- `app.main` i `app.mock_gaze` su pokrenuti zajedno. Fokus je pet puta zaredom ispravno prešao na prozor na ekranu na koji je pomaknut miš, u oba smjera, bez ijednog neuspjeha.
- Kašnjenje od uzorka koji je odlučio do prebacivanja fokusa: 107–142 ms. Od toga je 100 ms namjerno kašnjenje mocka, a ostatak je čekanje na takt slanja, odluka i KWin. Ukupno od pogleda do promjene fokusa ≈ 0,4 s dwella + 0,1 s + ~0,04 s.
- Primijećeno je poznato ograničenje: korisnik je ručno kliknuo prozor na drugom ekranu. Pravilo "ne prebacuj ako si već tamo" ispravno nije napravilo ništa.
- U log je dodano ime ekrana ciljnog prozora, jer prozori s istim naslovom nisu bili razlučivi.

### Gaze engine, korak 1: kamera

**Ovisnosti**
- Dodan je `mediapipe` (1.2.2). On sam povlači `numpy` i `opencv-contrib-python` (5.0).
- Svjesno **nije** dodan poseban `opencv-python`: dva OpenCV paketa u istom okruženju prepisuju si datoteke, a to je poznat izvor teško uhvatljivih grešaka. OpenCV koristimo izravno za kameru, ali preko paketa koji dolazi s MediaPipeom.

**Model (`scripts/download_models.py`)**
- `face_landmarker.task` (3,7 MB) preuzima se sa službenog MediaPipe servera. Verzija (`float16/1`) je zakucana u URL-u.
- Nakon preuzimanja provjerava se SHA-256, a datoteka se preimenuje tek kad je provjera prošla, tako da prekinuto preuzimanje ne ostavi pokvarenu datoteku. Ponovno pokretanje preskače već ispravan model.
- `models/` je u `.gitignore`.

**Kamera (`gaze/camera.py`)**
- Na demo laptopu su dva uređaja: `/dev/video0` je prava kamera, a `/dev/video1` je metapodatkovni čvor iste kamere i ne daje slike (provjereno).
- Vrijeme snimanja `t` uzima se odmah nakon čitanja slike. Red slika u driveru postavljen je na 1, da se uvijek obrađuje svježa slika, a ne stara iz reda.
- Dijagnostika `python -m gaze.camera` samo broji slike: ne sprema ih i ne prikazuje.

**Mjerenje FPS-a (navečer, prigušeno svjetlo)**

| Traženo | Dobiveno | FPS |
| --- | --- | --- |
| 640×480, zadani format | 640×480 YUYV | 15,0 |
| 1280×720 MJPG | 1280×720 MJPG | 15,0–16,9 |
| 1280×720, zadani format | 1280×720 YUYV | 10,0 |

- Odabrano je **1280×720 MJPG**: više piksela na očima za isti FPS. Najdulja pauza između slika je 74 ms.
- 15 FPS i u maloj rezoluciji upućuje na to da kamera zbog slabog svjetla sama produljuje ekspoziciju. Treba ponoviti mjerenje uz dobro svjetlo.
- Za odluku na razini ekrana 15 FPS je dovoljno: u 0,4 s dwella stane oko 6 uzoraka.

**Zajednički učitavač configa (`shared/config.py`)**
- Strogo učitavanje YAML-a u dataclass premješteno je iz `app/config.py` u `shared/`, da ga `gaze/` koristi bez kopiranja koda i bez ovisnosti `gaze/` ↔ `app/`.
- Tipovi se sad čitaju preko `typing.get_type_hints`, a ne po imenima, pa je robusnije. Dodatno se odbija `bool` umjesto `int` i `int` umjesto `bool`.
- 64 testa prolaze.

**README** opisuje što projekt radi, arhitekturu, stanje, postavljanje i pokretanje.

### Kamera: pronađen i popravljen pad na 15 FPS

**Simptom:** `gaze.camera` je davao 15 FPS i uz ugašeno i uz upaljeno svjetlo.

**Dijagnoza, korak po korak** (sve provjere su samo čitale, osim jedne kratke probe čija je postavka vraćena):
1. Iz drivera su pročitani podržani načini rada (V4L2 `VIDIOC_ENUM_FRAMEINTERVALS`). MJPG 1280×720 i 640×480 podržavaju 30 FPS, a YUYV 1280×720 samo 10 FPS.
2. Postavke kamere: `exposure_auto = 3` (automatska ekspozicija) i `exposure_dynamic_framerate = 1`, što znači da kamera smije usporiti snimanje da dulje osvjetljava sliku.
3. Proba s privremeno ugašenim `exposure_dynamic_framerate` dala je 28,2 → 30,0 FPS. **Ali** 28,2 FPS i s tvorničkom postavkom nije objašnjavalo 15 FPS iz `gaze.camera`.
4. Jedina preostala razlika bila je `CAP_PROP_BUFFERSIZE = 1` u `gaze/camera.py`. Mjereno naizmjence u istom svjetlu:

| `BUFFERSIZE` | FPS |
| --- | --- |
| zadano (4) | 30,0 / 27,8 |
| 1 | 15,8 / 15,0 |

**Uzrok:** naša greška. `BUFFERSIZE = 1` je postavljen da se uvijek obrađuje svježa slika, ali s jednim međuspremnikom kamera nema kamo snimiti sljedeću sliku dok se trenutna čita, pa preskoči svaku drugu (30 / 2 = 15). Promjena nije bila izmjerena kad je uvedena. **Pouka:** svaku promjenu postavki kamere odmah izmjeriti.

Drugi, manji faktor je `exposure_dynamic_framerate`. Prvo mjerenje navečer, prije `camera.py`, dalo je 15 FPS i bez `BUFFERSIZE`, vjerojatno zbog slabog svjetla.

**Popravak**
- `BUFFERSIZE = 1` je maknut, a u kodu stoji komentar zašto se ne smije vratiti.
- **Svježina slike je riješena zasebnom niti.** Nit stalno čita kameru punom brzinom i čuva samo zadnju sliku. `read()` vraća najnoviju sliku koja još nije vraćena. Kad je obrada sporija od kamere, stare slike se preskaču (brojač `skipped`) umjesto da se gomilaju u redu, gdje bi bile stare i do ~130 ms (4 slike).
- **`camera.fixed_framerate`** (prekidač u `gaze/config.yaml`, zadano `true`): dok program radi, postavlja `exposure_dynamic_framerate = 0`, a na izlazu vraća staru vrijednost. To je Linux-only i radi se izravno preko V4L2 ioctla (`gaze/v4l2.py`), jer OpenCV tu postavku ne nudi. Na drugim platformama se samo zapiše u log. Ako se proces sruši s `kill -9`, postavka ostaje do ponovnog spajanja kamere ili restarta, što je bezopasno.
- Ako se kamera ne uspije otvoriti, postavka se i dalje vraća.

**Mjerenje nakon popravka** (1280×720 MJPG, uz upaljeno svjetlo):

| `fixed_framerate` | FPS | Najdulja pauza |
| --- | --- | --- |
| off | 29,9 | 40 ms |
| on | 29,9 | 41 ms |

Uz ovo svjetlo prekidač ne mijenja ništa. Razlika se očekuje navečer ili u tamnijoj sobi, što treba izmjeriti. Nakon oba pokretanja postavka kamere je vraćena na 1 (provjereno).

**Testovi:** 4 nova testa s lažnom kamerom provjeravaju svježe slike, preskakanje kod spore obrade, istek čekanja i uredno zatvaranje kad kamera ne daje slike. Ukupno 68 testova prolazi.

**Mjerenje u mraku** (Mateo, soba bez svjetla, 1280×720 MJPG):

| `fixed_framerate` | FPS | Najdulja pauza |
| --- | --- | --- |
| off | 15,0 | 74 ms |
| on | 29,9 | 39 ms |

Potvrđeno je da kamera u mraku sama prepolovi FPS i da je prekidač to sprječava. Zato je `fixed_framerate: true` zadana vrijednost. Otvoreno pitanje je je li tamnija i zrnatija slika u mraku dovoljna za pouzdano prepoznavanje šarenice. To se provjerava u koraku 2.

### Gaze engine, korak 2: značajke

**MediaPipe Face Landmarker** (`gaze/landmarks.py`)
- Način rada `VIDEO`, uz praćenje lica između slika. Vremenske oznake moraju strogo rasti, pa se po potrebi povećaju za 1 ms.
- Vraća 478 točaka (uključujući šarenice), 52 blendshapea i 4×4 matricu poze glave (rotacija + translacija u cm).
- `num_faces: 2`, da se primijeti druga osoba u kadru. Za značajke se uzima **najbliže lice**, ono s najvećim razmakom između zjenica.
- Izmjereno: **13–17 ms po slici** (p95 22 ms). To stane u 33 ms, pa se uz MediaPipe drži puna brzina od **30 FPS bez preskočenih slika**.

**Značajke** (`gaze/features.py`, čista matematika bez MediaPipea, 12 testova na umjetnim licima)
- **Poza glave:** pitch, yaw i roll (Eulerovi kutovi, R = Rz·Ry·Rx) i položaj glave x, y, z u cm. Predznak pitcha (je li gore + ili −) određuje se mjerenjem, ne pretpostavkom.
- **Položaj šarenice u oku**, za svako oko posebno:
  - `h`: položaj duž crte od kuta do kuta oka, od 0 do 1.
  - `v`: udaljenost od te crte, podijeljena sa širinom oka; pozitivno znači prema dolje u slici.
  - Ne ovisi o veličini lica ni o nagibu glave u ravnini slike (testirano).
- **Blendshapeovi:** `look_up`, `look_down` (prosjek oba oka) i `blink` po oku. Treptaj je `blink ≥ 0,5` (prekidač u configu).
- `eye_distance_px` služi kao mjera veličine lica, odnosno udaljenosti.
- `Face` je definiran u `features.py`, a ne u `landmarks.py`, da značajke i njihovi testovi ne uvoze MediaPipe.

**Alat za provjeru** (`python -m gaze.feature_probe`)
- Ispisuje vrijednosti uživo dvaput u sekundi. Slike se ne spremaju i ne prikazuju.
- `--compare` je vođeni test: 5 s gledanja u monitor, zatim 5 s u laptop. Zatim se za svaku značajku ispiše prosjek na oba ekrana i odvojivost **d′** = razlika prosjeka podijeljena sa zajedničkom standardnom devijacijom. d′ > 2 znači da se ekrani dobro razlikuju, a d′ > 4 vrlo dobro. Uzorci s treptajem se preskaču.
- Prva proba uživo: pitch od −15° do −20°, šarenica h ≈ 0,5, glava 46 cm od kamere.

**Prvo mjerenje odvojivosti ekrana** (`--compare`, Mateo, 5 s po ekranu, 151 uzorak po ekranu, bez treptaja i bez izgubljenog lica)

| Značajka | Monitor | Laptop | d′ |
| --- | --- | --- | --- |
| pitch | −19,6° | −6,5° | **7,7** |
| head_z | −41,5 cm | −39,7 cm | 6,0 |
| head_y | −15,0 | −16,2 | 4,0 |
| iris_v (L / D) | −0,110 / −0,115 | −0,049 / −0,052 | **3,5** |
| eye_distance_px | 95,6 | 99,2 | 2,8 |
| blink (L / D) | 0,04 | 0,10 / 0,11 | 2,4 / 1,5 |
| roll, yaw | | | 0,8 / 0,7 |
| look_up, look_down | | | 0,5 / 0,4 |
| head_x, iris_h | | | ≤ 0,3 |

Zaključci:
- **Poza glave (pitch) i položaj šarenice (iris_v) razlikuju ekrane neovisno jedno o drugome.** To je i više nego dovoljno za dva ekrana. Predznak pitcha je izmjeren: **pogled gore znači negativniji pitch**.
- head_z, head_y i eye_distance_px razlikuju ekrane samo zato što se korisnik pri gledanju laptopa nagne ~2 cm bliže. To je posljedica držanja tijela i ne mora se ponoviti u drugom snimanju. U koraku 3 treba usporediti model s tim značajkama i bez njih, na odvojenim snimanjima.
- Kad korisnik gleda dolje, `blink` raste, ali ostaje daleko od praga 0,5, pa nema lažnih treptaja.
- MediaPipeovi blendshapeovi za smjer pogleda (`eyeLookUp/Down`) gotovo ne razlikuju ekrane.
- d′ je ovdje vjerojatno optimističan: jedno kratko snimanje, a susjedne slike su jako slične. Pouzdan broj točnosti dat će kalibracija s točkama i provjera na odvojenom snimanju.

### Gaze engine, korak 3a: vodič preko cijelog ekrana

**Provjera prije gradnje:** zna li Qt na KDE Waylandu otvoriti prozor preko cijelog ekrana na zadanom ekranu i vidi li ekrane jednako kao KWin?
- Qt (platforma `wayland`) daje iste ekrane i koordinate kao KWin: 0 = HDMI-A-1 (0,0), 1 = eDP-1 (0,1080).
- Prozor otvoren preko cijelog ekrana na svakom ekranu provjeren je preko KWina, ne preko Qt-a. Oba su završila na traženom ekranu.

**Kako radi**
- `gaze/targets.py` (čista logika, 5 testova):
  - Mreža 5×3 točke po ekranu, s rubom od 8 %. Točke se obilaze zmijasto (red po red, naizmjeničnim smjerom), da pogled ne skače preko cijelog ekrana.
  - Raspored je izračunat unaprijed od trenutka početka: odbrojavanje 3 s, zatim za svaku točku 0,4 s smirivanja (oči putuju, ne snima se) i 0,6 s snimanja.
  - Uzorci se pridružuju točki po **vremenu snimanja slike**, a ne po vremenu obrade, pa kašnjenje MediaPipea ne kvari oznake.
- `gaze/overlay.py` (PySide6):
  - Ekran koji treba gledati ima osvijetljenu pozadinu, plavi rub, odbrojavanje u kutu i točku. Ostali ekrani su crni s uputom.
  - Dok se oči smiruju, oko točke je prsten koji se smanjuje. Kad prsten nestane i točka postane puna, snima se.
  - Kursor je skriven. Esc ili Ctrl+C prekida.
- `gaze/session.py`:
  - Kamera i MediaPipe rade u zasebnoj niti, jer Qt zauzima glavnu nit.
  - Vodič kreće tek kad kamera stvarno daje slike. Ako kamera zakaže usred rada, vodič se zaustavlja.
- `python -m gaze.feature_probe --compare` sad koristi ovaj vodič na svim ekranima.
- Postavke su u `gaze/config.yaml`, odjeljak `calibration`.

**Proba (skraćena mreža 2×1, bez gledanja):**
- Proba je došla do kraja i snimala je 30,1 uzorak u sekundi.
- Označeno je 59 uzoraka, a očekivano je 4 točke × 0,5 s × 30 = 60.
- KWin je vidio prozore na ispravnim ekranima, a postavka kamere je vraćena.

**Pronađena greška u PySide6 6.12.0**
- Simptom: `feature_probe --compare` se rušio (segmentation fault, `Fatal Python error: none_dealloc`) i kad bi se prekinuo i kad bi došao do kraja. Prva proba je prošla samo slučajno.
- Dijagnoza:
  - `coredumpctl` je pokazao pad unutar Qt crtanja.
  - `faulthandler` je pokazao `paintEvent` i poruku "deallocating None: bug likely caused by a refcount error in a C extension".
  - Mjereno crtanjem u memoriju, bez prozora: u PySide6 6.12.0 **svaki poziv Qt funkcije koja ne vraća vrijednost smanji brojač referenci na `None` za 1** (`fillRect`, `setPen`, `drawRect`, `drawEllipse`... −1000 na 1000 poziva). Uz 60 osvježavanja u sekundi brojač padne na nulu za nekoliko sekundi.
  - U Pythonu 3.12+ `None` je "besmrtan" i greška se ne vidi. Mi koristimo 3.11 zbog MediaPipea, pa nas pogađa.
- Provjereno: 6.11.3 i 6.10.3 nemaju grešku (brojač stalan, +17, ne raste s brojem poziva).
- **Odluka:** `PySide6-Essentials==6.11.3`, zakucano u `requirements.txt` uz obrazloženje. `Essentials` sadrži samo osnovne Qt module i zauzima ~244 MB (procjena prije mjerenja bila je ~100 MB).
- Nakon zamjene sva tri načina završetka rade uredno: normalni kraj, prekid iz koda jer kamera ne radi, i Ctrl+C. Postavka kamere se svaki put vraća.

**Pouka (druga danas):** jedna uspješna proba nije dokaz. Prekid i normalni kraj treba isprobati namjerno i više puta. Ovdje je to otkrilo grešku koja bi se inače pojavila usred demoa.

**Prvo pravo snimanje s vodičem** (Mateo, bez naočala, 5×3 točke po ekranu)
- 540 označenih uzoraka (očekivano 2 × 15 × 0,6 s × 30 = 540), nijedan bez lica, 1 treptaj.
- Razlike prosjeka: pitch −21,9° naspram −5,8° (16°), iris_v −0,10 naspram −0,04.
- d′ je pao na 2,1–2,5 (prije 7,7). To nije pogoršanje: točke sad pokrivaju cijeli ekran, pa je raspršenje unutar jednog ekrana veliko (vrh i dno istog ekrana). d′ preko cijelog ekrana zato ne predviđa točnost. Ono što odlučuje je preklapanje donjeg reda monitora i gornjeg reda laptopa, a to mjeri model u koraku 3b.
- Ponovno se vidi naginjanje prema laptopu (eye_distance_px 98 → 109, head_z −39,8 → −37,6 cm). Kod ovog korisnika je dosljedno, ali je to navika, a ne pogled.

### Gaze engine, korak 3b: kalibracija i model za ekran

**Što se sprema** (`gaze/calibration.py`, `python -m gaze.calibration --condition normal`)
- Jedno snimanje je jedna mapa u `data/calibration/<datum-vrijeme>_<uvjet>/` s dvije datoteke:
  - `meta.json`: uvjet, ekrani, korištena konfiguracija, broj uzoraka
  - `samples.npz`: po označenom uzorku cilj (ekran, x, y, broj točke) i sirovi izlaz MediaPipea (478 točaka, blendshapeovi, matrica glave)
- **Odluka: slike se ne spremaju, ali sprema se više od samih značajki.**
  - Slike nisu potrebne za model, a slike lica su osobni podaci, što je posebno važno kod korisničkog testa.
  - Sirove točke lica omogućuju ponovni izračun bilo koje značajke bez novog snimanja, a lice se iz njih ne može rekonstruirati kao slika.
  - Veličina: ~2 MB po punom snimanju (izmjereno 142 KB za skraćeno od 120 uzoraka), naspram ~50 MB sa slikama.
- Postojeće snimanje se nikad ne prepisuje. Oznaka uvjeta smije sadržavati samo mala slova, brojke, `_` i `-`.

**Modeli** (`gaze/models.py`)
- `threshold(pitch)`: jedan prag na nagibu glave. To je najjednostavnija osnova, za usporedbu s ML-om.
- `logreg`: logistička regresija na standardiziranim značajkama (nova ovisnost: `scikit-learn`).
- Skupovi značajki:
  - `head`: pitch, yaw, roll
  - `eyes`: iris h i v za oba oka
  - `head+eyes`
  - `head+eyes+posture`: plus head_x, head_y, head_z i eye_distance_px. To su značajke koje ovise o tome kako korisnik sjedi.

**Pošteno mjerenje točnosti** (`python -m eval.screen_accuracy`)
- Uzastopne slike s iste točke gotovo su jednake. Nasumična podjela na učenje i test zato bi "procurila" i napuhala točnost.
- Zato se drži van **cijela točka**: model se uči na svim ostalim točkama i testira na izostavljenoj (leave-one-point-out), i tako za svaku od 30 točaka.
- Ispis daje točnost za svaki model i skup značajki, a za najbolji i točnost po redu točaka. Tako se vidi koliko se griješi blizu ruba između ekrana.
- S dva ili više snimanja dodatno se uči na jednom i testira na drugom (npr. `normal` → `naocale`).
- Točnost je po slici s kamere, prije dwella i histereze u `app/`. Stvarnih krivih prebacivanja fokusa bit će manje.
- Snimanje koje se ne može pošteno izmjeriti odbija se s jasnom porukom, umjesto da se program sruši. To je slučaj kad neki ekran nema lice na barem dvije točke. Ako više od 20 % uzoraka nema lice, ispisuje se upozorenje.

**Proba:** skraćeno snimanje (2×2 točke) pokrenuto bez najave, dok korisnik nije gledao, imalo je lice na samo 41 od 120 uzoraka, i to samo na jednom ekranu. To je otkrilo pad u mjerenju kad za neki ekran nema podataka, pa je dodana provjera iznad. Snimanje je spremljeno u privremenu mapu, ne u `data/`.

`Sample` iz `gaze/session.py` sad čuva sirovo lice (`Face`) umjesto izračunatih značajki, da se pri spremanju ništa ne izgubi.

92 testa prolaze.

**Prvi broj točnosti** (Mateo, uvjet `normal`, bez naočala, 10.11.2026. 20:47)
- Snimanje `20261110-204709_normal`: 539 uzoraka, svi s licem. 10 treptaja je preskočeno, 529 je korišteno.
- Točnost po slici, leave-one-point-out:

| Model | Značajke | Točnost |
| --- | --- | --- |
| prag | pitch | 99,6 % |
| logreg | head | **99,8 %** |
| logreg | eyes | 97,2 % |
| logreg | head+eyes | 98,9 % |
| logreg | head+eyes+posture | 99,6 % |

- Po redovima točaka (logreg head): svi redovi imaju 100 %, osim donjeg reda monitora (98,9 %, 1 greška od 90). Kao što se očekivalo, griješi se samo uz rub između ekrana.
- Zaključci:
  - Za ovog korisnika u ovim uvjetima i **jedan prag na nagibu glave** razlikuje ekrane skoro savršeno. U skladu s pravilom "jednostavno ima prednost" to je ozbiljan kandidat za demo.
  - Oči same daju 97 %, što znači da se i korisnik koji manje pomiče glavu može dobro razlikovati. Dodavanje očiju glavi ovdje malo smanjuje točnost (98,9 % naspram 99,8 %), jer je šarenica šumovitija od poze glave.
  - **Oprez:** ovo je jedan korisnik, jedno snimanje i isti uvjeti za učenje i test. Ovaj korisnik pomiče glavu za 13–16°. Pravu sliku robusnosti dat će snimanja u drugim uvjetima (naočale, prigušeno svjetlo, drukčije držanje, drugi dan) i uz druge ljude. Izbor između praga i logreg-a ostavlja se za taj trenutak.
  - Točnost je po slici. U `app/` odluku donosi tek pogled koji traje 0,4 s, pa se pojedinačna kriva slika ne pretvara u krivo prebacivanje.

**Naočale kao uvjet** (Mateo, nedioptrijske naočale, 20:50, isto držanje)
- Snimanje `20261110-205000_naocale`: 540 uzoraka, svi s licem, 3 treptaja preskočena.

| Model | Značajke | naočale (LOPO) | normal → naočale | naočale → normal |
| --- | --- | --- | --- | --- |
| prag | pitch | 99,8 % | **99,8 %** | **99,8 %** |
| logreg | head | 100,0 % | 98,7 % | 100,0 % |
| logreg | eyes | 89,4 % | **76,9 %** | 88,7 % |
| logreg | head+eyes | 98,5 % | 96,3 % | 98,9 % |
| logreg | head+eyes+posture | 99,6 % | 96,6 % | 98,9 % |

Zaključci:
- **Značajke očiju su osjetljive na naočale.** Unutar snimanja s naočalama padaju sa 97,2 % na 89,4 %. Kad se model nauči bez naočala, a testira s njima, padaju na **76,9 %**. Vjerojatno okvir i odsjaji pomiču točke šarenice ili kutova oka koje MediaPipe pronalazi. Ovo je nalaz za dio rada o robusnosti.
- **Poza glave je robusna.** Prag na pitchu drži 99,8 % u oba smjera, a izgleda da je **najrobusniji od svih**. logreg na glavi gubi malo pri prijelazu bez naočala → s naočalama (98,7 %), vjerojatno zato što koristi i yaw i roll, koji se između snimanja malo pomaknu.
- Dodavanje očiju glavi pri prijelazu između uvjeta šteti (96,3 % naspram 98,7 % i 99,8 %).
- **Odluka za demo (spajanje 1):** zadani model je **prag na pitchu**. Najjednostavniji je, determinističan i najrobusniji na izmjerenim podacima. logreg ostaje kao opcija u configu.
- **Oprez:** dva snimanja iste večeri, jedan korisnik koji puno pomiče glavu. Za korisnika koji pomiče samo oči prag na glavi bi bio lošiji, a upravo su oči osjetljive na naočale. To treba provjeriti na korisničkom testu.

### Gaze engine, korak 4: `gaze/main.py`, kamera prebacuje fokus

**Tok:** kamera → MediaPipe → značajke → One Euro zaglađivanje → model → UDP poruka. `app.main` ostaje nepromijenjen i ne zna razliku između kamere i mocka.

**Odluke**
- **Model se uči pri pokretanju** iz spremljene kalibracije. To traje manje od sekunde, pa nema zasebne datoteke modela koja bi mogla zastarjeti. Zadano se uzima najnovije snimanje, a `--condition normal` uzima najnovije s tim uvjetom, `--recording DIR` točno zadano.
- **Zadani model je prag na pitchu** (vidi mjerenja s naočalama). `model.kind: logreg` je opcija.
- **`conf` za prag** = sigmoid(udaljenost od praga / 2°). Na samom pragu je 0,5. To je ispod praga aplikacije (0,6), pa se odluka na samom rubu između ekrana namjerno ignorira. Pri 2° od praga `conf` je 0,73, a pri 6° 0,95.
- **`screen = null`** kad je `conf < 0,55` ("nije siguran", prema protokolu) ili kad nema lica.
- **One Euro filter** (Casiez i sur., 2012) na vektoru značajki: jako zaglađuje dok glava miruje, malo dok se brzo pomiče. Kad se lice izgubi na više od 0,5 s, filter kreće ispočetka. Ima prekidač `smoothing.enabled`, da se može mjeriti sa zaglađivanjem i bez njega.
- `x` i `y` se zasad šalju kao sredina ekrana (0,5). Trebaju tek za prebacivanje po prozorima (spajanje 2).
- Slanje UDP-a nikad ne zaustavlja engine. Greška se samo broji i zapiše u log jednom.

**Proba (bez `app.main`, poruke je hvatao obični slušač)**
- Prag naučen iz `normal`: −9,4°. Iz `naocale`: −8,5°. Na podacima za učenje oba daju 100 %.
- 30 FPS, MediaPipe 13 ms po slici. U 6 s stiglo je 179 poruka, sve ispravne prema `shared/protocol.py`.
- **Kašnjenje od snimanja slike do primanja poruke: medijan 12 ms, p95 19 ms.**
- Postavka kamere je nakon Ctrl+C vraćena.

97 testova prolazi. Novi testovi pokrivaju One Euro filter (uklanja šum, prati skok, kreće ispočetka nakon prekida), `conf` za prag (0,5 na pragu) i izgled poruke (nesiguran, bez lica, treptaj).

**Prvi pravi demo: pogled prebacuje fokus** (Mateo, 10.11.2026. 21:09)
- `app.main` i `gaze.main --condition normal`, uz OBS koji istovremeno snima kameru. Na svakom ekranu je bio po jedan VS Code prozor, u koji se tipkalo da se provjeri kamo ide fokus.
- U 37 s bilo je 9 prebacivanja fokusa između ekrana, sva ispravna (potvrđeno tekstom utipkanim u prozor na svakom ekranu). Od uzorka koji je odlučio do prebacivanja prošlo je 13–26 ms.
- 1 neuspjeh na kraju: `focus '' [HDMI-A-1] -> FAILED`. Ciljni prozor bez naslova nakon toga više nije postojao, pa je to bio privremeni prozor (dijalog koji se otvarao ili zatvarao). KWin ga nije htio aktivirati.

**Dijeljenje kamere s OBS-om**
- Preko V4L2 kameru može otvoriti samo jedan program: kad je OBS koristi, `gaze.main` javlja `cannot open camera 0`.
- Rješenje: OBS (Flatpak) čita kameru preko PipeWirea, a naš program se pokreće kroz `pw-v4l2` (paket `pipewire-v4l2`), koji V4L2 pozive preusmjerava na PipeWire. Tada oba programa dijele kameru.
- Rješenje s `v4l2loopback` odbačeno je jer je Secure Boot uključen, pa bi kernel modul trebalo potpisivati.
- Ograničenje: svi korisnici dijeljene kamere dobivaju format koji je dogovorio prvi (OBS: **640×480 YUYV**). Uz to je izmjereno 30 FPS i MediaPipe 14–18 ms. Prag naučen na kalibraciji u 1280×720 radio je bez vidljivog pogoršanja, ali točnost u 640×480 nije posebno izmjerena.
- `exposure_dynamic_framerate` je dok je OBS radio bio 0. Postavio ga je OBS, ne mi. Naš program vraća vrijednost koju je zatekao, pa je ne mijenja.

### Dorade za demo

**Rezerva kad aktivacija ne uspije** (`app/mapping.py`, `app/main.py`)
- Kandidati su svi prozori na ciljnom ekranu, poredani od gornjeg prema donjem. Ako KWin odbije aktivirati prvi (npr. dijalog koji se upravo zatvara), pokušava se sljedeći, najviše 3 prozora.
- Kašnjenje u logu sad se mjeri **nakon** uspješnog prebacivanja, a ne prije.
- `GazeReceiver` se stvara prije backenda, pa zauzet port ne ostavlja otvoren backend.

**Isticanje fokusiranog prozora**
- Prvo je isproban vlastiti okvir kao Qt prozor preko cijelog ekrana (Tool, Frameless, StaysOnTop, WindowDoesNotAcceptFocus, TransparentForInput). **Na KWin Waylandu to ne radi:** prozor je pri otvaranju ukrao fokus, pao je ispod sljedećeg aktiviranog prozora, a KWin ga vidi kao normalan prozor, pa bi ga naša aplikacija mogla pokušati fokusirati. Sve je provjereno preko KWina.
- **Odluka:** koristi se ugrađeni KWin efekt **"Dim Inactive"** (`diminactive`), koji zatamni sve prozore osim aktivnog. Nema crtanja i nema novih prozora.
  - Efekt se uključuje preko D-Bus-a (`org.kde.KWin /Effects loadEffect`) samo dok `app.main` radi. Ne zapisuje se u korisnikove postavke (`kwinrc` ostaje nepromijenjen, provjereno).
  - Na izlazu se isključuje **samo ako ga je uključio `app.main`**. Ako ga korisnik već koristi, ostaje kako je bio (provjereno).
  - Isključuje se i na Ctrl+C i na `kill` (SIGTERM), provjereno. Nakon `kill -9` ostaje uključen do odjave ili do: `busctl --user call org.kde.KWin /Effects org.kde.kwin.Effects unloadEffect s diminactive`.
  - Ima prekidač `highlight.dim_inactive` u `app/config.yaml`. Kod je u KDE backendu (`start_highlight` / `stop_highlight`). Na drugim platformama zasad nema isticanja.
- Vlastiti okvir ostaje ideja za platforme bez takvog efekta.

**Ideja za budućnost (Mateo):** zbog privatnosti bi dok OKOM radi samo on smio koristiti kameru, da nitko drugi ne može snimati korisnika sa strane. Tijekom razvoja to nije potrebno: sad se kamera namjerno dijeli s OBS-om preko `pw-v4l2`. U radu ide pod buduće značajke, kao prekidač u konfiguraciji.

99 testova prolazi.

### Dorade prebacivanja ekrana (prije Napretka I)

**Aplikacija prati promjene fokusa izvana**
- Dosad `app.main` nije znao kad korisnik sam klikne prozor na drugom ekranu ili napravi Alt+Tab. To je bilo poznato ograničenje iz koraka 3.
- Sad stalno učitana KWin skripta (`okom_focus`) javlja svaku promjenu aktivnog prozora (`workspace.windowActivated`), zajedno s ekranom na kojem je prozor. `ScreenDecider.set_current()` time drži stanje u skladu sa stvarnošću. Dwell prema ekranu koji je upravo dobio fokus se odbacuje.
- Kod za stalno učitane skripte (miš i fokus) spojen je u jednu klasu `_PersistentScript`: vlastita D-Bus veza, uklanjanje zaostale skripte nakon pada, potvrda primljenih poruka.
- Provjereno na sustavu: fokus prebačen izvana tamo i natrag oba je puta prepoznat ("focus moved to screen 1/0 outside OKOM"). Obje skripte se na izlazu uklone, a miš za `mock_gaze` i dalje radi.
- Ponašanje koje treba znati: ako korisnik klikne prozor na jednom ekranu, a dulje od dwella gleda drugi, fokus se vraća na ekran koji gleda. Upravo to aplikacija i treba raditi.

**Čišći ispis**
- MediaPipe pri učitavanju modela ispisuje pet bezopasnih C++ poruka (`Logging before InitGoogle`, `XNNPACK delegate`, `inference_feedback_manager`). Mjerenjem je utvrđeno da sve nastaju pri učitavanju, a nijedna tijekom obrade slika.
- Zato se samo za vrijeme učitavanja C-razinski stderr (fd 2) preusmjerava u privremenu datoteku. Ako učitavanje ne uspije, uhvaćeni tekst se ispiše kao greška. Ispisuje se tek nakon što je fd 2 vraćen, jer bi inače i sama poruka o grešci završila u datoteci (greška uočena pri pregledu koda, prije pokretanja).
- Prekidač `landmarks.quiet_native_logs` (zadano `true`).

102 testa prolaze.

### Uredno gašenje na SIGTERM i Ctrl+C

Pronađeno pri planiranju launchera, koji programe zaustavlja signalom SIGTERM:
- `gaze.main` i `gaze.calibration` na SIGTERM se nisu gasili uredno, pa postavka kamere nije bila vraćena. Sad SIGTERM radi isto što i Ctrl+C (`shared/signals.py`, zajedničko i za `app.main`).
- **Pad Qt-a pri prekidu kalibracije signalom** (segmentation fault u 3 od 16 pokušaja, s nasumičnim trenutkom prekida). Uzrok: Python obradi signal između bilo koje dvije naredbe u glavnoj niti, dakle i usred `paintEvent`, a gašenje Qt-a odatle ruši Qt-ov Wayland kod. Popravak: obrada signala samo postavlja zastavicu, a stvarno gašenje radi tajmer od 16 ms, izvan crtanja. Nakon toga je bilo 0 padova u 30 pokušaja, a s kamerom 12 od 12 prekida u raznim trenucima bez pada i uz vraćenu postavku kamere.
- Ako se kalibracija prekine dok se kamera još pokreće, nit kamere se sad uredno zaustavi prije izlaza.

### Launcher: jedan prozor za kalibraciju i pokretanje (`python -m okom`)

**Zašto:** dosad su trebala dva terminala i tri naredbe. Na novom računalu (npr. u učionici) ili za sudionika korisničkog testa to je nepraktično, a lako pokretanje je i samo po sebi tema komunikacije čovjeka i stroja. Ideja je Mateova.

**Kako radi**
- Mali prozor (PySide6, tekst na engleskom kao i vodič) prikazuje stanje: ekrane u protokolnom redoslijedu, backend za fokus, je li MediaPipe model preuzet i zadnju kalibraciju za upisani uvjet. Ako je kalibracija snimljena s drukčijim ekranima, prikazuje se upozorenje.
- Gumbi: **Calibrate** (vodič s točkama), **Start / Stop**, **Hide to tray** (ikona u traci sustava s izbornikom Show / Start / Quit). Kvačica **Share camera (OBS)** pokreće kameru kroz `pw-v4l2`.
- **Launcher samo pokreće postojeće programe** (`app.main`, `gaze.main`, `gaze.calibration`) kao zasebne procese, preko `QProcess`. Arhitektura s dva procesa i UDP-om ostaje ista, a svaki program i dalje radi i sam iz terminala.
- Gumbi su onemogućeni kad nemaju smisla: Start bez kalibracije, Calibrate dok program radi, jer oba trebaju kameru.
- **Stop** šalje SIGTERM, a nakon 5 s SIGKILL ako proces još radi. Ako se jedan od dva programa sam ugasi, launcher zaustavi i drugog, prikaže grešku i otvori log. Zatvaranje prozora zaustavlja sve i gasi launcher.
- Logovi oba procesa vide se u skrivenom prikazu "Show log" (zadnjih 1000 redaka, s oznakom `[app]` / `[gaze]` / `[calibration]`).
- Logika bez Qt-a (naredbe, zadnja kalibracija po uvjetu, opis starosti) je u `okom/commands.py` i ima testove.

Za uredno zaustavljanje launcher se oslanja na gašenje na SIGTERM (odjeljak iznad).

**Provjereno (launcher upravljan iz skripte, slike prozora pregledane):**
- Start pokreće oba procesa i uključuje zatamnjenje.
- Stop ih gasi, isključuje zatamnjenje i vraća postavku kamere.
- Calibrate s uvjetom bez snimanja: Start je onemogućen. Prekinuta kalibracija ništa ne sprema i vraća launcher u stanje mirovanja.

105 testova prolazi.

### Povratna informacija pri kalibraciji

**Problem (Mateo):** ako se tijekom kalibracije ne gleda pravi ekran ili kamera ne vidi lice, kalibracija se spremi, a greška se vidi tek kad `gaze.main` ne može naučiti model ili radi loše.

**Upozorenje uživo** (`gaze/overlay.py`, `gaze/session.py`)
- Nit kamere pamti kad je zadnji put vidjela lice. Ako lica nema dulje od `calibration.face_warning_s` (0,5 s), rub aktivnog ekrana postaje crven, a na dnu piše *"Can't see your face: face the camera and check the light"*. Korisnik problem vidi odmah i može ga ispraviti dok snimanje traje.
- Snimanje se ne prekida: uzorci bez lica se ionako ne koriste.
- Je li korisnik gledao **pravi** ekran ne može se pouzdano znati za vrijeme snimanja, jer model tada još ne postoji. Zato postoji ocjena na kraju.

**Ocjena kvalitete nakon snimanja** (`gaze.models.assess`, `gaze.calibration.record_quality`)
- Odmah nakon spremanja snimanje se ocijeni istom metodom kao `eval.screen_accuracy` (leave-one-point-out), s modelom iz konfiguracije. Rezultat se zapisuje u `meta.json` kao polje `quality`.
- Tri ishoda, s porukom koja kaže što napraviti:
  - **good** (≥ `calibration.good_accuracy`, 95 %): npr. *"screens told apart in 99.6 % of frames"*
  - **weak**: *"screens told apart in only 72 % of frames: they look too alike to the camera. Follow the dot on each screen and calibrate again"*
  - **unusable** (lice viđeno na manje od 2 točke nekog ekrana): *"face seen at only 0 of 15 points on screen 1 (eDP-1): look at that screen during its part…"*
  - Ako više od 20 % uzoraka nema lice, poruka dodaje *"check the light"*.
- Launcher uz kalibraciju prikazuje ocjenu u boji (zeleno, narančasto, crveno), a nakon kalibracije i poruku. **Start je onemogućen za neupotrebljivu kalibraciju.** Kod slabe kalibracije odluka je na korisniku.
- `gaze.main` za neupotrebljivu kalibraciju umjesto tracebacka javlja razlog i "calibrate again".

**Naknadno ocijenjena postojeća snimanja** (u `meta.json` dodano je samo polje `quality`, ostalo je provjereno nepromijenjeno):

| Snimanje | Ocjena |
| --- | --- |
| `20261110-204709_normal` | good, 99,6 % |
| `20261110-205000_naocale` | good, 99,8 % |
| `20261110-215841_normal` (snimljeno preko launchera) | good, **96,5 %** |

Treće snimanje je primjetno slabije od prvog u istim uvjetima: donji red monitora ima 86,7 %, a donji red laptopa 94,4 %. **Točnost dakle varira između kalibracija iste osobe**, za ~3 postotna boda. To je argument za prikaz ocjene u GUI-ju i nalaz za rad: jedna kalibracija nije dovoljna za pouzdan broj, treba ih više.

**Greška pronađena pri prvoj probi (Mateo: "ne da mi kalibrirati"):** nit za snimanje dobila je atribut `_started`, a to ime već interno koristi Pythonov `threading.Thread`. `start()` se zato srušio (`'float' object has no attribute 'is_set'`), pa kalibracija nije ni krenula. Ista vrsta greške dogodila se danas već jednom (`_stop`). Test nije pomogao jer je objekt stvarao zaobilazeći konstruktor.
- Popravak: atribut je preimenovan u `_ready_at`.
- **Novi test** čita imena atributa koje koriste metode klase `_Recorder` i provjerava da se nijedno ne poklapa s privatnim atributima klase `Thread`. Provjereno je da test pada kad se greška vrati.
- Nakon popravka kalibracija na sustavu prolazi do kraja, sprema se i dobiva ocjenu.

112 testova prolazi.

### Zapisivanje logova u datoteke

**Zašto (Mateo):** lakše traženje grešaka. Današnji pad kalibracije vidio se samo u terminalu, a iz launchera se ne bi vidio ni toliko.

**Kako radi** (`shared/logs.py`)
- Svaki program (`app`, `gaze`, `calibration`, `mock_gaze`, `feature_probe`, `launcher`) uz terminal piše i u vlastitu datoteku po pokretanju: `data/logs/<datum-vrijeme>_<program>.log`.
- Prvi redak datoteke je točna naredba. Svaki zapis ima datum, milisekunde, razinu, nit i modul.
- **Neuhvaćene greške**, i u glavnoj i u pozadinskim nitima, upisuju se s cijelim tracebackom prije nego program završi (`sys.excepthook`, `threading.excepthook`).
- Čuva se zadnjih 30 datoteka po programu, a starije se brišu.
- Ako se datoteka ne može napisati (npr. disk samo za čitanje), program radi dalje i samo to javi.
- Launcher ima gumb **Open logs** koji otvara mapu. U svoju datoteku zapisuje koje je procese pokrenuo i s kojim su izlaznim kodom završili.
- Dijagnostički alati (`detect`, `kde_wayland`, `camera`, `eval`) i dalje pišu samo u terminal.

**Privatnost:** logovi aplikacije sadrže **naslove prozora**, a oni mogu biti osobni (npr. ime razgovora). `data/` se nikad ne commita. Prije korisničkog testa treba odlučiti hoće li se naslovi u logu skrivati.

**Provjereno na sustavu:** `app` i `gaze` napisali su svoje datoteke, a namjerni pad (nepostojeća kalibracija) završio je u datoteci kao `CRITICAL uncaught exception` s cijelim tracebackom.

115 testova prolazi.
