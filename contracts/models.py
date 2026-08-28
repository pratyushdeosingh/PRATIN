"""Strict shared contracts for every PRATIN service boundary."""
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    REJECTED = "REJECTED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class Invoice(StrictModel):
    invoice_number: str = Field(min_length=3)
    supplier_name: str
    buyer_name: str
    amount: float = Field(gt=0)
    currency: Literal["INR"] = "INR"
    issue_date: date | None = None
    due_date: date | None = None
    industry: str = "Manufacturing"
    gstin: str | None = None
    purchase_order_reference: str | None = None
    subtotal: float | None = None
    tax_amount: float | None = None
    buyer_rating: float = Field(default=0.75, ge=0, le=1)
    supplier_history_months: int = Field(default=24, ge=0)
    on_time_payment_ratio: float = Field(default=0.86, ge=0, le=1)
    prior_defaults: int = Field(default=0, ge=0)

    @field_validator("due_date")
    @classmethod
    def due_after_issue(cls, value: date | None, info):
        if value is None:
            return value
        issue = info.data.get("issue_date")
        if issue and value <= issue:
            raise ValueError("due_date must be after issue_date")
        return value


class FinancingRequirements(StrictModel):
    minimum_amount: float = Field(gt=0)
    max_settlement_hours: int = Field(gt=0, le=720)
    desired_tenor_days: int = Field(gt=0, le=365)
    max_total_cost: float | None = Field(default=None, gt=0)


class OpportunityCreate(StrictModel):
    invoice: Invoice
    requirements: FinancingRequirements

    @field_validator("requirements")
    @classmethod
    def amount_within_invoice(cls, value: FinancingRequirements, info):
        invoice = info.data.get("invoice")
        if invoice and value.minimum_amount > invoice.amount:
            raise ValueError("minimum financing cannot exceed invoice amount")
        return value


class DuplicateCheckResult(StrictModel):
    duplicate_detected: bool = False
    matched_invoice_number: str | None = None
    matched_fields: list[str] = []
    reasons: list[str] = []


class VerificationResult(StrictModel):
    status: VerificationStatus
    confidence: float = Field(ge=0, le=1)
    verified_fields: list[str]
    uncertain_fields: list[str]
    reasons: list[str]
    reason_codes: list[str] = []
    duplicate_check: DuplicateCheckResult | None = None
    consistency_warnings: list[str] = []
    simulation_notice: str = "Synthetic rule-based verification; not a banking, GST, KYC, or legal verification."


class RiskFactor(StrictModel):
    label: str
    impact: Literal["positive", "negative", "neutral"]
    points: float
    explanation: str
    reason_code: str | None = None


class RiskAssessment(StrictModel):
    score: float = Field(ge=0, le=100, description="Higher means greater risk")
    band: RiskBand
    confidence: float = Field(ge=0, le=1)
    factors: list[RiskFactor]
    missing_information: list[str]
    policy_version: str = "risk-policy-1.0-demo"


class ExtractionConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExtractedInvoiceFields(StrictModel):
    invoice_number: str | None = None
    supplier_name: str | None = None
    buyer_name: str | None = None
    amount: float | None = None
    currency: Literal["INR"] = "INR"
    issue_date: date | None = None
    due_date: date | None = None
    gstin: str | None = None
    purchase_order_reference: str | None = None
    payment_terms: str | None = None
    subtotal: float | None = None
    tax_amount: float | None = None
    missing_fields: list[str] = []
    warnings: list[str] = []
    extraction_confidence: ExtractionConfidence = ExtractionConfidence.LOW


class InvoiceParseResponse(StrictModel):
    status: Literal["SUCCESS", "PDF_TEXT_UNREADABLE", "PDF_EMPTY", "PDF_INVALID"]
    extracted_fields: ExtractedInvoiceFields | None = None
    invoice: Invoice | None = None
    evaluation: InvoiceEvaluation | None = None
    ledger_entry: RiskLedgerEntry | None = None
    error_detail: str | None = None


class InvoiceEvaluationRequest(StrictModel):
    invoice: Invoice
    existing_invoices: list[Invoice] = []


class InvoiceEvaluation(StrictModel):
    verification: VerificationResult
    risk: RiskAssessment
    provenance: Literal["SERVICE", "FIXTURE"] = "SERVICE"


class RiskLedgerEntry(StrictModel):
    id: str
    opportunity_id: str | None = None
    invoice_number: str
    supplier_name: str
    buyer_name: str
    amount: float = Field(gt=0)
    evaluated_at: datetime
    verification: VerificationResult
    risk: RiskAssessment
    provenance: Literal["SERVICE", "FIXTURE"] = "SERVICE"
    source: str | None = None
    source_filename: str | None = None


