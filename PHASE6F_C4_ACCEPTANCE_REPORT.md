# Phase 6F-C4 Integrated Acceptance Report

Date: 2026-11-13

Branch: `feat/phase-6f-c4-integrated-acceptance`

## Verdict

**Integrated C1-C3 functionality: PASS.** The authenticated Neura-to-TKP path, approved
evidence retrieval, grounded generation, multi-turn context, citation reconstruction, append-only
audit, persistence, request replay, and SSE delivery passed against both real FastAPI services and
separate disposable PostgreSQL databases.

**Staging security gate: FAIL.** Current locked frontend and backend dependencies contain
unresolved advisories in runtime-relevant packages. These findings pre-date C4 and were not changed
because C4 is an acceptance phase, but they must be remediated or formally risk-accepted before a
staging deployment.

**Recommendation: GO for Phase 6F-D development; NO-GO for staging deployment.** No C1-C3
trust-boundary defect was found. Phase 6F-D may proceed without weakening the staging security gate.

## Acceptance areas

| Area | Result | Actual coverage |
|---|---|---|
| Authenticated Neura -> TKP -> answer -> audit -> SSE | PASS | Real Neura and TKP FastAPI processes; separate live PostgreSQL containers; signed Neura JWT; real HTTP bridge and SSE transport. |
| Approved evidence and lineage | PASS | Seeded reviewed canonical knowledge and verified projections; checked projection, article, revision, revision-claim, candidate-claim and source-fragment lineage. |
| Grounding and citation validation | PASS | Prompt-injection request for fabricated `E999` returned only reconstructed `E1`; explicit fabricated-citation output failed closed before persistence or answer streaming. |
| Multi-turn and evidence freshness | PASS | Follow-up rewrote context, performed a new TKP retrieval, and cited a newly approved revision created between turns; topic switch and ambiguous new-session reference were exercised. |
| Isolation and authorization | PASS | Live unauthenticated request returned 401 and live cross-user session access returned 404; focused tests covered cross-session/workspace membership and forged client controls. |
| Audit, transactions, billing and replay | PASS | Live append-only database trigger rejected mutation; duplicate request UUID replay created no duplicate turn; cancellation plus retry produced exactly one audit and two messages. Unit fault injection covered audit-construction and commit rollback. |
| Fail-closed behavior | PASS | Live stopped TKP, controlled LLM exception, controlled LLM timeout and fabricated citation emitted sanitized error-only SSE and did not persist partial answers. Focused tests covered contradictory/unsupported evidence and malformed provider output. |
| Migrations | PASS | Fresh upgrade, downgrade/re-upgrade, and upgrade of a database containing an existing session and two history messages passed on disposable PostgreSQL. |
| Frontend parser and citations | PASS (component/protocol) | Five Jest tests covered strict SSE ordering/malformed input and citation rendering/inspection; production build compiled. |
| Responsive/live-browser UI | PARTIAL | Responsive citation markup and production CSS were built, but no real mobile/desktop browser was driven against the live services in C4. |
| Live external LLM provider | NOT RUN | A deterministic provider double was used intentionally. Provider errors, timeout and cancellation were simulated through the real Neura service boundary. |
| Dependency security | FAIL for staging | Frontend and backend advisory audits found unresolved inherited dependency risk; details below. |

## Executed tests and checks

- Live integrated acceptance: **1 passed** in 43.56 s.
- Live PostgreSQL migration acceptance: **1 passed** in 36.34 s.
- Full Neura backend regression: **61 passed** in 9.08 s.
- Focused C1-C3 security/trust suite: **47 passed** in 8.29 s (subset of the 61).
- Frontend: **2 suites, 5 tests passed** in 38.21 s.
- Frontend production build: **PASS**.
- Focused Ruff: **PASS**; formatting: **16 files PASS**; mypy: **8 source files PASS**.
- `git diff --check`: **PASS**.

The live C4 test used TKP application services to create reviewed canonical knowledge and verified
projections, then started TKP and Neura as real HTTP services. Only answer/context model calls were
replaced with deterministic test doubles. No live commercial model call was made.

## Security and reliability findings

- Unconfirmed TKP projections were excluded from authoritative evidence. Runtime citations were
  reconstructed from the authenticated TKP response rather than accepted from model text or chat
  history.
- A historical fabricated citation did not survive the follow-up: the new turn retrieved fresh
  evidence and cited the newly approved revision.
- Answer text was released only after generation, entailment validation, citation validation and
  transactional persistence. Failure cases emitted no provisional factual answer chunks.
- Request UUID replay, cancellation and retry did not duplicate billing-counted user messages or
  evidence audits.
- Direct application endpoints expose no audit mutation operation, and PostgreSQL rejected a direct
  update through the append-only trigger.
- No product defect was found or fixed. C4 added only an opt-in acceptance test and this report.

## Performance observations

On the local disposable environment with the deterministic LLM double:

- time to first validated SSE answer event: **0.2876 s**;
- time to SSE completion: **0.2890 s**;
- sum of TKP-reported backend latency for that request: **97.96 ms**.

These are single local observations, not production targets. They exclude external-provider latency
and should not be used as capacity or percentile claims.

## Dependency audit and staging blockers

Frontend `npm audit` reported **41** advisories: 13 high, 12 moderate and 16 low, with no critical.
`npm audit --omit=dev` still reported **39** (13 high, 10 moderate, 16 low) because the legacy CRA
build chain is declared in runtime dependencies. High findings concentrate in the CRA/SVGO/PostCSS/
webpack chain; direct `react-router-dom` and `react-scripts` also require major/toolchain remediation.

Backend `pip-audit` over the installed environment reported **265 unique advisories across 41 of
150 packages**. Runtime-relevant affected packages include `authlib`, `python-jose`, `cryptography`,
`starlette`, `python-multipart`, `requests`, `urllib3`, `aiohttp`, `pypdf`, `PyPDF2`, Pillow and
LangChain components. `python-jose` had an advisory with no fix version reported by the audit.

Before staging:

1. triage and upgrade the authentication, framework, HTTP and crypto packages;
2. update or remove vulnerable document/upload parser dependencies;
3. migrate or explicitly isolate/risk-accept the CRA build chain and update React Router;
4. rerun both audits and document any justified exceptions;
5. run a live-provider validation and a real-browser desktop/mobile end-to-end pass.

## Changed files

- `backend/tests/test_phase6fc4_live_acceptance.py`
- `PHASE6F_C4_ACCEPTANCE_REPORT.md`

TKP source was not modified. No commit, push, merge, branch deletion or deployment was performed.
