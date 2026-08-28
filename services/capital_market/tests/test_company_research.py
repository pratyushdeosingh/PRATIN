"""Deterministic tests for company information enrichment. No network."""
import pytest

from services.capital_market.company_research import (
    CompanyResearch,
    build_company_query,
    research_companies,
    research_company,
)
from services.capital_market.research import FirecrawlClient, ResearchError


class FakeCompanyClient(FirecrawlClient):
    """Serves a deterministic company profile page."""

    def __init__(self, fail_search=False, fail_scrape=False):
        self.calls = []
        self.fail_search = fail_search
        self.fail_scrape = fail_scrape

    def search(self, query, limit=4, country="in"):
        self.calls.append(("search", query))
        if self.fail_search:
            raise ResearchError("search unavailable")
        return [
            {"url": "https://www.exampleco.in/about",
             "title": "Example Co — About Us",
             "description": "Example Co is a manufacturer of auto components "
                            "headquartered in Pune, India. Founded in 1992. "
                            "Rated CRISIL AA-. Revenue ₹2,500 crore.",
             "position": 1},
            {"url": "https://www.facebook.com/exampleco",
             "title": "Example Co — Facebook",
             "description": "Social page.",
             "position": 2},
        ]

    def scrape(self, url):
        self.calls.append(("scrape", url))
        if self.fail_scrape:
            raise ResearchError("scrape unavailable")
        return {"markdown": (
            "Example Co is a manufacturer of auto components headquartered in Pune, India. "
            "Founded in 1992, the company supplies OEMs across India. "
            "Rated CRISIL AA- with revenue of ₹2,500 crore. "
            "No defaults or insolvency proceedings are reported in public sources. "
            "Recently announced a new plant in Chennai."
        ), "metadata": {"title": "Example Co — About Us"}}


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPITAL_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))


def test_query_includes_company_name_and_context():
    query = build_company_query("Apex Heavy Castings Ltd")
    assert "Apex Heavy Castings Ltd" in query
    assert "company" in query
    assert "India" in query


def test_live_research_extracts_identity_industry_location_background():
    result = research_company("Example Co", client=FakeCompanyClient())
    assert result.status == "live"
    fields = {f.field for f in result.facts}
    assert {"identity", "industry", "location", "background", "news"} <= fields
    identity = next(f for f in result.facts if f.field == "identity")
    assert identity.value == "Example Co"
    assert identity.kind == "SOURCE_FACT"
    assert identity.source_url == "https://www.exampleco.in/about"
    location = next(f for f in result.facts if f.field == "location")
    assert "Pune" in location.value


def test_financial_signals_extracted_with_provenance():
    result = research_company("Example Co", client=FakeCompanyClient())
    signal_facts = [f for f in result.facts if f.field == "signal"]
    assert any("CRISIL" in f.value or "crore" in f.value.lower() for f in signal_facts)
    assert all(f.source_url == "https://www.exampleco.in/about" for f in signal_facts)
    assert all(f.kind == "SOURCE_FACT" for f in signal_facts)


def test_missing_name_returns_unavailable():
    result = research_company("")
    assert result.status == "unavailable"
    assert result.error


def test_search_failure_degrades():
    result = research_company("Example Co", client=FakeCompanyClient(fail_search=True))
    assert result.status == "unavailable"
    assert result.error


def test_empty_search_results_reported_honestly():
    class EmptyClient(FirecrawlClient):
        def search(self, query, limit=4, country="in"):
            return []

    result = research_company("Unknown Co", client=EmptyClient())
    assert result.status == "unavailable"
    assert "No public sources" in (result.error or "")


def test_scrape_failure_records_unknown_not_fabricated():
    result = research_company("Example Co", client=FakeCompanyClient(fail_scrape=True))
    assert result.status == "live"
    fields = {f.field: f for f in result.facts}
    # Extractable fields degrade to UNKNOWN; the news field may still fall
    # back to the search-result snippet, which is real source data.
    for field in ("industry", "location", "background"):
        assert fields[field].confidence == 0.0
        assert fields[field].value == "UNKNOWN"


def test_cache_hit_avoids_network():
    client = FakeCompanyClient()
    first = research_company("Example Co", client=client)
    assert first.status == "live"
    second = research_company("Example Co", client=client)
    assert second.status == "cached"
    assert len(client.calls) == 2  # 1 search + 1 scrape, no new calls
    assert second.facts == first.facts


def test_refresh_forces_new_research():
    client = FakeCompanyClient()
    research_company("Example Co", client=client)
    refreshed = research_company("Example Co", client=client, refresh=True)
    assert refreshed.status == "live"
    assert len(client.calls) == 4


def test_research_companies_both_parties_with_telemetry():
    client = FakeCompanyClient()
    result = research_companies("Example Co", "Other Co", firecrawl_client=client)
    assert result["seller"]["status"] in ("live", "cached")
    assert result["client"]["status"] in ("live", "cached")
    telemetry = result["telemetry"]
    assert telemetry["searches"] == 2
    assert telemetry["pages_scraped"] == 2


def test_research_companies_skips_empty_names():
    result = research_companies(None, None)
    assert result["seller"]["status"] == "unavailable"
    assert result["client"]["status"] == "unavailable"
    assert result["telemetry"]["searches"] == 0


def test_inference_is_separate_from_source_facts():
    result = research_company("Example Co", client=FakeCompanyClient())
    assert all(f.kind == "AGENT_INFERENCE" for f in result.inferences)
    assert all(f.kind == "SOURCE_FACT" for f in result.facts)


def test_no_signals_inference_when_clean_source():
    class CleanClient(FakeCompanyClient):
        def scrape(self, url):
            self.calls.append(("scrape", url))
            return {"markdown": "Example Co makes auto components in Pune since 1992.",
                    "metadata": {"title": "About"}}

    result = research_company("Example Co", client=CleanClient())
    assert any(f.field == "no_signals" for f in result.inferences)
