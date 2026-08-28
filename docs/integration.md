# Integration Contract

`contracts/models.py` is the single source of truth for service requests and responses. Every model forbids unknown fields. The core serialises with JSON-safe Pydantic output and revalidates HTTP responses before business logic uses them.

## Invoice/Risk service

- `GET /health`
- `POST /verify` with `InvoiceEvaluationRequest`
- `POST /evaluate` with `InvoiceEvaluationRequest`, returning `InvoiceEvaluation`

## Capital Market service

- `GET /health`
- `POST /offers` with `MarketRequest`, returning `MarketResponse`

The market request contains the exact invoice, supplier requirements, verification, risk and current provider snapshots. Provider agents never read browser state.

## Core lifecycle

1. `POST /api/opportunities` stores validated demand.
2. `run-market` calls Invoice/Risk, validates the result, then calls Capital Market with current provider state.
3. Core applies supplier hard constraints and produces `MatchDecision` with per-factor scores.
4. `accept` verifies the offer is still recommended and eligible, rechecks liquidity, settles once, updates provider state and writes audit history.
5. A later `run-market` receives the updated provider snapshots and may produce different offers.

Run final integration in `required` mode; use `fixture` only for deliberate offline demos.

