"""Tests for main.py — CLI argument parsing and scraper workflow."""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from main import parse_args, run_scraper
from models import Product, SessionExpiredError


class TestParseArgs:
    def test_keyword_required(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["main.py"]):
                parse_args()

    def test_keyword_positional(self):
        with patch("sys.argv", ["main.py", "手机壳"]):
            args = parse_args()
            assert args.keyword == "手机壳"

    def test_default_pages(self):
        with patch("sys.argv", ["main.py", "test"]):
            args = parse_args()
            import config
            assert args.pages == config.MAX_PAGES

    def test_custom_pages(self):
        with patch("sys.argv", ["main.py", "test", "--pages", "3"]):
            args = parse_args()
            assert args.pages == 3

    def test_details_flag(self):
        with patch("sys.argv", ["main.py", "test", "--details"]):
            args = parse_args()
            assert args.details is True

    def test_no_details_by_default(self):
        with patch("sys.argv", ["main.py", "test"]):
            args = parse_args()
            assert args.details is False

    def test_format_json(self):
        with patch("sys.argv", ["main.py", "test", "--format", "json"]):
            args = parse_args()
            assert args.format == "json"

    def test_format_csv(self):
        with patch("sys.argv", ["main.py", "test", "--format", "csv"]):
            args = parse_args()
            assert args.format == "csv"

    def test_invalid_format(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["main.py", "test", "--format", "xml"]):
                parse_args()

    def test_login_flag(self):
        with patch("sys.argv", ["main.py", "test", "--login"]):
            args = parse_args()
            assert args.login is True

    def test_headed_flag(self):
        with patch("sys.argv", ["main.py", "test", "--headed"]):
            args = parse_args()
            assert args.headed is True

    def test_dump_html_flag(self):
        with patch("sys.argv", ["main.py", "test", "--dump-html"]):
            args = parse_args()
            assert args.dump_html is True

    def test_all_flags_combined(self):
        with patch("sys.argv", [
            "main.py", "手机壳",
            "--pages", "2",
            "--details",
            "--format", "csv",
            "--login",
            "--headed",
            "--dump-html",
        ]):
            args = parse_args()
            assert args.keyword == "手机壳"
            assert args.pages == 2
            assert args.details is True
            assert args.format == "csv"
            assert args.login is True
            assert args.headed is True
            assert args.dump_html is True


# ── run_scraper ──────────────────────────────────────────────────────────────

def _make_args(**overrides):
    """Create a Namespace with sensible defaults for run_scraper."""
    defaults = dict(
        keyword="test", pages=1, details=False,
        format="json", login=False, headed=False, dump_html=False,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


class TestRunScraper:
    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        """Redirect session/data dirs to tmp so run_scraper doesn't touch real FS."""
        import config
        monkeypatch.setattr(config, "SESSION_DIR", tmp_path / "sessions")
        monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "sessions" / "state.json")
        # Create session file so login isn't triggered
        (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
        (tmp_path / "sessions" / "state.json").write_text("{}")

    @pytest.mark.asyncio
    async def test_search_and_save(self, tmp_path):
        products = [Product(id="1", title="p1")]
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.scrape_search", new_callable=AsyncMock, return_value=products) as mock_search, \
             patch("main.save_products", return_value=Path("/fake/out.json")) as mock_save:
            await run_scraper(_make_args())
            mock_search.assert_called_once_with(mock_context, "test", 1)
            mock_save.assert_called_once_with(products, "test", "json")
            mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_dump_html_mode(self, tmp_path):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.dump_page_html", new_callable=AsyncMock, return_value="/fake/debug.html") as mock_dump, \
             patch("main.scrape_search", new_callable=AsyncMock) as mock_search:
            await run_scraper(_make_args(dump_html=True))
            mock_dump.assert_called_once_with(mock_context, "test")
            mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_details_flag_triggers_detail_scraping(self, tmp_path):
        products = [Product(id="1")]
        detailed = [Product(id="1", title="detailed")]
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.scrape_search", new_callable=AsyncMock, return_value=products), \
             patch("main.scrape_details_batch", new_callable=AsyncMock, return_value=detailed) as mock_details, \
             patch("main.save_products", return_value=Path("/fake/out.json")) as mock_save:
            await run_scraper(_make_args(details=True))
            mock_details.assert_called_once_with(mock_context, products)
            # save_products receives the detailed products
            mock_save.assert_called_once_with(detailed, "test", "json")

    @pytest.mark.asyncio
    async def test_no_products_found_does_not_save(self, tmp_path):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.scrape_search", new_callable=AsyncMock, return_value=[]), \
             patch("main.save_products") as mock_save:
            await run_scraper(_make_args())
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_expired_saves_partial_data(self, tmp_path):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.scrape_search", new_callable=AsyncMock, side_effect=SessionExpiredError("expired")), \
             patch("main.save_products", return_value=Path("/fake/out.json")) as mock_save:
            with pytest.raises(SystemExit):
                await run_scraper(_make_args())
            # No products were captured before error, so no partial save
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_error_exits(self, tmp_path):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.scrape_search", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            with pytest.raises(SystemExit):
                await run_scraper(_make_args())
            mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_flag_triggers_login(self, tmp_path):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, return_value=(mock_browser, mock_context)), \
             patch("main.login_and_save_session", new_callable=AsyncMock) as mock_login, \
             patch("main.scrape_search", new_callable=AsyncMock, return_value=[]):
            await run_scraper(_make_args(login=True))
            mock_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_session_not_found_exits(self, tmp_path):
        with patch("main.async_playwright") as mock_pw, \
             patch("main.load_session", new_callable=AsyncMock, side_effect=FileNotFoundError("no session")):
            with pytest.raises(SystemExit):
                await run_scraper(_make_args())
