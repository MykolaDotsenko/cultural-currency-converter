# Integrations, AI and Media

This document describes the main external trust boundaries. Exact provider versions, endpoints and configuration live in code and environment settings.

## Integration principle

External data should enter the product through a small project-owned boundary:

```text
external response
→ transport/validation
→ normalized project-owned value
→ application/domain use
```

Do not spread provider-specific payload shapes through views, templates or domain models.

## Runtime FX

Frankfurter is the current runtime FX provider.

The exchange layer owns bounded timeout/retry behaviour, normalization, attribution, requested/effective-date semantics, historical coverage and cache/stale behaviour.

A successful HTTP response is not sufficient; validate semantic payloads before use or caching.

## Country/currency metadata

REST Countries is currently an import/reference source rather than a normal page-request dependency.

The adapter treats provider data as untrusted input: request timeouts must be positive, each response page is capped at 2 MiB before JSON parsing, malformed JSON/shape/pagination failures are normalized to a project-owned source error, and ISO/currency identifiers must satisfy canonical ASCII alphabetic shapes before entering normalized snapshots.

Normalize country/currency data locally so the product can preserve stable identity, temporal relationships and controlled reconciliation during upstream changes.

## Editorial/cultural sources

Curated cultural, payment, typical-price and story content should keep enough provenance to explain source, observation/verification time, scope and confidence.

Wikidata and similar services are candidate/research sources rather than automatic runtime truth.

## Premium photography strategy

The product uses **managed realistic photography**, not release-owned cartoon country illustrations.

Preferred hierarchy:

```text
high-quality owned/licensed contemporary photo
→ high-quality sourced editorial photo
→ authentic archival/heritage media for historical surfaces
→ no image
```

“No image” is an intentional valid state. Do not fill a premium layout with weak stock, cartoon fallback art or synthetic-looking placeholders merely to occupy a media slot.

Country hero and country teaser selection is restricted to reviewed, non-generated `contemporary_photo` assets.

Destination supporting roles are explicit managed-media roles:

- `everyday_value` — atmosphere paired with reviewed price observations;
- `payment_culture` — atmosphere paired with reviewed payment guidance;
- `local_detail` — supporting editorial detail shown only when the destination has reviewed context.

For these supporting roles, reviewed sourced media is preferred. Explicitly labelled generated editorial imagery may be used as atmosphere when it passes the normal review/publication gate, but it is never evidence for a price, payment claim or local custom. The sourced text/data provenance remains authoritative.

## Media pipeline

Managed external media can come from sources such as Wikimedia Commons, Europeana, institutions or manually curated licensed/owned photography.

Prefer:

```text
candidate/source
→ rights + provenance review
→ safe managed raster copy
→ normalization/derivatives
→ editorial approval
→ publish
→ local runtime selection
```

Normal page requests should not search the web or call an image-generation service.

For a small number of editorially selected production assets, the project can use a curated manifest plus an explicit operator command. The command may download from a narrow allowlisted source, but it remains outside normal request handling and never auto-approves or auto-publishes the result.

Curated manifests carry explicit semantic scope rather than relying on filenames or implied geography:

- current destination media can be country-scoped and currency-neutral;
- historical comparison media is countryless, explicitly currency-scoped and temporally scoped;
- `comparison_then` manifests must use sourced historical-evidence media, never generated imagery;
- country/currency reference data is resolved before any download begins, so an unknown scope fails without network I/O.

Finland is the first production vertical slice. Its selected hero source is a 24 May 2026 Helsinki tram photograph by JIP from Wikimedia Commons, available under CC BY-SA 4.0. The source is 4608×3456 and fits under the managed-media byte cap. Ingestion validates the host, media type, response size, redirect target and expected dimensions before the existing sanitizer stores a managed copy.

Operator flow:

```bash
python manage.py ingest_curated_media --slug finland-helsinki-tram-2026 --dry-run
python manage.py ingest_curated_media --slug finland-helsinki-tram-2026
```

Then:

1. review source metadata, composition, rights and managed bytes in admin;
2. approve the high-resolution managed source;
3. create reviewed-width candidates explicitly, for example `python manage.py build_media_derivative --asset-id <source-id> --width 640 --width 1200 --width 1600`;
4. review each derivative and publish the appropriate responsive widths, not the high-resolution source;
5. verify the Finland destination context in browser QA.

The runtime selector remains local/database-backed. If no reviewed published derivative exists, the product intentionally renders no destination hero.

