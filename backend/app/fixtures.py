from datetime import date, timedelta
from contracts.models import FinancingRequirements, Invoice, OpportunityCreate, Provider

def providers() -> list[Provider]:
    return [
        Provider(id="bank-a", name="Astra Commercial Bank", provider_type="BANK", available_liquidity=5_000_000,
            risk_appetite=42, min_return_rate=8.2, max_ticket_size=700_000, preferred_industries=["Manufacturing", "Automotive"],
            settlement_hours=96, max_concentration_ratio=.60, current_exposure=900_000, portfolio_capacity=8_000_000,
            base_advance_rate=.70, fee_rate=.002),
        Provider(id="nbfc-b", name="VegaFlow NBFC", provider_type="NBFC", available_liquidity=1_650_000,
            risk_appetite=68, min_return_rate=9.4, max_ticket_size=1_500_000, preferred_industries=["Manufacturing", "Logistics", "Retail"],
            settlement_hours=24, max_concentration_ratio=.72, current_exposure=1_300_000, portfolio_capacity=6_000_000,
            base_advance_rate=.85, fee_rate=.008),
        Provider(id="fintech-c", name="PulseTrade Capital", provider_type="FINTECH", available_liquidity=2_400_000,
            risk_appetite=78, min_return_rate=10.5, max_ticket_size=1_200_000, preferred_industries=["Technology", "Retail"],
            settlement_hours=2, max_concentration_ratio=.82, current_exposure=1_100_000, portfolio_capacity=4_000_000,
            base_advance_rate=.92, fee_rate=.04),
        Provider(id="fund-d", name="Meridian Yield Fund", provider_type="FUND", available_liquidity=6_000_000,
            risk_appetite=58, min_return_rate=10.1, max_ticket_size=2_500_000, preferred_industries=["Pharma", "Automotive"],
            settlement_hours=48, max_concentration_ratio=.50, current_exposure=2_600_000, portfolio_capacity=10_000_000,
            base_advance_rate=.80, fee_rate=.012),
    ]

def scenarios() -> dict[str, OpportunityCreate]:
    today = date.today()
    base = dict(issue_date=today - timedelta(days=8), due_date=today + timedelta(days=52), currency="INR",
        purchase_order_reference="PO-2026-1188", supplier_history_months=38)
    return {
        "urgent": OpportunityCreate(invoice=Invoice(invoice_number="INV-PRATIN-1001", supplier_name="Shakti Components",
            buyer_name="Orion Auto Systems", amount=1_000_000, industry="Manufacturing", gstin="27ABCDE1234F1Z5",
            buyer_rating=.88, on_time_payment_ratio=.93, prior_defaults=0, **base),
            requirements=FinancingRequirements(minimum_amount=800_000, max_settlement_hours=48, desired_tenor_days=60)),
        "strong": OpportunityCreate(invoice=Invoice(invoice_number="INV-PRATIN-1002", supplier_name="Nova Pharma Pack",
            buyer_name="Aster Healthcare", amount=1_400_000, industry="Pharma", gstin="27ABCDE1234F1Z5",
            buyer_rating=.94, on_time_payment_ratio=.96, prior_defaults=0, **base),
            requirements=FinancingRequirements(minimum_amount=900_000, max_settlement_hours=96, desired_tenor_days=45)),
        "high-risk": OpportunityCreate(invoice=Invoice(invoice_number="INV-PRATIN-1003", supplier_name="Rapid Retail Works",
            buyer_name="Urban Cart", amount=850_000, industry="Retail", gstin=None,
            buyer_rating=.42, on_time_payment_ratio=.61, prior_defaults=1, supplier_history_months=9,
            issue_date=base["issue_date"], due_date=base["due_date"], currency="INR", purchase_order_reference=None),
            requirements=FinancingRequirements(minimum_amount=550_000, max_settlement_hours=24, desired_tenor_days=75)),
    }
