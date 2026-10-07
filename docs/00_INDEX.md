# Documentation Guide

This directory is the working knowledge base for Cultural Currency Converter.

It is intentionally small. Documentation should help a developer or AI understand **why the product exists, what matters, how the current system is shaped, and what to check before changing it**. It should not duplicate the code or freeze past implementation decisions.

## Read this first

For most non-trivial work, use this order:

1. [AI development guide](AI_DEVELOPMENT_GUIDE.md)
2. [Product](01_PRODUCT_SPEC.md)
3. the document closest to the change:
   - [UX](02_UX_RESEARCH_AND_FLOWS.md)
   - [Design](03_UI_DESIGN_SYSTEM.md)
   - [Architecture](04_ARCHITECTURE.md)
   - [Domain model](05_DOMAIN_MODEL.md)
   - [Integrations, AI and media](INTEGRATIONS_AI_MEDIA.md)
   - [Country media production system](media/00_COUNTRY_MEDIA_SYSTEM.md)
   - [Quality, security and accessibility](07_QUALITY_SECURITY_ACCESSIBILITY.md)
   - [Public API v1](API_V1.md) when changing native/server-to-server transport contracts
4. [Roadmap](08_IMPLEMENTATION_ROADMAP.md) when planning what to do next
5. [Production 100/100 execution plan](PRODUCTION_100_EXECUTION_PLAN.md) when executing the production-readiness PR sequence
6. [Release runbook](RELEASE_RUNBOOK.md) when cutting, deploying, recovering or responding to an incident
7. [Release certification scorecard](RELEASE_CERTIFICATION.md) when recording final repository/deployment evidence
8. [Decision log](09_ADR_LOG.md) when changing a durable architectural choice
9. [References](10_REFERENCES.md) when external evidence is needed

## Source-of-truth hierarchy

When information conflicts, do not blindly follow the oldest or most detailed document.

Use this order:

1. the current task and explicit product intent;
2. executable behaviour in code, migrations, tests and CI;
3. the canonical documents listed above;
4. active decisions in the ADR log;
5. roadmap ideas;
6. external references and historical context.

A mismatch between code and docs is a signal to investigate. Fix the mismatch in the same change when practical.

## What deserves a strong rule

Use strong language only for constraints where being flexible can cause real harm or semantic corruption, for example:

- financial correctness and Decimal/rounding semantics;
- security and secret handling;
- privacy and ownership;
- accessibility requirements;
- source/provenance integrity;
- destructive data changes;
- explicit user consent;
- invariants enforced by schema, tests or CI.

For ordinary architecture, UI, dependency and workflow choices, prefer language such as:

- “currently”;
- “prefer”;
- “default”;
- “usually”;
- “unless there is a measured reason to change”.

The project is expected to improve. A documented preference is not a reason to preserve a worse design.

## Documentation maintenance rules

Keep documentation close to stable knowledge.

Good documentation explains:

- product goals and non-goals;
- important user flows;
- domain meaning and invariants;
- architectural boundaries;
- external trust boundaries;
- test/quality expectations;
- reasons behind durable decisions;
- active next steps.

Avoid documenting:

- every PR that has already merged;
- exact implementation details already obvious in code;
- large catalogs of hypothetical scenarios;
- repeated copies of the same UX rule;
- dependency versions already pinned in config files;
- exact pixel values unless the value is itself a product/accessibility requirement;
- “locked forever” technology choices.

When a new topic fits an existing canonical document, update that document instead of creating another file.

## Stable product priorities

When trade-offs conflict, generally prefer:

1. correctness and trust;
2. the primary conversion task;
3. privacy, accessibility and recoverability;
4. clarity and maintainability;
5. useful destination/cultural context;
6. performance;
7. decorative novelty.

These are priorities, not a prohibition on experimentation.

## Product boundary

This is an informational travel-money product, not a trading, banking, remittance or financial-advice platform.

The UI should avoid implying:

- executable or guaranteed FX rates;
- exact card/ATM/merchant fees without authoritative data;
- universal prices for an entire country;
- current facts as historical facts;
- cultural or historical claims without adequate provenance.

## Keep the handbook healthy

A documentation refactor is successful when a capable developer or AI can answer these questions quickly:

- What user problem are we solving?
- What behaviour exists today?
- Where should this logic live?
- Which invariants are actually important?
- Which tests prove the change?
- Is an old decision still justified?
- What should be updated if the implementation changes?
