# Suffolk Village Signs

A static website tracking cycling visits to Suffolk settlements, built from geotagged iPhone photos.

## Setup

```bash
cd village-signs
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

## Workflow

1. Export photos from iCloud Photos into the `photos/` folder (HEIC format is fine).
2. Run the build script:

```bash
python scripts/build.py
```

3. Preview locally by opening `docs/index.html` in a browser.
4. Push to GitHub — the site is served from the `docs/` folder on the `main` branch.

To add new photos, drop them into `photos/` and re-run the build script.

## Options

```bash
# Re-fetch settlement data from OpenStreetMap (first run, or to pick up new data)
python scripts/build.py --refresh-settlements
```

## GitHub Pages setup

1. Create a new repository on github.com and push this project to it.
2. Go to **Settings → Pages**.
3. Set source to **Deploy from a branch**, branch `main`, folder `/docs`.
4. Save — your site will be live at `https://<your-username>.github.io/<repo-name>/`.

## How it works

| Step | What happens |
|------|-------------|
| Scan | Reads all HEIC/JPEG files in `photos/` that contain GPS data |
| Deduplicate | Photos within 50 m of each other are treated as one visit; most recent is kept |
| Match | Each photo is matched to the nearest Suffolk settlement within 1.5 km using OpenStreetMap data |
| Export | Photos are resized to max 1200 px and saved as JPEG into `docs/photos/` |
| Output | `docs/data.json` is written with all visited and unvisited settlements |

Settlement data (hamlets, villages, towns) is fetched from OpenStreetMap on first run and cached in `data/settlements.json`.