## File formats

Managed media validation accepts JPEG, PNG and WebP and rejects SVG ingestion.

For photographic delivery:

- retain a high-quality managed source;
- generate appropriately sized derivatives;
- preserve reviewed focal-point metadata when derivatives are created;
- publish multiple reviewed widths when a surface should use responsive delivery; presentation builds `srcset` only from published assets in the same derivative family, while the template supplies the layout `sizes` hint;
- prefer modern compressed delivery such as WebP where supported by the current pipeline;
- preserve intrinsic dimensions and focal/composition information.

SVG remains suitable for interface icons and small vector marks; it is not used as large editorial country imagery.

## Media quality bar

Before publishing a destination image, check:

- realistic and contemporary when used as current country atmosphere;
- strong composition and sufficient resolution;
- natural, premium editorial treatment;
- no obvious stock cliché or country stereotype;
- no misleading logos, text or manipulated factual cues;
- rights/provenance are sufficient;
- licence attribution is visible and links to the source/licence where available;
- managed normalization/resizing is disclosed when the licence requires change indication;
- useful alt text when the image carries meaning.

## Historical media

Historical surfaces use sourced archival photography, documents, currency objects and institutional/heritage imagery as evidence. Historical-evidence roles (`comparison_then` and `historical_timeline`) reject generated media at publication and selection time.

Then & Now can render optional `comparison_then` media beside the selected historical observation. That asset must be explicitly scoped to the quote currency and its temporal range must include the selected observation date; the product does not infer a country from a shared currency such as EUR. Curated ingestion preserves that same contract by allowing a blank country scope plus an explicit currency code and temporal metadata.

Historical candidate ingestion records that scope before the external search result becomes a review candidate. For example:

```bash
python manage.py ingest_media_candidates \
  --source wikimedia \
  --query "Tokyo 1998 street" \
  --role comparison_then \
  --kind archival_photo \
  --currency JPY \
  --valid-from 1998-01-01 \
  --valid-to 1998-12-31 \
  --date-precision year \
  --dry-run
```

Remove `--dry-run` only after reviewing the query/source intent. Historical-evidence roles require a non-generated archival/artwork/heritage/map kind plus explicit temporal precision and scope; `comparison_then` additionally requires currency scope. Invalid scope is rejected before external network search.

Temporal precision should be honest. A visually attractive but misleading historical image is worse than no image. Missing or malformed historical media is non-fatal and leaves the FX comparison intact.

## AI role

AI is optional synthesis, not a source of FX rates, historical observations or published factual truth.

Current runtime behaviour remains server-side, explicit, structured, validated and AI-independent for the core conversion path.

The configured provider/model is an implementation choice and may change after quality, latency, cost and reliability evaluation.

## Generated imagery

Runtime image generation is disabled.

Generated imagery may be used as an explicitly reviewed atmospheric/supporting asset when factual authenticity is not implied. The curated country generation workflow lives in `media/00_COUNTRY_MEDIA_SYSTEM.md`. Generated assets remain classified as synthetic in media metadata and must not masquerade as archival evidence, a source for prices, or proof of payment behaviour. Authentic sourced photography remains preferable where equivalent quality and rights are available.

## AI availability and cost

AI should remain:

- explicitly configurable;
- bounded by timeout/attempts;
- server-side with no browser-exposed key;
- absent from normal live-provider CI;
- gracefully degradable.

Validated runtime explanations are persisted as a reuse/cost optimization, not as a financial truth source. Operators can bound that table with:

```bash
python manage.py prune_runtime_explanation_cache --older-than-days <days> --dry-run
python manage.py prune_runtime_explanation_cache --older-than-days <days> --batch-size <rows>
```

The retention window is deliberately explicit rather than hard-coded into application behaviour. Pruning uses a fixed cutoff and bounded batches; deleting an old explanation only means a later request may generate it again or use the deterministic fallback.

## Security/privacy at external boundaries

Avoid sending unnecessary personal/user-owned data to external providers.

Never log credentials, bearer tokens or provider secrets.

Avoid holding database locks/transactions around external network calls unless there is a concrete transactional reason.

## Adding a new integration

Before adding one, answer:

- What user problem does it solve?
- Is runtime access necessary, or can data be imported/cached?
- What is the project-owned normalized contract?
- What happens when the provider fails or changes shape?
- What provenance/licensing constraints apply?
- What tests can run without live provider dependence?
- What data leaves our system?
