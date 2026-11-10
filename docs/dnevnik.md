# Dnevnik rada

Kronološki zapis važnih radnji i odluka. Najnovije na dnu.

## 10.11.2026.

### Repozitorij
- Napravljen repozitorij na GitHubu (`AceTep/okom`). Glavna grana je `main`, a rad ide na granama `mateo/...`.
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
