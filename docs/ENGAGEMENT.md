# Engagement plan: FOIA intake assistant

A worked example of taking one agency use case from workshop to production with a systems integrator. The agency, its people and its numbers are fictional.

## Stakeholders

| Who | Cares about | What they get from us |
|---|---|---|
| Chief FOIA Officer (sponsor) | Backlog, statutory deadlines, litigation risk | Monthly read-out on cycle time and quality |
| FOIA analysts (users) | Fewer manual searches; not being blamed for model mistakes | Every flag explained; they make every decision |
| Office of General Counsel | Exemption decisions stay defensible | Pre-screen is "candidate" only; full audit trail |
| CISO / authorizing official | Data boundaries, ATO scope | Endpoint authorization enforced in code; audit to SIEM |
| CAIO / AI governance board | Agency AI policy, inventory, impact assessment | Use-case documentation; human-decision points named |
| Systems integrator | A clear build target and acceptance tests | This repo, eval gates in CI, connector spec |

## Phases

| Phase | Weeks | Output | Exit criteria |
|---|---|---|---|
| Discovery | 1–2 | Use-case backlog (`docs/BACKLOG.md`), baseline metrics | Sponsor picks Phase 1 use cases |
| Prototype | 3–5 | This repo running on sanitized data; eval set v1 | Gates pass offline; analysts have tried it |
| Security & governance | 4–8 (parallel) | Data-flow diagram, endpoint authorization, AI use-case record | CISO and governance board sign-off for pilot |
| Pilot with SI | 9–16 | Connector to records system, SSO, 6 analysts on live intake | Cycle-time and quality targets (below) |
| Scale | 17+ | SI owns operations; agency owns eval set | Handoff checklist in `DEPLOYMENT.md` complete |

## Pilot success measures

| Measure | Baseline | Target |
|---|---|---|
| Time from receipt to acknowledgment | 6 business days | 1 business day |
| Analyst time to first search | 2.5 hours (complex track) | 45 minutes |
| Responsive records missed at first search (QA sample) | Measured in pilot week 1 | No worse than baseline |
| Unflagged SSNs / DOBs in released records | 0 | 0 |
| Restricted content sent to an unauthorized endpoint | — | 0 (blocking control, audited) |

## Working with the systems integrator

- Agree on interfaces early: the `Document` dataclass and `endpoints.json` are the contract. The SI builds the connector and identity integration; we own the model-facing logic and the evals until handoff.
- The eval suite runs in the SI's CI from week 9. A failing gate blocks their deploys the same way it blocks ours.
- Weekly joint stand-up with the agency's technical lead; issues that need a product change go into the feedback log, not into custom code.
