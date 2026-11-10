# OKOM – fokus prozora pogledom

Aplikacija prati pogled korisnika običnom web kamerom i prebacuje fokus tipkovnice na ekran ili prozor u koji korisnik gleda, bez miša i bez Alt+Taba.

Seminarski projekt za kolegij Komunikacija čovjek–stroj, FIDIT, 2026./2027.

## Kako radi

Dva neovisna procesa razgovaraju samo preko UDP-a:

```
kamera → gaze/ ──UDP 127.0.0.1:5555, JSON──→ app/ → fokus prozora
```

- **`gaze/`** procjenjuje na koji ekran i u koju točku korisnik gleda. Ne zna ništa o prozorima.
- **`app/`** odlučuje kada prebaciti fokus i na koji prozor (dwell, pauza, preskakanje treptaja). Ne zna ništa o kameri.
- **`shared/protocol.py`** definira poruku koju obje strane koriste.

Dok gaze engine nije gotov, `app/mock_gaze.py` šalje iste poruke, a pogled glumi pozicija miša s dodanim šumom i kašnjenjem.

## Stanje

| Dio | Stanje |
| --- | --- |
| Protokol poruke | gotovo |
| Prebacivanje fokusa na KDE Plasma 6 (Wayland i X11) | gotovo |
| Odluka o prebacivanju između ekrana + lažni pogled mišem | gotovo, ručno isprobano |
| Kamera, značajke lica (poza glave, šarenica) | gotovo |
| Vodič preko cijelog ekrana (točke za kalibraciju) | gotovo |
| Kalibracija, model za ekran, mjerenje točnosti | gotovo (99,8 % po slici, i s naočalama) |
| Prebacivanje ekrana pogledom, kamera → aplikacija (`gaze/main.py`) | gotovo |
| Launcher (`python -m okom`): kalibracija, start/stop, traka sustava | gotovo |
| Prebacivanje po prozorima (točka pogleda) | nije počelo |
| Windows, Hyprland, Sway, GNOME | nije počelo |

Detaljan zapis odluka i mjerenja je u [`docs/dnevnik.md`](docs/dnevnik.md).

## Postavljanje

Treba Python 3.11 jer MediaPipe nema wheel za novije verzije. Najlakše je preko [`uv`](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.11
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
python scripts/download_models.py  # MediaPipe model u models/
```

## Pokretanje

Okruženje mora biti aktivno (`source .venv/bin/activate`) u svakom terminalu.

**Najlakše, preko launchera:**

```bash
python -m okom
```

Otvara se prozor sa stanjem (ekrani, backend, model, kalibracija s ocjenom kvalitete) i gumbima **Calibrate**, **Start / Stop** i **Hide to tray**. Ako kamera tijekom kalibracije ne vidi lice, vodič to odmah javi, a nakon kalibracije launcher kaže je li dobra. Kvačica **Share camera (OBS)** dijeli kameru s OBS-om. Launcher samo pokreće programe ispod, pa sve radi i iz terminala:

**Prebacivanje ekrana pogledom iz terminala**: prvo jednom kalibracija, zatim dva terminala:

```bash
python -m gaze.calibration --condition normal   # jednom: prati točku po oba ekrana
python -m app.main                              # terminal 1: aplikacija
python -m gaze.main --condition normal          # terminal 2: kamera
```

Pogledaj drugi ekran i zadrži pogled oko pola sekunde. Fokus prelazi na gornji prozor na tom ekranu. Na KDE-u su dok `app.main` radi svi ostali prozori zatamnjeni, da se vidi koji ima fokus.

Ako OBS istovremeno koristi kameru, pokreni `gaze` kroz PipeWire: `pw-v4l2 python -m gaze.main --condition normal` (paket `pipewire-v4l2`).

**Isto bez kamere, miš glumi pogled**, u dva terminala:

```bash
python -m app.main        # aplikacija
python -m app.mock_gaze   # lažni pogled
```

Pomakni miš na drugi ekran i zadrži ga tamo oko pola sekunde. Fokus prelazi na gornji prozor na tom ekranu.

**Točnost:**

```bash
python -m eval.screen_accuracy        # točnost na svim snimanjima iz data/calibration/
```

**Provjere:**

```bash
python -m app.backends.detect        # koji je backend odabran i vidi li prozore
python -m app.backends.kde_wayland   # popis ekrana i prozora
python -m gaze.camera                # otvara kameru i mjeri FPS, ne sprema slike
python -m gaze.feature_probe         # značajke uživo u terminalu
python -m gaze.feature_probe --compare  # prati točku po ekranima, usporedi značajke
pytest                               # testovi
ruff check . && ruff format .        # lint i format
```

## Postavke

- `app/config.yaml`: dwell, pauza, prag pouzdanosti, port, isticanje fokusiranog prozora, parametri lažnog pogleda.
- `gaze/config.yaml`: kamera, MediaPipe, prag treptaja, mreža i trajanje točaka, model, zaglađivanje.

Nepoznat ili nedostajući ključ u konfiguraciji je greška, pa se tipfeler odmah vidi.

## Privatnost

Snimke lica, kalibracijski podaci i logovi spremaju se u `data/` i nikad se ne commitaju. Gaze engine ne sprema video, za modele su dovoljne značajke.
