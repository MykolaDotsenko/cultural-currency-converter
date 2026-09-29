# Japan (JP) — Country Media Prompt Pack

Currency: `JPY`

Read [Country Media Production System](../00_COUNTRY_MEDIA_SYSTEM.md) before using these prompts. Every generation is assembled as:

`Global Premium Image Contract + role contract + country prompt body below`.

## Visual thesis

Urban precision with layered warmth: contemporary Japan should feel ordered, tactile, technologically fluent and culturally specific without collapsing into anime, neon overload or shrine clichés.

### Premium material palette

- dark timber and warm paper
- glazed ceramic
- brushed steel
- controlled rain reflections

### Premium mood keywords

- urban precision
- layered calm
- refined density
- quiet technological fluency

### Premium image goals

- premium first, authentic second, iconic only third;
- communicate the country through atmosphere, material, light, rhythm and everyday behaviour before relying on landmarks;
- make every image feel editorial and useful enough to sit inside an expensive real product, not a tourism campaign;
- preserve one clear visual story per frame and enough compositional calm for interface use where relevant.

### Preferred local cues

- Tokyo side streets, rail infrastructure, compact storefront rhythm and clean wayfinding
- wood, ceramic, brushed steel, paper texture and restrained signage
- kissaten/café, ramen/lunch-set, convenience or transit details used naturally
- evening city light with controlled red/amber/cool highlights
- IC-card/contactless and cash can coexist in atmosphere without making a factual claim

### Avoid

- anime/manga styling
- overwhelming Shibuya neon as the only Japan image
- torii, geisha, samurai, cherry blossoms and Mount Fuji stacked together
- fake Japanese text as a focal point

## Production hero source

The reviewed contemporary source selected for the first production P01 pass is separate from the generated prompt workflow.

- slug: `japan-tokyo-street-night-2019`
- role: `country_hero`
- kind: `contemporary_photo`
- country scope: `JP`
- city: Tokyo
- captured: 29 November 2019
- source: Wikimedia Commons, `Tokyo street at night, 2019 - 771.jpg`
- creator: Another Believer
- licence: CC BY-SA 4.0
- upstream raster: 4000 × 3000 JPEG
- runtime policy: ingest to managed media, review focal point/crop, create responsive derivatives, then explicitly approve/publish the reviewed derivative family

The source is a contemporary Tokyo street photograph rather than a generated country illustration. It has no runtime status merely because it appears in the curated manifest; ingestion remains `needs_review` until editorial approval.

## P01 — Hero Wide

**Target:** `static/images/country-media/jp/hero/jp-hero-v01.webp`

**Premium execution:** Use a believable 35–50 mm full-frame-equivalent editorial perspective, eye level or only slightly elevated, with realistic architectural geometry and medium depth rather than extreme bokeh. Grade around dark timber and warm paper, glazed ceramic, brushed steel and aim for urban precision + layered calm. Make the environment carry identity; keep roughly 25–35% of the frame visually calm enough to coexist with product UI.

Photograph a refined Tokyo street at early evening after light rain: layered narrow storefronts, rail or station infrastructure hinted in the distance, clean pavement reflections, warm pools of interior light and a few commuters moving naturally through the frame. Use controlled color—charcoal, warm paper/wood, muted red accents—and avoid cyberpunk saturation. Leave one side visually quieter for interface overlay.

Composition: one coherent contemporary scene, not a collage. Keep the main visual interest away from at least one outer third so product UI can coexist with the crop. Preserve architectural lines and realistic scale. People, if present, should feel incidental and unposed.

## Production everyday-value source

The first sourced P02 candidate is a contemporary food image, not a price observation.

- slug: `japan-shoyu-ramen-everyday-value-2025`
- role: `everyday_value`
- kind: `contemporary_photo`
- country scope: `JP`
- city scope: none; the Commons description identifies the dish as Tokyo ramen style but does not establish where the photograph was captured
- captured: 11 May 2025
- subject: shoyu ramen / Tokyo ramen style
- source: Wikimedia Commons, `Shoyu Ramen（Tokyo Ramen） - 01.jpg`
- creator: Quercus acuta
- licence: CC BY-SA 4.0
- upstream raster: 3299 × 2474 JPEG
- runtime policy: the image can render only beside reviewed everyday-price context; it is atmosphere/supporting media and is never evidence for a price

