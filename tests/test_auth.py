"""Tests for auth.py — session management and validation."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auth import is_session_valid, load_session, login_and_save_session


class TestIsSessionValid:
    @pytest.mark.asyncio
    async def test_valid_search_page(self):
        page = AsyncMock()
        page.url = "https://s.1688.com/selloffer/offer_search.htm"
        page.content = AsyncMock(return_value="<html>normal content</html>")
        assert await is_session_valid(page) is True

    @pytest.mark.asyncio
    async def test_valid_detail_page(self):
        page = AsyncMock()
        page.url = "https://detail.1688.com/offer/123.html"
        page.content = AsyncMock(return_value="<html>product</html>")
        assert await is_session_valid(page) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url_fragment", [
        "captcha",
        "punish",
        "x5secdata",
        "login.1688.com",
        "login.taobao.com",
        "sec.1688.com",
    ])
    async def test_invalid_url_indicators(self, url_fragment):
        page = AsyncMock()
        page.url = f"https://{url_fragment}/page"
        page.content = AsyncMock(return_value="<html></html>")
        assert await is_session_valid(page) is False

    @pytest.mark.asyncio
    async def test_captcha_in_content(self):
        page = AsyncMock()
        page.url = "https://s.1688.com/search"
        page.content = AsyncMock(return_value='<html>"action":"captcha"</html>')
        assert await is_session_valid(page) is False

    @pytest.mark.asyncio
    async def test_baxia_dialog_in_content(self):
        page = AsyncMock()
        page.url = "https://s.1688.com/search"
        page.content = AsyncMock(return_value="<html>baxia-dialog</html>")
        assert await is_session_valid(page) is False

    @pytest.mark.asyncio
    async def test_content_exception_still_valid(self):
        page = AsyncMock()
        page.url = "https://s.1688.com/search"
        page.content = AsyncMock(side_effect=Exception("timeout"))
        assert await is_session_valid(page) is True

    @pytest.mark.asyncio
    async def test_case_insensitive_url_check(self):
        page = AsyncMock()
        page.url = "https://LOGIN.1688.COM/member/signin.htm"
        page.content = AsyncMock(return_value="<html></html>")
        assert await is_session_valid(page) is False


class TestLoadSession:
    @pytest.mark.asyncio
    async def test_missing_session_file(self, tmp_path):
        playwright = AsyncMock()
        missing_path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match="No session file"):
            await load_session(playwright, session_path=missing_path)

    @pytest.mark.asyncio
    async def test_loads_with_existing_session(self, tmp_path):
        session_path = tmp_path / "state.json"
        session_path.write_text("{}")

        browser = AsyncMock()
        context = AsyncMock()
        browser.new_context = AsyncMock(return_value=context)

        playwright = AsyncMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)

        with patch("auth.Stealth") as mock_stealth_cls:
            mock_stealth = MagicMock()
            mock_stealth.apply_stealth_async = AsyncMock()
            mock_stealth_cls.return_value = mock_stealth

            result_browser, result_context = await load_session(
                playwright, session_path=session_path, headless=True
            )
            assert result_browser is browser
            assert result_context is context
            playwright.chromium.launch.assert_called_once_with(headless=True)

    @pytest.mark.asyncio
    async def test_default_headless_from_config(self, tmp_path):
        session_path = tmp_path / "state.json"
        session_path.write_text("{}")

        browser = AsyncMock()
        context = AsyncMock()
        browser.new_context = AsyncMock(return_value=context)

        playwright = AsyncMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)

        with patch("auth.Stealth") as mock_stealth_cls, \
             patch("auth.config") as mock_config:
            mock_config.HEADLESS = True
            mock_config.SESSION_FILE = session_path
            mock_config.VIEWPORT = {"width": 1366, "height": 768}
            mock_config.LOCALE = "zh-CN"
            mock_config.TIMEZONE = "Asia/Shanghai"
            mock_stealth = MagicMock()
            mock_stealth.apply_stealth_async = AsyncMock()
            mock_stealth_cls.return_value = mock_stealth

            await load_session(playwright, session_path=session_path)
            playwright.chromium.launch.assert_called_once_with(headless=True)

    @pytest.mark.asyncio
    async def test_stealth_applied(self, tmp_path):
        session_path = tmp_path / "state.json"
        session_path.write_text("{}")

        browser = AsyncMock()
        context = AsyncMock()
        browser.new_context = AsyncMock(return_value=context)

        playwright = AsyncMock()
        playwright.chromium.launch = AsyncMock(return_value=browser)

        with patch("auth.Stealth") as mock_stealth_cls:
            mock_stealth = MagicMock()
            mock_stealth.apply_stealth_async = AsyncMock()
            mock_stealth_cls.return_value = mock_stealth

            await load_session(playwright, session_path=session_path, headless=True)
            mock_stealth.apply_stealth_async.assert_called_once_with(context)


class TestLoginAndSaveSession:
    @pytest.mark.asyncio
    async def test_saves_session_file(self, tmp_path):
        session_path = tmp_path / "sessions" / "state.json"

        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.storage_state = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        with patch("auth.async_playwright") as mock_pw, \
             patch("auth.Stealth") as mock_stealth_cls, \
             patch("auth.asyncio.get_event_loop") as mock_loop:
            # Mock the playwright context manager
            mock_pw_instance = AsyncMock()
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_stealth = MagicMock()
            mock_stealth.apply_stealth_async = AsyncMock()
            mock_stealth_cls.return_value = mock_stealth

            # Mock input() so the test doesn't block
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=None)

            await login_and_save_session(session_path=session_path)

        # Verify session directory was created
        assert session_path.parent.exists()
        # Verify browser was launched in headed mode
        mock_pw_instance.chromium.launch.assert_called_once_with(headless=False)
        # Verify stealth was applied
        mock_stealth.apply_stealth_async.assert_called_once_with(mock_context)
        # Verify storage_state was saved
        mock_context.storage_state.assert_called_once_with(path=str(session_path))
        # Verify browser was closed
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_navigates_to_login_url(self, tmp_path):
        session_path = tmp_path / "state.json"
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        with patch("auth.async_playwright") as mock_pw, \
             patch("auth.Stealth") as mock_stealth_cls, \
             patch("auth.asyncio.get_event_loop") as mock_loop, \
             patch("auth.config") as mock_config:
            mock_config.LOGIN_URL = "https://login.1688.com/member/signin.htm"
            mock_config.PAGE_TIMEOUT = 30000
            mock_config.VIEWPORT = {"width": 1366, "height": 768}
            mock_config.LOCALE = "zh-CN"
            mock_config.TIMEZONE = "Asia/Shanghai"
            mock_config.SESSION_FILE = session_path

            mock_pw_instance = AsyncMock()
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_stealth_cls.return_value = MagicMock(apply_stealth_async=AsyncMock())
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=None)

            await login_and_save_session(session_path=session_path)

        mock_page.goto.assert_called_once_with(
            "https://login.1688.com/member/signin.htm", timeout=30000
        )
