#!/usr/bin/env python3
"""Daily, evidence-first audit for Portfolio Signal Lab.

The audit distinguishes primary-source facts from transparent model inputs. It
never upgrades an unavailable source or a forecast into a verified fact.
"""
from __future__ import annotations
import csv, html, io, itertools, json, math, pathlib, re, statistics, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

from drawdown_data import refresh_historical_drawdowns, synchronized_portfolio_history
from portfolio_model import build_model, cap_from_rate as robust_cap_from_rate

ROOT = pathlib.Path(__file__).parents[1]
DATA = ROOT / "data" / "market-data.json"
CLAIMS = ROOT / "data" / "claims.json"
REPORTS = ROOT / "reports" / "daily"
HEADERS = {"User-Agent": "f1fad-hue GPTBinance PortfolioSignalLab contact@f1fad-hue.github.io", "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
NASDAQ_HEADERS = {"User-Agent": "Mozilla/5.0 GPTBinance-PortfolioSignalLab/1.0 contact@f1fad-hue.github.io", "Accept": "application/json, text/plain, */*", "Accept-Encoding": "identity", "Connection": "close", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
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
    "Industrial production":"INDPRO",
    "Bank lending standards":"DRTSCILM",
    "Nominal Treasury yields":"DGS10",
    "Inflation expectations":"T5YIE",
    "Payroll momentum":"PAYEMS",
    "Real consumer demand":"RRSFS",
}
MIN_WEIGHT = 5
WEIGHT_STEP = 5
MONTE_CARLO_PATHS = 10_000
MONTE_CARLO_YEARS = 10
TICKERS = ("QQQ", "IEMG", "SGOV", "BMNR")
DRIVER_EXPOSURE = {
    "Inflation trend": (.85, .70, .95, .65),
    "Policy rates": (.95, .60, 1.00, .80),
    "Real yields": (1.00, .70, .90, .85),
    "Yield curve": (.75, .60, .80, .55),
    "Credit spreads": (.70, .75, .25, .80),
    "Labor & activity": (.80, .65, .30, .55),
    "Financial conditions": (.90, .80, .45, 1.00),
    "System liquidity": (.90, .75, .35, 1.00),
    "Market volatility": (.85, .80, .45, 1.00),
    "USD / EM FX trend": (.45, 1.00, .40, .65),
    "Industrial production": (.65, .90, .25, .45),
    "Bank lending standards": (.60, .65, .30, .70),
    "Nominal Treasury yields": (.95, .55, 1.00, .65),
    "Inflation expectations": (.85, .65, .90, .65),
    "Payroll momentum": (.75, .55, .25, .45),
    "Real consumer demand": (.80, .60, .25, .50),
}
REGION_DRIVER_WEIGHTS = {
    "US": {"Inflation trend":.8,"Policy rates":1,"Real yields":1,"Yield curve":.8,"Credit spreads":.8,"Labor & activity":.9,"Financial conditions":1,"System liquidity":.9,"Market volatility":.8,"Nominal Treasury yields":1,"Inflation expectations":.8,"Payroll momentum":.9,"Real consumer demand":.9},
    "Europe": {"Inflation trend":.6,"Policy rates":.5,"Real yields":.6,"Yield curve":.5,"Credit spreads":.8,"Labor & activity":.6,"Financial conditions":.9,"System liquidity":.7,"Market volatility":.8,"USD / EM FX trend":.8,"Industrial production":.8,"Bank lending standards":.7,"Nominal Treasury yields":.5,"Inflation expectations":.6,"Real consumer demand":.7},
    "Asia": {"Inflation trend":.6,"Policy rates":.5,"Real yields":.5,"Yield curve":.5,"Credit spreads":.7,"Labor & activity":.6,"Financial conditions":.9,"System liquidity":.8,"Market volatility":.9,"USD / EM FX trend":1,"Industrial production":1,"Bank lending standards":.6,"Nominal Treasury yields":.5,"Inflation expectations":.6,"Payroll momentum":.5,"Real consumer demand":.8},
}
RESPONSE_CACHE: dict[str, str] = {}

def get(url: str) -> str:
    if url in RESPONSE_CACHE:
        return RESPONSE_CACHE[url]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            headers = NASDAQ_HEADERS if "api.nasdaq.com" in url else HEADERS
            timeout = 180 if "get-fund-document" in url else (90 if "api.nasdaq.com" in url else 30)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
                body=response.read().decode("utf-8", errors="replace")
                RESPONSE_CACHE[url]=body
                return body
        except Exception as exc:
            last_error = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise RuntimeError(f"source fetch failed after 3 attempts for {url}: {last_error}") from last_error

def extract_gross_expense_ratio(body: str) -> float:
    """Extract one issuer-labelled gross/total expense ratio; reject ambiguity."""
    structured=re.findall(r'"name"\s*:\s*"Expense Ratio:?"\s*,\s*"value"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',body,re.I)
    if structured: candidates={round(float(value),4) for value in structured}
    else:
        plain=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",body)))
        total=re.findall(r"total expense ratio\s+(?:is\s+)?([0-9]+(?:\.[0-9]+)?)\s*%",plain,re.I)
        gross=re.findall(r"(?<!Net )Expense Ratio:\s*(?:Fees as stated in the prospectus\s*)?([0-9]+(?:\.[0-9]+)?)\s*%",plain,re.I)
        candidates={round(float(value),4) for value in total+gross}
    if len(candidates)!=1: raise RuntimeError(f"ambiguous or missing issuer-labelled gross expense ratio: {sorted(candidates)}")
    fee=candidates.pop()
    if not 0<=fee<=5: raise RuntimeError(f"issuer fee outside sanity range: {fee}%")
    return fee

def fred_values(series: str) -> list[tuple[date,float]]:
    rows = csv.DictReader(io.StringIO(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")))
    values=[]; date_column=rows.fieldnames[0]
    for row in rows:
        try: values.append((date.fromisoformat(row[date_column]),float(row.get(series, ""))))
        except (TypeError,ValueError): pass
    if len(values)<13: raise RuntimeError(f"too little data for {series}")
    return values

def score(series: str, values: list[tuple[date,float]]) -> tuple[float,float,float]:
    inverse=series in {"CPIAUCSL","EFFR","DFII10","DGS10","T5YIE","BAMLH0A0HYM2","UNRATE","NFCI","VIXCLS","DTWEXBGS","DRTSCILM"}
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

def cap_from_rate(rate: float) -> float: return 30 if rate>=5 else 25 if rate>=4 else 20

def _horizon_scores(macro: list[dict], driver_weights: dict[str,float] | None = None) -> dict[str,float]:
    weights=driver_weights or {item["driver"]:1.0 for item in macro}
    return {key:round(sum(item[key]*weights.get(item["driver"],0) for item in macro)/sum(weights.get(item["driver"],0) for item in macro),2) for key in ("m3","m6","m12")}

def sentiment_outputs(macro: list[dict], assets: list[dict], weights: list[float]) -> tuple[dict,dict,list[dict]]:
    broad=_horizon_scores(macro)
    ticker_index={ticker:index for index,ticker in enumerate(TICKERS)}
    transmission={}
    for driver,exposure in DRIVER_EXPOSURE.items():
        transmission[driver]=sum(weights[ticker_index[ticker]]*exposure[ticker_index[ticker]] for ticker in TICKERS)/100
    correlated=_horizon_scores(macro,transmission)
    regional=[]
    for region,region_weights in REGION_DRIVER_WEIGHTS.items():
        scores=_horizon_scores(macro,region_weights)
        regional.append({"region":region,**scores,"average":round(sum(scores.values())/3,2)})
    regional.sort(key=lambda item:(-item["average"],item["region"]))
    for rank,item in enumerate(regional,1): item["rank"]=rank
    return broad,correlated,regional

def select_rate(assets: list[dict], macro: list[dict], scenarios: dict[int,list[float]]) -> tuple[float,list[float],dict,dict,list[dict]]:
    band=4
    seen=[]
    while band not in seen:
        seen.append(band)
        weights=scenarios[band]
        broad,correlated,regional=sentiment_outputs(macro,assets,weights)
        rate=round(max(1,min(5,.40*sum(broad.values())/3+.60*sum(correlated.values())/3)),2)
        new_band=5 if rate>=5 else 4 if rate>=4 else 3
        if new_band==band: return rate,weights,broad,correlated,regional
        band=new_band
    band=min(seen[-1],band)
    weights=scenarios[band]
    broad,correlated,regional=sentiment_outputs(macro,assets,weights)
    rate=round(max(1,min(5,.40*sum(broad.values())/3+.60*sum(correlated.values())/3)),2)
    rate=min(rate,3.99) if band==3 else min(max(rate,4),4.99) if band==4 else 5.0
    return rate,weights,broad,correlated,regional

def optimize(assets: list[dict], cap: float) -> list[float]:
    """Exhaustively maximize net CAGR on the 5% allocation grid."""
    units=(100-MIN_WEIGHT*len(assets))//WEIGHT_STEP; best=None
    for prefix in itertools.product(range(units+1),repeat=len(assets)-1):
        used=sum(prefix)
        if used>units: continue
        extras=(*prefix,units-used)
        weights=[float(MIN_WEIGHT+WEIGHT_STEP*x) for x in extras]
        drawdown=sum(w*a["historicalDD"] for w,a in zip(weights,assets))/100
        if drawdown>cap+1e-9: continue
        growth=sum(w*(a["grossCagr"]-a["fee"]) for w,a in zip(weights,assets))/100
        candidate=(growth,-drawdown,weights)
        if best is None or candidate[:2]>best[:2]: best=candidate
    if best is None: raise RuntimeError(f"no feasible allocation under {cap}% drawdown cap")
    return best[2]

def monte_carlo_summary(assets: list[dict], weights: list[float]) -> dict:
    cagr=sum(w*(a["grossCagr"]-a["fee"]) for w,a in zip(weights,assets))/100
    volatility=sum(w*a["vol"] for w,a in zip(weights,assets))/100
    state=107; mask=0xFFFFFFFF
    def browser_random() -> float:
        nonlocal state
        state=(state+0x6D2B79F5)&mask
        value=((state^(state>>15))*(1|state))&mask
        value=(value^(value+(((value^(value>>7))*(61|value))&mask)))&mask
        return ((value^(value>>14))&mask)/4294967296
    terminals=[]
    for _ in range(MONTE_CARLO_PATHS):
        value=1.0
        for _ in range(MONTE_CARLO_YEARS):
            z=(sum(browser_random() for _ in range(6))-3)*math.sqrt(2)
            value*=math.exp(cagr/100-.5*(volatility/100)**2+(volatility/100)*z)
        terminals.append(value)
    terminals.sort(); p10=terminals[999]; p50=terminals[4999]; p90=terminals[8999]
    return {"paths":MONTE_CARLO_PATHS,"years":MONTE_CARLO_YEARS,"p10Terminal":round(p10,3),"p50Terminal":round(p50,3),"p90Terminal":round(p90,3),"p50Annualized":round((p50**(1/MONTE_CARLO_YEARS)-1)*100,3)}

def math_checks(payload: dict) -> list[dict]:
    assets=payload["assets"]; macro=payload["macro"]; model=payload["model"]
    required=set(TICKERS)
    assert [x["ticker"] for x in assets]==list(TICKERS)
    assert all(x["fee"]>=0 and x["grossCagr"]>x["fee"] and x["vol"]>0 and x["forecastUncertainty"]>0 and 1<=x["relevance"]<=100 for x in assets)
    assert "forwardDDModel" not in payload and all(not any(key.startswith("forward") and key.endswith("DD") for key in x) for x in assets)
    assert all(x["historicalDD"]>0 and x["historicalDDMethod"].startswith("Observed daily") and x["historicalDDStart"]<=x["historicalDDPeak"]<=x["historicalDDTrough"]<=x["historicalDDEnd"] for x in assets)
    assert all(x["monitorStatus"] in {"Relevant","Watch","Not relevant"} and x["monitorNote"] and x["notRelevant"] and x["cadence"] for x in assets)
    assert len(macro)==len(FRED)==16 and {x["driver"] for x in macro}==set(FRED) and all(1<=x[k]<=5 for x in macro for k in ("m3","m6","m12"))
    assert all(x["why"] and ("all four holdings" in x["why"] or any(ticker in x["why"] for ticker in required)) for x in macro)
    overlay=payload["bmnrOverlay"]; assert 1<=overlay["score"]<=5 and overlay["source"].startswith("https://www.sec.gov/")
    assert model["method"]=="robust-path-growth-v1" and model["history"]["observations"]>=250
    assert model["history"]["tickers"]==list(TICKERS) and model["history"]["rebalance"]=="monthly"
    assert set(model["scenarios"])=={"3","4","5"}
    scenario_weights={int(rate):[scenario["weights"][ticker] for ticker in TICKERS] for rate,scenario in model["scenarios"].items()}
    for rate,weights in scenario_weights.items():
        scenario=model["scenarios"][str(rate)]; cap=robust_cap_from_rate(rate)
        assert scenario["cap"]==cap and sum(weights)==100
        assert all(weight>=MIN_WEIGHT and weight%WEIGHT_STEP==0 for weight in weights)
        assert scenario["weights"]["BMNR"]<=model["constraints"]["bmnrMaximumWeight"]
        assert scenario["observedPortfolio"]["maxDrawdown"]<=cap and scenario["stress"]["worstLoss"]<=cap
        assert scenario["simulation"]["paths"]==10_000 and scenario["simulation"]["years"]==10
        assert scenario["simulation"]["breachProbability"]<=model["constraints"]["maximumDrawdownBreachProbability"]+.015
        assert 0<scenario["simulation"]["p10Terminal"]<scenario["simulation"]["p50Terminal"]<scenario["simulation"]["p90Terminal"]
    rate,weights,broad,correlated,regional=select_rate(assets,macro,scenario_weights); band=5 if rate>=5 else 4 if rate>=4 else 3
    assert weights==scenario_weights[band]
    assert len(DRIVER_EXPOSURE)==16 and set(DRIVER_EXPOSURE)==set(FRED)
    assert {item["region"] for item in regional}=={"US","Europe","Asia"} and {item["rank"] for item in regional}=={1,2,3}
    assert all(1<=value<=5 for output in (broad,correlated) for value in output.values())
    selected=model["scenarios"][str(band)]
    return [
        {"name":"required holdings and allocation grid","status":"pass"},
        {"name":"input, uncertainty and relevance bounds","status":"pass"},
        {"name":"synchronized monthly-rebalanced portfolio path","status":"pass","start":model["history"]["start"],"end":model["history"]["end"],"observations":model["history"]["observations"]},
        {"name":"robust drawdown controls","status":"pass","observedPath":True,"stressScenarios":len(model["stressScenarios"]),"maximumBreachProbability":model["constraints"]["maximumDrawdownBreachProbability"]},
        {"name":"sixteen distinct portfolio-related macro drivers","status":"pass"},
        {"name":"broad and allocation-correlated sentiment","status":"pass","broad":broad,"correlated":correlated,"rate":rate},
        {"name":"US Europe Asia transmission ranking","status":"pass","ranking":regional},
        {"name":"robust growth scenario allocations","status":"pass","scenarios":model["scenarios"]},
        {"name":"10-year correlated Monte Carlo return and drawdown simulation","status":"pass",**selected["simulation"]},
        {"name":"BMNR concentration and digital-asset gates","status":"pass","score":overlay["score"],"maximumWeight":model["constraints"]["bmnrMaximumWeight"]},
    ]

def audit_sources(payload: dict, claims: list[dict], drawdown_evidence: list[dict]) -> tuple[list[dict],list[dict],list[str]]:
    evidence=[]; claim_evidence=[]; hard_failures=[]; source_status={}
    for source in payload["sources"]:
        if source.get("automation") == "historical-drawdown":
            result=next((item for item in drawdown_evidence if item.get("ticker")==source.get("asset_ticker")),None)
            status=("pass-retained" if result and result.get("status")=="retained" else "pass" if result and result.get("status")=="pass" else "fail")
            item={"source":source["name"],"status":status,"ticker":source.get("asset_ticker")}
            if result: item.update(usedHistoricalDrawdownPercent=result.get("usedPercent"),observations=result.get("observations"),period=f"{result.get('start')} to {result.get('end')}",dataUrl=result.get("source"))
            if status=="fail": hard_failures.append(f"{source['name']}: historical series validation missing")
            evidence.append(item); source_status[source["name"]]=status
            continue
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
            item={"source":source["name"],"status":"pass","bytes":len(body),"identityMarkers":markers}
            if source.get("fee_field")=="gross_expense_ratio":
                fee=extract_gross_expense_ratio(body); ticker=source["asset_ticker"]
                asset=next(asset for asset in payload["assets"] if asset["ticker"]==ticker)
                item["previousFeePercent"]=asset["fee"]; asset["fee"]=fee; item["usedFeePercent"]=fee
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

def main() -> int:
    original_data=DATA.read_text(encoding="utf-8")
    payload=json.loads(original_data); claims=json.loads(CLAIMS.read_text(encoding="utf-8"))["claims"]
    for asset in payload["assets"]:
        for key in list(asset):
            if key.startswith("forward") and key.endswith("DD"): asset.pop(key)
    payload.pop("forwardDDModel",None)
    failures=[]
    for driver,series in FRED.items():
        try:
            m3,m6,m12=score(series,fred_values(series)); next(x for x in payload["macro"] if x["driver"]==driver).update(m3=m3,m6=m6,m12=m12)
        except Exception as exc: failures.append(f"FRED {series}: {exc}")
    drawdown_evidence=refresh_historical_drawdowns(payload,get)
    failures.extend(f"historical drawdown {item['ticker']}: {item['reason']}" for item in drawdown_evidence if item["status"]=="fail")
    try:
        history=synchronized_portfolio_history(payload,get)
        payload["model"]=build_model(payload,history)
    except Exception as exc:
        failures.append(f"synchronized robust portfolio model: {exc}")
    evidence,claim_evidence,source_failures=audit_sources(payload,claims,drawdown_evidence); failures.extend(source_failures)
    try: checks=math_checks(payload)
    except Exception as exc: checks=[{"name":"math and schema","status":"fail","reason":str(exc)}]; failures.append(f"math: {exc}")
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'); payload["asOf"]=now[:10]
    manual=any(x["status"]=="manual-review" for x in evidence)
    status="PASS — primary-source, macro and math checks completed" if not failures and not manual else ("PASS WITH MANUAL REVIEW — automated checks completed; restricted source remains queued for human review" if not failures else "REVIEW REQUIRED — "+" | ".join(failures))
    payload["validation"]={"status":status,"checkedAt":now}
    REPORTS.mkdir(parents=True,exist_ok=True)
    report={"checkedAt":now,"status":status,"sourceEvidence":evidence,"historicalDrawdownEvidence":drawdown_evidence,"claimEvidence":claim_evidence,"mathChecks":checks,"failures":failures,"limitations":["Observed portfolio maximum drawdown uses only the synchronized live period shared by all four holdings; BMNR makes that period materially shorter than ten years.","The 10-year correlated simulation, stress shocks, forecast uncertainty and correlation matrix are transparent model assumptions, not verified future facts.","The official Nasdaq endpoint does not reliably expose a complete ten-year archive on every run; last verified full-history QQQ and BMNR drawdowns are retained while the common live period is revalidated.","No historical or simulated constraint can guarantee a future drawdown cap.","BMNR SEC EDGAR is retained as the authoritative source but marked manual-review because the SEC restricts this automated runner."]}
    (REPORTS/f"{now[:10]}.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if not failures:
        DATA.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(status)
    return 1 if failures else 0
if __name__ == "__main__": sys.exit(main())
