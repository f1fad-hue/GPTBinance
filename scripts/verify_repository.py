#!/usr/bin/env python3
"""Deterministic daily schema, claims, math, and static-dashboard audit."""
from __future__ import annotations

import json
import pathlib
from html.parser import HTMLParser
from urllib.parse import urlparse

import update_data

ROOT = pathlib.Path(__file__).parents[1]
DATA = ROOT / "data" / "market-data.json"
CLAIMS = ROOT / "data" / "claims.json"
ALLOWED_PRIMARY_DOMAINS = {
    "www.ishares.com", "www.invesco.com", "www.sec.gov", "data.sec.gov",
    "fred.stlouisfed.org", "home.treasury.gov", "www.nasdaq.com", "api.nasdaq.com",
}
REQUIRED_DOM_IDS = {
    "portfolio-rate", "allocation", "heatmap", "donuts", "slides",
    "monitoring", "sources", "validation-status",
}


class IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.ids.update(value for key, value in attrs if key == "id" and value)


def main() -> None:
    data=json.loads(DATA.read_text(encoding="utf-8"))
    claims=json.loads(CLAIMS.read_text(encoding="utf-8"))["claims"]
    assets={asset["ticker"]:asset for asset in data["assets"]}
    sources={source["name"]:source for source in data["sources"]}

    assert set(assets)=={"QQQ","IEMG","BINC","BMNR"}
    assert all("historicalDD" in asset and "forwardP50DD" in asset for asset in assets.values())
    assert all(asset.get("historicalDDSource","").startswith("https://") for asset in assets.values())
    assert all("forwardP90DD" not in asset and "forwardMedianDD" not in asset and "forwardDD" not in asset for asset in assets.values())
    assert all("weight" not in asset for asset in assets.values()), "stale stored allocations must not override the optimizer"
    assert all(asset.get("monitorStatus") and asset.get("monitorNote") for asset in assets.values())
    assert len(sources)==len(data["sources"])
    assert len({claim["id"] for claim in claims})==len(claims)
    for source in sources.values():
        for key in ("url","validation_url"):
            if key not in source: continue
            parsed=urlparse(source[key]); assert parsed.scheme=="https"
            assert parsed.hostname in ALLOWED_PRIMARY_DOMAINS, f"unapproved primary domain: {parsed.hostname}"
        if source.get("automation") not in {"restricted","historical-drawdown"}: assert source.get("required_text")
    for claim in claims:
        if claim["kind"].startswith("model"):
            assert claim["source"]=="Model methodology"
        else:
            assert claim["source"] in sources, f"unregistered claim source: {claim['source']}"
    for ticker in ("QQQ","IEMG","BINC"):
        source=next(item for item in sources.values() if item.get("asset_ticker")==ticker)
        assert source["fee_field"]=="gross_expense_ratio"
        assert source["url"]==assets[ticker]["source"]

    update_data.math_checks(data)
    report=ROOT/"reports"/"daily"/f"{data['asOf']}.json"
    assert report.exists(), "today's evidence report is missing"
    evidence=json.loads(report.read_text(encoding="utf-8"))
    assert not evidence["failures"] and len(evidence["claimEvidence"])==len(claims)
    drawdown_evidence={item["ticker"]:item for item in evidence["historicalDrawdownEvidence"]}
    assert set(drawdown_evidence)==set(assets)
    for ticker,asset in assets.items():
        item=drawdown_evidence[ticker]
        assert item["status"]=="pass" and item["usedPercent"]==asset["historicalDD"]
        assert item["observations"]>=250 and item["start"]==asset["historicalDDStart"] and item["end"]==asset["historicalDDEnd"]
    forward_evidence={item["ticker"]:item for item in evidence["forwardP50DrawdownEvidence"]}
    assert set(forward_evidence)==set(assets)
    for ticker,asset in assets.items():
        assert forward_evidence[ticker]["status"]=="pass"
        assert forward_evidence[ticker]["usedP50Percent"]==asset["forwardP50DD"]
        assert update_data.forward_p50_drawdown(asset)==asset["forwardP50DD"]
    math_evidence={item["name"]:item for item in evidence["mathChecks"]}
    assert math_evidence["forward P50-only drawdown rule"]["historicalWeight"]==0
    assert math_evidence["forward P50-only drawdown rule"]["forwardP50Weight"]==1
    assert math_evidence["P50 10-year forward maximum-drawdown simulation"]["paths"]==10_000
    assert math_evidence["P50 10-year forward maximum-drawdown simulation"]["years"]==10
    assert math_evidence["P50 10-year forward maximum-drawdown simulation"]["stepsPerYear"]==12
    assert math_evidence["twelve distinct portfolio-related macro drivers"]["status"]=="pass"
    assert math_evidence["10-year Monte Carlo simulation"]["paths"]==10_000
    assert math_evidence["10-year Monte Carlo simulation"]["years"]==10
    scenario_evidence=math_evidence["exact max-CAGR scenario allocations"]
    assert set(scenario_evidence["allocations"])==set(scenario_evidence["drawdownChecks"])=={"3","4","5"}
    for scenario,item in scenario_evidence["drawdownChecks"].items():
        assert item["cap"]==update_data.cap_from_rate(float(scenario)) and item["computedP50Drawdown"]<=item["cap"]
    source_evidence={item["source"]:item for item in evidence["sourceEvidence"]}
    for ticker in ("QQQ","IEMG","BINC"):
        source=next(item for item in sources.values() if item.get("asset_ticker")==ticker)
        assert source_evidence[source["name"]]["usedFeePercent"]==assets[ticker]["fee"]

    parser=IdParser(); parser.feed((ROOT/"index.html").read_text(encoding="utf-8"))
    assert REQUIRED_DOM_IDS <= parser.ids, f"missing dashboard elements: {REQUIRED_DOM_IDS-parser.ids}"
    app=(ROOT/"app.js").read_text(encoding="utf-8")
    assert "fetch('data/market-data.json'" in app
    assert "function optimize" in app and "No feasible allocation" in app
    assert not (ROOT/"sw.js").exists(), "obsolete service worker should remain removed"
    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["display"]=="standalone" and manifest["start_url"]=="."
    print("PASS — repository schema, claims, math, report, and dashboard sanity checks completed")


if __name__ == "__main__": main()
