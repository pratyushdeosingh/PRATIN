"""Deterministic capital provider scoring from researched intelligence.

Each dimension produces: score (0..100), weight, evidence, explanation and
confidence. Missing evidence is scored as UNKNOWN with low confidence — it
is never silently turned into a positive score. The composite is a weighted
average over the dimensions that have evidence; the resulting score also
carries an overall confidence so the UI can show how solid it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .research import Fact, ProviderResearch


@dataclass
class ScoreDimension:
    """One scored dimension of the Capital Provider Score."""

    name: str
    score: float
    weight: float
    evidence: str
    explanation: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "weight": round(self.weight, 2),
            "evidence": self.evidence,
            "explanation": self.explanation,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ProviderScore:
    """Composite provider score with per-dimension explainability."""

    total: float
    confidence: float
    dimensions: list[ScoreDimension] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 1),
            "confidence": round(self.confidence, 2),
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


def _fact_value(profile: ProviderResearch, field_name: str) -> str:
    fact = profile.fact(field_name)
    return (fact.value if fact and fact.confidence > 0 else "UNKNOWN")


def _confidence(profile: ProviderResearch, field_name: str) -> float:
    fact = profile.fact(field_name)
    return fact.confidence if fact else 0.0


def _dimension(profile: ProviderResearch, name: str, weight: float,
               score: float, evidence: str, explanation: str, confidence: float) -> ScoreDimension:
    return ScoreDimension(name=name, score=round(score, 1), weight=weight,
                          evidence=evidence, explanation=explanation,
                          confidence=confidence)


def score_provider(profile: ProviderResearch, invoice_industry: str) -> ProviderScore:
    """Score a researched provider across six explainable dimensions.

    Evidence drives each score. An UNKNOWN value yields score 0 with low
    confidence (not a neutral positive), so fabricated-looking strength is
    impossible.
    """
    dims: list[ScoreDimension] = []

    # 1. Financial health (rating, scale, years)
    rating = _fact_value(profile, "rating")
    scale = _fact_value(profile, "scale")
    years = _fact_value(profile, "years")
    health_evidence = "; ".join(v for v in [rating, scale, years] if v != "UNKNOWN") or "No evidence found."
    health_conf = max(_confidence(profile, "rating"), _confidence(profile, "scale"), _confidence(profile, "years"))
    if rating != "UNKNOWN":
        health_score = 75 + 15 * _confidence(profile, "rating")
        health_note = f"Published rating information: {rating[:120]}"
    elif scale != "UNKNOWN":
        health_score = 65 + 10 * _confidence(profile, "scale")
        health_note = f"Scale evidence found: {scale[:120]}"
    else:
        health_score = 0.0
        health_note = "No financial health evidence found in the researched source."
    dims.append(_dimension(profile, "Financial Health", 0.25, health_score,
                           health_evidence, health_note, health_conf))

    # 2. Capital strength (limit, scale)
    limit = _fact_value(profile, "limit")
    capital_evidence = "; ".join(v for v in [limit, scale] if v != "UNKNOWN") or "No evidence found."
    capital_conf = max(_confidence(profile, "limit"), _confidence(profile, "scale"))
    if limit != "UNKNOWN":
        capital_score = 70 + 15 * _confidence(profile, "limit")
        capital_note = f"Published financing limit: {limit[:140]}"
    else:
        capital_score = 0.0
        capital_note = "No published financing limit found."
    dims.append(_dimension(profile, "Capital Strength", 0.20, capital_score,
                           capital_evidence, capital_note, capital_conf))

    # 3. Track record (years, rating)
    track_evidence = "; ".join(v for v in [years, rating] if v != "UNKNOWN") or "No evidence found."
    track_conf = max(_confidence(profile, "years"), _confidence(profile, "rating"))
    if years != "UNKNOWN" or rating != "UNKNOWN":
        track_score = 65 + 15 * track_conf
        track_note = f"Track record evidence: {track_evidence[:140]}"
    else:
        track_score = 0.0
        track_note = "No track record evidence found."
    dims.append(_dimension(profile, "Track Record", 0.15, track_score,
                           track_evidence, track_note, track_conf))

    # 4. SCF capability (product)
    product = _fact_value(profile, "product")
    product_conf = _confidence(profile, "product")
    if product != "UNKNOWN":
        scf_score = 85 + 10 * product_conf
        scf_note = f"Supply-chain finance product evidence: {product[:140]}"
    else:
        scf_score = 0.0
        scf_note = "No supply-chain finance product evidence found."
    dims.append(_dimension(profile, "SCF Capability", 0.20, scf_score,
                           product if product != "UNKNOWN" else "No evidence found.",
                           scf_note, product_conf))

    # 5. Pricing competitiveness (rate, fees)
    rate = _fact_value(profile, "rate")
    fees = _fact_value(profile, "fees")
    pricing_evidence = "; ".join(v for v in [rate, fees] if v != "UNKNOWN") or "No evidence found."
    pricing_conf = max(_confidence(profile, "rate"), _confidence(profile, "fees"))
    if rate != "UNKNOWN":
        try:
            rate_value = float(rate.replace("%", ""))
        except ValueError:
            rate_value = None
        if rate_value is not None:
            # Lower published rates are more competitive: 6% -> 100, 16%+ -> 40
            pricing_score = max(40.0, min(100.0, 100 - (rate_value - 6) * 6))
            pricing_note = f"Published rate {rate_value}% maps to competitiveness {pricing_score:.0f}/100."
        else:
            pricing_score = 60 * pricing_conf
            pricing_note = f"Rate evidence found but not parseable: {rate[:120]}"
    else:
        pricing_score = 0.0
        pricing_note = "No published pricing found."
    dims.append(_dimension(profile, "Pricing Competitiveness", 0.10, pricing_score,
                           pricing_evidence, pricing_note, pricing_conf))

    # 6. Industry fit (sectors vs invoice industry)
    sectors = _fact_value(profile, "sectors")
    sectors_conf = _confidence(profile, "sectors")
    industry_lower = invoice_industry.lower()
    if sectors != "UNKNOWN" and industry_lower in sectors.lower():
        fit_score = 100.0
        fit_note = f"Researched source mentions {invoice_industry}, matching the invoice industry."
    elif sectors != "UNKNOWN":
        fit_score = 45.0
        fit_note = f"No explicit {invoice_industry} mention in the researched source."
    else:
        fit_score = 0.0
        fit_note = "No sector information found."
    dims.append(_dimension(profile, "Industry Fit", 0.10, fit_score,
                           sectors if sectors != "UNKNOWN" else "No evidence found.",
                           fit_note, sectors_conf))

    # Composite: weighted average over dimensions with any evidence; the
    # weights of evidence-free dimensions are redistributed so the total
    # reflects what is actually known.
    evidenced = [d for d in dims if d.confidence > 0]
    if not evidenced:
        return ProviderScore(total=0.0, confidence=0.0, dimensions=dims)
    weight_sum = sum(d.weight for d in evidenced)
    total = sum(d.score * (d.weight / weight_sum) for d in evidenced)
    confidence = sum(d.confidence * d.weight for d in evidenced) / weight_sum
    return ProviderScore(total=round(total, 1), confidence=round(confidence, 2), dimensions=dims)


def score_breakdown(score: ProviderScore) -> dict:
    """JSON-safe breakdown for the UI."""
    return score.to_dict()
