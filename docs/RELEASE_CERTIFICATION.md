# Release Certification Scorecard

This document records what can be demonstrated for the current web product and what still requires deployment-specific evidence.

The functional roadmap is complete: the current product includes all 36 scoped roadmap items, including signed trusted Budget and Destination Comparison AI. Final certification is therefore a **release-evidence exercise**, not a feature-development phase.

## Candidate baseline

- Feature-complete master before this certification pass: `495ce394d6fa31148d173039859c699fd2892cae`.
- Latest fully green certification-branch evidence before this scorecard update: `71b54988da10fe163a9f90413d95ead1ecc90e28`.
- Repository issue snapshot checked on **2026-10-03**: **0 open issues, 0 open P0, 0 open P1**.
- Repository hygiene snapshot checked on **2026-10-03**: **0 TODO and 0 FIXME code-search hits**.
- Final P0/P1 query must be repeated immediately before the deployed release cut.

Green evidence from a commit other than the final candidate SHA is background evidence only. The final release SHA belongs in the deployment/release evidence record after the certification PR is merged; committing a self-referential SHA here would create a different SHA.

### Repository CI evidence for `71b54988...`

- Required merge quality: run `37096108372` — success, including Python 3.13 required, PostgreSQL 18.6 required, Frontend required and Chromium required.
- Python quality: run `37096108424` — success on Python 3.13, Python 3.14 and PostgreSQL 18.6 / Python 3.13.
- Browser quality: run `37096108390` — success on Chromium full, Firefox smoke and WebKit smoke.
- Frontend quality: run `37096108364` — success.
- Converter primitive preview: run `37096108434` — success.
- Quiet Atlas shell preview: run `37096108375` — success.

The certification PR must rerun the applicable gates on its exact final head, and post-merge `master` must be verified again.

## Repository-side scorecard

| Category | Repository evidence | Status |
| --- | --- | --- |
| Financial correctness | Decimal domain contracts, canonical FX/conversion paths, budget/comparison invariants, Python/PostgreSQL suites | Candidate evidence available |
| Trust / provenance | effective-date/provider semantics, reviewed destination context, explicit city/national fallback, media/data provenance | Candidate evidence available |
| Reliability | provider-failure tests, deterministic fallback, shared-cache semantics, browser interaction recovery | Candidate evidence available |
| Security | signed tokens, owner scoping, CSRF/CSP/deploy checks, upload normalization, dependency audit | Candidate evidence available |
| Accessibility | axe, keyboard, focus, reflow, reduced-motion, forced-colors, touch-target/browser checks | Candidate evidence available |
| Core UX | full Chromium flows plus Firefox/WebKit smoke; canonical re-entry/re-check semantics | Candidate evidence available |
| City/context quality | canonical city contract, freshness/provenance checks and coverage reporting | Candidate evidence available |
| AI boundaries | conversion/Explore/Budget/Comparison grounded packets, strict validation, deterministic fallback, no financial recalculation | Candidate evidence available |
| Camera privacy boundary | real browser upload through sanitizer, signed candidate confirmation and separate spend handoff using a test-only extractor | Candidate evidence available |
| Offline semantics | server tests plus browser download/open/self-contained HTML and stored-not-live assertions | Candidate evidence available |
| Performance | deterministic bundle/request/query/layout budgets | Candidate evidence available |
| Database recovery | executable PostgreSQL backup → fresh restore → verification CI drill | Candidate evidence available |
| Documentation | canonical architecture/quality/integration docs plus release runbook | Candidate evidence available |

## Deployment-side evidence still required

The following cannot be honestly certified from repository CI alone:

| Evidence | Why it is deployment-specific | Required proof |
| --- | --- | --- |
| Production backup schedule/retention | CI creates an isolated test backup, not the operator's real schedule | backup policy plus a current recoverable backup |
| Measured RPO/RTO | depends on real backup age, database size, infrastructure and cutover | timed recovery drill |
| Managed-media object recovery | CI validates application media contracts but not the production bucket's retained object versions | versioning/retention evidence + restore of a known object/version |
| RC infrastructure smoke | depends on deployed networking, TLS/proxy, database/cache/object store and provider configuration | execute the release runbook against the RC |
| Real provider reachability | CI intentionally avoids depending on public/live providers for deterministic acceptance | bounded RC/provider smoke without changing deterministic truth semantics |

Until those items are recorded, the correct release state is:

> **Repository-side release candidate ready; final production 100/100 certification pending deployed operational evidence.**

## Final RC smoke contract

The deployed release candidate must complete:

```text
Convert → Context → Budget → Save → Reopen → Re-check
→ Camera → Confirm → Spend → Offline Pack → Explore → Compare
```

The smoke is invalid if it bypasses canonical paths, relies on hidden administrative writes, or treats cached/saved values as automatically current.

## Zero-P1 gate

Immediately before release:

1. query open GitHub issues;
2. confirm open `P0` count is zero;
3. confirm open `P1` count is zero;
4. inspect any unlabeled open defect for severity before treating the gate as passed;
5. record the query time and release SHA in release evidence.

An empty tracker is evidence only for tracked known defects, not proof that defects cannot exist.

## Certification rule

Call the current web scope **100/100 certified** only when:

- every applicable CI gate is green on the exact final release SHA;
- final P0/P1 counts are zero;
- the RC smoke succeeds;
- production database recovery evidence is current;
- managed-media recovery evidence is current when managed media is deployed;
- measured RPO/RTO claims, if published, come from an actual timed recovery drill;
- no release exception contradicts a financial, security, privacy, ownership or accessibility invariant.

Do not round a pending operational category up to 100.
