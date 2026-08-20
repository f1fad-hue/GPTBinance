# Portfolio Signal Lab

Mobile-first, installable, tabbed scenario dashboard for QQQ, IEMG, SGOV and BMNR.

## What it does

- Shows a two-decimal 1–5 portfolio rate blending broad and allocation-correlated macro sentiment, with the corresponding 20% / 25% / 30% drawdown cap.
- Replaces the weighted-standalone-drawdown proxy with the actual monthly-rebalanced portfolio path over the common authoritative history. It also requires simultaneous stress losses and the modeled 10-year cap-breach probability to stay within their limits.
- Refreshes historical drawdown from official daily issuer NAV or Nasdaq closing-price histories, with cash distributions reinvested, using trailing 10 years where available and all available current-fund/ticker history otherwise. SGOV uses its official iShares NAV and distribution workbook from inception in 2020.
- Exhaustively searches every feasible 5%-increment allocation, keeps every required holding at 5% or more, caps BMNR at 10%, and maximizes net CAGR after a transparent forecast-uncertainty penalty.
- Shows 16 non-duplicative portfolio-related macro drivers across true calendar-based 3, 6 and 12 month horizons, broad and allocation-correlated sentiment, US/Europe/Asia portfolio-transmission rankings, three max-growth scenario donuts, holding slides, and a relevance-monitoring register.
- Runs a daily GitHub Actions job at 02:20 UTC (10:20 AM Asia/Manila) that refreshes FRED macro data, extracts the official gross/total expense ratios used by the model, scrubs each primary-source page for expected identity, retries transient failures, maps factual claims to registered authoritative sources, and commits corrected data only if every required automated check passes.
- Rechecks the repository schema, exact scenario allocations, synchronized portfolio-path MDD, stress losses, 10,000-path correlated return/drawdown simulation, relevance statuses, required dashboard elements, Python and JavaScript syntax, and the daily evidence report. A failed run retains its report, publishes no invalid data, and creates or updates one GitHub review issue; the issue closes automatically after a later clean run.

## Data controls

Portfolio facts and refreshed model inputs use only primary issuer, SEC, Nasdaq, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled process does not ingest Yahoo Finance, Google Finance, Alpha Vantage, social media, or unsourced web data. It validates source identity, registered factual claims, issuer-fee evidence, historical-series calculations, refreshed government data, and deterministic model math. Forecasts remain clearly labeled assumptions; a failed source or code check blocks publication and opens a review issue. This is not financial advice.

## Live site

After the Pages workflow finishes, the site is served at `https://f1fad-hue.github.io/GPTBinance/`.
