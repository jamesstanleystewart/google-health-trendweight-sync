#!/usr/bin/env python3
"""
Sync today's weight (and body fat %) from Google Health API to TrendWeight.

Reads credentials from a .env file in the same directory, or from environment
variables directly. See .env.example for the required variables.

Usage:
    python3 weight_sync.py [--date YYYY-MM-DD] [--dry-run]
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Load .env from the same directory as the script
# ---------------------------------------------------------------------------

def load_dotenv(path: Path) -> dict:
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


SCRIPT_DIR = Path(__file__).parent
dotenv = load_dotenv(SCRIPT_DIR / ".env")


def env(key: str) -> str:
    return os.environ.get(key) or dotenv.get(key) or ""


GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = env("GOOGLE_REFRESH_TOKEN")
TRENDWEIGHT_API_KEY = env("TRENDWEIGHT_API_KEY")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOKEN_URL = "https://oauth2.googleapis.com/token"
WEIGHT_URL = "https://health.googleapis.com/v4/users/me/dataTypes/weight/dataPoints"
BODY_FAT_URL = "https://health.googleapis.com/v4/users/me/dataTypes/body-fat/dataPoints"
TRENDWEIGHT_URL = "https://trendweight.com/api/v1/measurements/manual"

# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

def get_access_token() -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {resp.json()}")
    return token

# ---------------------------------------------------------------------------
# Google Health — generic civil-date matcher
# ---------------------------------------------------------------------------

def _fetch_for_date(url: str, access_token: str, date_str: str, data_key: str) -> dict | None:
    """
    Page through `url` (newest-first) and return the first data point whose
    civil date matches `date_str` (YYYY-MM-DD). `data_key` is the top-level
    field in each point (e.g. "weight" or "bodyFat").
    """
    target = tuple(int(p) for p in date_str.split("-"))
    page_token = None

    for _ in range(10):
        params: dict = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"},
                            params=params, timeout=20)
        if resp.status_code != 200:
            print(f"{url} returned {resp.status_code}: {resp.text}", file=sys.stderr)
            resp.raise_for_status()

        data = resp.json()
        for point in data.get("dataPoints", []):
            payload = point.get(data_key, {})
            civil_date = payload.get("sampleTime", {}).get("civilTime", {}).get("date", {})
            if not civil_date:
                continue
            point_date = (civil_date.get("year", 0), civil_date.get("month", 0), civil_date.get("day", 0))
            if point_date == target:
                return payload
            if point_date < target:
                return None

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return None


def get_weight_kg(access_token: str, date_str: str) -> float | None:
    payload = _fetch_for_date(WEIGHT_URL, access_token, date_str, "weight")
    if payload is None:
        return None
    grams = payload.get("weightGrams")
    return grams / 1000.0 if grams is not None else None


def get_fat_ratio(access_token: str, date_str: str) -> float | None:
    payload = _fetch_for_date(BODY_FAT_URL, access_token, date_str, "bodyFat")
    if payload is None:
        return None
    pct = payload.get("percentage")
    return pct / 100.0 if pct is not None else None

# ---------------------------------------------------------------------------
# TrendWeight
# ---------------------------------------------------------------------------

def push_to_trendweight(weight_kg: float, fat_ratio: float | None,
                        date_str: str, dry_run: bool = False) -> None:
    url = f"{TRENDWEIGHT_URL}/{date_str}"
    body: dict = {"weight": weight_kg}
    if fat_ratio is not None:
        body["fatRatio"] = fat_ratio

    if dry_run:
        print(f"[dry-run] PUT {url}  body={body}")
        return

    resp = requests.put(url, json=body, headers={
        "Authorization": f"Bearer {TRENDWEIGHT_API_KEY}",
        "Content-Type": "application/json",
    }, timeout=15)
    resp.raise_for_status()
    fat_str = f", fat {fat_ratio * 100:.1f}%" if fat_ratio is not None else ""
    print(f"Synced {weight_kg} kg{fat_str} for {date_str} → TrendWeight ({resp.status_code})")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Date to sync (default: today, YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch from Google Health but don't push to TrendWeight")
    args = parser.parse_args()

    missing = [k for k, v in {
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH_TOKEN,
        "TRENDWEIGHT_API_KEY": TRENDWEIGHT_API_KEY,
    }.items() if not v]
    if missing and not (args.dry_run and missing == ["TRENDWEIGHT_API_KEY"]):
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    print(f"Fetching data for {args.date}...")
    token = get_access_token()

    weight_kg = get_weight_kg(token, args.date)
    if weight_kg is None:
        sys.exit(f"No weight data in Google Health for {args.date}")

    fat_ratio = get_fat_ratio(token, args.date)

    print(f"Weight:   {weight_kg} kg")
    if fat_ratio is not None:
        print(f"Body fat: {fat_ratio * 100:.2f}%")
    else:
        print("Body fat: not found for this date")

    push_to_trendweight(weight_kg, fat_ratio, args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
