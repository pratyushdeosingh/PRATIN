# Judging Q&A

**Why is this not a loan comparison site?** Provider participation and terms depend on mutable risk, liquidity and portfolio state. Supplier hard constraints are enforced, settlement changes the market, and the next allocation differs.

**Why agents? Where is AI?** Each provider is an autonomous software actor with state, goals, constraints and actions. The MVP uses transparent deterministic policy because regulated decisions should not depend on an opaque LLM. A future copilot may narrate structured reasons, never decide eligibility.

**Why does the lowest rate lose?** A rate is useless if the advance misses the liquidity floor or settles too late. PRATIN gates those requirements before ranking total cost, amount, speed, tenor and provider-side objectives.

**How is risk handled?** Explainable rule factors cover buyer reliability, repayment history, supplier history, defaults, invoice scale and verification uncertainty. Providers apply their own appetite.

**Are invoices really verified?** No production verification is claimed. The MVP exposes a synthetic verification abstraction and distinguishes verified, partially verified, uncertain and rejected states. Production would integrate GST/e-invoice, PO/GRN, KYC/KYB, banking and fraud systems.

**How do providers differ?** Their liquidity, risk appetite, required return, ticket size, sector preference, speed, advance, fee and concentration constraints differ. Tests prevent renamed-identical providers.

**How are inappropriate opportunities hidden?** Provider agents decline when verification, risk appetite, liquidity, ticket size or concentration fails. Reasons are returned and audited.

**How does portfolio concentration work?** Current exposure divided by portfolio capacity is checked against each provider’s ceiling before an offer.

**What changes after settlement?** Provider liquidity decreases, exposure rises, a settlement and audit event persist, and subsequent agent decisions consume the updated snapshot.

**Where does durable state live?** The primary deployment configuration uses a private Supabase Postgres schema. Opportunity and provider rows are locked during acceptance, and provider state, settlement, opportunity status and audit event commit atomically. SQLite is retained only for explicitly labelled offline demos and tests.

**How is matching fair and auditable?** Hard gates run first. Versioned weights and per-factor values are returned. Stable inputs produce stable results. Production would add governed policy configuration, adverse-action review, fairness testing and immutable audit retention.

**What is simulated?** Verification, risk inputs, providers, offers and settlement rails. The allocation logic, persistence, integration boundaries, constraint enforcement and state mutation are implemented.

**How would banks integrate?** Adapters would map partner APIs/events into the shared contracts, with signed webhooks, mTLS/OAuth, idempotency keys, reconciliation, SLAs and human exception workflows.

**How would it scale?** The implemented Supabase Postgres store replaces the demo-only SQLite store when that backend is configured. Next steps are durable workflow/event processing, tenant partitioning, reference-policy caching, observability and idempotent asynchronous provider fan-out.
