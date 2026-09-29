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
