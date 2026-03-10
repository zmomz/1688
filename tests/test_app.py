"""Tests for app module (FastAPI routes and WebSocket)."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import Product


@pytest.fixture
def mock_session_mgr():
    mgr = AsyncMock()
    mgr.is_initialized = True
    mgr.get_context = AsyncMock(return_value=AsyncMock())
    mgr.acquire = AsyncMock()
    mgr.release = MagicMock()
    return mgr


@pytest.fixture
def products():
    return [
        Product(
            id="111",
            title="测试产品1",
            url="https://detail.1688.com/offer/111.html",
            price_min=1.0,
            price_max=2.0,
        ),
        Product(
            id="222",
            title="测试产品2",
            url="https://detail.1688.com/offer/222.html",
            price_min=3.0,
            price_max=4.0,
        ),
    ]


class TestAppEndpoints:
    @pytest.mark.asyncio
    async def test_index_page(self):
        """Test that the index page is served."""
        # Import inside test to avoid side effects
        with patch("app.session_mgr") as mock_mgr:
            mock_mgr.is_initialized = True
            from fastapi.testclient import TestClient
            from app import app

            client = TestClient(app)
            resp = client.get("/")
            assert resp.status_code == 200
            assert "1688 Product Search" in resp.text


class TestWebSocketFlow:
    @pytest.mark.asyncio
    async def test_search_flow(self, mock_session_mgr, products):
        """Test the full search flow through WebSocket."""
        with patch("app.session_mgr", mock_session_mgr), \
             patch("app.check_ollama_health", return_value=True), \
             patch("app.translate_to_search_terms", return_value={
                 "action": "search",
                 "terms": ["手机壳"],
             }), \
             patch("app.scrape_search", return_value=products), \
             patch("app.save_products", return_value=Path("data/test.json")):

            from fastapi.testclient import TestClient
            from app import app

            client = TestClient(app)
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"text": "phone cases"})

                # Expect: progress ("Thinking..."), assistant_message (search terms),
                # progress (scraping), results_summary
                messages = []
                for _ in range(4):
                    msg = ws.receive_json()
                    messages.append(msg)

                types = [m["type"] for m in messages]
                assert "results_summary" in types

                summary = next(m for m in messages if m["type"] == "results_summary")
                assert summary["total"] == 2

    @pytest.mark.asyncio
    async def test_question_flow(self, mock_session_mgr):
        """Test that non-search queries return assistant messages."""
        with patch("app.session_mgr", mock_session_mgr), \
             patch("app.check_ollama_health", return_value=True), \
             patch("app.translate_to_search_terms", return_value={
                 "action": "question",
                 "text": "What products are you looking for?",
             }):

            from fastapi.testclient import TestClient
            from app import app

            client = TestClient(app)
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"text": "help"})

                # Expect: progress ("Thinking..."), then assistant_message
                msg1 = ws.receive_json()
                msg2 = ws.receive_json()

                messages = [msg1, msg2]
                assert any(
                    m["type"] == "assistant_message" and "looking for" in m["text"]
                    for m in messages
                )
