"""Shared fixtures for 1688 scraper tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is on sys.path so we can import modules directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import Product


@pytest.fixture
def sample_product():
    """Return a Product with all fields populated."""
    return Product(
        id="123456",
        title="测试产品",
        url="https://detail.1688.com/offer/123456.html",
        price_min=1.50,
        price_max=3.20,
        price_unit="元",
        moq=2,
        moq_unit="件",
        supplier_name="测试供应商",
        supplier_url="https://shop.1688.com/test",
        supplier_location="浙江 义乌",
        supplier_years=5,
        image_url="https://example.com/img.jpg",
        image_urls=["https://example.com/img1.jpg", "https://example.com/img2.jpg"],
        specs={"材质": "塑料", "颜色": "红色"},
        sales_count="1000+",
        scraped_at="2025-01-01T00:00:00+00:00",
    )


@pytest.fixture
def empty_product():
    """Return a Product with default (empty) fields."""
    return Product()


@pytest.fixture
def mock_page():
    """Return an AsyncMock mimicking a Playwright Page."""
    page = AsyncMock()
    page.url = "https://s.1688.com/selloffer/offer_search.htm"
    page.content = AsyncMock(return_value="<html></html>")
    page.evaluate = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.close = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page):
    """Return an AsyncMock mimicking a Playwright BrowserContext."""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    return context


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect config.DATA_DIR to a temp directory."""
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path
