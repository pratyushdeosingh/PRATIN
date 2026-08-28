# Architecture

PRATIN implements the official continuous allocation loop:

`Invoice → Verify → Assess Risk → Discover Capital → Generate Offers → Compare → Match → Finance → Settle → Learn / Reallocate`

## Boundaries

- **Invoice/Risk Agent:** performs clearly labelled synthetic consistency checks, separates verified and uncertain fields, and produces an explainable risk score with confidence and missing information.
- **Capital Market Agents:** each provider owns state, objectives and constraints. It may decline or create a multi-dimensional offer. Providers differ materially.
- **Core:** owns opportunity lifecycle, integration policy, response validation, hard constraints, ranking, settlement, persistence, metrics and audit.
- **Cockpit:** displays backend decisions and sends commands; it never computes the authoritative ranking.

Supabase Postgres is the deployed durable store for opportunities, provider state, settlements and audit events. The backend connects server-side to a private `pratin` schema; browser roles have no schema access and the database URL is never exposed to React. Settlement locks the opportunity and provider rows and commits provider liquidity/exposure, opportunity status, settlement and audit event in one PostgreSQL transaction. Replaying the same acceptance returns the original settlement without mutating capital twice. A stale recommendation is rejected if current liquidity, exposure, capacity or concentration can no longer support it.

SQLite implements the same store contract only for deterministic offline demos and unit tests. The cockpit exposes which backend is active, so SQLite is never presented as Supabase persistence.

## Decision model

Provider participation gates verification, risk appetite, liquidity, ticket size and concentration. Matching then rejects offers that miss supplier capital, time or cost mandates. Remaining offers receive factor scores and weights from `backend/app/matching.py`. The response includes the full decomposition and a policy-version notice.

The canonical `matching-policy-1.1-demo` weights are usable capital 28%, total effective cost 32%, settlement speed 16%, tenor 8%, provider risk-adjusted return 8% and remaining liquidity 8%.

## Resilience and provenance

- `required`: unavailable services fail visibly with HTTP 503.
- `fixture`: deterministic in-process agents are used and labelled `FIXTURE`.
- `auto`: HTTP services are preferred; fallback is labelled `DEGRADED_FIXTURE`.

This follows ARGUS_CSI's proven separation of orchestration, strict contracts, visible provenance, deterministic demo data and durable state without copying its fraud-detection functionality.

The market lifecycle is exposed as a reusable backend orchestration function and triggered by the demo API. The prototype demonstrates stateful adaptive reallocation; it does not claim autonomous background clearing or learning infrastructure.

## Security boundary

Only synthetic data is bundled. Verification is not GST/KYC/legal validation. Settlement never invokes payment rails. CORS is restricted to local demo origins, extra contract fields are rejected, and secrets remain environment-based. The Supabase schema is private, RLS is enabled as defense in depth, `anon` and `authenticated` have no schema access, and the server-only database URL is excluded from Docker build context and Git.
