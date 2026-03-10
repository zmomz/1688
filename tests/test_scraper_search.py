"""Tests for scraper_search.py — parsing helpers and search scraping logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraper_search import (
    _extract_offer_id,
    _parse_moq,
    _parse_price,
    _try_select,
    _try_select_attr,
    _try_select_href,
    _extract_products_from_page,
    _random_delay,
    _scroll_page,
    scrape_search,
    dump_page_html,
)
from models import Product, SessionExpiredError


# ── _parse_price ──────────────────────────────────────────────────────────────

class TestParsePrice:
    def test_range(self):
        assert _parse_price("1.50 - 3.20") == (1.50, 3.20)

    def test_single_price(self):
        assert _parse_price("5.00") == (5.00, 5.00)

    def test_with_yen_sign(self):
        assert _parse_price("¥5.00") == (5.00, 5.00)

    def test_with_yuan_sign(self):
        assert _parse_price("￥10.00") == (10.00, 10.00)

    def test_with_commas(self):
        assert _parse_price("1,200.00") == (1200.00, 1200.00)

    def test_empty_string(self):
        assert _parse_price("") == (None, None)

    def test_no_numbers(self):
        assert _parse_price("abc") == (None, None)

    def test_whitespace(self):
        assert _parse_price("  ") == (None, None)

    def test_three_prices_min_max(self):
        assert _parse_price("1.00 2.00 3.00") == (1.00, 3.00)

    def test_price_with_currency_and_dash(self):
        assert _parse_price("¥1.50 - ¥3.20") == (1.50, 3.20)

    def test_integer_price(self):
        assert _parse_price("10") == (10.0, 10.0)

    def test_price_reverse_order(self):
        # max comes first
        assert _parse_price("5.00 - 1.00") == (1.00, 5.00)


# ── _parse_moq ────────────────────────────────────────────────────────────────

class TestParseMoq:
    def test_standard_format(self):
        assert _parse_moq("2件起批") == (2, "件")

    def test_with_order_variant(self):
        assert _parse_moq("10件起订") == (10, "件")

    def test_number_only(self):
        qty, unit = _parse_moq("5")
        assert qty == 5

    def test_with_whitespace(self):
        assert _parse_moq("  3 件起批  ") == (3, "件")

    def test_empty_string(self):
        assert _parse_moq("") == (None, "")

    def test_no_number(self):
        assert _parse_moq("件起批") == (None, "")

    def test_different_unit(self):
        qty, unit = _parse_moq("100个起批")
        assert qty == 100
        assert unit == "个"

    def test_large_quantity(self):
        qty, _ = _parse_moq("10000件起批")
        assert qty == 10000


# ── _extract_offer_id ─────────────────────────────────────────────────────────

class TestExtractOfferId:
    def test_standard_url(self):
        assert _extract_offer_id("https://detail.1688.com/offer/123456.html") == "123456"

    def test_url_with_params(self):
        assert _extract_offer_id("https://detail.1688.com/offer/789.html?spm=abc") == "789"

    def test_protocol_relative(self):
        assert _extract_offer_id("//detail.1688.com/offer/111.html") == "111"

    def test_no_offer(self):
        assert _extract_offer_id("https://1688.com/page") == ""

    def test_empty_string(self):
        assert _extract_offer_id("") == ""

    def test_long_id(self):
        assert _extract_offer_id("https://detail.1688.com/offer/12345678901.html") == "12345678901"


# ── _try_select ───────────────────────────────────────────────────────────────

class TestTrySelect:
    @pytest.mark.asyncio
    async def test_first_selector_matches(self):
        inner_el = AsyncMock()
        inner_el.inner_text = AsyncMock(return_value="Hello")
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=inner_el)
        result = await _try_select(element, ".a, .b")
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_fallback_to_second(self):
        inner_el = AsyncMock()
        inner_el.inner_text = AsyncMock(return_value="World")
        element = AsyncMock()
        element.query_selector = AsyncMock(side_effect=[None, inner_el])
        result = await _try_select(element, ".a, .b")
        assert result == "World"

    @pytest.mark.asyncio
    async def test_no_match(self):
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=None)
        result = await _try_select(element, ".a, .b")
        assert result == ""

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        inner_el = AsyncMock()
        inner_el.inner_text = AsyncMock(return_value="  spaced  ")
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=inner_el)
        result = await _try_select(element, ".a")
        assert result == "spaced"

    @pytest.mark.asyncio
    async def test_skips_empty_text(self):
        empty_el = AsyncMock()
        empty_el.inner_text = AsyncMock(return_value="")
        good_el = AsyncMock()
        good_el.inner_text = AsyncMock(return_value="found")
        element = AsyncMock()
        element.query_selector = AsyncMock(side_effect=[empty_el, good_el])
        result = await _try_select(element, ".a, .b")
        assert result == "found"

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        element = AsyncMock()
        element.query_selector = AsyncMock(side_effect=Exception("fail"))
        result = await _try_select(element, ".a")
        assert result == ""


# ── _try_select_attr ──────────────────────────────────────────────────────────

class TestTrySelectAttr:
    @pytest.mark.asyncio
    async def test_returns_attribute(self):
        el = AsyncMock()
        el.get_attribute = AsyncMock(return_value="https://img.jpg")
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=el)
        result = await _try_select_attr(element, ".img", "src")
        assert result == "https://img.jpg"

    @pytest.mark.asyncio
    async def test_strips_attribute(self):
        el = AsyncMock()
        el.get_attribute = AsyncMock(return_value="  url  ")
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=el)
        result = await _try_select_attr(element, ".a", "href")
        assert result == "url"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=None)
        result = await _try_select_attr(element, ".a", "src")
        assert result == ""

    @pytest.mark.asyncio
    async def test_null_attribute(self):
        el = AsyncMock()
        el.get_attribute = AsyncMock(return_value=None)
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=el)
        result = await _try_select_attr(element, ".a", "src")
        assert result == ""

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        element = AsyncMock()
        element.query_selector = AsyncMock(side_effect=Exception("fail"))
        result = await _try_select_attr(element, ".a", "src")
        assert result == ""


# ── _try_select_href ──────────────────────────────────────────────────────────

class TestTrySelectHref:
    @pytest.mark.asyncio
    async def test_returns_href(self):
        el = AsyncMock()
        el.get_attribute = AsyncMock(return_value="https://example.com")
        element = AsyncMock()
        element.query_selector = AsyncMock(return_value=el)
        result = await _try_select_href(element, ".a")
        assert result == "https://example.com"


# ── _random_delay ─────────────────────────────────────────────────────────────

class TestRandomDelay:
    @pytest.mark.asyncio
    async def test_calls_sleep(self):
        with patch("scraper_search.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _random_delay()
            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            import config
            assert config.MIN_DELAY <= delay <= config.MAX_DELAY


# ── _scroll_page ──────────────────────────────────────────────────────────────

class TestScrollPage:
    @pytest.mark.asyncio
    async def test_scrolls_incrementally_and_returns_to_top(self):
        page = AsyncMock()
        page.evaluate = AsyncMock(side_effect=[800, None, None, None])
        with patch("scraper_search.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _scroll_page(page)
        calls = page.evaluate.call_args_list
        # First call reads scrollHeight
        assert "scrollHeight" in calls[0][0][0]
        # Middle calls scroll down incrementally
        assert "scrollTo" in calls[1][0][0]
        assert "scrollTo(0, 0)" not in calls[1][0][0]
        # Last call scrolls back to top
        assert "scrollTo(0, 0)" in calls[-1][0][0]
        # Sleep was called between scroll steps
        assert mock_sleep.call_count >= 1


# ── _extract_products_from_page ───────────────────────────────────────────────

class TestExtractProductsFromPage:
    # ── Strategy 1: embedded JSON extraction ──

    @pytest.mark.asyncio
    async def test_json_extraction_basic(self, mock_page):
        """Strategy 1 returns products from embedded JSON data."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [
                {
                    "id": "12345",
                    "subject": "蓝牙耳机TWS无线",
                    "priceDisplay": "¥15.00 - ¥25.00",
                    "quantityBegin": 10,
                    "image": {"imgUrl": "//img.alicdn.com/pic.jpg"},
                    "detailUrl": "//detail.1688.com/offer/12345.html",
                    "company": {
                        "name": "深圳科技公司",
                        "url": "//shop123.1688.com",
                        "location": "广东 深圳",
                    },
                }
            ],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert len(products) == 1
        p = products[0]
        assert p.id == "12345"
        assert p.title == "蓝牙耳机TWS无线"
        assert p.price_min == 15.0
        assert p.price_max == 25.0
        assert p.moq == 10
        assert p.moq_unit == "件"
        assert p.image_url == "https://img.alicdn.com/pic.jpg"
        assert p.url == "https://detail.1688.com/offer/12345.html"
        assert p.supplier_name == "深圳科技公司"
        assert p.supplier_url == "https://shop123.1688.com"
        assert p.supplier_location == "广东 深圳"

    @pytest.mark.asyncio
    async def test_json_extraction_alternate_field_names(self, mock_page):
        """Strategy 1 handles alternate field names (offerId, title, price, etc.)."""
        json_result = {
            "source": "pageData",
            "offers": [
                {
                    "offerId": "67890",
                    "title": "Product via title field",
                    "price": "8.50",
                    "moq": "5件起批",
                    "imageUrl": "https://img.alicdn.com/alt.jpg",
                    "offerUrl": "https://detail.1688.com/offer/67890.html",
                    "companyName": "义乌贸易",
                }
            ],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert len(products) == 1
        p = products[0]
        assert p.id == "67890"
        assert p.title == "Product via title field"
        assert p.price_min == 8.5
        assert p.moq == 5
        assert p.image_url == "https://img.alicdn.com/alt.jpg"
        assert p.supplier_name == "义乌贸易"

    @pytest.mark.asyncio
    async def test_json_extraction_numeric_price(self, mock_page):
        """Strategy 1 handles numeric price values (int/float)."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [{"id": "111", "subject": "T", "tradePrice": 42.5}],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert products[0].price_min == 42.5
        assert products[0].price_max == 42.5

    @pytest.mark.asyncio
    async def test_json_extraction_skips_offers_without_id(self, mock_page):
        """Strategy 1 skips offers that have no id field."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [
                {"subject": "No ID product"},
                {"id": "222", "subject": "Has ID"},
            ],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert len(products) == 1
        assert products[0].id == "222"

    @pytest.mark.asyncio
    async def test_json_extraction_generates_url_when_missing(self, mock_page):
        """Strategy 1 generates URL from offer ID when detailUrl/offerUrl missing."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [{"id": "333", "subject": "No URL"}],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert products[0].url == "https://detail.1688.com/offer/333.html"

    @pytest.mark.asyncio
    async def test_json_extraction_dict_image_no_imgurl(self, mock_page):
        """Strategy 1 handles image dict without imgUrl key."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [{"id": "444", "image": {"unexpected": "structure"}}],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        assert products[0].image_url == ""

    @pytest.mark.asyncio
    async def test_json_extraction_offer_raises_exception(self, mock_page):
        """Strategy 1 gracefully handles an offer that causes an exception."""
        json_result = {
            "source": "__INIT_DATA",
            "offers": [
                # This offer will raise because image.get() on a non-dict
                {"id": "bad", "image": 12345, "subject": "Bad"},
                {"id": "good", "subject": "Good Product"},
            ],
        }
        mock_page.evaluate = AsyncMock(return_value=json_result)
        products = await _extract_products_from_page(mock_page)
        # The bad offer may or may not parse depending on the code path,
        # but at least the good one should be there and no crash
        ids = [p.id for p in products]
        assert "good" in ids

    @pytest.mark.asyncio
    async def test_json_extraction_falls_through_to_dom_on_unparseable(self, mock_page):
        """When JSON offers exist but all fail to parse, falls back to DOM strategies."""
        json_result = {
            "source": "__INIT_DATA",
            # Offers with no id at all — all will be skipped
            "offers": [{"no_id_field": True}, {"also_no_id": True}],
        }
        # evaluate call 1: Strategy 1 returns unparseable offers
        # evaluate call 2: Strategy 3 JS fallback returns empty
        mock_page.evaluate = AsyncMock(side_effect=[json_result, []])
        mock_page.query_selector_all = AsyncMock(return_value=[])
        products = await _extract_products_from_page(mock_page)
        assert products == []
        # Verify it fell through: query_selector_all was called (Strategy 2)
        mock_page.query_selector_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_extraction_null_skips_to_dom(self, mock_page):
        """When page.evaluate returns None (no JSON), skips to DOM strategies."""
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        products = await _extract_products_from_page(mock_page)
        assert products == []
        # Should have tried CSS selectors after JSON returned None
        mock_page.query_selector_all.assert_called_once()

    # ── Strategy 3: JS DOM fallback ──

    @pytest.mark.asyncio
    async def test_no_cards_no_js_fallback(self, mock_page):
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.evaluate = AsyncMock(return_value=[])
        products = await _extract_products_from_page(mock_page)
        assert products == []

    @pytest.mark.asyncio
    async def test_js_fallback_extracts_products(self, mock_page):
        # First call: query_selector_all returns empty (no cards)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        # Second call: evaluate for fallback HTML returns strings (skipped)
        # Third call: evaluate for JS extraction returns raw products
        raw = [
            {
                "id": "999",
                "title": "JS Product",
                "url": "https://detail.1688.com/offer/999.html",
                "priceText": "5.00 - 10.00",
                "imgSrc": "https://img.jpg",
                "supplierName": "Supplier",
                "supplierUrl": "https://shop.1688.com",
                "moqText": "2件起批",
            }
        ]
        mock_page.evaluate = AsyncMock(side_effect=[None, raw])
        products = await _extract_products_from_page(mock_page)
        assert len(products) == 1
        assert products[0].id == "999"
        assert products[0].title == "JS Product"
        assert products[0].price_min == 5.0
        assert products[0].price_max == 10.0
        assert products[0].moq == 2

    @pytest.mark.asyncio
    async def test_standard_card_extraction(self, mock_page):
        # Create a mock card element
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(return_value="https://detail.1688.com/offer/555.html")
        link_el.inner_text = AsyncMock(return_value="Card Title")

        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=[link_el, None])

        mock_page.query_selector_all = AsyncMock(return_value=[card])

        # Mock _try_select and friends via card
        with patch("scraper_search._try_select", new_callable=AsyncMock) as mock_ts, \
             patch("scraper_search._try_select_attr", new_callable=AsyncMock) as mock_tsa, \
             patch("scraper_search._try_select_href", new_callable=AsyncMock) as mock_tsh:
            mock_ts.side_effect = ["Card Title", "8.00", "5件起批", "TestSupplier"]
            mock_tsa.side_effect = ["https://img.jpg", ""]
            mock_tsh.return_value = "https://supplier.com"

            products = await _extract_products_from_page(mock_page)
            assert len(products) == 1
            assert products[0].id == "555"
            assert products[0].price_min == 8.0
            assert products[0].moq == 5

    @pytest.mark.asyncio
    async def test_standard_card_protocol_relative_url(self, mock_page):
        """Strategy 2 normalizes protocol-relative URLs (//detail.1688.com/...)."""
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(return_value="//detail.1688.com/offer/777.html")
        link_el.inner_text = AsyncMock(return_value="Protocol Relative")

        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=[link_el, None])

        mock_page.query_selector_all = AsyncMock(return_value=[card])

        with patch("scraper_search._try_select", new_callable=AsyncMock) as mock_ts, \
             patch("scraper_search._try_select_attr", new_callable=AsyncMock) as mock_tsa, \
             patch("scraper_search._try_select_href", new_callable=AsyncMock) as mock_tsh:
            mock_ts.side_effect = ["Title", "5.00", "1件起批", "Supplier"]
            mock_tsa.side_effect = ["https://img.jpg", ""]
            mock_tsh.return_value = ""

            products = await _extract_products_from_page(mock_page)
            assert len(products) == 1
            assert products[0].url == "https://detail.1688.com/offer/777.html"

    @pytest.mark.asyncio
    async def test_standard_card_title_fallback_to_link_text(self, mock_page):
        """Strategy 2 falls back to link inner_text when title selector returns empty."""
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(return_value="https://detail.1688.com/offer/888.html")
        link_el.inner_text = AsyncMock(return_value="Link Text Title")

        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=[link_el, None])

        mock_page.query_selector_all = AsyncMock(return_value=[card])

        with patch("scraper_search._try_select", new_callable=AsyncMock) as mock_ts, \
             patch("scraper_search._try_select_attr", new_callable=AsyncMock) as mock_tsa, \
             patch("scraper_search._try_select_href", new_callable=AsyncMock) as mock_tsh:
            # First _try_select call (title) returns empty → falls back to link_el.inner_text
            mock_ts.side_effect = ["", "5.00", "1件起批", "Supplier"]
            mock_tsa.side_effect = ["https://img.jpg", ""]
            mock_tsh.return_value = ""

            products = await _extract_products_from_page(mock_page)
            assert len(products) == 1
            assert products[0].title == "Link Text Title"

    @pytest.mark.asyncio
    async def test_standard_card_image_fallback_to_data_src(self, mock_page):
        """Strategy 2 tries data-src when src returns empty."""
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(return_value="https://detail.1688.com/offer/999.html")
        link_el.inner_text = AsyncMock(return_value="Title")

        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=[link_el, None])

        mock_page.query_selector_all = AsyncMock(return_value=[card])

        with patch("scraper_search._try_select", new_callable=AsyncMock) as mock_ts, \
             patch("scraper_search._try_select_attr", new_callable=AsyncMock) as mock_tsa, \
             patch("scraper_search._try_select_href", new_callable=AsyncMock) as mock_tsh:
            mock_ts.side_effect = ["Title", "5.00", "1件起批", ""]
            # First call (src) returns empty, second call (data-src) returns URL
            mock_tsa.side_effect = ["", "https://lazy-img.jpg"]
            mock_tsh.return_value = ""

            products = await _extract_products_from_page(mock_page)
            assert len(products) == 1
            assert products[0].image_url == "https://lazy-img.jpg"

    @pytest.mark.asyncio
    async def test_standard_card_exception_skipped(self, mock_page):
        """Strategy 2 skips a card that raises an exception during extraction."""
        bad_card = AsyncMock()
        bad_card.query_selector = AsyncMock(side_effect=Exception("DOM error"))

        good_link = AsyncMock()
        good_link.get_attribute = AsyncMock(return_value="https://detail.1688.com/offer/100.html")
        good_link.inner_text = AsyncMock(return_value="Good")
        good_card = AsyncMock()
        good_card.query_selector = AsyncMock(side_effect=[good_link, None])

        mock_page.query_selector_all = AsyncMock(return_value=[bad_card, good_card])

        with patch("scraper_search._try_select", new_callable=AsyncMock) as mock_ts, \
             patch("scraper_search._try_select_attr", new_callable=AsyncMock) as mock_tsa, \
             patch("scraper_search._try_select_href", new_callable=AsyncMock) as mock_tsh:
            mock_ts.side_effect = ["Good", "3.00", "1件起批", ""]
            mock_tsa.side_effect = ["https://img.jpg", ""]
            mock_tsh.return_value = ""

            products = await _extract_products_from_page(mock_page)
            assert len(products) == 1
            assert products[0].id == "100"

    @pytest.mark.asyncio
    async def test_card_without_link_skipped(self, mock_page):
        card = AsyncMock()
        card.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[card])
        products = await _extract_products_from_page(mock_page)
        assert products == []

    @pytest.mark.asyncio
    async def test_card_without_offer_id_skipped(self, mock_page):
        link_el = AsyncMock()
        link_el.get_attribute = AsyncMock(return_value="https://1688.com/other-page")
        card = AsyncMock()
        card.query_selector = AsyncMock(side_effect=[None, link_el])
        mock_page.query_selector_all = AsyncMock(return_value=[card])
        products = await _extract_products_from_page(mock_page)
        assert products == []


