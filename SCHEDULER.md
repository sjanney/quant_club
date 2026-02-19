# Scheduled Trading: After-Hours Analysis & Execute at Open

Run analysis after the market closes and submit orders when the market opens—without leaving your computer on.

## Modes

| Mode | When to run | What it does |
|------|-------------|--------------|
| **after-hours** | Once, after market close (e.g. 4:35 PM ET) | Fetches data, runs RAMmageddon, computes target orders, saves to `state/scheduled_orders.json` |
| **execute-open** | Once, at market open (e.g. 9:31 AM ET) | Loads scheduled orders, submits to Alpaca, archives the file |
| **scheduler** | Long-running daemon | Every minute checks the clock (ET); runs after-hours once per day after close, execute-open once per day at open |

All times use **America/New_York**. Configure in `config/settings.py` under `ScheduleConfig`.

---

## Option 0: GitHub Actions (free on public repos)

If your repo is public, GitHub Actions can run this for free (within fair-use limits), so your computer can stay off.

### Workflows

- **CI checks:** `.github/workflows/ci.yml`
- **Scheduled trading:** `.github/workflows/scheduled_trading.yml`
- **Daily no-trade health-check:** `.github/workflows/trading_healthcheck.yml`

### Required GitHub Secrets

Set these in **Settings → Secrets and variables → Actions**:

- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- optional: `LOG_LEVEL`
- optional: `DISCORD_WEBHOOK_URL` (for free Discord notifications)

`ALPACA_BASE_URL` is forced to paper in workflow env:

`https://paper-api.alpaca.markets`

### Scheduled Trading Cron (UTC)

GitHub cron is UTC, so both EST and EDT entries are included:

- **After-hours (16:35 ET):**
  - `35 21 * * 1-5` (EST)
  - `35 20 * * 1-5` (EDT)
- **Execute-open (09:31 ET):**
  - `31 14 * * 1-5` (EST)
  - `31 13 * * 1-5` (EDT)

The app still applies ET windows and “once per day” checks, so duplicate triggers are ignored safely.

### Manual Runs

Use **Actions → scheduled-trading → Run workflow** and choose:

- `after-hours`
- `execute-open`
- `both`

For non-trading validation, run **Actions → trading-healthcheck → Run workflow**.
It checks broker auth + market data + signal generation, but does not submit orders.

### Discord notifications (optional, free)

Create a Discord channel webhook URL and add it as the `DISCORD_WEBHOOK_URL` secret.
When set, you will receive notifications for:

- after-hours analysis completion (with number of scheduled orders)
- execute-open completion (submitted order count)
- live-mode order submissions/rejections

### Artifacts and Auditing

- After-hours uploads `scheduled-orders` artifact.
- Execute-open uploads logs/archive artifacts.
- Concurrency guard prevents overlapping runs.

---

## Option A: Run on your computer (scheduler daemon)

Start the daemon and leave the terminal open (or run in `screen`/`tmux`):

```bash
cd /path/to/quant_club
source venv/bin/activate
python main.py --mode scheduler
```

- **After 4:35 PM ET** on a trading day it runs after-hours analysis and writes `state/scheduled_orders.json`.
- **After 9:31 AM ET** the next day it loads that file, submits orders, archives it to `state/archive/`, and clears the file.
- It only runs each job **once per calendar day** (tracked in `state/scheduler_state.json`).

If your machine sleeps or is off at those times, the job for that day is skipped until the next day.

---

## Option B: Run without your computer (cron on a server)

Use a server or cloud VM that’s always on (e.g. a $5/mo VPS, or a free-tier instance). Install the project and dependencies, set `.env` with your Alpaca keys, then use cron.

### 1. One-shot commands (no daemon)

Run after-hours once after close, and execute-open once at open:

```bash
# After market close (e.g. 4:35 PM ET = 21:35 UTC in winter, 20:35 in summer — adjust for DST)
35 21 * * 1-5  cd /path/to/quant_club && /path/to/venv/bin/python main.py --mode after-hours

# At market open (e.g. 9:31 AM ET = 14:31 UTC in winter, 13:31 in summer)
31 14 * * 1-5  cd /path/to/quant_club && /path/to/venv/bin/python main.py --mode execute-open
```

Cron uses the **server’s timezone**. Either set the server TZ to `America/New_York` or convert ET → UTC (and adjust for DST):

- ET = UTC−5 (EST) or UTC−4 (EDT).  
  Example: 9:31 AM ET = 14:31 UTC (EST) or 13:31 UTC (EDT).

### 2. Or run the scheduler on the server

Same as Option A, but on the server so it’s always on:

```bash
# In screen/tmux or as a systemd service
python main.py --mode scheduler
```

Then you don’t need cron; the scheduler handles timing.

---

## Configuration

In `config/settings.py`, `ScheduleConfig`:

- **after_hours_hour / after_hours_minute** — when to run after-hours (default 4:35 PM ET).
- **market_open_hour / market_open_minute** — when to run execute-open (default 9:31 AM ET).
- **timezone** — `America/New_York`.
- **state_dir** — where `scheduled_orders.json` and `scheduler_state.json` live (default `state/`).
- **archive_dir** — where executed order payloads are saved (default `state/archive/`).

---

## Files

- **state/scheduled_orders.json** — written by after-hours; read and deleted by execute-open. Contains `generated_at_et`, `strategy`, `equity_snapshot`, `signals_snapshot`, and `orders` (list of `{symbol, side, quantity}`).
- **state/scheduler_state.json** — last run dates for after-hours and execute-open so each runs at most once per day.
- **state/archive/executed_YYYYMMDD_HHMMSS.json** — copy of the executed scheduled orders for audit.

---

## Summary

- **Computer on, one process:** `python main.py --mode scheduler`.
- **Computer off:** run the same repo on a server and use cron for `--mode after-hours` and `--mode execute-open`, or run `--mode scheduler` there.

All execution is **paper trading** as long as `.env` uses `ALPACA_BASE_URL=https://paper-api.alpaca.markets`.
