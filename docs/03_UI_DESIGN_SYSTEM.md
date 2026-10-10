# Design System

## Design direction

The visual language is **Quiet Atlas Premium**: calm financial trust combined with high-end editorial travel photography.

The product should feel closer to a premium travel magazine and modern financial service than to an illustrated travel app.

## Premium visual principles

Prefer:

- quiet neutral surfaces and restrained country accents;
- strong typography and deliberate whitespace;
- one obvious primary action;
- realistic, editorial photography with natural light and believable local detail;
- consistent colour treatment across destinations;
- imagery with enough negative space to coexist with product UI;
- subtle depth, borders and materials rather than heavy effects.

Avoid:

- cartoon or flat country illustrations;
- decorative country SVG scenes;
- generic tourist-postcard imagery;
- oversaturated stock photography;
- staged handshake/credit-card stock clichés;
- stereotypical visual shorthand for a country;
- dense dashboards, excessive glass effects and visual noise.

## Country atmosphere

Country identity comes primarily from:

1. typography and country/currency naming;
2. subtle colour/surface atmosphere;
3. curated realistic photography when a suitable published asset exists.

The converter should remain elegant without an image. Missing media is preferable to weak media.

For country hero/teaser roles, production selection uses reviewed contemporary photography rather than illustration fallbacks.

## Country theme profiles

A country may define a restrained theme profile so source and destination can feel culturally distinct without becoming separate visual systems.

A theme profile may include:

- restrained accent/surface palette;
- atmosphere/mood words;
- approved editorial image cues and roles;
- one short optional cultural micro-line;
- material/architecture/transit/everyday-life cues;
- prohibited clichés or stereotypes;
- motion tone for state transitions.

Theme profiles must not prescribe flags, famous people, brands, landmarks or decorative motifs as mandatory identity shortcuts. Real reviewed photography, typography and material atmosphere remain preferred.

The bilateral workspace may show two different country atmospheres at once, but both sides must still feel like one **Quiet Atlas Premium** product.

The first curated country-theme release is now represented by explicit presentation profiles for the 30 countries in the country-media index. Each profile owns a stable theme key, restrained palette, documented atmosphere, motion tone and editorial cues. Countries outside that curated set keep a deterministic generic Atlas atmosphere rather than receiving invented country-specific styling. Theme profiles are presentation-only: they never establish payment behaviour, cultural facts, prices or financial meaning.

## Photography art direction

Target a consistent editorial look:

- realistic contemporary scenes;
- natural or cinematic available light;
- restrained saturation;
- sophisticated warm-neutral grading;
- real streets, cafés, transit, markets, architecture and everyday payment moments;
- people may appear naturally, but avoid posed advertising imagery;
- composition should feel observed rather than staged;
- when managed media is cropped, use reviewed focal-point metadata so the important subject survives responsive aspect ratios.

A photo should communicate place or everyday value without becoming a tourism cliché.

## Historical imagery

Historical surfaces should prefer authentic archival photography, documents, currency objects or museum/heritage material with provenance. Story-chapter and timeline evidence are date-scoped and may show a concise human-readable temporal-match label such as exact-date, year-level or reviewed-period match.

Do not use a photorealistic reconstruction as if it were archival evidence. AI-generated media is not eligible for historical-evidence roles.

If an illustration or generated reconstruction is ever used for a non-factual supporting role, its status should be clear and it should not compete visually with authentic evidence.

Historical/editorial media should use progressive provenance rather than dense permanent metadata. The default caption may show attribution/licence and temporal scope; **Image provenance** may reveal creator, source/institution, rights statement, retrieval date, original media record, evidence class and temporal-match quality. Internal selector reason/fallback level remain implementation details and are not user-facing trust labels.

Explore may use reviewed `COUNTRY_TEASER` photography only on curated editorial cards where it strengthens place recognition without turning the page into a tourism gallery. Managed `SOCIAL_PREVIEW` media may populate OG/Twitter metadata downstream of canonical page data; it never creates a second content/calculation path.

## Image formats

Large editorial product imagery is managed raster media:

- JPEG for photographic masters where appropriate;
- WebP for optimized delivery/derivatives;
- PNG when lossless/alpha is genuinely useful.

SVG remains appropriate for interface icons and small vector UI marks. It is not the country/editorial photography format.

## Components

The current UI uses reusable Django templates/partials plus CSS and focused TypeScript.

Important component families include:

- amount/input fields;
- country/currency picker;
- swap action;
- conversion result/provenance;
- historical controls/chart;
- contextual content;
- managed media/image frame;
- saved/recent state;
- account surfaces.

Prefer simplifying an existing pattern before adding another component abstraction.

## Information hierarchy

