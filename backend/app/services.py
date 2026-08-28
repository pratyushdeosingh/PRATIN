import httpx
from contracts.models import InvoiceEvaluation, InvoiceEvaluationRequest, MarketRequest, MarketResponse
from services.invoice_risk.engine import evaluate
from services.capital_market.engine import generate_market
from .config import Settings

class IntegrationClient:
    def __init__(self, settings: Settings): self.settings = settings

    async def invoice_evaluation(self, request: InvoiceEvaluationRequest):
        if self.settings.integration_mode == "fixture":
            return evaluate(request.invoice).model_copy(update={"provenance": "FIXTURE"}), "FIXTURE"
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
                response = await client.post(f"{self.settings.invoice_risk_url}/evaluate", json=request.model_dump(mode="json")); response.raise_for_status()
            return InvoiceEvaluation.model_validate(response.json()), "SERVICE"
        except Exception:
            if self.settings.integration_mode == "required": raise
            return evaluate(request.invoice).model_copy(update={"provenance": "FIXTURE"}), "DEGRADED_FIXTURE"

    async def market(self, request: MarketRequest):
        if self.settings.integration_mode == "fixture":
            return generate_market(request).model_copy(update={"provenance": "FIXTURE"}), "FIXTURE"
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
                response = await client.post(f"{self.settings.capital_market_url}/offers", json=request.model_dump(mode="json")); response.raise_for_status()
            return MarketResponse.model_validate(response.json()), "SERVICE"
        except Exception:
            if self.settings.integration_mode == "required": raise
            return generate_market(request).model_copy(update={"provenance": "FIXTURE"}), "DEGRADED_FIXTURE"