# ── scrape_search ─────────────────────────────────────────────────────────────

class TestScrapeSearch:
    @pytest.mark.asyncio
    async def test_returns_products(self, mock_context, mock_page):
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search._random_delay", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_extract.return_value = [Product(id="1", title="p1")]
            mock_page.query_selector = AsyncMock(return_value=None)  # no next page

            products = await scrape_search(mock_context, "test", max_pages=1)
            assert len(products) == 1
            assert products[0].id == "1"

    @pytest.mark.asyncio
    async def test_session_expired_raises(self, mock_context, mock_page):
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=False), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(SessionExpiredError):
                await scrape_search(mock_context, "test", max_pages=1)

    @pytest.mark.asyncio
    async def test_pagination_stops_at_max_products(self, mock_context, mock_page):
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search._random_delay", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock), \
             patch("scraper_search.config") as mock_config:
            mock_config.SEARCH_URL = "https://s.1688.com/selloffer/offer_search.htm"
            mock_config.PAGE_TIMEOUT = 30000
            mock_config.NETWORK_IDLE_TIMEOUT = 15000
            mock_config.MAX_PRODUCTS = 3
            mock_config.MAX_PAGES = 5
            mock_config.SELECTORS = {"next_page": ".next"}

            mock_extract.return_value = [Product(id=str(i)) for i in range(5)]
            products = await scrape_search(mock_context, "test", max_pages=5)
            assert len(products) <= 3

    @pytest.mark.asyncio
    async def test_no_next_page_stops(self, mock_context, mock_page):
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search._random_delay", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_extract.return_value = [Product(id="1")]
            mock_page.query_selector = AsyncMock(return_value=None)

            products = await scrape_search(mock_context, "test", max_pages=3)
            # Should stop after page 1 since no next page
            assert mock_extract.call_count == 1

    @pytest.mark.asyncio
    async def test_networkidle_timeout_continues(self, mock_context, mock_page):
        """scrape_search proceeds when networkidle times out."""
        mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_extract.return_value = [Product(id="1")]
            mock_page.query_selector = AsyncMock(return_value=None)
            products = await scrape_search(mock_context, "test", max_pages=1)
            assert len(products) == 1

    @pytest.mark.asyncio
    async def test_redirect_logs_warning(self, mock_context, mock_page):
        """scrape_search logs a warning when the page URL differs from requested URL."""
        mock_page.url = "https://www.1688.com/redirected"
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock), \
             patch("scraper_search.logger") as mock_logger:
            mock_extract.return_value = [Product(id="1")]
            mock_page.query_selector = AsyncMock(return_value=None)
            await scrape_search(mock_context, "test", max_pages=1)
            # Should have logged a redirect warning
            redirect_calls = [
                c for c in mock_logger.warning.call_args_list
                if "redirected" in str(c).lower()
            ]
            assert len(redirect_calls) >= 1

    @pytest.mark.asyncio
    async def test_screenshot_failure_continues(self, mock_context, mock_page, tmp_data_dir):
        """scrape_search continues when screenshot fails."""
        mock_page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_extract.return_value = [Product(id="1")]
            mock_page.query_selector = AsyncMock(return_value=None)
            products = await scrape_search(mock_context, "test", max_pages=1)
            assert len(products) == 1

    @pytest.mark.asyncio
    async def test_uses_gbk_encoding_in_search_url(self, mock_context, mock_page):
        """scrape_search encodes keywords as GBK in the URL."""
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock, return_value=[]), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_page.query_selector = AsyncMock(return_value=None)
            await scrape_search(mock_context, "手机壳", max_pages=1)
        goto_url = mock_page.goto.call_args[0][0]
        assert "%CA%D6%BB%FA%BF%C7" in goto_url  # GBK
        assert "%E6%89%8B" not in goto_url  # not UTF-8

    @pytest.mark.asyncio
    async def test_multi_page_calls_random_delay(self, mock_context, mock_page):
        """scrape_search calls _random_delay between pages when next page exists."""
        next_btn = AsyncMock()  # truthy = next page exists
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.is_session_valid", new_callable=AsyncMock, return_value=True), \
             patch("scraper_search._extract_products_from_page", new_callable=AsyncMock) as mock_extract, \
             patch("scraper_search._random_delay", new_callable=AsyncMock) as mock_delay, \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            mock_extract.return_value = [Product(id="1")]
            # Page 1: next button found → delay → Page 2: no next button
            mock_page.query_selector = AsyncMock(side_effect=[next_btn, None])
            products = await scrape_search(mock_context, "test", max_pages=2)
            assert mock_extract.call_count == 2
            mock_delay.assert_called_once()


