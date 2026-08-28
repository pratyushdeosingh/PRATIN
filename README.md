# PRATIN — Procurement Receivables & Agentic Trade Invoice Network

> **A competitive capital-allocation market for supply-chain working capital.**

PRATIN turns a verified invoice into a financing opportunity evaluated by autonomous capital-provider agents with different liquidity, risk appetites, expected returns, sector preferences and portfolio constraints. Competing offers are filtered against supplier hard requirements and ranked on total suitability—not headline interest alone—before simulated settlement changes the next market outcome.

**The hackathon moment:** Astra Bank advertises the lowest rate, but cannot advance the required ₹8 lakh or settle within 48 hours. VegaFlow NBFC wins because it satisfies the complete mandate. Its liquidity then falls, and the next invoice clears to a different provider.

> All data, verification and settlement are synthetic. No real underwriting, GST/KYC verification, financial advice or fund movement occurs.

## Why this is not a loan comparison site

PRATIN is stateful and two-sided. Supplier constraints are hard gates; providers independently decide whether to participate; risk-adjusted return and portfolio capacity affect their actions; every score has factor-level reasons; and accepting an offer mutates provider liquidity/exposure. The next ranking therefore changes.

## Architecture

```mermaid
flowchart LR
  I[Invoice + supplier mandate] --> R[Invoice / Risk Agent :8001]
  R --> O[PRATIN Orchestrator :8000]
  O --> C[Capital Provider Agents :8002]
  C --> M[Hard gates + multi-objective match]
  M --> S[Simulated settlement]
  S --> DB[(SQLite market state + audit)]
  DB --> O
  O --> UI[React Market Cockpit :5173]
```

The browser talks only to the orchestrator. HTTP service responses are validated against strict shared Pydantic contracts. `required`, `auto` and `fixture` modes make live service provenance or degradation visible.

| Component | Responsibility | Port |
|---|---|---:|
| PRATIN core | Orchestration, matching, SQLite, settlement, metrics, audit | 8000 |
| Invoice & Risk Agent | Synthetic verification, uncertainty and explainable deterministic risk | 8001 |
| Capital Market Agents | Discovery, provider constraints and differentiated offers | 8002 |
| Market Cockpit | Live competition, explanations and reallocation demo | 5173 |

## One-command demo

Prerequisite: Docker Desktop / Docker Engine with Compose v2.

```bash
docker compose up --build
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173), select **Run flagship market**, accept the recommendation, then select **Run next allocation**. API docs are available on ports 8000, 8001 and 8002 at `/docs`.

## Local development

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
corepack pnpm --dir frontend install
```

Start four terminals:

```powershell
python -m uvicorn services.invoice_risk.app:app --port 8001
python -m uvicorn services.capital_market.app:app --port 8002
$env:PRATIN_INTEGRATION_MODE="required"; python -m uvicorn backend.app.main:app --port 8000
corepack pnpm --dir frontend dev
```

For a completely offline, deterministic presentation set `PRATIN_INTEGRATION_MODE=fixture`. `auto` prefers services and visibly reports `DEGRADED_FIXTURE` when it falls back.

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/opportunities` | Admit an invoice and supplier mandate |
| `POST` | `/api/opportunities/{id}/run-market` | Verify, assess risk, discover, offer and match |
| `POST` | `/api/opportunities/{id}/accept/{offer_id}` | Idempotent simulated settlement |
| `GET` | `/api/opportunities` | Durable opportunity history |
| `GET` | `/api/providers` | Current liquidity and portfolio exposure |
| `GET` | `/api/settlements` | Simulated settlement ledger |
| `GET` | `/api/audit` | Explainable event trail |
| `GET` | `/api/platform/metrics` | Data-derived marketplace metrics |
| `POST` | `/api/demo/reset` | Restore deterministic synthetic state |

## Matching policy

Offers first fail hard constraints: financing floor, settlement ceiling, supplier cost ceiling, risk appetite, liquidity, ticket size and portfolio concentration. Eligible offers are scored using configurable prototype weights: capital 30%, total effective cost 23%, settlement speed 20%, tenor 10%, provider risk-adjusted return 9% and remaining liquidity 8%. Each component is returned to the UI with its value, weight and explanation. These are demonstration policy parameters, not a production credit model.

## Verification

```powershell
python -m pytest -q
corepack pnpm --dir frontend test
corepack pnpm --dir frontend run build
```

Current baseline: **9 Python tests**, **1 frontend test**, and the production build pass. Coverage includes uncertainty, provider differentiation, risk appetite, insufficient liquidity, deterministic ranking, “lowest rate loses,” complete settlement, idempotency, liquidity mutation and audit creation.

With all three Python services running in `required` mode, `python -m backend.app.integration_check` verifies the live HTTP path and asserts that the second invoice moves to a different provider.

## Repository map

```text
backend/                 Core API, integration clients, matching, SQLite
contracts/               Strict shared Pydantic contracts
services/invoice_risk/   Pratham-owned verification and risk agent
services/capital_market/ Nitin-owned provider agents and offer generation
frontend/                Pratyush-owned React market cockpit
docs/                    Architecture, integration, demo, team and judge pack
.github/workflows/       Deterministic CI
docker-compose.yml       Health-checked four-service stack
```

## Built vs future

**Built:** synthetic rule verification; uncertainty; deterministic risk; differentiated provider agents; two-sided constraints; total effective cost; explainable ranking; SQLite persistence; simulated settlement; audit; reallocation; fixture/auto/required modes; responsive market UI; tests; Docker; CI.

**Future production work:** GST/e-invoice and KYC/KYB integrations, bureau/open-banking data, bank/NBFC APIs, PostgreSQL, event streaming, OIDC/RBAC, encryption and key management, fraud detection, digital signatures, regulated settlement rails, model governance, fairness monitoring, privacy controls and production-calibrated policies.

PRATIN is named for Pratyush, Pratham and Nitin. See [the team guide](docs/team-start-here.md) and [the 2–3 minute demo](docs/demo-script.md).