For conversion surfaces, visual emphasis generally follows:

1. task/amount/result;
2. selected source and destination;
3. trust/provenance/date;
4. practical interpretation;
5. exploration/save utilities;
6. photography.

Photography should elevate the experience without overpowering the financial task.

## Motion

Motion should clarify state change, not decorate routine interaction.

Respect reduced-motion preferences and avoid animation that delays access to information.

Historical Series is the reference implementation: chronology, Then & Now, summary facts and the data table are complete without animation. Its line chart may use one short 220 ms draw transition only when the operating system does not request reduced motion; `prefers-reduced-motion: reduce` disables that animation. Never use motion to imply causality, purchasing power, exchange timing or financial significance.

Signature motion may include:

- restrained country-atmosphere crossfades;
- source/destination swap transitions;
- monetary result transitions;
- contextual-card reveals;
- cultural/history surface reveals;
- short save/re-check feedback.

Motion should explain a state change, not decorate a static screen.

## Responsive design

Prefer flexible layout rules over fixed replicas.

Use the shared `--qa-space-*` scale for repeated structural spacing. Add a token when a spacing value is intentionally reused across product surfaces; keep one-off optical adjustments local and documented by context. Frontend quality checks reject references to undefined CSS custom properties.

Components should survive:

- narrow screens;
- large text and 200% zoom/reflow;
- long country/currency names;
- different browser/font metrics;
- missing imagery.

## Accessibility visual baseline

Maintain:

- readable contrast;
- visible keyboard focus;
- non-colour state cues;
- sufficient interactive target area;
- text that wraps without hiding functionality;
- core layouts without horizontal scrolling at narrow reflow widths;
- meaningful alt text for informative photography.

## Evolving the design system

This is a visual direction, not a frozen mood board.

New patterns may replace existing ones when they improve comprehension, accessibility, consistency or perceived product quality. Keep the premium, trustworthy and culturally authentic character coherent across those changes.


## Premium composition rules

The premium pass intentionally reduces visible UI chrome.

Prefer:

- one strong surface over nested card stacks;
- typographic separation before borders;
- hairline dividers before boxed containers;
- restrained radii rather than pill-shaped controls;
- a large monetary result as a primary visual moment;
- source/destination as one bilateral instrument rather than two independent cards;
- contextual sections that read like an editorial spread rather than a dashboard.

The project uses a platform-native sans stack so first-paint metrics stay stable and no runtime webfont activation can move navigation or financial UI. Premium hierarchy comes from scale, weight, spacing and composition rather than a downloaded typeface.

The free-tier Gemini runtime explanation remains part of the product. Premium visual direction does not imply paid AI infrastructure.


## Product state grammar

Optional or incomplete product surfaces use one semantic state grammar rather than ad-hoc alert cards.

The supported presentation states are:

- **empty** — no reviewed evidence exists yet;
- **partial** — some independent results are valid while another part failed or is absent;
- **unavailable** — the optional subsystem cannot currently resolve;
- **stale** — stored evidence is still being shown with explicit stale semantics;
- **not applicable** — the surrounding workflow is complete without that subsystem.

Every state must be named in text, not colour alone. The state panel must explain what remains valid and must not imply that missing financial/context data was inferred. Financial stale state can stay in the dedicated provenance/status-badge system when a conversion result exists; the product-state panel is for surrounding optional surfaces, not a second FX freshness contract.

## Global navigation contract

Every full-page Quiet Atlas surface uses the same server-rendered primary navigation:
**Convert, Plan, Compare, Explore, Saved**. The Cultural Currency wordmark links to
the canonical converter. Account sign-in/profile/sign-out actions remain independent
of the primary navigation. A page may add a genuinely contextual action (for example,
**Back to trip** from Camera), but it must not reproduce primary navigation links.

On compact screens the same links wrap into rows rather than a horizontally scrolling
menu. The active top-level route has a text-and-border indicator with
`aria-current="page"`; it is never indicated by colour alone. All links work
without JavaScript.

## Mobile navigation and active-trip shortcuts

At narrow widths the same five primary destinations occupy one compact row,
with keyboard order independent from layout. At 320px the links may wrap their
text rather than overflow or hide destinations. For authenticated people,
account actions may occupy a separate line when they cannot share the header
safely. Each target remains at least 44px high.

Only an authenticated owner with a saved **active** date window, or a
**started-without-end** trip, sees the contextual mobile quick-action rail on
the clean converter home and saved budget-trip detail. The rail reuses canonical
Convert, Camera (only when enabled), saved Budget and Trip routes; it performs
no automatic FX query, scan, spend write or notification. No rail appears for
anonymous, upcoming, ended or unscheduled journeys. The desktop trip
continuity UI remains unchanged.
