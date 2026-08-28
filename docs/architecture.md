# Architecture

PRATIN implements the official continuous allocation loop:

`Invoice → Verify → Assess Risk → Discover Capital → Generate Offers → Compare → Match → Finance → Settle → Learn / Reallocate`

## Boundaries

- **Invoice/Risk Agent:** performs clearly labelled synthetic consistency checks, separates verified and uncertain fields, and produces an explainable risk score with confidence and missing information.
- **Capital Market Agents:** each provider owns state, objectives and constraints. It may decline or create a multi-dimensional offer. Providers differ materially.
- **Core:** owns opportunity lifecycle, integration policy, response validation, hard constraints, ranking, settlement, persistence, metrics and audit.
- **Cockpit:** displays backend decisions and sends commands; it never computes the authoritative ranking.

SQLite persists opportunities, provider state, settlements and audit events. Settlement uses a process lock and a unique opportunity constraint to prevent duplicate allocation. Provider liquidity/exposure and settlement are written in one transaction.

## Decision model

Provider participation gates verification, risk appetite, liquidity, ticket size and concentration. Matching then rejects offers that miss supplier capital, time or cost mandates. Remaining offers receive factor scores and weights from `backend/app/matching.py`. The response includes the full decomposition and a policy-version notice.

## Resilience and provenance

- `required`: unavailable services fail visibly with HTTP 503.
- `fixture`: deterministic in-process agents are used and labelled `FIXTURE`.
- `auto`: HTTP services are preferred; fallback is labelled `DEGRADED_FIXTURE`.

This follows ARGUS_CSI's proven separation of orchestration, strict contracts, visible provenance, deterministic demo data and durable state without copying its fraud-detection functionality.

## Security boundary

Only synthetic data is bundled. Verification is not GST/KYC/legal validation. Settlement never invokes payment rails. CORS is restricted to local demo origins, extra contract fields are rejected, secrets remain environment-based, and no API key is required.

