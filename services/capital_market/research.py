"""Firecrawl-backed capital market research for the Capital Agent.

Research flow (credit-conservative):

    ONE targeted search  ->  TWO best relevant providers  ->  scrape only
    their official pages  ->  extract facts  ->  cache

Cached intelligence is reused on subsequent runs; the CLI is only invoked
for genuine misses. Every fact carries provenance: source URL, source title,
retrieval timestamp, confidence, and an explicit SOURCE_FACT / AGENT_INFERENCE
kind. Missing evidence is recorded as UNKNOWN — never fabricated.

The Firecrawl client is a small seam (``FirecrawlClient``) so automated tests
can mock it without touching the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DEFAULT_CACHE_DIR = "/tmp/pratin-capital-cache"


def _cache_dir() -> str:
    """Resolve the cache directory at call time so tests can override it."""
    return os.environ.get("CAPITAL_RESEARCH_CACHE_DIR", DEFAULT_CACHE_DIR)


def _cache_file() -> str:
    return os.path.join(_cache_dir(), "providers.json")


def _telemetry_file() -> str:
    return os.path.join(_cache_dir(), "telemetry.json")

_SOCIAL_DOMAINS = {"facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com", "youtube.com"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------

@dataclass
class Fact:
    """One extracted piece of provider intelligence with full provenance."""

    field: str            # e.g. "rate", "tenor", "limit", "advance", "fees",
                          # "settlement", "eligibility", "sectors", "rating",
                          # "scale", "years", "product"
    value: str
    kind: str = "SOURCE_FACT"          # "SOURCE_FACT" | "AGENT_INFERENCE"
    confidence: float = 0.0            # 0..1
    source_url: str = ""
    source_title: str = ""
    retrieved_at: str = ""
    evidence: str = ""                 # short supporting excerpt from the source

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "kind": self.kind,
            "confidence": round(self.confidence, 2),
            "source_url": self.source_url,
            "source_title": self.source_title,
            "retrieved_at": self.retrieved_at,
            "evidence": self.evidence,
        }


@dataclass
class ProviderResearch:
    """Researched profile of one real capital provider."""

    provider_name: str
    provider_type: str                 # BANK | NBFC | FINTECH | FUND | UNKNOWN
    source_url: str
    source_title: str
    retrieved_at: str
    facts: list[Fact] = field(default_factory=list)

    def fact(self, field_name: str) -> Fact | None:
        for fact in self.facts:
            if fact.field == field_name:
                return fact
        return None

    def to_dict(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "retrieved_at": self.retrieved_at,
            "facts": [f.to_dict() for f in self.facts],
        }


@dataclass
class ResearchTelemetry:
    """Honest accounting of Firecrawl usage."""

    searches: int = 0
    providers_researched: int = 0
    pages_scraped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    last_research_at: str | None = None
    source: str = "firecrawl"

    def to_dict(self) -> dict:
        return {
            "searches": self.searches,
            "providers_researched": self.providers_researched,
            "pages_scraped": self.pages_scraped,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "last_research_at": self.last_research_at,
            "source": self.source,
        }


@dataclass
class ResearchOutcome:
    """Result of one research pass over the opportunity."""

    status: str = "unavailable"        # "live" | "cached" | "unavailable"
    providers: list[ProviderResearch] = field(default_factory=list)
    telemetry: ResearchTelemetry = field(default_factory=ResearchTelemetry)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "providers": [p.to_dict() for p in self.providers],
            "telemetry": self.telemetry.to_dict(),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Firecrawl client seam (mocked in tests)
# ---------------------------------------------------------------------------

class FirecrawlClient:
    """Thin wrapper over the installed Firecrawl CLI.

    `firecrawl search --json` and `firecrawl scrape --json` are subprocess
    calls; parse errors and missing CLI surface as ResearchError so the
    agent can degrade to its deterministic fallback instead of crashing.
    """

    def search(self, query: str, limit: int = 6, country: str = "in") -> list[dict]:
        """Return raw web results: [{url, title, description, ...}]."""
        try:
            proc = subprocess.run(
                ["firecrawl", "search", query, "--limit", str(limit), "--country", country, "--json"],
                capture_output=True, text=True, timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ResearchError(f"firecrawl search unavailable: {exc}") from exc
        if proc.returncode != 0:
            raise ResearchError(f"firecrawl search failed: {proc.stderr.strip()[:200]}")
        try:
            payload = json.loads(proc.stdout)
        except ValueError as exc:
            raise ResearchError("firecrawl search returned invalid JSON") from exc
        if not payload.get("success"):
            raise ResearchError("firecrawl search was not successful")
        return payload.get("data", {}).get("web", [])

    def scrape(self, url: str) -> dict:
        """Return {markdown, metadata} for one URL."""
        try:
            proc = subprocess.run(
                ["firecrawl", "scrape", url, "--json"],
                capture_output=True, text=True, timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ResearchError(f"firecrawl scrape unavailable: {exc}") from exc
        if proc.returncode != 0:
            raise ResearchError(f"firecrawl scrape failed: {proc.stderr.strip()[:200]}")
        try:
            payload = json.loads(proc.stdout)
        except ValueError as exc:
            raise ResearchError("firecrawl scrape returned invalid JSON") from exc
        if "markdown" not in payload:
            raise ResearchError("firecrawl scrape returned no markdown")
        return payload


class ResearchError(RuntimeError):
    """Firecrawl research failed; the agent must degrade gracefully."""


# ---------------------------------------------------------------------------
# Discovery: ONE search -> TWO providers
# ---------------------------------------------------------------------------

def _context_key(invoice, requirements) -> str:
    amount_bucket = 500_000 * round(invoice.amount / 500_000) if invoice.amount else 0
    tenor_bucket = 30 * round(requirements.desired_tenor_days / 30) if requirements.desired_tenor_days else 0
    material = f"{invoice.industry.lower()}|{amount_bucket}|{tenor_bucket}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def build_search_query(invoice, requirements) -> str:
    """One targeted query combining the opportunity's real context."""
    return (
        f"invoice discounting loan for {invoice.industry.lower()} "
        f"supply chain finance India bank NBFC"
    )


