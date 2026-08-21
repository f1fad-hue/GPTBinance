#!/usr/bin/env python3
"""Authoritative holding histories and synchronized portfolio-return data."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

ISHARES_PORTFOLIOS = {"IEMG": "244050", "SGOV": "314116"}
NASDAQ_ASSET_CLASSES = {"QQQ": "etf", "BMNR": "stocks"}
NASDAQ_HISTORY_STARTS = {"BMNR": date(2025, 5, 16)}
ISHARES_DOWNLOAD = (
    "https://www.blackrock.com/varnish-api/blk-one01-product-data/"
    "product-data/api/v1/get-fund-document?appSubType=ISHARES&appType=PRODUCT_PAGE&"
    "component=fundDownload&locale=en_US&portfolioId={portfolio_id}&"
    "targetSite=us-ishares&userType=individual"
)


def _number(value: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", value))


def _cutoff(today: date) -> date:
    try:
        return today.replace(year=today.year - 10)
    except ValueError:
        return today.replace(year=today.year - 10, day=28)


def _total_returns(rows: list[tuple[date, float, float]]) -> dict[date, float]:
    rows = sorted(rows)
    returns: dict[date, float] = {}
    for index in range(1, len(rows)):
        observed, value, distribution = rows[index]
        previous_value = rows[index - 1][1]
        if value <= 0 or previous_value <= 0:
            raise RuntimeError("non-positive historical value")
        returns[observed] = (value + distribution) / previous_value - 1
    return returns


def _max_drawdown(rows: list[tuple[date, float, float]], source_type: str) -> dict:
    rows = sorted(rows)
    if len(rows) < 2:
        raise RuntimeError("insufficient observations for historical drawdown")
    wealth = peak = 1.0
    peak_date = rows[0][0]
    worst = 0.0
    worst_peak = worst_trough = peak_date
    for observed, daily_return in _total_returns(rows).items():
        wealth *= 1 + daily_return
        if wealth > peak:
            peak = wealth
            peak_date = observed
        drawdown = wealth / peak - 1
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = observed
    return {
        "value": round(-worst * 100, 4),
        "start": rows[0][0].isoformat(),
        "end": rows[-1][0].isoformat(),
        "peak": worst_peak.isoformat(),
        "trough": worst_trough.isoformat(),
        "observations": len(rows),
        "method": f"Observed daily {source_type} total return; cash distributions reinvested",
    }


def _ishares_rows(ticker: str, get, today: date) -> tuple[list[tuple[date, float, float]], str]:
    url = ISHARES_DOWNLOAD.format(portfolio_id=ISHARES_PORTFOLIOS[ticker])
    body = get(url)
    start = body.find('<ss:Worksheet ss:Name="Historical">')
    end = body.find("</ss:Worksheet>", start)
    if start < 0 or end < 0:
        raise RuntimeError(f"{ticker} official Historical sheet missing")
    block = body[start:end]
    rows = []
    cutoff = _cutoff(today)
    for row in re.findall(r"<ss:Row[^>]*>(.*?)</ss:Row>", block, re.S)[1:]:
        values = [value.strip() for value in re.findall(r"<ss:Data[^>]*>(.*?)</ss:Data>", row, re.S)]
        if len(values) < 3:
            continue
        try:
            observed = datetime.strptime(values[0], "%b %d, %Y").date()
            nav = _number(values[1])
            distribution = 0.0 if values[2] == "--" else _number(values[2])
        except (ValueError, IndexError):
            continue
        if observed >= cutoff:
            rows.append((observed, nav, distribution))
    if len(rows) < 250:
        raise RuntimeError(f"{ticker} official history has only {len(rows)} observations")
    return sorted(rows), url


def _nasdaq_rows(ticker: str, get, start_date: date, end_date: date) -> tuple[list[tuple[date, float, float]], str]:
    """Download bounded official windows; long Nasdaq queries are unreliable."""
    rows_by_date: dict[date, float] = {}
    window_start = start_date
    while window_start <= end_date:
        window_end = min(window_start + timedelta(days=31), end_date)
        params = urlencode({
            "assetclass": NASDAQ_ASSET_CLASSES[ticker],
            "fromdate": window_start.isoformat(),
            "todate": window_end.isoformat(),
            "limit": 100,
            "offset": 0,
        })
        api_url = f"https://api.nasdaq.com/api/quote/{ticker}/historical?{params}"
        payload = json.loads(get(api_url))
        data = payload.get("data") or {}
        rows_payload = (data.get("tradesTable") or {}).get("rows") or []
        for item in rows_payload:
            try:
                observed = datetime.strptime(item["date"], "%m/%d/%Y").date()
                rows_by_date[observed] = _number(item["close"])
            except (KeyError, ValueError):
                continue
        window_start = window_end + timedelta(days=1)
    if len(rows_by_date) < 2:
        raise RuntimeError(f"{ticker} official Nasdaq history returned insufficient rows")
    distributions: dict[date, float] = {}
    dividend_url = f"https://api.nasdaq.com/api/quote/{ticker}/dividends?assetclass={NASDAQ_ASSET_CLASSES[ticker]}"
    dividend_payload = json.loads(get(dividend_url))
    for item in (((dividend_payload.get("data") or {}).get("dividends") or {}).get("rows") or []):
        try:
            observed = datetime.strptime(item["exOrEffDate"], "%m/%d/%Y").date()
            distributions[observed] = distributions.get(observed, 0.0) + _number(item["amount"])
        except (KeyError, ValueError):
            continue
    rows = [(observed, close, distributions.get(observed, 0.0)) for observed, close in rows_by_date.items()]
    public_url = f"https://www.nasdaq.com/market-activity/{NASDAQ_ASSET_CLASSES[ticker]}/{ticker.lower()}/historical"
    return sorted(rows), public_url


def refresh_historical_drawdowns(payload: dict, get, today: date | None = None) -> list[dict]:
    """Refresh complete issuer histories; retain no values when validation fails."""
    today = today or date.today()
    evidence = []
    for asset in payload["assets"]:
        ticker = asset["ticker"]
        if ticker in NASDAQ_ASSET_CLASSES:
            evidence.append({
                "ticker": ticker, "status": "retained", "previousPercent": asset["historicalDD"],
                "usedPercent": asset["historicalDD"], "value": asset["historicalDD"],
                "start": asset["historicalDDStart"], "end": asset["historicalDDEnd"],
                "peak": asset["historicalDDPeak"], "trough": asset["historicalDDTrough"],
                "observations": None, "method": asset["historicalDDMethod"],
                "source": asset["historicalDDSource"],
                "reason": "Retained last verified full-history result; the current official Nasdaq endpoint is revalidated over the synchronized live portfolio period.",
            })
            continue
        try:
            rows, data_url = _ishares_rows(ticker, get, today)
            result = _max_drawdown(rows, "issuer NAV")
        except Exception as exc:
            evidence.append({"ticker": ticker, "status": "fail", "reason": str(exc)})
            continue
        previous = asset["historicalDD"]
        asset.update(
            historicalDD=round(result["value"], 2), historicalDDMethod=result["method"],
            historicalDDStart=result["start"], historicalDDEnd=result["end"],
            historicalDDPeak=result["peak"], historicalDDTrough=result["trough"],
            historicalDDSource=data_url,
        )
        evidence.append({"ticker": ticker, "status": "pass", "previousPercent": previous,
                         "usedPercent": asset["historicalDD"], **result, "source": data_url})
    return evidence


def synchronized_portfolio_history(payload: dict, get, today: date | None = None) -> dict:
    """Return daily total returns over the common live history of all holdings."""
    today = today or date.today()
    assets = payload["assets"]
    common_start = max(
        max(date.fromisoformat(asset["historicalDDStart"]) for asset in assets),
        today - timedelta(days=350),
    )
    common_end = today - timedelta(days=1)
    histories: dict[str, dict[date, float]] = {}
    sources = {}
    for asset in assets:
        ticker = asset["ticker"]
        if ticker in ISHARES_PORTFOLIOS:
            rows, source = _ishares_rows(ticker, get, today)
        else:
            rows, source = _nasdaq_rows(ticker, get, common_start - timedelta(days=2), common_end)
        histories[ticker] = {observed: value for observed, value in _total_returns(rows).items() if observed >= common_start}
        sources[ticker] = source
    common_dates = sorted(set.intersection(*(set(values) for values in histories.values())))
    if len(common_dates) < 220:
        raise RuntimeError(f"synchronized portfolio history has only {len(common_dates)} observations")
    return {
        "tickers": [asset["ticker"] for asset in assets], "start": common_dates[0].isoformat(),
        "end": common_dates[-1].isoformat(), "observations": len(common_dates), "rebalance": "monthly",
        "sources": sources,
        "returns": [[observed.isoformat(), *[round(histories[asset["ticker"]][observed], 8) for asset in assets]] for observed in common_dates],
    }
