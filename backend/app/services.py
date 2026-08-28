import httpx
from pydantic import ValidationError

from contracts.models import InvoiceEvaluation, InvoiceEvaluationRequest, MarketRequest, MarketResponse
from services.invoice_risk.engine import evaluate
from services.capital_market.engine import generate_market
from .config import Settings

class IntegrationClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def _post(self, url: str, request, response_model):
        async with httpx.AsyncClient(timeout=self.settings.timeout, transport=self.transport) as client:
            response = await client.post(url, json=request.model_dump(mode="json"))
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise ValueError(f"Invalid JSON returned by {url}") from exc
            try:
                return response_model.model_validate(payload)
            except ValidationError as exc:
                raise ValueError(f"Contract validation failed for {url}: {exc}") from exc

    async def invoice_evaluation(self, request: InvoiceEvaluationRequest):
        if self.settings.integration_mode == "fixture":
            return evaluate(request.invoice).model_copy(update={"provenance": "FIXTURE"}), "FIXTURE"
        try:
            evaluation = await self._post(
                f"{self.settings.invoice_risk_url}/evaluate", request, InvoiceEvaluation
            )
            return evaluation, "SERVICE"
        except (httpx.HTTPError, ValueError):
            if self.settings.integration_mode == "required":
                raise
            return evaluate(request.invoice).model_copy(update={"provenance": "FIXTURE"}), "DEGRADED_FIXTURE"

    async def market(self, request: MarketRequest):
        if self.settings.integration_mode == "fixture":
            return generate_market(request).model_copy(update={"provenance": "FIXTURE"}), "FIXTURE"
        try:
            market = await self._post(
                f"{self.settings.capital_market_url}/offers", request, MarketResponse
            )
            return market, "SERVICE"
        except (httpx.HTTPError, ValueError):
            if self.settings.integration_mode == "required":
                raise
            return generate_market(request).model_copy(update={"provenance": "FIXTURE"}), "DEGRADED_FIXTURE"

    async def parse_invoice_pdf(self, pdf_bytes: bytes, filename: str):
        from contracts.models import InvoiceParseResponse
        if self.settings.integration_mode == "fixture":
            from services.invoice_risk.pdf_parser import parse_and_evaluate_pdf
            return parse_and_evaluate_pdf(pdf_bytes, filename=filename), "FIXTURE"
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout, transport=self.transport) as client:
                files = {"file": (filename, pdf_bytes, "application/pdf")}
                response = await client.post(f"{self.settings.invoice_risk_url}/parse-invoice", files=files)
                if response.status_code == 422:
                    return InvoiceParseResponse.model_validate(response.json()), "SERVICE"
                response.raise_for_status()
                return InvoiceParseResponse.model_validate(response.json()), "SERVICE"
        except (httpx.HTTPError, ValueError):
            if self.settings.integration_mode == "required":
                raise
            from services.invoice_risk.pdf_parser import parse_and_evaluate_pdf
            return parse_and_evaluate_pdf(pdf_bytes, filename=filename), "DEGRADED_FIXTURE"
