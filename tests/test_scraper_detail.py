"""Tests for scraper_detail.py — detail page scraping logic."""

from unittest.mock import AsyncMock, patch

import pytest

from models import Product, SessionExpiredError
from scraper_detail import _random_delay, scrape_detail, scrape_details_batch


class TestRandomDelay:
    @pytest.mark.asyncio
    async def test_sleeps_within_bounds(self):
        with patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _random_delay()
            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            import config
            assert config.MIN_DELAY <= delay <= config.MAX_DELAY


class TestScrapeDetail:
    @pytest.fixture
    def detail_page(self):
        page = AsyncMock()
        page.url = "https://detail.1688.com/offer/123.html"
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.content = AsyncMock(return_value="<html></html>")
        page.evaluate = AsyncMock(return_value=None)
        return page

    @pytest.mark.asyncio
    async def test_enriches_title(self, detail_page):
        detail_page.evaluate = AsyncMock(
            side_effect=["New Title", None, None, None, None, None, None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.title == "New Title"

    @pytest.mark.asyncio
    async def test_enriches_images(self, detail_page):
        images = ["https://img1.jpg", "https://img2.jpg"]
        detail_page.evaluate = AsyncMock(
            side_effect=["", images, None, None, None, None, None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.image_urls == images
            assert result.image_url == "https://img1.jpg"

    @pytest.mark.asyncio
    async def test_enriches_prices(self, detail_page):
        detail_page.evaluate = AsyncMock(
            side_effect=["", None, [5.0, 10.0, 15.0], None, None, None, None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.price_min == 5.0
            assert result.price_max == 15.0

    @pytest.mark.asyncio
    async def test_enriches_specs(self, detail_page):
        specs = {"材质": "金属", "颜色": "银色"}
        detail_page.evaluate = AsyncMock(
            side_effect=["", None, None, specs, None, None, None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.specs == specs

    @pytest.mark.asyncio
    async def test_enriches_supplier(self, detail_page):
        supplier = {
            "name": "TestCo",
            "url": "https://shop.1688.com/testco",
            "location": "广东 深圳",
            "years": 8,
        }
        detail_page.evaluate = AsyncMock(
            side_effect=["", None, None, None, supplier, None, None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.supplier_name == "TestCo"
            assert result.supplier_location == "广东 深圳"
            assert result.supplier_years == 8

    @pytest.mark.asyncio
    async def test_enriches_sales_count(self, detail_page):
        detail_page.evaluate = AsyncMock(
            side_effect=["", None, None, None, None, "500+件", None]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.sales_count == "500+件"

    @pytest.mark.asyncio
    async def test_enriches_moq_when_not_set(self, detail_page):
        detail_page.evaluate = AsyncMock(
            side_effect=["", None, None, None, None, None, "10件起批"]
        )
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            assert result.moq == 10

    @pytest.mark.asyncio
    async def test_keeps_existing_moq(self, detail_page):
        detail_page.evaluate = AsyncMock(return_value=None)
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html", moq=5)
            result = await scrape_detail(detail_page, product)
            assert result.moq == 5

    @pytest.mark.asyncio
    async def test_session_expired_raises(self, detail_page):
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=False), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", url="https://detail.1688.com/offer/123.html")
            with pytest.raises(SessionExpiredError):
                await scrape_detail(detail_page, product)

    @pytest.mark.asyncio
    async def test_graceful_on_evaluate_exceptions(self, detail_page):
        detail_page.evaluate = AsyncMock(side_effect=Exception("JS error"))
        with patch("scraper_detail.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_detail.asyncio.sleep", new_callable=AsyncMock):
            product = Product(id="123", title="original", url="https://detail.1688.com/offer/123.html")
            result = await scrape_detail(detail_page, product)
            # Should return product with original data, not crash
            assert result.title == "original"


class TestScrapeDetailsBatch:
    @pytest.mark.asyncio
    async def test_enriches_all_products(self, mock_context, mock_page):
        products = [
            Product(id="1", title="p1", url="https://detail.1688.com/offer/1.html"),
            Product(id="2", title="p2", url="https://detail.1688.com/offer/2.html"),
        ]
        with patch("scraper_detail.scrape_detail", new_callable=AsyncMock) as mock_detail, \
             patch("scraper_detail._random_delay", new_callable=AsyncMock):
            mock_detail.side_effect = [
                Product(id="1", title="enriched1", url="https://detail.1688.com/offer/1.html"),
                Product(id="2", title="enriched2", url="https://detail.1688.com/offer/2.html"),
            ]
            result = await scrape_details_batch(mock_context, products)
            assert len(result) == 2
            assert result[0].title == "enriched1"
            assert result[1].title == "enriched2"

    @pytest.mark.asyncio
    async def test_keeps_partial_on_failure(self, mock_context, mock_page):
        products = [
            Product(id="1", title="p1", url="https://detail.1688.com/offer/1.html"),
            Product(id="2", title="p2", url="https://detail.1688.com/offer/2.html"),
        ]
        with patch("scraper_detail.scrape_detail", new_callable=AsyncMock) as mock_detail, \
             patch("scraper_detail._random_delay", new_callable=AsyncMock):
            mock_detail.side_effect = [
                Product(id="1", title="enriched1", url="u"),
                Exception("network error"),
            ]
            result = await scrape_details_batch(mock_context, products)
            assert len(result) == 2
            assert result[0].title == "enriched1"
            assert result[1].title == "p2"  # kept original

    @pytest.mark.asyncio
    async def test_session_expired_propagates(self, mock_context, mock_page):
        products = [
            Product(id="1", title="p1", url="https://detail.1688.com/offer/1.html"),
        ]
        with patch("scraper_detail.scrape_detail", new_callable=AsyncMock) as mock_detail, \
             patch("scraper_detail._random_delay", new_callable=AsyncMock):
            mock_detail.side_effect = SessionExpiredError("expired")
            with pytest.raises(SessionExpiredError):
                await scrape_details_batch(mock_context, products)

    @pytest.mark.asyncio
    async def test_empty_list(self, mock_context, mock_page):
        result = await scrape_details_batch(mock_context, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_closes_page(self, mock_context, mock_page):
        with patch("scraper_detail.scrape_detail", new_callable=AsyncMock, return_value=Product()), \
             patch("scraper_detail._random_delay", new_callable=AsyncMock):
            await scrape_details_batch(mock_context, [Product(id="1", url="u")])
            mock_page.close.assert_called_once()
