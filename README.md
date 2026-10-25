# plex-to-letterboxd

A small service that logs the films you watch in Plex to your Letterboxd diary. It has its own memory (SQLite) and a web UI.

Letterboxd has no public API (access requires [special approval](https://letterboxd.com/api-beta/)), so the service drives the website with a headless [Camoufox](https://camoufox.com) (Firefox/Playwright) browser.

## How it works

Every watch (film + date) is tracked in a database with a status: `pending`, `synced`, `failed` or `skipped`.

1. **Scan.** Reads watched films from Plex. Each film's last finished play is recorded, plus per-play history for the last `history_days` days, so rewatches are captured too. Films still in progress, or without an IMDb/TMDB id, are ignored.
2. **Check the diary.** Before uploading, the service reads the recent pages of your Letterboxd diary. Any pending watch that is already logged (same film, date ±1 day) is marked `synced` instead of being uploaded again, so you get no duplicates.
3. **Import.** Remaining watches are uploaded as a Letterboxd CSV import, with rating, watched date and rewatch flag.
4. **Verify.** The diary is read again after the import. A watch only becomes `synced` once its entry is actually there. Otherwise it is marked `failed` and retried on the next runs, up to `max_attempts`.

Films are matched to Letterboxd by TMDB/IMDb id (via `letterboxd.com/tmdb/<id>/`), and the resulting slug is cached per film.

By default, a watch waits as **needs rating** until you rate the film in Plex, so no unrated diary entries are created.

### Shared account (skip until the next play)

If someone else watched a film on your Plex account, **Skip** that watch in the UI. It is never uploaded, but the film is not ignored: the next play is picked up as a new watch. That includes a later play on the same day (at least 30 minutes after the skipped one).

The **Rewatch** flag only counts viewings you logged yourself, meaning an earlier synced watch or an earlier entry in your Letterboxd diary. Skipped plays and Plex's play count are ignored, so your first real viewing after your partner's is not marked as a rewatch.

### First run (baseline)

The database starts empty, so the first sync reads your **entire** Letterboxd diary:
- Plex watches already in the diary are marked `synced`.
- Watches not in the diary and older than `max_age_days` (default 30) are marked `skipped`, so years of old history don't flood the diary. You can queue them manually in the UI.
- More recent unlogged watches are uploaded.

After the baseline, a newly discovered watch that is already older than `max_age_days` is also skipped. This covers cases like bulk "mark as watched" in Plex.

## Web UI

Open `http://<host>:7477`:

- **Dashboard**: counts, recently logged films, next/last sync and connection status.
- **Watches**: every tracked watch with poster, rating and status, with filters and search. Per-row or bulk actions: **Queue** (sync again), **Skip** (until the next play), **Mark synced**.
- **Runs**: history of every sync, scan and reconcile, with live logs.
- **Settings**: schedule, rating requirement, age limit, retries, batch size, Plex library/user and Telegram. Maintenance buttons: *Scan Plex*, *Reconcile with diary* (full diary re-check).

The UI has no authentication; keep it on your LAN.

## Usage

```bash
# create .env with the variables below
docker compose up -d
```

Optional: trigger a sync as soon as something is watched. In Tautulli, add a **Webhook** notification agent (POST, JSON body `{"media_type": "{media_type}"}`) on *Watched* pointing to `http://<host>:7477/api/webhook/tautulli`.

One-off job from the CLI (uses the same database; avoid while a job is running in the service):
```bash
docker exec plex-to-letterboxd python main.py sync     # or: scan, reconcile
```

`cleanup_diary.py` is a separate maintenance tool. It deletes unrated and duplicate diary entries: `python cleanup_diary.py [--delete]`.

## Environment variables

| Variable              | Description                                              | Default                  |
|-----------------------|----------------------------------------------------------|--------------------------|
| `LETTERBOXD_USERNAME` | Letterboxd username or email                             | -                        |
| `LETTERBOXD_PASSWORD` | Letterboxd password                                      | -                        |
| `PLEX_URL`            | Plex URL                                                 | `http://localhost:32400` |
| `PLEX_TOKEN`          | Plex token ([how to find][plex])                         | -                        |
| `PLEX_PUBLIC_URL`     | Plex address used for links in the web UI                | `PLEX_URL`               |
| `TELEGRAM_BOT_TOKEN`  | Optional. Telegram bot token for notifications           | -                        |
| `TELEGRAM_CHAT_ID`    | Optional. Telegram chat ID for notifications             | -                        |
| `TZ`                  | Time zone used to turn Plex play times into diary dates  | `UTC`                    |
| `PORT`                | Web UI / API port                                        | `7477`                   |
| `DATA_DIR`            | Database and poster cache location                       | `/data`                  |
| `JOB_TIMEOUT_MINUTES` | A job running longer than this is killed                 | `60`                     |

Initial values for UI settings can also be set with `PLEX_LIBRARY` (`Films`), `PLEX_USER`, `SYNC_INTERVAL_MINUTES` (`360`), `MAX_AGE_DAYS` (`30`), `MAX_RETRIES` (`3`) and `AUTO_SYNC` (`true`). Once a setting is saved in the UI, the stored value wins.

[plex]: https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

## API

`GET /api/status`, `GET /api/watches?status=&q=&page=`, `POST /api/watches/action` (`{"ids": [...], "action": "queue|skip|mark_synced"}`), `POST /api/jobs/{scan|sync|reconcile}`, `GET /api/runs`, `GET /api/runs/{id}`, `GET|PUT /api/settings`, `POST /api/webhook/tautulli`, `GET /api/health`.

## Development

```bash
# backend
cd app && pip install -r requirements.txt && DATA_DIR=./data python server.py
# frontend (proxies /api to :7477)
cd web && npm install && npm run dev
# tests
pip install pytest && python -m pytest tests
```
