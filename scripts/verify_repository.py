#!/usr/bin/env python3
"""Deterministic weekend schema, claims, math, and static-dashboard audit."""
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
    "monitoring", "sources", "validation-status", "broad-sentiment",
    "correlated-sentiment", "regional-ranking",
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

    assert set(assets)=={"QQQ","IEMG","SGOV","BMNR"}
    assert all("historicalDD" in asset for asset in assets.values())
    assert all(asset.get("historicalDDSource","").startswith("https://") for asset in assets.values())
    assert "forwardDDModel" not in data
    assert all(not any(key.startswith("forward") and key.endswith("DD") for key in asset) for asset in assets.values())
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
    for ticker in ("QQQ","IEMG","SGOV"):
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
        assert item["status"] in {"pass","retained"} and item["usedPercent"]==asset["historicalDD"]
        if item["status"]=="pass": assert item["observations"]>=250
        assert item["start"]==asset["historicalDDStart"] and item["end"]==asset["historicalDDEnd"]
    math_evidence={item["name"]:item for item in evidence["mathChecks"]}
    assert math_evidence["synchronized monthly-rebalanced portfolio path"]["observations"]>=220
    assert math_evidence["robust drawdown controls"]["observedPath"] is True
    assert math_evidence["proportional macro-driven SGOV cushion"]["minimumSgovWeight"] in {60,65,70,75,80}
    assert math_evidence["sixteen distinct portfolio-related macro drivers"]["status"]=="pass"
    assert math_evidence["broad and allocation-correlated sentiment"]["status"]=="pass"
    assert {item["region"] for item in math_evidence["US Europe Asia transmission ranking"]["ranking"]}=={"US","Europe","Asia"}
    assert math_evidence["10-year correlated Monte Carlo return and drawdown simulation"]["paths"]==10_000
    assert math_evidence["10-year correlated Monte Carlo return and drawdown simulation"]["years"]==10
    assert set(data["model"]["scenarios"])=={"3","4","5"}
    for scenario,item in data["model"]["scenarios"].items():
        assert item["cap"]==update_data.cap_from_rate(float(scenario))
        assert item["observedPortfolio"]["maxDrawdown"]<=item["cap"] and item["stress"]["worstLoss"]<=item["cap"]
    active=data["model"]["active"]
    assert active["minimumSgovWeight"]==update_data.proportional_cushion(active["macroRate"])
    assert active["weights"]["SGOV"]>=active["minimumSgovWeight"] and active["cap"]==update_data.cap_from_rate(active["macroRate"])
    assert active["observedPortfolio"]["maxDrawdown"]<=active["cap"] and active["stress"]["worstLoss"]<=active["cap"]
    source_evidence={item["source"]:item for item in evidence["sourceEvidence"]}
    for ticker in ("QQQ","IEMG","SGOV"):
        source=next(item for item in sources.values() if item.get("asset_ticker")==ticker)
        assert source_evidence[source["name"]]["usedFeePercent"]==assets[ticker]["fee"]

    parser=IdParser(); parser.feed((ROOT/"index.html").read_text(encoding="utf-8"))
    assert REQUIRED_DOM_IDS <= parser.ids, f"missing dashboard elements: {REQUIRED_DOM_IDS-parser.ids}"
    app=(ROOT/"app.js").read_text(encoding="utf-8")
    assert "fetch('data/market-data.json'" in app
    assert "data.model.scenarios" in app and "data.model.active" in app and "Proportional macro cushion validation failed" in app
    assert "module.exports" in app and (ROOT/"scripts"/"verify_app.js").exists()
    assert not (ROOT/"sw.js").exists(), "obsolete service worker should remain removed"
    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["display"]=="standalone" and manifest["start_url"]=="."
    print("PASS — repository schema, claims, math, report, and dashboard sanity checks completed")


if __name__ == "__main__": main()
