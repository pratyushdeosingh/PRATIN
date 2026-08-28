"""Deterministic tests for the Firecrawl research layer. All Firecrawl
calls are mocked — no network in tests."""
import json
import os

import pytest

from backend.app.fixtures import providers, scenarios
from contracts.models import (
    MarketRequest,
    RiskAssessment,
    RiskBand,
    VerificationResult,
    VerificationStatus,
)
from services.capital_market.research import (
    FirecrawlClient,
    ResearchError,
    _context_key,
    build_search_query,
    extract_facts,
    run_research,
    select_providers,
)
from services.capital_market.intelligence import build_intelligence, evaluate_intelligence
from services.capital_market.scoring import score_provider


def scenario():
    return scenarios()["urgent"]


def search_results():
    return [
        {"url": "https://www.examplebank.in/supply-chain-finance",
         "title": "Example Bank — Supply Chain Finance for Manufacturers",
         "description": "Invoice discounting and working capital finance up to ₹5 crore for Indian manufacturers.",
         "position": 1},
        {"url": "https://www.facebook.com/examplebank/posts/123",
         "title": "Example Bank — Facebook",
         "description": "Social post about working capital.",
         "position": 2},
        {"url": "https://www.examplefinance.com/scf",
         "title": "Example Finance — Invoice Factoring for MSMEs",
         "description": "Working capital solutions with same-day disbursal, NBFC lender.",
         "position": 3},
        {"url": "https://www.blog.example/how-to-choose-a-lender",
         "title": "How to Choose a Lender: A Guide",
         "description": "Editorial guide to invoice financing.",
         "position": 4},
    ]


class FakeClient(FirecrawlClient):
    """Records calls and serves deterministic pages."""

    def __init__(self, fail_search=False, fail_scrape=False):
        self.calls = []
        self.fail_search = fail_search
        self.fail_scrape = fail_scrape

    def search(self, query, limit=6, country="in"):
        self.calls.append(("search", query))
        if self.fail_search:
            raise ResearchError("search unavailable")
        return search_results()

    def scrape(self, url):
        self.calls.append(("scrape", url))
        if self.fail_scrape:
            raise ResearchError("scrape unavailable")
        markdown = (
            "Example Provider offers supply chain finance for manufacturers. "
            "Interest rate 11.5% per annum. Tenor up to 90 days. "
            "Financing limit up to ₹5 crore. Advance up to 80% of invoice value. "
            "Processing fee 1%. Same-day disbursal. MSMEs eligible. "
            "Rated AAA by CRISIL. Operating since 1995. Loan book ₹20,000 crore. "
            "Focused on manufacturing, automotive and pharma sectors."
        )
        return {"markdown": markdown, "metadata": {"title": f"Official page for {url}"}}


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPITAL_RESEARCH_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path / "cache"


# --- discovery -------------------------------------------------------------

def test_search_query_uses_opportunity_context():
    query = build_search_query(scenario().invoice, scenario().requirements)
    assert "manufacturing" in query
    assert "supply chain finance" in query
    assert "India" in query
    assert "bank" in query and "NBFC" in query


def test_select_providers_picks_two_relevant_and_skips_social_and_editorial():
    selected = select_providers(search_results())
    assert len(selected) == 2
    urls = [s["url"] for s in selected]
    assert "facebook.com" not in urls
    assert "blog.example" not in urls
    assert urls[0] == "https://www.examplebank.in/supply-chain-finance"


def test_context_key_buckets_amount_and_tenor():
    key_a = _context_key(scenario().invoice, scenario().requirements)
    same = scenario().invoice.model_copy(update={"amount": 1_100_000})
    same_reqs = scenario().requirements.model_copy(update={"desired_tenor_days": 70})
    key_b = _context_key(same, same_reqs)
    assert key_a == key_b
    diff = scenario().invoice.model_copy(update={"amount": 2_000_000})
    assert _context_key(diff, scenario().requirements) != key_a


# --- extraction ------------------------------------------------------------

def test_extract_facts_records_provenance_and_unknowns(tmp_cache, monkeypatch):
    profile = run_research(scenario().invoice, scenario().requirements, client=FakeClient())
    assert len(profile.providers) == 2
    for provider in profile.providers:
        fields = {f.field for f in provider.facts}
        assert {"rate", "tenor", "limit", "advance", "fees", "settlement", "eligibility",
                "sectors", "rating", "scale", "years", "product"} <= fields
        for fact in provider.facts:
            assert fact.kind == "SOURCE_FACT"
            assert fact.source_url == provider.source_url
            assert fact.retrieved_at
            assert fact.confidence >= 0
            if fact.value == "UNKNOWN":
                assert fact.confidence == 0.0


def test_extract_facts_parses_known_values(tmp_cache):
    outcome = run_research(scenario().invoice, scenario().requirements, client=FakeClient())
    provider = outcome.providers[0]
    rate = provider.fact("rate")
    assert rate.value == "11.5"
    limit = provider.fact("limit")
    assert "50,000,000" in limit.value