# ── dump_page_html ────────────────────────────────────────────────────────────

class TestDumpPageHtml:
    @pytest.mark.asyncio
    async def test_dumps_html_and_screenshot(self, mock_context, mock_page, tmp_data_dir):
        mock_page.content = AsyncMock(return_value="<html>test content</html>")
        mock_page.url = "https://s.1688.com/selloffer/offer_search.htm?keywords=test"
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            path = await dump_page_html(mock_context, "test")

        # Verify HTML file was written with correct content
        html_path = tmp_data_dir / "debug_search_page.html"
        assert html_path.exists()
        assert html_path.read_text(encoding="utf-8") == "<html>test content</html>"
        assert str(html_path) == path

        # Verify screenshot was attempted
        mock_page.screenshot.assert_called_once()
        screenshot_call = mock_page.screenshot.call_args
        assert "debug_search_screenshot.png" in str(screenshot_call)

    @pytest.mark.asyncio
    async def test_uses_gbk_encoding_in_url(self, mock_context, mock_page, tmp_data_dir):
        mock_page.content = AsyncMock(return_value="<html></html>")
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            await dump_page_html(mock_context, "手机壳")
        # Verify goto was called with GBK-encoded keyword, not UTF-8
        goto_url = mock_page.goto.call_args[0][0]
        assert "%CA%D6%BB%FA%BF%C7" in goto_url  # 手机壳 in GBK
        assert "%E6%89%8B" not in goto_url  # NOT UTF-8 for 手

    @pytest.mark.asyncio
    async def test_networkidle_timeout_continues(self, mock_context, mock_page, tmp_data_dir):
        """dump_page_html proceeds when networkidle times out."""
        mock_page.content = AsyncMock(return_value="<html>ok</html>")
        mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("timeout"))
        with patch("scraper_search._scroll_page", new_callable=AsyncMock), \
             patch("scraper_search.asyncio.sleep", new_callable=AsyncMock):
            path = await dump_page_html(mock_context, "test")
        assert "debug_search_page.html" in path
        html_path = tmp_data_dir / "debug_search_page.html"
        assert html_path.read_text(encoding="utf-8") == "<html>ok</html>"
