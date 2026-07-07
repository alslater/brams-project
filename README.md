# Currency Converter

A small single-page app with two views:

- **Exchange Rates** — live currency conversion with rate trends, a 7-day
  history chart, sortable results, and click-to-copy amounts.
- **Screening** — a mock transaction-screening tool that checks a
  customer/transaction against a small illustrative sanctions/watchlist
  rule set and returns a CLEAR / REVIEW / BLOCKED outcome.

There's no build step or framework — [index.html](index.html) is a
self-contained page, and [server.py](server.py) is a plain-stdlib Python
HTTP server that serves it and proxies a couple of API calls.

## Running it

```bash
python3 server.py
```

Then open `http://localhost:8765/index.html` in a browser.

The server has no third-party dependencies — it uses only the Python
standard library.

## How it works

### Exchange Rates view

The frontend never calls the exchange rate API directly; it goes through
this server, which proxies requests to
[Frankfurter](https://www.frankfurter.app/) (ECB reference rates):

- `GET /api/convert?amount=<n>&from=<CCY>&to=<CCY,CCY,...>` — latest rates.
- `GET /api/history?from=<CCY>&to=<CCY,...>&end=<YYYY-MM-DD>&days=<1-30>` —
  a historical rate range, used for the day-over-day trend indicator and the
  7-day chart you get by clicking a row.

Both endpoints validate their query parameters (currency codes must be
3 uppercase letters, `days` is clamped to 1–30) before building the
upstream request, and forward upstream errors without leaking internal
exception details to the client.

### Screening view

`POST /screen` with a JSON body:

```json
{
  "customerName": "Alice Wong",
  "nationality": "GBR",
  "amount": 1500,
  "currency": "USD",
  "destinationCountry": "DEU"
}
```

`nationality` and `destinationCountry` are ISO 3166-1 alpha-3 country
codes (the frontend form provides these as dropdowns). The server:

1. Converts `amount` to its GBP equivalent via the same Frankfurter proxy
   (skipped if `currency` is already `GBP`), so the high-value threshold is
   applied consistently regardless of currency.
2. Runs a small rule set (see `screen_transaction` in
   [server.py](server.py)):
   - destination country or nationality on a sanctions list → **BLOCKED**
   - customer name is an exact match against a name watchlist → **BLOCKED**
   - customer name is a *fuzzy* match (typo/transliteration, ≥85%
     similarity) against the watchlist → **REVIEW**
   - destination country on a (non-sanctioned) high-risk watchlist →
     **REVIEW**
   - GBP-equivalent amount exceeds the review threshold (currently £5,000)
     → **REVIEW**
   - if the live currency conversion fails, that also escalates to
     **REVIEW** rather than silently skipping the check
3. Returns `{"outcome": "CLEAR" | "REVIEW" | "BLOCKED", "reasons": [...]}`.

The sanctions/watchlist data (`SANCTIONED_COUNTRIES`, `WATCHLIST_COUNTRIES`,
`NAME_WATCHLIST`) is hardcoded in `server.py`. **This is illustrative demo
data only** — not a real sanctions data source — used purely to make the
rule engine produce varied, testable outcomes.

The result panel encodes each outcome with an icon *and* a text label *and*
a colour (not colour alone), so it's still readable at a glance for
colour-blind users: ✓ green **Clear**, ⚠ amber **Review required**,
⛔ red **Blocked**.

## Tests

```bash
pytest
```

Tests live in [tests/](tests/) and cover:

- input validation (`tests/test_validators.py`)
- `/api/convert` and `/api/history`, including malformed/injection-style
  input and static file serving (`tests/test_endpoints.py`)
- upstream error handling — that exceptions don't leak internal details to
  the client (`tests/test_error_handling.py`)
- `/screen` outcomes (CLEAR/REVIEW/BLOCKED, fuzzy name matching, currency
  conversion and its failure fallback) and input validation
  (`tests/test_screen_endpoint.py`)

`tests/conftest.py` spins up the real server on an ephemeral port for each
test and mocks `urllib.request.urlopen` so nothing hits the real
Frankfurter API during tests.

## Project layout

```
index.html   — the entire frontend (HTML/CSS/JS, no build step)
server.py    — stdlib HTTP server: static files + API proxy + /screen
tests/       — pytest suite (see above)
pytest.ini   — points pytest at tests/
```
