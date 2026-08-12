# Portfolio Signal Lab

Mobile-first, installable scenario dashboard for the required BAI, QQQ, IEMG, BINC and BMNR instruments.

## What it does

- Shows an explicit 1–5 macro-aware portfolio rate and the corresponding 20% / 25% / 30% composite drawdown cap.
- Uses a transparent gross-CAGR-minus-fee input, a 60% historical-proxy / 40% forward Monte-Carlo drawdown blend, and 10,000 deterministic 10-year simulations.
- Shows 10 distinct portfolio-related macro drivers across true calendar-based 3, 6 and 12 month horizons, rate-conditioned allocation donuts, instrument slides, and a relevance-monitoring register.
- Runs a daily GitHub Actions job at 02:20 UTC (10:20 AM Asia/Manila) that refreshes FRED macro data, scrubs each listed primary-source page for expected identity and issuer-fee evidence, retries transient failures, maps factual claims to registered authoritative sources, performs supplemental public-price checks, and commits corrected data only if every required automated check passes.
- Rechecks the repository schema, drawdown/allocation math, required dashboard elements, Python and JavaScript syntax, and the daily evidence report. A failed run retains its report, publishes no invalid data, and creates or updates one GitHub review issue; the issue closes automatically after a later clean run.

## Data controls

Portfolio claims continue to use only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. Alpha Vantage (preferred) and Yahoo Finance (fallback) are supplemental public market-price checks only: neither supplies a portfolio claim, forecast, allocation, or macro input, and a rate-limited quote is logged as manual review rather than treated as a verified fact.

To enable the preferred check, create a free Alpha Vantage key and save it in the repository as the Actions secret `ALPHA_VANTAGE_API_KEY`. The key is read only during the daily workflow and is never written to the repository or dashboard.

This project links to only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled job validates source identity, registered factual claims, issuer-fee evidence, refreshed government data, and deterministic model math. It cannot independently prove a forecast or safely rewrite arbitrary code, so forecast values remain labeled model inputs and code failures are blocked and queued for review instead of being silently “fixed.” BMNR SEC checks remain explicit manual review when SEC blocks the GitHub runner. This is not financial advice.

## Live site

After the Pages workflow finishes, the site is served at `https://f1fad-hue.github.io/GPTBinance/`.