As with P01, manifest inclusion is not publication. Managed ingestion remains `needs_review` until editorial review, responsive derivative creation and explicit publication.

## P02 — Everyday Value

**Target:** `static/images/country-media/jp/everyday-value/jp-everyday-value-v01.webp`

**Premium execution:** Treat this as a 50–70 mm observational editorial frame, not food advertising. Let tactile local materials—dark timber and warm paper, glazed ceramic, brushed steel—carry perceived quality. Use one believable spending ritual, one clear focal point, natural imperfections and restrained depth of field. The result should express urban precision without looking staged or aspirational.

Create an elevated but ordinary Tokyo spending scene: a small lunch set or ramen bowl with tea/water, or a sophisticated convenience/café purchase arranged exactly as someone might actually receive it. Include ceramic, tray, chopsticks or compact counter context, with a human presence implied naturally. No invented menu prices in focus.

Frame at table/counter/hand level rather than as a product advertisement. Do not print an invented price as a focal element. Any signage should be incidental and plausible, not AI-generated gibberish dominating the scene.

## Production payment-culture source

The first sourced P03 candidate documents an actual Suica payment interaction rather than a generic payment-terminal product shot.

- slug: `japan-suica-vending-payment-2020`
- role: `payment_culture`
- kind: `contemporary_photo`
- country scope: `JP`
- city scope: none; the source does not establish a capture city
- captured: 14 November 2020
- subject: Suica contactless payment at a vending machine
- source: Wikimedia Commons, `Suica payment on vending machine (50607340823).jpg`
- creator/source account: Real Estate Japan; photo credit: Scott Kouchi
- licence: CC BY 2.0
- upstream raster: 6240 × 4160 JPEG
- runtime policy: supporting atmosphere only; it may render beside separately reviewed payment guidance and does not establish how common any payment method is

The visible Suica branding is incidental and factual to the documented interaction. The asset is not used as evidence that cashless payment is universal, preferred or exclusive in Japan.

As with P01/P02, manifest inclusion is not publication. Managed ingestion remains `needs_review` until editorial review, responsive derivative creation and explicit publication.

## P03 — Payment Culture

**Target:** `static/images/country-media/jp/payment-culture/jp-payment-culture-v01.webp`

**Premium execution:** The payment gesture should occupy only about 20–30% of the visual story; the environment should communicate the country. Use a natural 40–60 mm documentary perspective, anatomically correct hands, plausible device proportions and dark timber and warm paper / glazed ceramic as environmental anchors. Make the moment routine, discreet and trustworthy rather than fintech advertising.

Show a believable tap payment using a transit/contactless card or phone at a clean urban retail or café counter in Tokyo. The device and hand interaction must be anatomically precise. Include subtle station/city cues in the background, but no recognizable payment-app logos and no claim that this is the only payment method.

Show the transaction naturally inside a real-feeling setting. Keep hands anatomically correct, device geometry plausible and the payment terminal/phone secondary to the human context. No visible bank/app logos unless they are incidental and accurate; preferably use neutral interfaces.

## P04 — Local Detail

**Target:** `static/images/country-media/jp/local-detail/jp-local-detail-v01.webp`

**Premium execution:** Use a close observational 65–85 mm feel with two to four carefully chosen elements, tactile side-light and real material texture. Build around dark timber and warm paper, glazed ceramic, brushed steel and refined density. Leave breathing room; avoid decorative flat-lays, souvenir arrangements and perfect AI symmetry.

Create a restrained Japanese urban still life: a ceramic cup, folded paper receipt with no legible fabricated totals, compact rail/ticketing texture, brushed metal, warm wood and a softly blurred Tokyo street or station beyond. Make the composition feel designed yet observed, not arranged as souvenirs.

Treat this as a premium editorial insert: tactile materials, quiet composition, a small number of meaningful local cues and excellent light. No souvenir arrangement, flag palette, postcard montage or overloaded prop styling.

