# Release checklist

- [ ] No real customer data, credentials or fund movement.
- [ ] `.env.example` matches runtime configuration.
- [ ] Python tests, frontend tests and production build pass.
- [ ] Required-mode services are healthy on 8000/8001/8002.
- [ ] Core health and cockpit show `SUPABASE POSTGRES`; no database secret reaches the frontend.
- [ ] Supabase migration `20260828091405_create_pratin_marketplace` is applied and advisors reviewed.
- [ ] Docker Compose starts from a clean checkout.
- [ ] Flagship invoice verifies and produces multiple distinct responses.
- [ ] Astra’s lowest-rate offer fails visible hard constraints.
- [ ] VegaFlow is recommended with factor-level reasons.
- [ ] Duplicate acceptance returns the original settlement and no second capital mutation occurs.
- [ ] Liquidity/exposure, metrics, settlement history and audit update.
- [ ] Second scenario recommends a different provider after changed liquidity.
- [ ] Fixture/degraded provenance is visible and never described as live service output.
- [ ] Mobile and 1366×768 layouts remain usable.
- [ ] README links, API docs and two-minute script are current.
- [ ] Collaborator branches pass CI and merge through reviewed PRs.
