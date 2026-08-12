# Portfolio Signal Lab

Mobile-first, installable scenario dashboard for the required BAI, QQQ, IEMG, BINC and BMNR instruments.

## What it does

- Shows an explicit 1–5 macro-aware portfolio rate and the corresponding 20% / 25% / 30% composite drawdown cap.
- Uses a transparent gross-CAGR-minus-fee input and an exact composite drawdown of 60% historical proxy plus 40% forward-looking median drawdown, alongside 10,000 deterministic 10-year simulations.
- Exhaustively searches every feasible 5%-increment allocation, keeps every required holding at 5% or more, and selects the highest modeled net CAGR that stays inside the rate-specific drawdown cap.
- Shows 10 distinct portfolio-related macro drivers across true calendar-based 3, 6 and 12 month horizons, rate-conditioned allocation donuts, instrument slides, and a relevance-monitoring register.
- Runs a daily GitHub Actions job at 02:20 UTC (10:20 AM Asia/Manila) that refreshes FRED macro data, extracts the official gross/total expense ratios used by the model, scrubs each primary-source page for expected identity, retries transient failures, maps factual claims to registered authoritative sources, and commits corrected data only if every required automated check passes.
- Rechecks the repository schema, exact scenario allocations, 10,000-path Monte Carlo output, relevance statuses, drawdown math, required dashboard elements, Python and JavaScript syntax, and the daily evidence report. A failed run retains its report, publishes no invalid data, and creates or updates one GitHub review issue; the issue closes automatically after a later clean run.

## Data controls

Portfolio facts and refreshed model inputs use only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled process does not ingest Yahoo Finance, Google Finance, Alpha Vantage, social media, or unsourced web data.

This project links to only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled job validates source identity, registered factual claims, issuer-fee evidence, refreshed government data, and deterministic model math. It cannot independently prove a forecast or safely rewrite arbitrary code, so forecast values remain labeled model inputs and code failures are blocked and queued for review instead of being silently “fixed.” BMNR SEC checks remain explicit manual review when SEC blocks the GitHub runner. This is not financial advice.

## Live site

After the Pages workflow finishes, the site is served at `https://f1fad-hue.github.io/GPTBinance/`.
