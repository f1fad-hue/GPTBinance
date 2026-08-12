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
    "fred.stlouisfed.org", "home.treasury.gov",
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

    assert set(assets)=={"BAI","QQQ","IEMG","BINC","BMNR"}
    assert len(sources)==len(data["sources"])
    assert len({claim["id"] for claim in claims})==len(claims)
    for source in sources.values():
        for key in ("url","validation_url"):
            if key not in source: continue
            parsed=urlparse(source[key]); assert parsed.scheme=="https"
            assert parsed.hostname in ALLOWED_PRIMARY_DOMAINS, f"unapproved primary domain: {parsed.hostname}"
        if source.get("automation") != "restricted": assert source.get("required_text")
    for claim in claims:
        if claim["kind"].startswith("model"):
            assert claim["source"]=="Model methodology"
        else:
            assert claim["source"] in sources, f"unregistered claim source: {claim['source']}"
    for ticker in ("BAI","QQQ","IEMG","BINC"):
        source=next(item for item in sources.values() if item.get("asset_ticker")==ticker)
        assert source["fee_field"]=="gross_expense_ratio"
        assert source["url"]==assets[ticker]["source"]

    update_data.math_checks(data)
    report=ROOT/"reports"/"daily"/f"{data['asOf']}.json"
    assert report.exists(), "today's evidence report is missing"
    evidence=json.loads(report.read_text(encoding="utf-8"))
    assert not evidence["failures"] and len(evidence["claimEvidence"])==len(claims)
    source_evidence={item["source"]:item for item in evidence["sourceEvidence"]}
    for ticker in ("BAI","QQQ","IEMG","BINC"):
        source=next(item for item in sources.values() if item.get("asset_ticker")==ticker)
        assert source_evidence[source["name"]]["usedFeePercent"]==assets[ticker]["fee"]

    parser=IdParser(); parser.feed((ROOT/"index.html").read_text(encoding="utf-8"))
    assert REQUIRED_DOM_IDS <= parser.ids, f"missing dashboard elements: {REQUIRED_DOM_IDS-parser.ids}"
    assert "fetch('data/market-data.json'" in (ROOT/"app.js").read_text(encoding="utf-8")
    print("PASS — repository schema, claims, math, report, and dashboard sanity checks completed")


if __name__ == "__main__": main()
