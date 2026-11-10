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
| Kamera | gotovo |
| Značajke lica, kalibracija, model | u izradi |
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

**Prebacivanje ekrana mišem umjesto pogleda**, u dva terminala:

```bash
python -m app.main        # aplikacija
python -m app.mock_gaze   # lažni pogled
```

Pomakni miš na drugi ekran i zadrži ga tamo oko pola sekunde. Fokus prelazi na gornji prozor na tom ekranu.

**Provjere:**

```bash
python -m app.backends.detect        # koji je backend odabran i vidi li prozore
python -m app.backends.kde_wayland   # popis ekrana i prozora
python -m gaze.camera                # otvara kameru i mjeri FPS, ne sprema slike
pytest                               # testovi
ruff check . && ruff format .        # lint i format
```

## Postavke

- `app/config.yaml`: dwell, pauza, prag pouzdanosti, port, parametri lažnog pogleda.
- `gaze/config.yaml`: kamera.

Nepoznat ili nedostajući ključ u konfiguraciji je greška, pa se tipfeler odmah vidi.

## Privatnost

Snimke lica, kalibracijski podaci i logovi spremaju se u `data/` i nikad se ne commitaju. Gaze engine ne sprema video, za modele su dovoljne značajke.
