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
