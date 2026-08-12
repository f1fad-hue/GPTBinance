# Portfolio Signal Lab

Mobile-first, installable scenario dashboard for the required BAI, QQQ, IEMG, BINC and BMNR instruments.

## What it does

- Shows an explicit 1–5 macro-aware portfolio rate and the corresponding 20% / 25% / 30% composite drawdown cap.
- Uses a transparent gross-CAGR-minus-fee input, a 60% historical-proxy / 40% forward Monte-Carlo drawdown blend, and 10,000 deterministic 10-year simulations.
- Shows 10 distinct portfolio-related macro drivers across true calendar-based 3, 6 and 12 month horizons, rate-conditioned allocation donuts, instrument slides, and a relevance-monitoring register.
- Runs a daily GitHub Actions job that refreshes FRED macro data, checks the listed primary-source endpoints, performs Alpha Vantage and Yahoo Finance supplemental public-price checks, validates the required holdings and weights, and commits the refreshed JSON if successful.

## Data controls

Portfolio claims continue to use only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. Alpha Vantage (preferred) and Yahoo Finance (fallback) are supplemental public market-price checks only: neither supplies a portfolio claim, forecast, allocation, or macro input, and a rate-limited quote is logged as manual review rather than treated as a verified fact.

To enable the preferred check, create a free Alpha Vantage key and save it in the repository as the Actions secret `ALPHA_VANTAGE_API_KEY`. The key is read only during the daily workflow and is never written to the repository or dashboard.

This project links to only primary issuer, SEC, Federal Reserve/FRED, and U.S. Treasury sources. The scheduled job validates availability; it cannot independently prove every statement made by every third-party issuer. Forecast values are model inputs—not factual claims or financial advice. In particular, BAI and BINC are too new to have 10 years of live fund history, and BMNR's long-horizon data are not a reliable analogue. The dashboard labels those figures as assumptions.

## Live site

After the Pages workflow finishes, the site is served at `https://f1fad-hue.github.io/GPTBinance/`.
