"""Tests for config.py — configuration constants and selectors."""

from pathlib import Path

import config


class TestPaths:
    def test_base_dir_is_path(self):
        assert isinstance(config.BASE_DIR, Path)

    def test_session_dir_under_base(self):
        assert config.SESSION_DIR == config.BASE_DIR / "sessions"

    def test_data_dir_under_base(self):
        assert config.DATA_DIR == config.BASE_DIR / "data"

    def test_session_file_under_session_dir(self):
        assert config.SESSION_FILE == config.SESSION_DIR / "state.json"


class TestURLs:
    def test_search_url(self):
        assert "1688.com" in config.SEARCH_URL
        assert "selloffer" in config.SEARCH_URL

    def test_login_url(self):
        assert "login.1688.com" in config.LOGIN_URL

    def test_detail_url_pattern(self):
        assert "{offer_id}" in config.DETAIL_URL_PATTERN
        assert "detail.1688.com" in config.DETAIL_URL_PATTERN


class TestBrowserSettings:
    def test_viewport_has_width_height(self):
        assert "width" in config.VIEWPORT
        assert "height" in config.VIEWPORT
        assert config.VIEWPORT["width"] > 0
        assert config.VIEWPORT["height"] > 0

    def test_locale_is_chinese(self):
        assert config.LOCALE == "zh-CN"

    def test_timezone_is_shanghai(self):
        assert config.TIMEZONE == "Asia/Shanghai"


class TestScrapingLimits:
    def test_max_pages_positive(self):
        assert config.MAX_PAGES > 0

    def test_max_products_positive(self):
        assert config.MAX_PRODUCTS > 0

    def test_timeouts_positive(self):
        assert config.PAGE_TIMEOUT > 0
        assert config.NETWORK_IDLE_TIMEOUT > 0


class TestDelays:
    def test_min_less_than_max(self):
        assert config.MIN_DELAY < config.MAX_DELAY

    def test_scroll_delay_positive(self):
        assert config.SCROLL_DELAY > 0

    def test_scroll_step_positive(self):
        assert config.SCROLL_STEP > 0


class TestSelectors:
    def test_selectors_is_dict(self):
        assert isinstance(config.SELECTORS, dict)

    def test_required_search_selectors(self):
        for key in ["product_card", "title", "price", "moq", "supplier", "image", "next_page"]:
            assert key in config.SELECTORS, f"Missing selector: {key}"

    def test_required_detail_selectors(self):
        for key in [
            "detail_images", "detail_title", "detail_price",
            "detail_specs", "detail_supplier_name", "detail_supplier_location",
        ]:
            assert key in config.SELECTORS, f"Missing selector: {key}"

    def test_selectors_are_nonempty_strings(self):
        for key, value in config.SELECTORS.items():
            assert isinstance(value, str), f"{key} is not a string"
            assert len(value.strip()) > 0, f"{key} is empty"

    def test_output_format_valid(self):
        assert config.OUTPUT_FORMAT in ("json", "csv")
