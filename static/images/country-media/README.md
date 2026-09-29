# Country Media

This directory contains repository-tracked country visual outputs used by the editorial media workflow.

A file being present here does **not** make it runtime-published. The live product selects managed `MediaAsset` records, and those assets must separately pass provenance/rights review, editorial approval and explicit publication. Synthetic trial/reference files may remain here when their country generation log labels them as such.

Generation workflow and prompt architecture live in:

- `docs/media/00_COUNTRY_MEDIA_SYSTEM.md`
- `docs/media/01_COUNTRY_INDEX.md`
- `docs/media/countries/*.md`

## Canonical repository paths

```text
<iso2>/hero/<iso2>-hero-vNN.webp
<iso2>/everyday-value/<iso2>-everyday-value-vNN.webp
<iso2>/payment-culture/<iso2>-payment-culture-vNN.webp
<iso2>/local-detail/<iso2>-local-detail-vNN.webp
```

Do not store generated interface mockups here. Interface concepts belong under:

`docs/assets/country-interface-concepts/<iso2>/...`

Rejected generation attempts should not be committed.

## Runtime boundary

Country hero/teaser runtime selection currently requires reviewed, published, non-generated contemporary photography. Do not infer runtime eligibility from a filename, folder or generation-log approval alone.
