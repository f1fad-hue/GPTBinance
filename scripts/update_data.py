#!/usr/bin/env python3
"""Daily, evidence-first audit for Portfolio Signal Lab.

The audit distinguishes primary-source facts from transparent model inputs. It
never upgrades an unavailable source or a forecast into a verified fact.
"""
from __future__ import annotations
import csv, html, io, itertools, json, math, os, pathlib, re, shutil, statistics, subprocess, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone

from drawdown_data import refresh_historical_drawdowns

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
}
MIN_WEIGHT = 1
WEIGHT_STEP = 1
MONTE_CARLO_PATHS = 10_000
MONTE_CARLO_YEARS = 10

def get(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if "api.nasdaq.com" in url:
                if os.name == "nt":
                    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
                    if not powershell: raise RuntimeError("PowerShell is required for Nasdaq's streaming API on Windows")
                    command = "$ProgressPreference='SilentlyContinue';(Invoke-WebRequest -UseBasicParsing -Uri $env:GPTBINANCE_NASDAQ_URL -Headers @{'User-Agent'='Mozilla/5.0';'Accept'='application/json';'Origin'='https://www.nasdaq.com';'Referer'='https://www.nasdaq.com/'} -TimeoutSec 90).Content"
                    environment = os.environ.copy(); environment["GPTBINANCE_NASDAQ_URL"] = url
                    response = subprocess.run([powershell,"-NoProfile","-Command",command],capture_output=True,check=False,timeout=100,env=environment)
                else:
                    curl = shutil.which("curl")
                    if not curl: raise RuntimeError("curl is required for Nasdaq's streaming API")
                    response = subprocess.run(
                        [curl, "--ipv4", "--retry", "3", "--retry-all-errors", "--retry-delay", "2",
                         "--fail", "--silent", "--show-error", "--max-time", "90",
                         "--user-agent", NASDAQ_HEADERS["User-Agent"], "--header", "Accept: application/json",
                         "--header", "Origin: https://www.nasdaq.com", "--header", "Referer: https://www.nasdaq.com/", url],
                        capture_output=True, check=False, timeout=100,
                    )
                if response.returncode: raise RuntimeError(response.stderr.decode("utf-8",errors="replace").strip())
                return response.stdout.decode("utf-8",errors="replace")
            headers = NASDAQ_HEADERS if "api.nasdaq.com" in url else HEADERS
            timeout = 180 if "get-fund-document" in url else (120 if "api.nasdaq.com" in url else 30)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200: raise RuntimeError(f"HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < 2: time.sleep(2 ** attempt)
    raise RuntimeError(f"source fetch failed after 3 attempts: {last_error}") from last_error

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
    inverse=series in {"CPIAUCSL","EFFR","DFII10","BAMLH0A0HYM2","UNRATE","NFCI","VIXCLS","DTWEXBGS","DRTSCILM"}
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

def optimize(assets: list[dict], cap: float) -> list[float]:
    """Exhaustively maximize net CAGR on the 1% allocation grid."""
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
    assets=payload["assets"]; macro=payload["macro"]
    required={"QQQ","IEMG","BINC","BMNR"}
    assert {x["ticker"] for x in assets}==required
    assert all(x["fee"]>=0 and x["grossCagr"]>x["fee"] and x["vol"]>0 and 1<=x["relevance"]<=100 for x in assets)
    assert "forwardDDModel" not in payload and all(not any(key.startswith("forward") and key.endswith("DD") for key in x) for x in assets)
    assert all(x["historicalDD"]>0 and x["historicalDDMethod"].startswith("Observed daily") and x["historicalDDStart"]<=x["historicalDDPeak"]<=x["historicalDDTrough"]<=x["historicalDDEnd"] for x in assets)
    assert all(x["monitorStatus"] in {"Relevant","Watch","Not relevant"} and x["monitorNote"] and x["notRelevant"] and x["cadence"] for x in assets)
    assert len(macro)==len(FRED)==12 and {x["driver"] for x in macro}==set(FRED) and all(1<=x[k]<=5 for x in macro for k in ("m3","m6","m12"))
    assert all(x["why"] and ("all four holdings" in x["why"] or any(ticker in x["why"] for ticker in required)) for x in macro)
    overlay=payload["bmnrOverlay"]; assert 1<=overlay["score"]<=5 and overlay["source"].startswith("https://www.sec.gov/")
    macro_avg=sum((x["m3"]+x["m6"]+x["m12"])/3 for x in macro)/len(macro)
    scenarios={scenario:optimize(assets,cap_from_rate(scenario)) for scenario in (3,4,5)}
    rate=round(max(1,min(5,2.2+macro_avg*.47)),1); cap=cap_from_rate(rate); weights=scenarios[5 if rate>=5 else 4 if rate>=4 else 3]
    weighted_dd=sum(w*a["historicalDD"] for w,a in zip(weights,assets))/100
    assert math.isclose(sum(weights),100,abs_tol=.0001) and weighted_dd<=cap+.001 and all(w%WEIGHT_STEP==0 and w>=MIN_WEIGHT for w in weights)
    simulation=monte_carlo_summary(assets,weights); assert 0<simulation["p10Terminal"]<simulation["p50Terminal"]<simulation["p90Terminal"]
    scenario_check={str(scenario):dict(zip([a["ticker"] for a in assets],[round(w) for w in scenario_weights])) for scenario,scenario_weights in scenarios.items()}
    scenario_dd={str(scenario):{"cap":cap_from_rate(scenario),"computedHistoricalDrawdown":round(sum(w*a["historicalDD"] for w,a in zip(scenario_weights,assets))/100,3)} for scenario,scenario_weights in scenarios.items()}
    assert all(item["computedHistoricalDrawdown"]<=item["cap"] for item in scenario_dd.values())
    return [{"name":"required holdings","status":"pass"},{"name":"input and relevance bounds","status":"pass"},{"name":"historical maximum-drawdown-only rule","status":"pass","historicalWeight":1,"forwardWeight":0},{"name":"twelve distinct portfolio-related macro drivers","status":"pass"},{"name":"exact max-CAGR scenario allocations","status":"pass","allocations":scenario_check,"drawdownChecks":scenario_dd},{"name":"10-year Monte Carlo return simulation","status":"pass",**simulation},{"name":"BMNR digital-asset overlay bounds","status":"pass","score":overlay["score"]},{"name":"max-growth historical drawdown constraint","status":"pass","rate":rate,"cap":cap,"computed_drawdown":round(weighted_dd,3)}]

def audit_sources(payload: dict, claims: list[dict], drawdown_evidence: list[dict]) -> tuple[list[dict],list[dict],list[str]]:
    evidence=[]; claim_evidence=[]; hard_failures=[]; source_status={}
    for source in payload["sources"]:
        if source.get("automation") == "historical-drawdown":
            result=next((item for item in drawdown_evidence if item.get("ticker")==source.get("asset_ticker")),None)
            status="pass" if result and result.get("status")=="pass" else "fail"
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
    payload=json.loads(DATA.read_text(encoding="utf-8")); claims=json.loads(CLAIMS.read_text(encoding="utf-8"))["claims"]
    for asset in payload["assets"]:
        for key in list(asset):
            if key.startswith("forward") and key.endswith("DD"): asset.pop(key)
    payload.pop("forwardDDModel",None)
    failures=[]
    for driver,series in FRED.items():
        try:
            m3,m6,m12=score(series,fred_values(series)); next(x for x in payload["macro"] if x["driver"]==driver).update(m3=m3,m6=m6,m12=m12)
        except Exception as exc: failures.append(f"FRED {series}: {exc}")
    try: drawdown_evidence=refresh_historical_drawdowns(payload,get)
    except Exception as exc: drawdown_evidence=[{"status":"fail","reason":str(exc)}]; failures.append(f"historical drawdown: {exc}")
    evidence,claim_evidence,source_failures=audit_sources(payload,claims,drawdown_evidence); failures.extend(source_failures)
    try: checks=math_checks(payload)
    except Exception as exc: checks=[{"name":"math and schema","status":"fail","reason":str(exc)}]; failures.append(f"math: {exc}")
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'); payload["asOf"]=now[:10]
    manual=any(x["status"]=="manual-review" for x in evidence)
    status="PASS — primary-source, macro and math checks completed" if not failures and not manual else ("PASS WITH MANUAL REVIEW — automated checks completed; restricted source remains queued for human review" if not failures else "REVIEW REQUIRED — "+" | ".join(failures))
    payload["validation"]={"status":status,"checkedAt":now}
    REPORTS.mkdir(parents=True,exist_ok=True)
    report={"checkedAt":now,"status":status,"sourceEvidence":evidence,"historicalDrawdownEvidence":drawdown_evidence,"claimEvidence":claim_evidence,"mathChecks":checks,"failures":failures,"limitations":["Historical maximum drawdown is the sole optimizer and cap input; it is not a forecast and may understate future losses.","No automated system can prove a forecast or perform unrestricted deep research without a separately configured research provider.","BMNR SEC EDGAR is retained as the authoritative source but marked manual-review because the SEC blocks this automated runner.","Historical drawdown uses trailing 10 years where available and otherwise the complete authoritative history available for the current ticker/fund.","Deterministic checks can refresh data and reject invalid output, but arbitrary code defects require review rather than unsafe automated rewriting."]}
    (REPORTS/f"{now[:10]}.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    DATA.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(status)
    return 1 if failures else 0
if __name__ == "__main__": sys.exit(main())
