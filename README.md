# google-health-trendweight-sync

Pulls today's weight and body fat % from the Google Health API (Fitbit/Aria 2 data) and pushes it to [TrendWeight](https://trendweight.com) via their API.

## Setup

### 1. Credentials

Copy `.env.example` to `.env` and fill in:

- **Google OAuth** — reuse credentials from an existing GCP project that has the Health API enabled, or follow the [hevy heartrate sync setup](https://github.com/jamesstanleystewart/google-health-hevy-heartrate-sync#2-google-health-oauth) to create them. Google refresh tokens don't rotate, so the same token can be used by multiple scripts.
- **TrendWeight API key** — generate at trendweight.com → Settings → API Keys (starts with `sk-`)

### 2. Install dependency

```bash
pip3 install requests
```

### 3. Test

```bash
python3 weight_sync.py --dry-run
```

Fetches from Google Health but doesn't write to TrendWeight. If you see a weight value, remove `--dry-run` to sync for real.

### 4. Cron (Raspberry Pi)

Run daily at 8am:

```bash
crontab -e
```

Add:

```
0 8 * * * /usr/bin/python3 /home/pi/google-health-trendweight-sync/weight_sync.py >> /home/pi/weight_sync.log 2>&1
```

Adjust the Python path (`which python3`) and repo path as needed.

## Usage

```
python3 weight_sync.py [--date YYYY-MM-DD] [--dry-run]
```

- `--date` — sync a specific date instead of today (useful for backfilling)
- `--dry-run` — print what would be synced without pushing to TrendWeight
