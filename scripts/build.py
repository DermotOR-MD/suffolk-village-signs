#!/usr/bin/env python3
"""
Suffolk Village Signs — build script.

Usage:
    python scripts/build.py                    # normal build
    python scripts/build.py --refresh-settlements  # re-fetch OSM data
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import osxphotos
import requests
from PIL import Image, ImageOps
from geopy.distance import geodesic

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    print("Error: pillow-heif not installed. Run: pip install -r scripts/requirements.txt")
    sys.exit(1)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
PHOTOS_OUT = ROOT / "docs" / "photos"
DATA_DIR   = ROOT / "data"
DOCS_DIR   = ROOT / "docs"
SETTLEMENTS_FILE = DATA_DIR / "settlements.json"
DATA_OUT         = DOCS_DIR / "data.json"

# ── Config ────────────────────────────────────────────────────────────────────
ALBUM_NAME      = "Village Signs"
HOME_COORDS     = (52.2355, 0.9014)   # Elmswell, IP30 9HD (approx.)
CLUSTER_RADIUS_M = 50
CLUSTER_MINUTES  = 2
MATCH_RADIUS_KM  = 1.5
MAX_PHOTO_PX     = (1200, 1200)


# ── Photo loading & deduplication ─────────────────────────────────────────────

def load_photos_from_library():
    """Load photos from the macOS Photos album, reading directly from the library."""
    db = osxphotos.PhotosDB()
    album_photos = db.photos(albums=[ALBUM_NAME])
    print(f"  Found {len(album_photos)} photos in '{ALBUM_NAME}' album")

    photos = []
    for p in album_photos:
        lat, lon = p.location
        if lat is None or lon is None:
            print(f"  skip  {p.original_filename}  (no GPS)")
            continue
        path = p.path
        if path is None:
            print(f"  skip  {p.original_filename}  (not downloaded from iCloud)")
            continue
        try:
            img = Image.open(path)
            photos.append({
                "path":     Path(path),
                "img":      img,
                "coords":   (lat, lon),
                "datetime": p.date.replace(tzinfo=None),
            })
        except Exception as exc:
            print(f"  error {p.original_filename}: {exc}")

    return photos


def cluster_photos(photos):
    """Group photos within CLUSTER_RADIUS_M metres AND CLUSTER_MINUTES of each other.

    Returns a list of clusters; each cluster is a list of photo dicts sorted
    newest-first.  Clusters are also sorted newest-first (by their most recent photo).
    """
    clusters = []
    for photo in photos:
        placed = False
        for cluster in clusters:
            rep = cluster[0]
            dist = geodesic(photo["coords"], rep["coords"]).meters
            mins = abs((photo["datetime"] - rep["datetime"]).total_seconds()) / 60
            if dist <= CLUSTER_RADIUS_M and mins <= CLUSTER_MINUTES:
                cluster.append(photo)
                placed = True
                break
        if not placed:
            clusters.append([photo])

    for c in clusters:
        c.sort(key=lambda p: p["datetime"], reverse=True)
    clusters.sort(key=lambda c: c[0]["datetime"], reverse=True)
    return clusters

# ── Settlement data ───────────────────────────────────────────────────────────

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = """
[out:json][timeout:90];
area["name"="Suffolk"]["boundary"="administrative"]["admin_level"="6"]->.suffolk;
(
  node["place"~"^(hamlet|village|town|city)$"](area.suffolk);
);
out body;
"""


def fetch_settlements():
    print("Fetching Suffolk settlements from OpenStreetMap (this may take ~30s)…")
    resp = requests.post(OVERPASS_URL, data={"data": OVERPASS_QUERY}, timeout=120)
    resp.raise_for_status()
    elements = resp.json()["elements"]

    settlements = []
    for el in elements:
        name = el.get("tags", {}).get("name")
        if not name:
            continue
        settlements.append({
            "name":  name,
            "lat":   el["lat"],
            "lon":   el["lon"],
            "place": el["tags"].get("place", ""),
        })

    print(f"  Found {len(settlements)} settlements")
    DATA_DIR.mkdir(exist_ok=True)
    with open(SETTLEMENTS_FILE, "w") as f:
        json.dump(settlements, f, indent=2)
    return settlements


def load_settlements(refresh=False):
    if not refresh and SETTLEMENTS_FILE.exists():
        print("Loading cached settlements…")
        with open(SETTLEMENTS_FILE) as f:
            return json.load(f)
    return fetch_settlements()

# ── Matching ──────────────────────────────────────────────────────────────────

def nearest_settlement(coords, settlements):
    """Return (settlement, distance_km) for nearest within MATCH_RADIUS_KM, else (None, None)."""
    best, best_dist = None, float("inf")
    for s in settlements:
        d = geodesic(coords, (s["lat"], s["lon"])).km
        if d < best_dist:
            best, best_dist = s, d
    if best_dist <= MATCH_RADIUS_KM:
        return best, best_dist
    return None, None

# ── Image output ──────────────────────────────────────────────────────────────

def save_web_photo(img, out_path):
    copy = ImageOps.exif_transpose(img)   # correct rotation from EXIF orientation tag
    copy.thumbnail(MAX_PHOTO_PX, Image.LANCZOS)
    if copy.mode not in ("RGB", "L"):
        copy = copy.convert("RGB")
    copy.save(out_path, "JPEG", quality=85, optimize=True)

# ── Main build ────────────────────────────────────────────────────────────────

def build(refresh_settlements=False):
    PHOTOS_OUT.mkdir(parents=True, exist_ok=True)

    # 1. Photos
    print(f"\nReading from Photos library …")
    raw = load_photos_from_library()
    print(f"  {len(raw)} photos with GPS data")
    clusters = cluster_photos(raw)
    total_photos = sum(len(c) for c in clusters)
    print(f"  {len(clusters)} location clusters ({total_photos} photos total)")

    # 2. Settlements
    print()
    settlements = load_settlements(refresh_settlements)

    # 3. Match & export
    print("\nMatching clusters to settlements…")
    visited_names = set()
    visited = []

    # clusters are already sorted newest-first; remove stale photos before writing.
    for old in PHOTOS_OUT.iterdir():
        old.unlink()

    for cluster in clusters:
        # Use the most-recent photo's coords for settlement matching.
        rep = cluster[0]
        settlement, dist = nearest_settlement(rep["coords"], settlements)
        if settlement is None:
            print(f"  no match  {rep['path'].name}  (nearest >1.5km)")
            continue

        name = settlement["name"]
        if name in visited_names:
            print(f"  dup match {rep['path'].name}  → {name}, skipping")
            continue
        visited_names.add(name)

        # Save every photo in the cluster.
        photo_paths = []
        for photo in cluster:
            out_name = photo["path"].stem + ".jpg"
            save_web_photo(photo["img"], PHOTOS_OUT / out_name)
            photo_paths.append(f"photos/{out_name}")

        date_str = rep["datetime"].strftime("%Y-%m-%d") if rep["datetime"] != datetime.min else None
        visited.append({
            "name":   name,
            "lat":    rep["coords"][0],
            "lon":    rep["coords"][1],
            "photos": photo_paths,
            "date":   date_str,
        })
        count_str = f" ({len(cluster)} photos)" if len(cluster) > 1 else ""
        print(f"  ✓  {name:<30}  {dist:.2f} km{count_str}")

    # 4. Unvisited with distance from home
    print("\nBuilding unvisited list…")
    unvisited = []
    for s in settlements:
        if s["name"] not in visited_names:
            d = geodesic(HOME_COORDS, (s["lat"], s["lon"])).km
            unvisited.append({
                "name":        s["name"],
                "lat":         s["lat"],
                "lon":         s["lon"],
                "distance_km": round(d, 1),
            })

    # 5. Write data.json
    data = {
        "visited":   visited,
        "unvisited": unvisited,
        "stats": {
            "visited":   len(visited),
            "total":     len(visited) + len(unvisited),
            "generated": datetime.now().strftime("%Y-%m-%d"),
        },
    }
    with open(DATA_OUT, "w") as f:
        json.dump(data, f, indent=2)

    # Write unvisited CSV sorted by distance from home
    csv_out = DOCS_DIR / "unvisited.csv"
    sorted_unvisited = sorted(unvisited, key=lambda s: s["distance_km"])
    with open(csv_out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Settlement", "Distance from home (km)"])
        for s in sorted_unvisited:
            writer.writerow([s["name"], s["distance_km"]])

    total = data["stats"]["total"]
    pct   = 100 * len(visited) / total if total else 0
    print(f"\nDone — {len(visited)} visited / {total} total ({pct:.1f}%)")
    print(f"Site data: {DATA_OUT}")
    print(f"CSV:       {csv_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Suffolk Village Signs static site.")
    parser.add_argument(
        "--refresh-settlements",
        action="store_true",
        help="Re-fetch settlement data from OpenStreetMap (ignores cache)",
    )
    args = parser.parse_args()
    build(refresh_settlements=args.refresh_settlements)
