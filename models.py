"""Data models for scraped product data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Product:
    id: str = ""
    title: str = ""
    url: str = ""
    price_min: float | None = None
    price_max: float | None = None
    price_unit: str = "元"
    moq: int | None = None
    moq_unit: str = ""
    supplier_name: str = ""
    supplier_url: str = ""
    supplier_location: str = ""
    supplier_years: int | None = None
    image_url: str = ""
    image_urls: list[str] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    sales_count: str = ""
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "price_unit": self.price_unit,
            "moq": self.moq,
            "moq_unit": self.moq_unit,
            "supplier_name": self.supplier_name,
            "supplier_url": self.supplier_url,
            "supplier_location": self.supplier_location,
            "supplier_years": self.supplier_years,
            "image_url": self.image_url,
            "image_urls": self.image_urls,
            "specs": self.specs,
            "sales_count": self.sales_count,
            "scraped_at": self.scraped_at,
        }

    @staticmethod
    def csv_headers() -> list[str]:
        return [
            "id", "title", "url", "price_min", "price_max", "price_unit",
            "moq", "moq_unit", "supplier_name", "supplier_url",
            "supplier_location", "supplier_years", "image_url",
            "image_urls", "specs", "sales_count", "scraped_at",
        ]

    def to_csv_row(self) -> dict[str, str]:
        d = self.to_dict()
        d["image_urls"] = ";".join(self.image_urls)
        d["specs"] = json.dumps(self.specs, ensure_ascii=False)
        return {k: str(v) if v is not None else "" for k, v in d.items()}


class SessionExpiredError(Exception):
    """Raised when the 1688.com session is expired or CAPTCHA is detected."""
    pass
