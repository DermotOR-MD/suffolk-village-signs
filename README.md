# Suffolk Village Signs

A static website tracking cycling visits to Suffolk settlements, built from geotagged iPhone photos.

## Setup

```bash
cd village-signs
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

## Adding new photos

1. Take a geotagged photo and add it to the **Village Signs** album in Photos.
2. Double-click **`update-site.command`** — it reads directly from your Photos library, builds the site, and pushes to GitHub.

Your site will update within a minute.

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
| Scan | Reads all photos in the **Village Signs** Photos album that contain GPS data |
| Deduplicate | Photos within 50 m of each other are treated as one visit; most recent is kept |
| Match | Each photo is matched to the nearest Suffolk settlement within 1.5 km using OpenStreetMap data |
| Export | Photos are resized to max 1200 px and saved as JPEG into `docs/photos/` |
| Output | `docs/data.json` is written with all visited and unvisited settlements |

Settlement data (hamlets, villages, towns) is fetched from OpenStreetMap on first run and cached in `data/settlements.json`.
