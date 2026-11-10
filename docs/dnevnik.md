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