def _candidate_score(result: dict) -> tuple[int, list[str]]:
    """Deterministic relevance scoring for search results."""
    url = (result.get("url") or "").lower()
    title = (result.get("title") or "").lower()
    snippet = (result.get("description") or "").lower()
    text = f"{title} {snippet} {url}"
    reasons: list[str] = []
    score = 0
    domain = url.split("/")[2] if "://" in url and url.split("/")[2:] else url
    if any(social in domain for social in _SOCIAL_DOMAINS):
        score -= 60
        reasons.append("social media source")
    if "/blog" in url or "/blogs" in url or any(w in title for w in ("blog", "guide", "news", "how to", "top picks", "best")):
        score -= 40
        reasons.append("editorial content rather than official product page")
    if any(word in text for word in ("supply chain", "invoice discount", "factoring", "working capital")):
        score += 25
        reasons.append("supply-chain financing product")
    if any(word in domain for word in ("bank", "nbfc", "financ", "capital", "factor", "lend", "cred", "yubi", "vayana", "credable", "rxil", "treds")):
        score += 25
        reasons.append("financial institution domain")
    elif re.search(r"\b(bank|nbfc|finance|capital|factor|lender)\b", text):
        score += 15
        reasons.append("financial institution")
    if "india" in text or domain.endswith(".in"):
        score += 10
        reasons.append("Indian provider")
    if re.search(r"(\d+\s*%|\u20b9|rs\.?|crore|lakh)", text):
        score += 10
        reasons.append("published terms")
    return score, reasons


def select_providers(results: list[dict]) -> list[dict]:
    """Pick the TWO most relevant official-ish providers from search results."""
    scored = []
    for result in results:
        score, reasons = _candidate_score(result)
        if score >= 0:
            scored.append((score, reasons, result))
    scored.sort(key=lambda item: (-item[0], item[2].get("position", 99)))
    return [item[2] for item in scored[:2]]