## P05 — Desktop Interface Concept

**Target:** `docs/assets/country-interface-concepts/jp/desktop/jp-interface-desktop-v01.webp`

**Premium execution:** Make this look like a shippable high-end product concept, not a fantasy Dribbble shot. Use one dominant monetary result, one bilateral conversion area, one restrained country photograph occupying roughly 20–30% of the composition, and very little copy. Express urban precision + layered calm through spacing, type scale, material tone and image crop—not flags, ornamental motifs or fake widgets. Omit uncertain text rather than invent it.

Create a 16:10 premium desktop design concept for Cultural Currency Converter focused on Japan. Use the sample conversion **100 EUR → JPY**. Use warm off-white, ink-black/charcoal, deep forest and one muted vermilion or bronze accent. Keep the JPY result very large and typographically clean; Japan enters through a single refined Tokyo crop and compact precision. The screen should communicate: source amount → destination amount → local context. Make the numeric result the largest element. Use only minimal readable text: “Cultural Currency”, country name, currency codes, amount and result. Integrate the P01 visual language as one restrained destination image area. Do not turn the interface into a travel booking site or analytics dashboard.

## P06 — Mobile Interface Concept

**Target:** `docs/assets/country-interface-concepts/jp/mobile/jp-interface-mobile-v01.webp`

**Premium execution:** Use a realistic modern mobile viewport with safe margins, believable control sizes and a single-column reading order. Let the monetary result occupy the strongest visual position, with one country image taking roughly 20–25% of the screen and no decorative phone frame. Express urban precision + layered calm through spacing, palette and crop. Prefer quiet space over invented microcopy, tiny cards or fake OS details.

Create a 9:16 premium mobile design concept for Cultural Currency Converter focused on Japan, using **100 EUR → JPY**. Translate the desktop hierarchy into a believable single-column mobile flow: compact source/destination selector, large conversion result, one editorial country image, then concise local-value/payment context. Use one dominant JPY result, a minimal country selector and a Tokyo crop with controlled evening light; avoid decorative Japanese characters unless they are accurate and necessary. Keep tap targets believable, spacing generous and visible copy minimal. No tiny dashboard cards, fake phone chrome, floating glass panels or crowded widgets.

## Curated historical comparison source

The runtime historical-media slice is separate from the generated country prompt pack.

Reviewed source for JPY Then & Now:

- slug: `jpy-series-d-1000-yen-1984-2007`
- role: `comparison_then`
- kind: `heritage_object`
- currency scope: `JPY`
- country scope: none; historical comparison selection is currency-scoped
- temporal scope: 1 November 1984 through 2 April 2007
- subject: front of a Series D 1,000-yen Bank of Japan note featuring Natsume Soseki
- source: Wikimedia Commons, `Series D 1K Yen Bank of Japan note - front.jpg`
- creator/uploader credit: Eclipse2009
- rights: public domain in Japan; preserve the Commons source page in provenance
- upstream raster: 900 × 456 JPEG

This asset is historical evidence/supporting context for a JPY observation inside its documented temporal scope. It is not a contemporary Japan hero and does not satisfy P01–P04.

## Generation log

| Prompt | Version | Date | Generator/model | Repository path | Status | Review note |
| --- | --- | --- | --- | --- | --- | --- |
| P01 | source selected | 2026-09-29 | Wikimedia Commons / Another Believer | managed-media curated manifest | sourced candidate | Contemporary Tokyo source selected; ingestion/review/publication remain separate. |
| P02 | source selected | 2026-09-29 | Wikimedia Commons / Quercus acuta | managed-media curated manifest | sourced candidate | Tokyo ramen-style image selected; no capture-city or price claim inferred. |
| P03 | source selected | 2026-09-29 | Wikimedia Commons / Real Estate Japan / Scott Kouchi | managed-media curated manifest | sourced candidate | Suica vending-machine payment interaction selected; no city or payment-prevalence claim inferred. |
| P04 | — | — | — | — | planned | — |
| P05 | — | — | — | — | planned | — |
| P06 | — | — | — | — | planned | — |
