"""Tests for ollama_client module."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ollama_client import (
    _format_history,
    check_ollama_health,
    translate_to_search_terms,
)


class TestFormatHistory:
    def test_empty_history(self):
        assert _format_history([]) == ""

    def test_single_message(self):
        history = [{"role": "user", "content": "hello"}]
        assert _format_history(history) == "User: hello"

    def test_multiple_messages(self):
        history = [
            {"role": "user", "content": "find phone cases"},
            {"role": "assistant", "content": "Searching..."},
        ]
        result = _format_history(history)
        assert "User: find phone cases" in result
        assert "Assistant: Searching..." in result

    def test_truncates_to_last_10(self):
        history = [{"role": "user", "content": f"msg{i}"} for i in range(15)]
        result = _format_history(history)
        assert "msg5" in result
        assert "msg14" in result
        assert "msg4" not in result


class TestCheckOllamaHealth:
    @pytest.mark.asyncio
    async def test_healthy(self):
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            assert await check_ollama_health() is True

    @pytest.mark.asyncio
    async def test_unhealthy(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            assert await check_ollama_health() is False


class TestTranslateToSearchTerms:
    @pytest.mark.asyncio
    async def test_search_response(self):
        ollama_response = {
            "message": {
                "content": json.dumps(
                    {"action": "search", "terms": ["手机壳", "硅胶手机套"]}
                )
            }
        }

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: ollama_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            result = await translate_to_search_terms("phone cases", [])

        assert result["action"] == "search"
        assert result["terms"] == ["手机壳", "硅胶手机套"]

    @pytest.mark.asyncio
    async def test_question_response(self):
        ollama_response = {
            "message": {
                "content": json.dumps(
                    {"action": "question", "text": "What kind of products?"}
                )
            }
        }

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: ollama_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            result = await translate_to_search_terms("help", [])

        assert result["action"] == "question"
        assert "What kind" in result["text"]

    @pytest.mark.asyncio
    async def test_empty_terms_filtered(self):
        ollama_response = {
            "message": {
                "content": json.dumps(
                    {"action": "search", "terms": ["手机壳", "", "  "]}
                )
            }
        }

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: ollama_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            result = await translate_to_search_terms("phone cases", [])

        assert result["terms"] == ["手机壳"]

    @pytest.mark.asyncio
    async def test_http_error_handled(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            result = await translate_to_search_terms("test", [])

        assert result["action"] == "question"
        assert "Ollama" in result["text"] or "error" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_conversation_history_passed(self):
        ollama_response = {
            "message": {
                "content": json.dumps(
                    {"action": "search", "terms": ["便宜手机壳"]}
                )
            }
        }

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: ollama_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        history = [
            {"role": "user", "content": "phone cases"},
            {"role": "assistant", "content": "Found 50 products"},
        ]

        with patch("ollama_client.httpx.AsyncClient", return_value=mock_client):
            result = await translate_to_search_terms("cheaper ones", history)

        # Verify history was included in the request
        call_args = mock_client.post.call_args
        messages = call_args.kwargs["json"]["messages"]
        history_msg = [m for m in messages if "Conversation so far" in m.get("content", "")]
        assert len(history_msg) == 1
