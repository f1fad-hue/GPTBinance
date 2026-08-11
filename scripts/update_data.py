#!/usr/bin/env python3
"""Daily source availability, macro-score and math validation for Portfolio Signal Lab.

This deliberately uses public, primary endpoints only. It does not manufacture a
price history, issue trade instructions, or claim that a model forecast is factual.
"""
from __future__ import annotations
import csv, io, json, math, pathlib, statistics, sys, urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).parents[1]
DATA = ROOT / "data" / "market-data.json"
HEADERS = {"User-Agent": "PortfolioSignalLab/1.0 research-contact: github.com/f1fad-hue/GPTBinance"}
FRED = {"Inflation trend":"CPIAUCSL","Policy & real rates":"EFFR","Yield curve":"T10Y2Y","Credit spreads":"BAMLH0A0HYM2","Labor & activity":"UNRATE","Market volatility":"VIXCLS"}

def get(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200: raise RuntimeError(f"{response.status}: {url}")
        return response.read().decode("utf-8")

def fred_values(series: str) -> list[float]:
    body = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    rows = csv.DictReader(io.StringIO(body)); values=[]
    for row in rows:
        raw=row.get(series, "")
        try: values.append(float(raw))
        except ValueError: pass
    if len(values)<13: raise RuntimeError(f"too little data for {series}")
    return values

def score(series: str, values: list[float]) -> tuple[float,float,float]:
    """Return bounded 1–5 directional persistence scores at 3/6/12 months.
    For inflation, unemployment, spreads and volatility, declines are supportive;
    for EFFR and curve, the score follows easing/steepening persistence.
    """
    inverse=series in {"CPIAUCSL","EFFR","BAMLH0A0HYM2","UNRATE","VIXCLS"}
    def one(months):
        change=values[-1]-values[-min(months,len(values)-1)-1]
        signed=-change if inverse else change
        scale=max(statistics.pstdev(values[-min(60,len(values)):]),.05)
        return round(max(1,min(5,3.5+signed/scale*.45)),1)
    return one(3),one(6),one(12)

def validate_model(payload: dict) -> None:
    assets=payload["assets"]
    assert {x["ticker"] for x in assets} == {"BAI","QQQ","IEMG","BINC","BMNR"}
    assert all(x["fee"]>=0 and x["grossCagr"]>x["fee"] for x in assets)
    macro=payload["macro"]; assert len(macro)==6 and all(1<=x[k]<=5 for x in macro for k in ("m3","m6","m12"))

def main() -> int:
    payload=json.loads(DATA.read_text(encoding="utf-8")); failed=[]
    # Validate all displayed primary source URLs; FRED fields are refreshed below.
    for source in payload["sources"]:
        try: get(source["url"])
        except Exception as exc: failed.append(f"{source['name']}: {exc}")
    for driver,series in FRED.items():
        try:
            values=fred_values(series); m3,m6,m12=score(series,values)
            row=next(x for x in payload["macro"] if x["driver"]==driver)
            row.update(m3=m3,m6=m6,m12=m12)
        except Exception as exc: failed.append(f"FRED {series}: {exc}")
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
    try: validate_model(payload)
    except Exception as exc: failed.append(f"model validation: {exc}")
    payload["asOf"]=now[:10]
    payload["validation"]={"status":("PASS — source endpoints and model checks completed" if not failed else "REVIEW REQUIRED — " + " | ".join(failed)),"checkedAt":now}
    DATA.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(payload["validation"]["status"])
    # Preserve last usable data but fail the job visibly when a source is unavailable.
    return 1 if failed else 0
if __name__ == "__main__": sys.exit(main())
