from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ProductDataSourceError(RuntimeError):
    pass


class ProductNotFound(ProductDataSourceError):
    pass


class ProductSourceRateLimited(ProductDataSourceError):
    pass


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    barcode: str
    product_name: str
    brands: tuple[str, ...]
    quantity: str
    categories: tuple[str, ...]
    source_name: str
    source_url: str
    retrieved_at: datetime
