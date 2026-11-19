# tap-cme

Singer tap for CME Group's Reference Data API v3, built with the [Meltano Singer SDK](https://sdk.meltano.com).
It loads CME's own Globex trading hours and holiday schedules, a year back and two years ahead, so a trading desk
and its replays read the exchange's published sessions instead of a hand-maintained calendar.

## Stream

`trading_schedules`, keyed by `fetch_id` and `trading_schedule_id`, holds one record per schedule per fetch. Each record
holds every trading date's market events (`preopen`, `open`, `paused`, `pcp`, `closed`) in CME's order, with times in
UTC.

- **All or nothing.** A fetch's pages are held until its last one lands, then written together, each record carrying
  the fetch's summary. A fetch that fails part-way writes nothing.
- **Proving a fetch whole.** A reader proves it from the fetch's own rows: its distinct `trading_schedule_id`s landed
  must equal `fetch_schedules`.
- **Maintenance.** A fetch started inside CME's weekly maintenance (Friday 22:00 to Saturday 19:00 CT) is flagged
  `fetch_in_maintenance`.
- **Empty answers.** A requested group whose answer holds no schedule is listed in `groups_without_schedules`. That
  means unknown, never closed.
- **Unstable ids.** `trading_schedule_id` is not stable across fetches: CME renumbered the treasury schedule within 23
  minutes on 2026-11-19. Join fetches on Globex group codes, never on that id.
- **Trading dates.** CME files the Juneteenth session under the next Monday's trading date. Read sessions by their
  events' times, never by the trading date alone.
- **Refusals.** The tap refuses anything it cannot read and names the schedule, the date and the field:
  - a key CME has not sent before;
  - a key it stopped sending;
  - a date in another format.

## Configuration

| Setting | Required | Default |
|---|---|---|
| `client_id` | yes | the OAuth API ID (`API_...`), from CME Customer Center, My Profile, APIs |
| `client_secret` | yes | the API ID's generated password (expires yearly) |
| `globex_group_codes` | yes | Globex groups each fetch asks for, e.g. `["ZN"]` (its schedule also serves ZB and ZF) |
| `api_url` | no | `https://refdata.api.cmegroup.com/refdata/v3` |
| `auth_url` | no | `https://auth.cmegroup.com/as/token.oauth2` |
| `capture_dir` | no | a fetch saved to disk (`manifest.json` + `page-NNNNN.json`), loaded at its own fetch times |

Futures and options schedules need no CME entitlement beyond the API ID. Pages hold one schedule each, because a
response over 10 MB fails with HTTP 502.

## Development

```bash
uv sync
uv run pytest                                  # live SDK tests run only when CME_API_ID is set
uv run tap-cme --config config.json --config ENV   # TAP_CME_CLIENT_ID / TAP_CME_CLIENT_SECRET from the environment
```

Lint and types, as CI runs them: `uvx ruff@0.16.10 check tap_cme tests`, `uv run --group typing mypy tap_cme tests`,
`uv run --group typing ty check tap_cme tests`.