# --- caching ---------------------------------------------------------------

def test_cache_hit_avoids_network(tmp_cache):
    client = FakeClient()
    first = run_research(scenario().invoice, scenario().requirements, client=client)
    assert first.status == "live"
    assert len(client.calls) == 3  # 1 search + 2 scrapes
    second = run_research(scenario().invoice, scenario().requirements, client=client)
    assert second.status == "cached"
    assert second.providers
    assert len(client.calls) == 3  # no new network calls
    assert second.telemetry.cache_hits == 2


def test_refresh_forces_new_research(tmp_cache):
    client = FakeClient()
    run_research(scenario().invoice, scenario().requirements, client=client)
    refreshed = run_research(scenario().invoice, scenario().requirements, client=client, refresh=True)
    assert refreshed.status == "live"
    assert len(client.calls) == 6


def test_telemetry_counts_are_accurate(tmp_cache):
    client = FakeClient()
    outcome = run_research(scenario().invoice, scenario().requirements, client=client)
    telemetry = outcome.telemetry
    assert telemetry.searches == 1
    assert telemetry.pages_scraped == 2
    assert telemetry.cache_misses == 2
    assert telemetry.cache_hits == 0


def test_search_failure_degrades_to_unavailable(tmp_cache):
    outcome = run_research(scenario().invoice, scenario().requirements, client=FakeClient(fail_search=True))
    assert outcome.status == "unavailable"
    assert outcome.providers == []
    assert outcome.error


def test_scrape_failure_records_unknown_not_fabricated(tmp_cache):
    outcome = run_research(scenario().invoice, scenario().requirements, client=FakeClient(fail_scrape=True))
    assert outcome.status == "live"
    for provider in outcome.providers:
        assert all(f.value == "UNKNOWN" and f.confidence == 0.0 for f in provider.facts)


# --- scoring ---------------------------------------------------------------

def test_score_is_deterministic_and_explainable(tmp_cache):
    client = FakeClient()
    outcome = run_research(scenario().invoice, scenario().requirements, client=client)
    first = score_provider(outcome.providers[0], "Manufacturing")
    second = score_provider(outcome.providers[0], "Manufacturing")
    assert first.total == second.total
    assert len(first.dimensions) == 6
    for dim in first.dimensions:
        assert 0 <= dim.score <= 100
        assert dim.explanation
        assert 0 <= dim.confidence <= 1
    # Evidence exists so the score must be positive
    assert first.total > 0


def test_missing_evidence_scores_zero_not_positive():
    from services.capital_market.research import ProviderResearch
    empty = ProviderResearch(provider_name="Ghost", provider_type="UNKNOWN",
                             source_url="https://x.example", source_title="", retrieved_at="")
    score = score_provider(empty, "Manufacturing")
    assert score.total == 0.0
    assert score.confidence == 0.0
    assert all(dim.score == 0.0 for dim in score.dimensions)


# --- intelligence integration ----------------------------------------------

def test_intelligence_builds_provider_profiles_with_facts_and_inferences(tmp_cache):
    client = FakeClient()
    outcome = run_research(scenario().invoice, scenario().requirements, client=client)
    report = build_intelligence(outcome, scenario().invoice, scenario().requirements)
    assert len(report.providers) == 2
    for provider in report.providers:
        assert provider["score"]["total"] >= 0
        assert provider["facts"]
        assert provider["suitability_score"] >= 0
        assert isinstance(provider["suitable"], bool)


def test_intelligence_pricing_signals_are_bounded():
    outcome = run_research(scenario().invoice, scenario().requirements, client=FakeClient())
    report = build_intelligence(outcome, scenario().invoice, scenario().requirements)
    assert -0.75 <= report.rate_adjustment <= 0.75
    assert -0.10 <= report.advance_adjustment <= 0.10


def test_researched_adjustment_flows_into_agent_pricing(tmp_cache):
    from services.capital_market.agent import analyze_provider
    client = FakeClient()
    outcome = run_research(scenario().invoice, scenario().requirements, client=client)
    report = build_intelligence(outcome, scenario().invoice, scenario().requirements)
    request = MarketRequest(
        opportunity_id="OPP-R",
        invoice=scenario().invoice,
        requirements=scenario().requirements,
        verification=VerificationResult(status=VerificationStatus.VERIFIED, confidence=.95,
                                        verified_fields=[], uncertain_fields=[], reasons=[]),
        risk=RiskAssessment(score=24, band=RiskBand.LOW, confidence=.9, factors=[], missing_information=[]),
        providers=[providers()[1]],
    )
    base = analyze_provider(request, providers()[1])
    adjusted = analyze_provider(request, providers()[1],
                                research_adjustment=report.rate_adjustment,
                                advance_adjustment=report.advance_adjustment)
    assert adjusted.pricing.research_adjustment == report.rate_adjustment
    assert adjusted.pricing.final_rate == round(base.pricing.final_rate + report.rate_adjustment, 2)
