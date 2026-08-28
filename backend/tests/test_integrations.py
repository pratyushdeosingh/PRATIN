import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.fixtures import scenarios
from backend.app.services import IntegrationClient
from contracts.models import InvoiceEvaluationRequest


def request():
    return InvoiceEvaluationRequest(invoice=scenarios()["urgent"].invoice)


def client(mode, handler):
    return IntegrationClient(
        Settings(integration_mode=mode, invoice_risk_url="http://risk", capital_market_url="http://market"),
        transport=httpx.MockTransport(handler),
    )


def valid_payload():
    from services.invoice_risk.engine import evaluate
    return evaluate(request().invoice).model_dump(mode="json")


@pytest.mark.parametrize("status", [400, 404, 500])
def test_required_mode_surfaces_http_failures(status):
    integration = client("required", lambda req: httpx.Response(status, request=req))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(integration.invoice_evaluation(request()))


@pytest.mark.parametrize("failure", ["timeout", "connection"])
def test_required_mode_surfaces_transport_failures(failure):
    def handler(req):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        raise httpx.ConnectError("offline", request=req)
    with pytest.raises(httpx.HTTPError):
        asyncio.run(client("required", handler).invoice_evaluation(request()))


@pytest.mark.parametrize("payload", [
    {"verification": {}, "risk": {}},
    {**valid_payload(), "unexpected": True},
    {**valid_payload(), "provenance": "MAGIC"},
    {**valid_payload(), "risk": {**valid_payload()["risk"], "score": 101}},
])
def test_required_mode_rejects_contract_mismatch(payload):
    integration = client("required", lambda req: httpx.Response(200, json=payload, request=req))
    with pytest.raises(ValueError, match="Contract validation failed"):
        asyncio.run(integration.invoice_evaluation(request()))


def test_required_mode_rejects_malformed_json():
    integration = client(
        "required",
        lambda req: httpx.Response(200, content=b"not-json", request=req),
    )
    with pytest.raises(ValueError, match="Invalid JSON"):
        asyncio.run(integration.invoice_evaluation(request()))


def test_auto_mode_fallback_is_visibly_degraded():
    integration = client("auto", lambda req: (_ for _ in ()).throw(httpx.ConnectError("offline", request=req)))
    evaluation, status = asyncio.run(integration.invoice_evaluation(request()))
    assert status == "DEGRADED_FIXTURE"
    assert evaluation.provenance == "FIXTURE"


def test_fixture_mode_never_calls_http_or_claims_service():
    integration = client("fixture", lambda req: pytest.fail("fixture mode called HTTP"))
    evaluation, status = asyncio.run(integration.invoice_evaluation(request()))
    assert status == "FIXTURE"
    assert evaluation.provenance == "FIXTURE"


def test_invalid_integration_mode_fails_configuration():
    with pytest.raises(ValueError, match="PRATIN_INTEGRATION_MODE"):
        Settings(integration_mode="requird")  # type: ignore[arg-type]