class Provider(StrictModel):
    id: str
    name: str
    provider_type: Literal["BANK", "NBFC", "FINTECH", "FUND"]
    available_liquidity: float = Field(ge=0)
    risk_appetite: float = Field(ge=0, le=100)
    min_return_rate: float = Field(gt=0)
    max_ticket_size: float = Field(gt=0)
    preferred_industries: list[str]
    settlement_hours: int = Field(gt=0)
    max_concentration_ratio: float = Field(gt=0, le=1)
    current_exposure: float = Field(ge=0)
    portfolio_capacity: float = Field(gt=0)
    base_advance_rate: float = Field(gt=0, le=1)
    fee_rate: float = Field(ge=0, le=0.25)


class Offer(StrictModel):
    id: str
    opportunity_id: str
    provider_id: str
    provider_name: str
    provider_type: str
    status: Literal["OFFER", "DECLINE"]
    annual_rate: float | None = None
    advance_rate: float | None = None
    financed_amount: float | None = None
    fees: float | None = None
    tenor_days: int | None = None
    settlement_hours: int | None = None
    total_effective_cost: float | None = None
    expected_return: float | None = None
    reasons: list[str]


class MarketRequest(StrictModel):
    opportunity_id: str
    invoice: Invoice
    requirements: FinancingRequirements
    verification: VerificationResult
    risk: RiskAssessment
    providers: list[Provider]


class MarketResponse(StrictModel):
    offers: list[Offer]
    provenance: Literal["SERVICE", "FIXTURE"] = "SERVICE"


class ScoreFactor(StrictModel):
    name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    explanation: str


class RankedOffer(StrictModel):
    offer: Offer
    eligible: bool
    suitability_score: float = Field(ge=0, le=100)
    factors: list[ScoreFactor]
    hard_constraint_failures: list[str]
    rank: int | None = None


class MatchDecision(StrictModel):
    opportunity_id: str
    recommended_offer_id: str | None
    ranked_offers: list[RankedOffer]
    recommendation_reasons: list[str]
    policy_version: str = "matching-policy-1.1-demo"
    policy_notice: str = "Prototype policy weights are explainable demonstration parameters, not production-calibrated financial advice."


class OpportunityRecord(StrictModel):
    id: str
    created_at: datetime
    status: Literal["CREATED", "MARKET_RUN", "SETTLED"]
    invoice: Invoice
    requirements: FinancingRequirements
    evaluation: InvoiceEvaluation | None = None
    offers: list[Offer] = []
    match: MatchDecision | None = None
    integration_status: dict[str, str] = {}


class Settlement(StrictModel):
    id: str
    opportunity_id: str
    offer_id: str
    provider_id: str
    amount: float
    status: Literal["SIMULATED_SETTLED"] = "SIMULATED_SETTLED"
    settled_at: datetime
    notice: str = "Simulation only. No real funds moved."


class AuditEvent(StrictModel):
    id: str
    timestamp: datetime
    event_type: str
    opportunity_id: str | None = None
    detail: str


class PlatformMetrics(StrictModel):
    available_liquidity: float
    active_opportunities: int
    offers_generated: int
    financing_allocated: float
    settlements: int
    provider_participation_rate: float


class ProviderSimulationOverride(StrictModel):
    available_liquidity: float | None = Field(default=None, ge=0)
    current_exposure: float | None = Field(default=None, ge=0)
    risk_appetite: float | None = Field(default=None, ge=0, le=100)
    settlement_hours: int | None = Field(default=None, gt=0, le=720)
    max_ticket_size: float | None = Field(default=None, gt=0)
    max_concentration_ratio: float | None = Field(default=None, gt=0, le=1)


class MarketTwinOverrides(StrictModel):
    risk_score: float | None = Field(default=None, ge=0, le=100)
    minimum_amount: float | None = Field(default=None, gt=0)
    max_settlement_hours: int | None = Field(default=None, gt=0, le=720)
    desired_tenor_days: int | None = Field(default=None, gt=0, le=365)
    max_total_cost: float | None = Field(default=None, gt=0)
    market_regime: Literal["FAVORABLE", "NEUTRAL", "CAUTIOUS", "STRESSED"] | None = None
    provider_overrides: dict[str, ProviderSimulationOverride] = Field(default_factory=dict)
    removed_provider_ids: list[str] = Field(default_factory=list)
    confidence_stress: bool = False


class MarketTwinRequest(StrictModel):
    opportunity_id: str
    overrides: MarketTwinOverrides = Field(default_factory=MarketTwinOverrides)


class StrategySimulationRequest(StrictModel):
    opportunity_id: str
    minimum_amount: float | None = Field(default=None, gt=0)
    max_settlement_hours: int | None = Field(default=None, gt=0, le=720)
    desired_tenor_days: int | None = Field(default=None, gt=0, le=365)
    max_total_cost: float | None = Field(default=None, gt=0)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
