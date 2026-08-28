# Team start here

Shared rules: branch from `main`; read `README.md`, `docs/architecture.md`, `docs/integration.md` and `contracts/models.py`; do not silently change shared contracts; add or update tests; never put real customer data or secrets in the repository; open a PR and run all checks before merge.

## Pratham — invoice and risk

- Branch: `pratham/invoice-risk`
- Owns: `services/invoice_risk/**` and its tests; proposes contract changes through review.
- Definition of done: invalid invoices do not verify, uncertainty is explicit, normal invoices score better than risky fixtures, factors/confidence are explainable, service health and API tests pass.
- Do not change: capital agents, matching policy, frontend or orchestration without coordination.

**Codex prompt:** “On branch `pratham/invoice-risk`, read the four required files above. Work only in `services/invoice_risk/**` and associated tests. Implement deterministic synthetic invoice verification, explicit uncertainty, explainable risk factors and FastAPI endpoints against shared contracts. Do not claim real GST/KYC verification or change unrelated contracts. Done means tests cover verified, invalid, incomplete and risky invoices and the service contract remains compatible.”

## Nitin — capital agents

- Branch: `nitin/capital-agents`
- Owns: `services/capital_market/**` and its tests; proposes contract changes through review.
- Definition of done: providers behave differently; liquidity, risk appetite, ticket and concentration constraints work; rates, advances, fees and speed differ; reasons accompany decline/offer.
- Do not change: risk policy, matching weights, frontend or core persistence without coordination.

**Codex prompt:** “On branch `nitin/capital-agents`, read the four required files above. Work only in `services/capital_market/**` and associated tests. Implement stateful deterministic provider decisions and differentiated offers using shared contracts. Test liquidity, risk appetite, concentration, sector preference and provider differentiation. Do not calculate the final supplier recommendation or modify unrelated components.”

## Pratyush — orchestration and product

- Branch: `pratyush/orchestration-dashboard`
- Owns: `backend/**`, `frontend/**`, Docker, CI, docs and final integration.
- Definition of done: full API loop, hard gates, explainable deterministic ranking, idempotent settlement, private Supabase Postgres state with an explicit SQLite offline fallback, visible provenance, polished demo, required-mode integration and all repository checks.
- Do not rewrite teammate service internals during integration; resolve contract differences with tests and review.

**Codex prompt:** “On branch `pratyush/orchestration-dashboard`, read the four required files above. Own orchestration, HTTPX integration, matching, SQLite, settlement, audit, React cockpit, Docker, CI and demo QA. Keep business decisions in the backend and validate every service response. Demonstrate lowest-rate loss and a different second allocation after liquidity changes. Do not delete teammate work to resolve conflicts; reconcile contracts and run required-mode integration before the PR.”
