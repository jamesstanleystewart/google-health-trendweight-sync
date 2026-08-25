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
from datetime import datetime, timedelta
from pathlib import Path

import requests


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


dotenv = load_dotenv(Path(__file__).parent / ".env")


def env(key: str) -> str:
    return os.environ.get(key) or dotenv.get(key) or ""


GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = env("GOOGLE_REFRESH_TOKEN")
TRENDWEIGHT_API_KEY = env("TRENDWEIGHT_API_KEY")

TOKEN_URL = "https://oauth2.googleapis.com/token"
WEIGHT_URL = "https://health.googleapis.com/v4/users/me/dataTypes/weight/dataPoints"
BODY_FAT_URL = "https://health.googleapis.com/v4/users/me/dataTypes/body-fat/dataPoints"
TRENDWEIGHT_URL = "https://trendweight.com/api/v1/measurements/manual"


def get_access_token() -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {data}")
    return token


def _fetch_for_date(url: str, access_token: str, date_str: str,
                    filter_prefix: str, data_key: str) -> dict | None:
    """
    Return the latest data point recorded on `date_str` (YYYY-MM-DD), or None.

    Two API quirks: the filter prefix is snake_case (body_fat) while the URL
    segment is hyphenated (body-fat), and civil_time literals must be bare
    dates — a timezone suffix is rejected. Filtering on civil_time rather than
    physical_time keeps this in the scale's local day, no offset maths needed.
    """
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    field = f"{filter_prefix}.sample_time.civil_time"

    resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, params={
        "filter": f'{field} >= "{date_str}" AND {field} < "{next_day}"',
        "pageSize": 100,
    }, timeout=20)
    if resp.status_code != 200:
        print(f"{url} returned {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()

    points = resp.json().get("dataPoints", [])
    # Results are ordered newest-first, so [0] is the day's last measurement.
    return points[0].get(data_key) if points else None


def get_weight_kg(access_token: str, date_str: str) -> float | None:
    payload = _fetch_for_date(WEIGHT_URL, access_token, date_str, "weight", "weight") or {}
    grams = payload.get("weightGrams")
    return grams / 1000.0 if grams is not None else None


def get_fat_ratio(access_token: str, date_str: str) -> float | None:
    payload = _fetch_for_date(BODY_FAT_URL, access_token, date_str, "body_fat", "bodyFat") or {}
    pct = payload.get("percentage")
    return pct / 100.0 if pct is not None else None


def push_to_trendweight(weight_kg: float, fat_ratio: float | None,
                        date_str: str, dry_run: bool) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="Date to sync (default: today, YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch from Google Health but don't push to TrendWeight")
    args = parser.parse_args()

    required = {
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH_TOKEN,
    }
    if not args.dry_run:
        required["TRENDWEIGHT_API_KEY"] = TRENDWEIGHT_API_KEY

    missing = [k for k, v in required.items() if not v]
    if missing:
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

    push_to_trendweight(weight_kg, fat_ratio, args.date, args.dry_run)


if __name__ == "__main__":
    main()