def _infer_type(name: str, title: str, snippet: str) -> str:
    text = f"{name} {title} {snippet}".lower()
    if "bank" in text:
        return "BANK"
    if "nbfc" in text:
        return "NBFC"
    if re.search(r"\b(fintech|platform|capital)\b", text):
        return "FINTECH"
    if re.search(r"\b(fund|amc|asset)\b", text):
        return "FUND"
    return "UNKNOWN"


_MARKETING_WORDS = {"easy", "online", "application", "apply", "get", "loan", "finance", "now",
                   "today", "best", "fast", "quick", "instant", "secure", "smart", "solution"}


def _looks_like_brand(text: str) -> bool:
    words = [w for w in text.split() if w]
    if not words or len(words) > 5:
        return False
    if any(w.lower() in _MARKETING_WORDS for w in words):
        return False
    return True


def _provider_name(url: str, title: str) -> str:
    """Derive an institution name: domain first, title fallback.

    Official product pages put the product in the title ("Bill Invoice
    Discounting Under Value Chain Finance - Bank of Baroda"); the bank name
    lives in the domain, so the domain leads and the title only fills in
    when the domain is opaque (e.g. brand domains like credable.in).
    """
    domain = url.split("/")[2] if "://" in url and url.split("/")[2:] else url
    domain = domain.removeprefix("www.")
    # Strip the TLD and turn the domain into a readable brand name.
    parts = domain.split(".")
    brand_part = next((p for p in parts if p not in ("com", "in", "org", "net", "co", "bank")), parts[0])
    if title:
        for separator in (" - ", " | ", " — "):
            if separator in title:
                tail = title.split(separator)[-1].strip()
                if tail and len(tail) <= 40 and _looks_like_brand(tail):
                    return tail
        clean = re.sub(r"\s*[-|–].*$", "", title).strip()
        if clean and len(clean) <= 40 and clean.lower() != brand_part.lower() and _looks_like_brand(clean):
            return clean
    return brand_part


# ---------------------------------------------------------------------------
# Fact extraction (deterministic, evidence-backed)
# ---------------------------------------------------------------------------

