"""Tests for session_manager module."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from session_manager import BrowserSessionManager


class TestBrowserSessionManager:
    def test_initial_state(self):
        mgr = BrowserSessionManager()
        assert mgr.is_initialized is False

    @pytest.mark.asyncio
    async def test_get_context_before_init_raises(self):
        mgr = BrowserSessionManager()
        with pytest.raises(RuntimeError, match="not initialized"):
            await mgr.get_context()

    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        mock_pw = AsyncMock()
        mock_pw.start = AsyncMock(return_value=mock_pw)

        with patch("session_manager.async_playwright") as mock_apw, \
             patch("session_manager.load_session", return_value=(mock_browser, mock_context)):
            mock_apw.return_value = mock_pw

            mgr = BrowserSessionManager()
            await mgr.initialize()

            assert mgr.is_initialized is True
            ctx = await mgr.get_context()
            assert ctx is mock_context

            await mgr.shutdown()
            assert mgr.is_initialized is False
            mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        mgr = BrowserSessionManager()
        await mgr.acquire()
        # Lock should be held
        assert mgr._lock.locked()
        mgr.release()
        assert not mgr._lock.locked()

    @pytest.mark.asyncio
    async def test_restart(self):
        mock_browser = AsyncMock()
        mock_context = AsyncMock()

        mock_pw = AsyncMock()
        mock_pw.start = AsyncMock(return_value=mock_pw)

        with patch("session_manager.async_playwright") as mock_apw, \
             patch("session_manager.load_session", return_value=(mock_browser, mock_context)):
            mock_apw.return_value = mock_pw

            mgr = BrowserSessionManager()
            await mgr.initialize()
            assert mgr.is_initialized is True

            await mgr.restart()
            assert mgr.is_initialized is True
