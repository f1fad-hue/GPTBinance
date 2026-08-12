#!/usr/bin/env python3
"""Daily, evidence-first audit for Portfolio Signal Lab.

The audit distinguishes primary-source facts from transparent model inputs. It
never upgrades an unavailable source or a forecast into a verified fact.
"""
from __future__ import annotations
import csv, io, json, math, os, pathlib, statistics, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).parents[1]
DATA = ROOT / "data" / "market-data.json"
CLAIMS = ROOT / "data" / "claims.json"
REPORTS = ROOT / "reports" / "daily"
HEADERS = {"User-Agent": "f1fad-hue GPTBinance PortfolioSignalLab contact@f1fad-hue.github.io", "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
FRED = {
    "Inflation trend":"CPIAUCSL",
    "Policy rates":"EFFR",
    "Real yields":"DFII10",
    "Yield curve":"T10Y2Y",
    "Credit spreads":"BAMLH0A0HYM2",
    "Labor & activity":"UNRATE",
    "Financial conditions":"NFCI",
    "System liquidity":"M2SL",
    "Market volatility":"VIXCLS",
    "USD / EM FX trend":"DTWEXBGS",
}

def get(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise RuntimeError(f"source fetch failed after 3 attempts: {last_error}") from last_error

def fred_values(series: str) -> list[tuple[date,float]]:
    rows = csv.DictReader(io.StringIO(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")))
    values=[]; date_column=rows.fieldnames[0]
    for row in rows:
        try: values.append((date.fromisoformat(row[date_column]),float(row.get(series, ""))))
        except (TypeError,ValueError): pass
    if len(values)<13: raise RuntimeError(f"too little data for {series}")
    return values

def score(series: str, values: list[tuple[date,float]]) -> tuple[float,float,float]:
    inverse=series in {"CPIAUCSL","EFFR","DFII10","BAMLH0A0HYM2","UNRATE","NFCI","VIXCLS","DTWEXBGS"}
    latest_date,latest_value=values[-1]
    recent=[value for observed,value in values if observed>=latest_date-timedelta(days=5*365)]
    scale=max(statistics.pstdev(recent),.05)
    def one(months: int) -> float:
        target=latest_date-timedelta(days=round(months*365.25/12))
        prior=max((item for item in values if item[0]<=target),key=lambda item:item[0])
        change=latest_value-prior[1]
        signed=-change if inverse else change
        return round(max(1,min(5,3.5+signed/scale*.45)),1)
    return one(3),one(6),one(12)

def composite_dd(asset: dict) -> float: return .6*asset["historicalDD"]+.4*asset["forwardDD"]
def cap_from_rate(rate: float) -> float: return 30 if rate>=5 else 25 if rate>=4 else 20

def optimize(assets: list[dict], cap: float) -> list[float]:
    floor=5; step=5; dds=[composite_dd(x) for x in assets]; net=[x["grossCagr"]-x["fee"] for x in assets]
    ballast=min(range(len(assets)),key=lambda i:dds[i]); weights=[float(floor)]*len(assets); remaining=100-floor*len(assets)
    candidates=[i for i in range(len(assets)) if i!=ballast]
    best=max(candidates,key=lambda i:(net[i]-net[ballast])/(dds[i]-dds[ballast]))
    used=sum(w*d for w,d in zip(weights,dds)); raw_growth=max(0,min(remaining,(cap*100-used-remaining*dds[ballast])/(dds[best]-dds[ballast]))); growth=math.floor(raw_growth/step)*step
    weights[best]+=growth; weights[ballast]+=remaining-growth
    return weights

def math_checks(payload: dict) -> list[dict]:
    assets=payload["assets"]; macro=payload["macro"]
    assert {x["ticker"] for x in assets}=={"BAI","QQQ","IEMG","BINC","BMNR"}
    assert all(x["fee"]>=0 and x["grossCagr"]>x["fee"] and x["vol"]>0 for x in assets)
    assert len(macro)==10 and {x["driver"] for x in macro}==set(FRED) and all(1<=x[k]<=5 for x in macro for k in ("m3","m6","m12"))
    overlay=payload["bmnrOverlay"]; assert 1<=overlay["score"]<=5 and overlay["source"].startswith("https://www.sec.gov/")
    macro_avg=sum((x["m3"]+x["m6"]+x["m12"])/3 for x in macro)/len(macro)
    rate=round(max(1,min(5,2.2+macro_avg*.47)),1); cap=cap_from_rate(rate); weights=optimize(assets,cap)
    weighted_dd=sum(w*composite_dd(a) for w,a in zip(weights,assets))/100
    assert math.isclose(sum(weights),100,abs_tol=.0001) and weighted_dd<=cap+.001 and all(w%5==0 for w in weights)
    return [{"name":"required holdings","status":"pass"},{"name":"input bounds","status":"pass"},{"name":"ten distinct core macro-driver bounds","status":"pass"},{"name":"BMNR digital-asset overlay bounds","status":"pass","score":overlay["score"]},{"name":"max-growth drawdown constraint","status":"pass","rate":rate,"cap":cap,"computed_drawdown":round(weighted_dd,3)}]

def audit_sources(payload: dict, claims: list[dict]) -> tuple[list[dict],list[dict],list[str]]:
    evidence=[]; claim_evidence=[]; hard_failures=[]; source_status={}
    for source in payload["sources"]:
        if source.get("automation") == "restricted":
            item={"source":source["name"],"status":"manual-review","reason":"The authoritative endpoint restricts automated GitHub Actions access."}
            evidence.append(item); source_status[source["name"]]=item["status"]
            continue
        try:
            body=get(source.get("validation_url",source["url"]))
            if len(body) < 1000: raise RuntimeError(f"unexpectedly small response ({len(body)} bytes)")
            markers=source.get("required_text",[]); folded=body.casefold()
            missing=[marker for marker in markers if marker.casefold() not in folded]
            if missing: raise RuntimeError(f"missing expected source identity marker(s): {', '.join(missing)}")
            expected_fee=source.get("expected_fee")
            if expected_fee is not None:
                fee=f"{expected_fee:.2f}"; fee_markers=(f"{fee}%",f"{fee} %",f'"{fee}"')
                if not any(marker.casefold() in folded for marker in fee_markers): raise RuntimeError(f"expected fee value {fee}% was not found")
            item={"source":source["name"],"status":"pass","bytes":len(body),"identityMarkers":markers}
            if expected_fee is not None: item["verifiedFeePercent"]=expected_fee
            evidence.append(item); source_status[source["name"]]=item["status"]
        except Exception as exc:
            hard_failures.append(f"{source['name']}: {exc}")
            item={"source":source["name"],"status":"fail","reason":str(exc)}
            evidence.append(item); source_status[source["name"]]=item["status"]
    known={x["id"] for x in claims}; assert len(known)==len(claims)
    for claim in claims:
        if claim["kind"].startswith("model"):
            claim_evidence.append({"claim":claim["id"],"status":"model-assumption","source":claim["source"],"note":"Transparent model input/output; not an externally verified fact."})
            continue
        status=source_status.get(claim["source"])
        if status is None:
            status="fail"; hard_failures.append(f"claim {claim['id']}: unregistered source {claim['source']}")
        claim_evidence.append({"claim":claim["id"],"status":status,"source":claim["source"],"statement":claim["statement"]})
    return evidence,claim_evidence,hard_failures

def alpha_vantage_price_evidence(assets: list[dict]) -> list[dict]:
    """Preferred supplemental quote check. The key stays in GitHub Actions secrets."""
    api_key=os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return [{"source":"Alpha Vantage secondary market-price check","status":"manual-review","reason":"ALPHA_VANTAGE_API_KEY is not configured. Primary-source checks remain active."}]
    evidence=[]
    for asset in assets:
        ticker=asset["ticker"]
        try:
            payload=json.loads(get(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={api_key}"))
            quote=payload.get("Global Quote",{})
            price=float(quote.get("05. price",0))
            if quote.get("01. symbol")!=ticker or price<=0: raise RuntimeError(payload.get("Note") or payload.get("Information") or "missing or invalid quote")
            evidence.append({"source":f"Alpha Vantage secondary market-price check - {ticker}","status":"pass","price":price,"latestTradingDay":quote.get("07. latest trading day")})
        except Exception as exc:
            evidence.append({"source":f"Alpha Vantage secondary market-price check - {ticker}","status":"manual-review","reason":f"Supplemental quote unavailable: {exc}. This does not replace or invalidate primary-source checks."})
    return evidence

def yahoo_price_evidence(assets: list[dict]) -> list[dict]:
    """Optional secondary quote check; never a source of portfolio claims or inputs."""
    evidence=[]
    for asset in assets:
        ticker=asset["ticker"]
        try:
            payload=json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"))
            result=(payload.get("chart",{}).get("result") or [])[0]
            meta=result.get("meta",{})
            price=meta.get("regularMarketPrice")
            if meta.get("symbol")!=ticker or not isinstance(price,(int,float)) or price<=0: raise RuntimeError("missing or invalid quote")
            evidence.append({"source":f"Yahoo Finance secondary market-price check — {ticker}","status":"pass","price":price,"currency":meta.get("currency")})
        except Exception as exc:
            evidence.append({"source":f"Yahoo Finance secondary market-price check — {ticker}","status":"manual-review","reason":f"Supplemental public quote unavailable: {exc}. This does not replace or invalidate primary-source checks."})
    return evidence

def main() -> int:
    payload=json.loads(DATA.read_text(encoding="utf-8")); claims=json.loads(CLAIMS.read_text(encoding="utf-8"))["claims"]
    failures=[]
    for driver,series in FRED.items():
        try:
            m3,m6,m12=score(series,fred_values(series)); next(x for x in payload["macro"] if x["driver"]==driver).update(m3=m3,m6=m6,m12=m12)
        except Exception as exc: failures.append(f"FRED {series}: {exc}")
    try: checks=math_checks(payload)
    except Exception as exc: checks=[{"name":"math and schema","status":"fail","reason":str(exc)}]; failures.append(f"math: {exc}")
    evidence,claim_evidence,source_failures=audit_sources(payload,claims); failures.extend(source_failures); evidence.extend(alpha_vantage_price_evidence(payload["assets"])); evidence.extend(yahoo_price_evidence(payload["assets"]))
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'); payload["asOf"]=now[:10]
    manual=any(x["status"]=="manual-review" for x in evidence)
    status="PASS — primary-source, macro and math checks completed" if not failures and not manual else ("PASS WITH MANUAL REVIEW — automated checks completed; restricted source remains queued for human review" if not failures else "REVIEW REQUIRED — "+" | ".join(failures))
    payload["validation"]={"status":status,"checkedAt":now}
    REPORTS.mkdir(parents=True,exist_ok=True)
    report={"checkedAt":now,"status":status,"sourceEvidence":evidence,"claimEvidence":claim_evidence,"mathChecks":checks,"failures":failures,"limitations":["No automated system can prove a forecast or perform unrestricted deep research without a separately configured research provider.","BMNR SEC EDGAR is retained as the authoritative source but marked manual-review because the SEC blocks this automated runner.","Deterministic checks can refresh data and reject invalid output, but arbitrary code defects require review rather than unsafe automated rewriting."]}
    (REPORTS/f"{now[:10]}.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    DATA.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(status)
    return 1 if failures else 0
if __name__ == "__main__": sys.exit(main())
