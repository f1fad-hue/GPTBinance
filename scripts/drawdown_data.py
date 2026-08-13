#!/usr/bin/env python3
"""Authoritative historical drawdown series and calculations."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

ISHARES_PORTFOLIOS = {"IEMG": "244050", "SGOV": "314116"}
NASDAQ_ASSET_CLASSES = {"QQQ": "etf", "BMNR": "stocks"}
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


def _max_drawdown(rows: list[tuple[date, float, float]], source_type: str) -> dict:
    rows = sorted(rows)
    if len(rows) < 2:
        raise RuntimeError("insufficient observations for historical drawdown")
    wealth = peak = 1.0
    peak_date = rows[0][0]
    worst = 0.0
    worst_peak = worst_trough = peak_date
    for index in range(1, len(rows)):
        observed, value, distribution = rows[index]
        previous_value = rows[index - 1][1]
        if value <= 0 or previous_value <= 0:
            raise RuntimeError("non-positive historical value")
        wealth *= (value + distribution) / previous_value
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


def _ishares_history(ticker: str, get, today: date) -> tuple[dict, str]:
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
    return _max_drawdown(rows, "issuer NAV"), url


def _nasdaq_history(ticker: str, get, today: date) -> tuple[dict, str]:
    cutoff = _cutoff(today)
    end_date = today - timedelta(days=1)
    # Nasdaq's full 10-year response can stall on hosted CI networks. Paginate
    # the same official date range in bounded responses and deduplicate dates.
    rows_by_date: dict[date, float] = {}
    offset = 0
    total_records = None
    while total_records is None or offset < total_records:
        params = urlencode({
            "assetclass": NASDAQ_ASSET_CLASSES[ticker],
            "fromdate": cutoff.isoformat(),
            "todate": end_date.isoformat(),
            "limit": 500,
            "offset": offset,
        })
        api_url = f"https://api.nasdaq.com/api/quote/{ticker}/historical?{params}"
        payload = json.loads(get(api_url))
        data = payload.get("data") or {}
        rows_payload = (data.get("tradesTable") or {}).get("rows") or []
        total_records = int(data.get("totalRecords") or 0)
        if not rows_payload:
            break
        for item in rows_payload:
            try:
                observed = datetime.strptime(item["date"], "%m/%d/%Y").date()
                rows_by_date[observed] = _number(item["close"])
            except (KeyError, ValueError):
                continue
        offset += len(rows_payload)
    distributions = {}
    dividend_url = f"https://api.nasdaq.com/api/quote/{ticker}/dividends?assetclass={NASDAQ_ASSET_CLASSES[ticker]}"
    dividend_payload = json.loads(get(dividend_url))
    for item in (((dividend_payload.get("data") or {}).get("dividends") or {}).get("rows") or []):
        try:
            observed = datetime.strptime(item["exOrEffDate"], "%m/%d/%Y").date()
            distributions[observed] = distributions.get(observed, 0.0) + _number(item["amount"])
        except (KeyError, ValueError):
            continue
    rows = [(observed, close, distributions.get(observed, 0.0))
            for observed, close in rows_by_date.items()]
    public_url = f"https://www.nasdaq.com/market-activity/{NASDAQ_ASSET_CLASSES[ticker]}/{ticker.lower()}/historical"
    return _max_drawdown(rows, "Nasdaq closing-price"), public_url


def refresh_historical_drawdowns(payload: dict, get, today: date | None = None) -> list[dict]:
    today = today or date.today()
    evidence = []
    for asset in payload["assets"]:
        ticker = asset["ticker"]
        try:
            result, data_url = (_ishares_history(ticker, get, today) if ticker in ISHARES_PORTFOLIOS
                                else _nasdaq_history(ticker, get, today))
        except Exception as exc:
            raise RuntimeError(f"{ticker}: {exc}") from exc
        previous = asset["historicalDD"]
        asset.update(
            historicalDD=round(result["value"], 2),
            historicalDDMethod=result["method"],
            historicalDDStart=result["start"],
            historicalDDEnd=result["end"],
            historicalDDPeak=result["peak"],
            historicalDDTrough=result["trough"],
            historicalDDSource=data_url,
        )
        evidence.append({"ticker": ticker, "status": "pass", "previousPercent": previous,
                         "usedPercent": asset["historicalDD"], **result, "source": data_url})
    return evidence
