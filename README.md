# Portfolio Signal Lab

Mobile-first, installable scenario dashboard for QQQ, IEMG, BINC and BMNR.

## What it does

- Shows an explicit 1–5 macro-aware portfolio rate and the corresponding 20% / 25% / 30% P50 10-year forward maximum-drawdown cap.
- Uses a transparent gross-CAGR-minus-fee input and only the P50 10-year forward maximum drawdown. Each P50 input is the statistical median of peak-to-trough losses across 10,000 deterministic monthly 10-year paths. Historical drawdown is retained as reference evidence with zero optimizer weight.
- Refreshes historical drawdown from official daily issuer NAV or Nasdaq closing-price histories, with cash distributions reinvested, using trailing 10 years where available and all available current-fund/ticker history otherwise. BINC uses its official iShares NAV and distribution workbook from inception in 2023.
- Exhaustively searches every feasible 1%-increment allocation, keeps every required holding at 1% or more, and selects the highest modeled net CAGR that stays inside the rate-specific drawdown cap.
- Shows 12 distinct, non-duplicative portfolio-related macro drivers across true calendar-based 3, 6 and 12 month horizons, rate-conditioned allocation donuts, instrument slides, and a relevance-monitoring register.
- Runs a daily GitHub Actions job at 02:20 UTC (10:20 AM Asia/Manila) that refreshes FRED macro data, extracts the official gross/total expense ratios used by the model, scrubs each primary-source page for expected identity, retries transient failures, maps factual claims to registered authoritative sources, and commits corrected data only if every required automated check passes.
- Rechecks the repository schema, exact scenario allocations, 10,000-path Monte Carlo output, relevance statuses, drawdown math, required dashboard elements, Python and JavaScript syntax, and the daily evidence report. A failed run retains its report, publishes no invalid data, and creates or updates one GitHub review issue; the issue closes automatically after a later clean run.

## Data controls

Portfolio facts and refreshed model inputs use only primary issuer, SEC, Nasdaq, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled process does not ingest Yahoo Finance, Google Finance, Alpha Vantage, social media, or unsourced web data. It validates source identity, registered factual claims, issuer-fee evidence, historical-series calculations, refreshed government data, and deterministic model math. Forecasts remain clearly labeled assumptions; a failed source or code check blocks publication and opens a review issue. This is not financial advice.

## Live site

After the Pages workflow finishes, the site is served at `https://f1fad-hue.github.io/GPTBinance/`.
