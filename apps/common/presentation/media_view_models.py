from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImageViewModel:
    src: str
    ratio: str
    alt: str
    decorative: bool
    kind: str
    label: str
    width: int
    height: int
    focal_position: str = ""
    srcset: str = ""
    sizes: str = ""
    caption: str = ""
    attribution_text: str = ""
    source_url: str = ""
    licence_id: str = ""
    licence_url: str = ""
    change_note: str = ""
    authenticity_label: str = ""
    temporal_label: str = ""
    source_name: str = ""
    creator: str = ""
    rights_statement: str = ""
    original_source_url: str = ""
    retrieved_label: str = ""
    evidence_label: str = ""
    temporal_match_label: str = ""
