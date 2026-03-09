"""Data persistence: save scraped products to JSON or CSV."""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

import config
from models import Product

logger = logging.getLogger(__name__)


def generate_filename(keyword: str, fmt: str) -> Path:
    """Generate a timestamped output filename."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_keyword = "".join(c if c.isalnum() or c in "-_" else "_" for c in keyword)
    return config.DATA_DIR / f"{safe_keyword}_{timestamp}.{fmt}"


def save_json(products: list[Product], filepath: Path) -> None:
    """Save products as a JSON file with Chinese character support."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    data = [p.to_dict() for p in products]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d products to %s", len(products), filepath)


def save_csv(products: list[Product], filepath: Path) -> None:
    """Save products as a CSV file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not products:
        logger.warning("No products to save")
        return

    headers = Product.csv_headers()
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for p in products:
            writer.writerow(p.to_csv_row())
    logger.info("Saved %d products to %s", len(products), filepath)


def save_products(products: list[Product], keyword: str, fmt: str = "json") -> Path:
    """Save products in the specified format. Returns the output file path."""
    filepath = generate_filename(keyword, fmt)
    if fmt == "csv":
        save_csv(products, filepath)
    else:
        save_json(products, filepath)
    return filepath
