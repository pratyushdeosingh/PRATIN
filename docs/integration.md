# Integration Contract

`contracts/models.py` is the single source of truth for service requests and responses. Every model forbids unknown fields. The core serialises with JSON-safe Pydantic output and revalidates HTTP responses before business logic uses them.

## Persistence selection

- `PRATIN_DATABASE_BACKEND=supabase` requires a server-only `SUPABASE_DATABASE_URL` and uses the private `pratin` PostgreSQL schema.
- `PRATIN_DATABASE_BACKEND=sqlite` uses `PRATIN_DB_PATH` strictly as an offline/test fallback.
- If `SUPABASE_DATABASE_URL` is present and no backend is named, Supabase is selected automatically.

The browser never receives database credentials or writes marketplace tables directly. This preserves backend ownership of matching and settlement. Supabase tables are deliberately outside the exposed `public` schema.

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
4. `accept` verifies the offer is still recommended and eligible, rechecks mutable liquidity/exposure/capacity/concentration, then atomically updates provider state, opportunity state, settlement and audit history. Repeating the identical acceptance returns the original settlement without another mutation.
5. A later `run-market` receives the updated provider snapshots and may produce different offers.

Run final integration in `required` mode; use `fixture` only for deliberate offline demos.

`required` rejects transport, HTTP, JSON and schema failures without fallback. `auto` uses deterministic fallback only when a service call fails and labels the result `DEGRADED_FIXTURE`. `fixture` never makes an HTTP call and is labelled `FIXTURE`. Invalid integration-mode configuration fails at startup.
