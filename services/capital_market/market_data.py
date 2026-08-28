"""Market conditions for the Capital Agent.

The Capital Agent translates market information into a simple regime that
influences pricing and participation. Real external market data can be
injected through ``load_market()`` later; when it is unavailable the agent
falls back to an explicit deterministic NEUTRAL regime labelled as
synthetic/demo data. The fallback never pretends to be real market data.
"""
from dataclasses import dataclass


class MarketRegime:
    """Deterministic market regimes used by the Capital Agent."""

    FAVORABLE = "FAVORABLE"
    NEUTRAL = "NEUTRAL"
    CAUTIOUS = "CAUTIOUS"
    STRESSED = "STRESSED"


@dataclass(frozen=True)
class MarketConditions:
    """Interpreted market snapshot consumed by the Capital Agent."""

    regime: str
    source: str = "synthetic-demo-fallback"
    description: str = "No external market feed configured; deterministic demo regime."
    # Deterministic per-regime adjustments applied during pricing.
    risk_premium_bps: float = 0.0
    advance_rate_adjustment: float = 0.0
    tenor_adjustment_days: int = 0


# Deterministic adjustment table keyed by regime. These are explicit demo
# parameters, not production-calibrated market data.
_REGIME_TABLE: dict[str, tuple[float, float, int]] = {
    MarketRegime.FAVORABLE: (+0.0, +0.01, 0),     # slightly more competitive pricing
    MarketRegime.NEUTRAL: (+0.0, 0.0, 0),
    MarketRegime.CAUTIOUS: (+0.5, -0.02, -5),     # preserve liquidity
    MarketRegime.STRESSED: (+1.0, -0.04, -10),    # demand higher return, cut advance
}

_DESCRIPTIONS: dict[str, str] = {
    MarketRegime.FAVORABLE: "Favorable market: liquidity is abundant, pricing is competitive.",
    MarketRegime.NEUTRAL: "Neutral market: no directional pressure on pricing or participation.",
    MarketRegime.CAUTIOUS: "Cautious market: providers preserve liquidity and tighten terms.",
    MarketRegime.STRESSED: "Stressed market: providers demand higher returns and cut advance rates.",
}


def _conditions(regime: str) -> MarketConditions:
    premium, advance, tenor = _REGIME_TABLE[regime]
    return MarketConditions(
        regime=regime,
        source="synthetic-demo-fallback",
        description=_DESCRIPTIONS[regime],
        risk_premium_bps=premium,
        advance_rate_adjustment=advance,
        tenor_adjustment_days=tenor,
    )


def load_market() -> MarketConditions:
    """Return the current market snapshot.

    This is the single injection point for real external market data. When
    a real feed is added it must return a :class:`MarketConditions` built
    from that feed; until then the deterministic demo fallback is used and
    explicitly labelled synthetic.
    """
    # TODO(capital-agent): connect a real market feed here. Keep the
    # deterministic fallback so the agent never hard-depends on an API.
    return _conditions(MarketRegime.NEUTRAL)
