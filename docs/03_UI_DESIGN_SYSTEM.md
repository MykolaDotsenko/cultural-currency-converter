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

Historical surfaces should prefer authentic archival photography, documents, currency objects or museum/heritage material with provenance.

Do not use a photorealistic reconstruction as if it were archival evidence.

If an illustration or generated reconstruction is ever used for a non-factual supporting role, its status should be clear and it should not compete visually with authentic evidence.

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

## Responsive design

Prefer flexible layout rules over fixed replicas.

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

The project keeps Inter as the self-hosted UI/display typeface for now. Premium hierarchy comes from scale, weight, spacing and composition rather than an unbundled external font dependency.

The free-tier Gemini runtime explanation remains part of the product. Premium visual direction does not imply paid AI infrastructure.
