"""Company information enrichment for the Capital Agent.

Given a company name (seller or client extracted from an invoice), this
module runs ONE targeted Firecrawl search, scrapes the single most relevant
official source, and extracts deterministic public-information facts:

    identity, industry, location, background, financial signals,
    default/insolvency signals, legal/regulatory signals, recent news

Every fact keeps the same provenance rules as provider research: source URL,
source title, retrieval timestamp, confidence, and an explicit
SOURCE_FACT / AGENT_INFERENCE kind. Nothing is invented when evidence is
missing — UNKNOWN facts carry zero confidence. Results are cached by
company name so repeated analyses reuse research without new network calls.

This module is additive: the existing provider research flow in
``research.py`` is untouched.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .research import (
    Fact,
    FirecrawlClient,
    ResearchError,
    _SOCIAL_DOMAINS,
    _cache_dir,
    _utcnow,
)

# Deterministic keyword sets for public-information signal detection.
_FINANCIAL_KEYWORDS = (
    "rating", "crisil", "icra", "care ratings", "revenue", "turnover", "net worth",
    "assets under", "aum", "funding", "raised", "crore", "billion", "loan book",
)
_RISK_KEYWORDS = (
    "insolvency", "insolvent", "bankrupt", "bankruptcy", "default", "defaulter",
    "non-performing", "npa", "winding up", "liquidation", "lawsuit", "litigation",
    "fraud", "penalty", "prosecution", "investigation", "probe",
)
_LEGAL_KEYWORDS = (
    "sebi", "rbi", "regulator", "regulatory", "compliance", "audit", "court",
    "tribunal", "nclt", "arbitration", "notice",
)
_LOCATION_KEYWORDS = (
    "headquartered", "headquarters", "registered office", "based in", "located in",
    "office in", "mumbai", "delhi", "bangalore", "chennai", "pune", "gurgaon",
    "gurugram", "hyderabad", "kolkata", "ahmedabad", "india",
)

_UNCERTAIN_LOCATION_WORDS = {"the", "a", "an", "in", "and", "for", "with", "our", "their", "its"}


def _company_key(name: str) -> str:
    import hashlib
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()[:16]


def _company_cache_file() -> str:
    return os.path.join(_cache_dir(), "companies.json")


def _load_company_cache() -> dict:
    try:
        with open(_company_cache_file(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_company_cache(cache: dict) -> None:
    os.makedirs(_cache_dir(), exist_ok=True)
    with open(_company_cache_file(), "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2)


def build_company_query(name: str) -> str:
    """One targeted query for public company information."""
    return f'"{name}" company India business headquarters'


def _result_score(result: dict) -> int:
    url = (result.get("url") or "").lower()
    title = (result.get("title") or "").lower()
    text = f"{title} {url}"
    score = 0
    domain = url.split("/")[2] if "://" in url and url.split("/")[2:] else url
    if any(social in domain for social in _SOCIAL_DOMAINS):
        score -= 60
    if any(word in text for word in ("about", "profile", "company", "business")):
        score += 20
    if "india" in text or domain.endswith(".in"):
        score += 10
    if any(word in title for word in ("wiki", "wikipedia")):
        score += 5
    if any(word in title for word in ("job", "career", "vacancy", "hiring")):
        score -= 30
    return score


def _sentences(markdown: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", markdown) if len(s.strip()) > 15]


def _find_sentence(markdown: str, keywords: tuple[str, ...]) -> str | None:
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence[:280]
    return None


def _extract_location(markdown: str) -> str:
    window = _find_sentence(markdown, _LOCATION_KEYWORDS)
    return window or "UNKNOWN"


def _extract_industry(markdown: str) -> str:
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if any(word in lowered for word in ("manufactur", "sector", "industry", "business of",
                                             "engaged in", "provider of", "supplier of")):
            return sentence[:280]
    return "UNKNOWN"


def _extract_background(markdown: str) -> str:
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if any(word in lowered for word in ("founded", "established", "since", "history",
                                             "incorporated", "company was", "is a")):
            return sentence[:280]
    return "UNKNOWN"


def _extract_signals(markdown: str, keywords: tuple[str, ...]) -> list[Fact]:
    """Sentences matching the keyword set, as SOURCE_FACT evidence."""
    found: list[Fact] = []
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            found.append(Fact(
                field="signal",
                value=sentence[:280],
                kind="SOURCE_FACT",
                confidence=0.7,
                source_url="",
                source_title="",
                retrieved_at="",
                evidence=sentence[:280],
            ))
    return found[:5]


def _extract_news(result: dict, markdown: str) -> str:
    description = (result.get("description") or "").strip()
    if len(description) > 40:
        return description[:280]
    return _find_sentence(markdown, ("announced", "launched", "partnership", "news", "recently")) or "UNKNOWN"


@dataclass
class CompanyResearch:
    """Researched public profile of one company."""

    name: str
    status: str = "unavailable"        # live | cached | unavailable
    source_url: str = ""
    source_title: str = ""
    retrieved_at: str = ""
    facts: list[Fact] = field(default_factory=list)
    inferences: list[Fact] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "retrieved_at": self.retrieved_at,
            "facts": [f.to_dict() for f in self.facts],
            "inferences": [f.to_dict() for f in self.inferences],
            "error": self.error,
        }


@dataclass
class CompanyTelemetry:
    searches: int = 0
    pages_scraped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_dict(self) -> dict:
        return {
            "searches": self.searches,
            "pages_scraped": self.pages_scraped,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


def _facts_from_entry(entry: dict) -> tuple[list[Fact], list[Fact]]:
    facts = [Fact(**f) for f in entry.get("facts", [])]
    inferences = [Fact(**f) for f in entry.get("inferences", [])]
    return facts, inferences


def research_company(name: str, *, refresh: bool = False,
                     client: FirecrawlClient | None = None) -> CompanyResearch:
    """One search + one scrape for public company information, cached by name."""
    if not name or not name.strip():
        return CompanyResearch(name=name or "", status="unavailable",
                               error="No company name supplied.")
    client = client or FirecrawlClient()
    key = _company_key(name)
    cache = _load_company_cache()

    if key in cache and not refresh:
        entry = cache[key]
        facts, inferences = _facts_from_entry(entry)
        return CompanyResearch(
            name=entry.get("name", name),
            status="cached",
            source_url=entry.get("source_url", ""),
            source_title=entry.get("source_title", ""),
            retrieved_at=entry.get("retrieved_at", ""),
            facts=facts,
            inferences=inferences,
        )

    try:
        results = client.search(build_company_query(name), limit=4, country="in")
        scored = sorted(
            [(r, _result_score(r)) for r in results if r.get("url")],
            key=lambda item: (-item[1], item[0].get("position", 99)),
        )
        if not scored:
            return CompanyResearch(name=name, status="unavailable",
                                   error="No public sources found for this company.")
        best = scored[0][0]
        url = best.get("url", "")
        title = best.get("title", "")

        try:
            payload = client.scrape(url)
        except ResearchError:
            payload = {"markdown": "", "metadata": {"title": title}}

        markdown = payload.get("markdown", "") or ""
        retrieved_at = _utcnow()

        def fact(field_name: str, value: str, confidence: float, evidence: str) -> Fact:
            if value == "UNKNOWN":
                confidence = 0.0
                evidence = ""
            return Fact(field=field_name, value=value, kind="SOURCE_FACT",
                        confidence=confidence, source_url=url, source_title=title,
                        retrieved_at=retrieved_at, evidence=evidence)

        facts = [
            fact("identity", name, 0.9, f"Company name supplied from invoice: {name}."),
            fact("industry", _extract_industry(markdown), 0.7, _extract_industry(markdown)),
            fact("location", _extract_location(markdown), 0.7, _extract_location(markdown)),
            fact("background", _extract_background(markdown), 0.7, _extract_background(markdown)),
        ]

        financial_signals = _extract_signals(markdown, _FINANCIAL_KEYWORDS)
        risk_signals = _extract_signals(markdown, _RISK_KEYWORDS)
        legal_signals = _extract_signals(markdown, _LEGAL_KEYWORDS)

        news_value = _extract_news(best, markdown)
        facts.append(fact("news", news_value, 0.6, news_value))

        for signal in financial_signals + risk_signals + legal_signals:
            signal.source_url = url
            signal.source_title = title
            signal.retrieved_at = retrieved_at
            facts.append(signal)

        # AGENT INFERENCES: clearly separated from source facts.
        inferences: list[Fact] = []
        if risk_signals:
            inferences.append(Fact(
                field="risk_note", value=(
                    f"Public sources mention {len(risk_signals)} potential "
                    f"default/insolvency-related signal(s) for {name}."
                ), kind="AGENT_INFERENCE", confidence=0.5,
                source_url=url, source_title=title, retrieved_at=retrieved_at,
                evidence="Derived from matching public text against a deterministic risk keyword set.",
            ))
        if not financial_signals and not risk_signals and not legal_signals:
            inferences.append(Fact(
                field="no_signals", value=(
                    f"No public financial, default or legal signals found for {name} "
                    f"in the researched source."
                ), kind="AGENT_INFERENCE", confidence=0.4,
                source_url=url, source_title=title, retrieved_at=retrieved_at,
                evidence="No keyword matches in the scraped source text.",
            ))

        cache[key] = {
            "name": name,
            "source_url": url,
            "source_title": title,
            "retrieved_at": retrieved_at,
            "facts": [f.to_dict() for f in facts],
            "inferences": [f.to_dict() for f in inferences],
        }
        _save_company_cache(cache)

        return CompanyResearch(name=name, status="live", source_url=url,
                               source_title=title, retrieved_at=retrieved_at,
                               facts=facts, inferences=inferences)
    except ResearchError as exc:
        return CompanyResearch(name=name, status="unavailable", error=str(exc))


def research_companies(seller: str | None, client_name: str | None, *, refresh: bool = False,
                       firecrawl_client: FirecrawlClient | None = None) -> dict:
    """Research both parties; returns {seller, client, telemetry}."""
    telemetry = CompanyTelemetry()

    seller_research = CompanyResearch(name=seller or "", status="unavailable",
                                      error="No seller name supplied.")
    client_research = CompanyResearch(name=client_name or "", status="unavailable",
                                      error="No client name supplied.")

    if seller and seller.strip():
        seller_research = research_company(seller, refresh=refresh, client=firecrawl_client)
        _count(telemetry, seller_research)

    if client_name and client_name.strip():
        client_research = research_company(client_name, refresh=refresh, client=firecrawl_client)
        _count(telemetry, client_research)

    return {
        "seller": seller_research.to_dict(),
        "client": client_research.to_dict(),
        "telemetry": telemetry.to_dict(),
    }


def _count(telemetry: CompanyTelemetry, research: CompanyResearch) -> None:
    if research.status == "live":
        telemetry.searches += 1
        telemetry.pages_scraped += 1
        telemetry.cache_misses += 1
    elif research.status == "cached":
        telemetry.cache_hits += 1
