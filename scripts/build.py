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
PHOTOS_IN  = ROOT / "photos"
PHOTOS_OUT = ROOT / "docs" / "photos"
DATA_DIR   = ROOT / "data"
DOCS_DIR   = ROOT / "docs"
SETTLEMENTS_FILE = DATA_DIR / "settlements.json"
DATA_OUT         = DOCS_DIR / "data.json"

# ── Config ────────────────────────────────────────────────────────────────────
HOME_COORDS    = (52.2355, 0.9014)   # Elmswell, IP30 9HD (approx.)
DEDUP_RADIUS_M = 50
MATCH_RADIUS_KM = 1.5
MAX_PHOTO_PX   = (1200, 1200)

# ── EXIF helpers ──────────────────────────────────────────────────────────────

def _to_float(val):
    """Convert IFDRational, (num, den) tuple, or plain number to float."""
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        return float(val)
    if isinstance(val, tuple) and len(val) == 2:
        return val[0] / val[1] if val[1] != 0 else 0.0
    return float(val)


def _dms_to_decimal(dms, ref):
    d = _to_float(dms[0])
    m = _to_float(dms[1])
    s = _to_float(dms[2])
    dec = d + m / 60 + s / 3600
    return -dec if ref in ("S", "W") else dec


def extract_gps(img):
    """Return (lat, lon) or None."""
    try:
        gps = img.getexif().get_ifd(0x8825)  # GPSInfo IFD
    except Exception:
        raw = (img._getexif() or {})
        gps = raw.get(34853, {})

    if not gps:
        return None
    try:
        lat = _dms_to_decimal(gps[2], gps.get(1, "N"))
        lon = _dms_to_decimal(gps[4], gps.get(3, "E"))
        return (lat, lon)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def extract_datetime(img):
    """Return datetime or datetime.min if unavailable."""
    try:
        exif = img.getexif()
    except Exception:
        exif = img._getexif() or {}

    for tag in (36867, 36868, 306):   # DateTimeOriginal, DateTimeDigitized, DateTime
        val = exif.get(tag)
        if val:
            try:
                return datetime.strptime(val, "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return datetime.min

# ── Photo loading & deduplication ─────────────────────────────────────────────

SUPPORTED = {".heic", ".heif", ".jpg", ".jpeg", ".png"}


def load_photos(directory):
    """Load all supported images that have GPS data."""
    photos = []
    if not directory.exists():
        return photos

    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SUPPORTED:
            continue
        try:
            img = Image.open(path)
            coords = extract_gps(img)
            if not coords:
                print(f"  skip  {path.name}  (no GPS)")
                continue
            photos.append({
                "path":     path,
                "img":      img,
                "coords":   coords,
                "datetime": extract_datetime(img),
            })
        except Exception as exc:
            print(f"  error {path.name}: {exc}")

    return photos


def deduplicate(photos):
    """Cluster photos within DEDUP_RADIUS_M; keep most recent per cluster."""
    clusters = []
    for photo in photos:
        placed = False
        for cluster in clusters:
            rep = cluster[0]
            if geodesic(photo["coords"], rep["coords"]).meters <= DEDUP_RADIUS_M:
                cluster.append(photo)
                placed = True
                break
        if not placed:
            clusters.append([photo])

    return [max(c, key=lambda p: p["datetime"]) for c in clusters]

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
    print(f"\nScanning {PHOTOS_IN} …")
    raw = load_photos(PHOTOS_IN)
    print(f"  {len(raw)} photos with GPS data")
    photos = deduplicate(raw)
    print(f"  {len(photos)} after deduplication")

    # 2. Settlements
    print()
    settlements = load_settlements(refresh_settlements)

    # 3. Match & export
    print("\nMatching photos to settlements…")
    visited_names = set()
    visited = []

    for photo in photos:
        settlement, dist = nearest_settlement(photo["coords"], settlements)
        if settlement is None:
            print(f"  no match  {photo['path'].name}  (nearest >1.5km)")
            continue

        name = settlement["name"]
        if name in visited_names:
            # Two photos matched the same settlement — keep first (most recent wins dedup)
            print(f"  dup match {photo['path'].name}  → {name}, skipping")
            continue
        visited_names.add(name)

        out_name = photo["path"].stem + ".jpg"
        save_web_photo(photo["img"], PHOTOS_OUT / out_name)

        date_str = photo["datetime"].strftime("%Y-%m-%d") if photo["datetime"] != datetime.min else None
        visited.append({
            "name":  name,
            "lat":   photo["coords"][0],
            "lon":   photo["coords"][1],
            "photo": f"photos/{out_name}",
            "date":  date_str,
        })
        print(f"  ✓  {name:<30}  {dist:.2f} km")

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