_TERM_PATTERNS: list[tuple[str, list[str], re.Pattern]] = [
    ("rate", ["interest rate", "rate of interest", "p.a.", "per annum", "pricing", "roi"],
     re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")),
    ("tenor", ["tenor", "tenure", "repayment period", "loan tenure"],
     re.compile(r"(\d+(?:\s*[-–]\s*\d+)?)\s*(?:days|months?)")),
    ("advance", ["advance", "margin", "invoice value", "funding up to"],
     re.compile(r"(\d{1,3})\s*%")),
    ("fees", ["processing fee", "fee", "charges"],
     re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%")),
]

_CURRENCY_PATTERN = re.compile(
    r"(?:\u20b9|rs\.?|inr)\s*([\d,]+(?:\s*(?:crore|lakh|cr|l|k))?)", re.IGNORECASE)


def _parse_indian_amount(raw: str) -> float | None:
    """Parse ₹/Rs values with crore/lakh multipliers into rupees."""
    raw = raw.replace(",", "").strip().lower()
    match = re.match(r"([\d.]+)\s*(crore|cr|lakh|l|k)?", raw)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    if unit in ("crore", "cr"):
        number *= 10_000_000
    elif unit in ("lakh", "l"):
        number *= 100_000
    elif unit == "k":
        number *= 1_000
    return number


def _sentences(markdown: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", markdown) if len(s.strip()) > 15]


def _find_window(markdown: str, keywords: list[str]) -> str | None:
    """First sentence containing one of the keywords, as an evidence excerpt."""
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence[:280]
    return None


def _extract_value(window: str, pattern: re.Pattern) -> str:
    match = pattern.search(window or "")
    return match.group(1) if match else "UNKNOWN"


def extract_facts(markdown: str, metadata: dict, provider: ProviderResearch) -> list[Fact]:
    """Deterministic fact extraction with evidence excerpts."""
    title = metadata.get("title") or provider.source_title
    facts: list[Fact] = []

    def add(field: str, value: str, confidence: float, evidence: str, keywords: list[str] | None = None,
            pattern: re.Pattern | None = None):
        if value == "UNKNOWN" and pattern is not None:
            window = _find_window(markdown, keywords or [])
            if window:
                value = _extract_value(window, pattern)
                evidence = window
        facts.append(Fact(
            field=field,
            value=value if value else "UNKNOWN",
            confidence=confidence if value and value != "UNKNOWN" else 0.0,
            source_url=provider.source_url,
            source_title=title,
            retrieved_at=provider.retrieved_at,
            evidence=evidence,
        ))

    for field, keywords, pattern in _TERM_PATTERNS:
        window = _find_window(markdown, keywords)
        value = _extract_value(window, pattern) if window else "UNKNOWN"
        add(field, value, 0.8 if value != "UNKNOWN" else 0.0, window or "")

    # Financing limit (currency window, searched before generic "up to")
    limit_window = None
    for sentence in _sentences(markdown):
        lowered = sentence.lower()
        if _CURRENCY_PATTERN.search(sentence) and any(k in lowered for k in ("up to", "limit", "loan amount", "ticket")):
            limit_window = sentence[:280]
            break
    if limit_window is None:
        limit_window = _find_window(markdown, ["up to", "limit", "loan amount", "ticket", "crore", "lakh"])
    limit_value = "UNKNOWN"
    if limit_window:
        currency_match = _CURRENCY_PATTERN.search(limit_window)
        if currency_match:
            parsed = _parse_indian_amount(currency_match.group(1))
            limit_value = f"{parsed:,.0f}" if parsed else "UNKNOWN"
    add("limit", limit_value, 0.7 if limit_value != "UNKNOWN" else 0.0, limit_window or "")

    # Settlement / disbursement
    settle_window = _find_window(markdown, ["disburs", "same day", "within 24", "t\\+1", "settlement", "hours"])
    add("settlement", settle_window or "UNKNOWN", 0.6 if settle_window else 0.0, settle_window or "")

    # Eligibility
    elig_window = _find_window(markdown, ["eligible", "eligibility", "msme", "turnover", "minimum"])
    add("eligibility", elig_window or "UNKNOWN", 0.6 if elig_window else 0.0, elig_window or "")

    # Sectors targeted
    sectors_window = _find_window(markdown, ["sectors", "industries", "manufacturing", "auto", "pharma", "retail"])
    add("sectors", sectors_window or "UNKNOWN", 0.6 if sectors_window else 0.0, sectors_window or "")

    # Credit rating
    rating_window = _find_window(markdown, ["rating", "crisil", "icra", "aaa", "a1+"])
    add("rating", rating_window or "UNKNOWN", 0.7 if rating_window else 0.0, rating_window or "")

    # Scale / capacity
    scale_window = _find_window(markdown, ["aum", "assets under", "loan book", "net worth", "crore", "billion"])
    add("scale", scale_window or "UNKNOWN", 0.6 if scale_window else 0.0, scale_window or "")

    # Operating history
    years_window = _find_window(markdown, ["since", "years of", "established", "founded"])
    add("years", years_window or "UNKNOWN", 0.6 if years_window else 0.0, years_window or "")

    # Product capability
    product_window = _find_window(markdown, ["supply chain finance", "invoice discount", "factoring", "bill discount"])
    add("product", product_window or "UNKNOWN", 0.8 if product_window else 0.0, product_window or "")

    return facts


# ---------------------------------------------------------------------------
# Cache (provider intelligence is expensive; reuse it)
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        with open(_cache_file(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(_cache_dir(), exist_ok=True)
    with open(_cache_file(), "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2)


def _load_telemetry() -> dict:
    try:
        with open(_telemetry_file(), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _save_telemetry(telemetry: dict) -> None:
    os.makedirs(_cache_dir(), exist_ok=True)
    with open(_telemetry_file(), "w", encoding="utf-8") as handle:
        json.dump(telemetry, handle, indent=2)


def _profiles_from_cache(cache: dict) -> list[ProviderResearch]:
    profiles: list[ProviderResearch] = []
    for entry in cache.values():
        if not isinstance(entry, dict) or "facts" not in entry:
            continue
        profiles.append(ProviderResearch(
            provider_name=entry.get("provider_name", "Unknown provider"),
            provider_type=entry.get("provider_type", "UNKNOWN"),
            source_url=entry.get("source_url", ""),
            source_title=entry.get("source_title", ""),
            retrieved_at=entry.get("retrieved_at", ""),
            facts=[Fact(**fact) for fact in entry.get("facts", [])],
        ))
    return profiles


def _dedupe_urls(entries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in entries:
        url = entry.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(entry)
    return unique


def run_research(invoice, requirements, *, refresh: bool = False,
                 client: FirecrawlClient | None = None,
                 on_step=None) -> ResearchOutcome:
    """The full credit-conservative research pass.

    Returns a ResearchOutcome; every Firecrawl call is counted in the
    telemetry that ends up in the UI. Cache hits never touch the network.
    """
    client = client or FirecrawlClient()
    key = _context_key(invoice, requirements)
    cache = _load_cache()
    telemetry = _load_telemetry()
    cached_contexts: list[dict] = [v for v in cache.values() if v.get("context_key") == key]

    if cached_contexts and not refresh:
        on_step and on_step("cache_hit", "Provider intelligence found in cache")
        profiles = [
            ProviderResearch(
                provider_name=v.get("provider_name", "Unknown provider"),
                provider_type=v.get("provider_type", "UNKNOWN"),
                source_url=v.get("source_url", ""),
                source_title=v.get("source_title", ""),
                retrieved_at=v.get("retrieved_at", ""),
                facts=[Fact(**f) for f in v.get("facts", [])],
            ) for v in cached_contexts
        ]
        telemetry["cache_hits"] = telemetry.get("cache_hits", 0) + len(profiles)
        telemetry["providers_researched"] = telemetry.get("providers_researched", 0) + len(profiles)
        _save_telemetry(telemetry)
        return ResearchOutcome(
            status="cached",
            providers=profiles,
            telemetry=ResearchTelemetry(**telemetry),
        )

    try:
        on_step and on_step("searching", "Searching capital market via Firecrawl")
        query = build_search_query(invoice, requirements)
        results = client.search(query)
        telemetry["searches"] = telemetry.get("searches", 0) + 1

        on_step and on_step("selecting", "Selecting the two best relevant providers")
        selected = select_providers(_dedupe_urls(results))

        profiles: list[ProviderResearch] = []
        for entry in selected:
            url = entry.get("url", "")
            on_step and on_step("scraping", f"Researching official source: {url}")
            try:
                payload = client.scrape(url)
            except ResearchError:
                # One failed scrape must not sink the whole pass; record the
                # provider with UNKNOWN facts rather than fabricating.
                payload = {"markdown": "", "metadata": {"title": entry.get("title", url)}}
            telemetry["pages_scraped"] = telemetry.get("pages_scraped", 0) + 1

            profile = ProviderResearch(
                provider_name=_provider_name(url, entry.get("title", "")),
                provider_type=_infer_type(
                    _provider_name(url, entry.get("title", "")),
                    entry.get("title", ""),
                    entry.get("description", ""),
                ),
                source_url=url,
                source_title=entry.get("title", ""),
                retrieved_at=_utcnow(),
            )
            profile.facts = extract_facts(payload.get("markdown", ""), payload.get("metadata", {}), profile)
            profiles.append(profile)
            # Persist immediately so re-runs hit the cache.
            cache[url] = {
                "context_key": key,
                "provider_name": profile.provider_name,
                "provider_type": profile.provider_type,
                "source_url": profile.source_url,
                "source_title": profile.source_title,
                "retrieved_at": profile.retrieved_at,
                "facts": [f.to_dict() for f in profile.facts],
            }

        telemetry["cache_misses"] = telemetry.get("cache_misses", 0) + len(profiles)
        telemetry["providers_researched"] = telemetry.get("providers_researched", 0) + len(profiles)
        telemetry["last_research_at"] = _utcnow()
        _save_cache(cache)
        _save_telemetry(telemetry)
        return ResearchOutcome(
            status="live" if profiles else "unavailable",
            providers=profiles,
            telemetry=ResearchTelemetry(**telemetry),
        )
    except ResearchError as exc:
        _save_telemetry(telemetry)
        return ResearchOutcome(
            status="unavailable",
            providers=[],
            telemetry=ResearchTelemetry(**telemetry),
            error=str(exc),
        )
