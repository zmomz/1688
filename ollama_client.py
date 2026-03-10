"""Ollama API client for translating user requests into Chinese search terms."""

import json
import logging

import httpx

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a product sourcing assistant for 1688.com (Chinese wholesale marketplace).

The user will describe products they want to find. Your job is to translate their request \
into Chinese search keywords that would work well on 1688.com.

CRITICAL RULES:
- Output ONLY valid JSON, nothing else
- For product search requests, output: {"action": "search", "terms": ["中文搜索词1", "中文搜索词2"]}
- ALL search terms MUST be in Chinese (Simplified Chinese characters only). NEVER include English, pinyin, or mixed-language terms.
- Generate 1-3 search terms per request
- Use common Chinese product names as they appear on wholesale marketplaces (e.g. "无线蓝牙耳机" not "wireless earphone")
- Consider synonyms and alternative Chinese product names
- If the user is refining a previous search, adjust terms accordingly
- If the user asks a general question or wants help, output: {"action": "question", "text": "your helpful answer"}

Examples:
- User: "wireless earbuds" → {"action": "search", "terms": ["无线蓝牙耳机", "TWS耳机"]}
- User: "phone cases" → {"action": "search", "terms": ["手机壳", "手机保护套"]}
- User: "LED strip lights" → {"action": "search", "terms": ["LED灯带", "LED软灯条"]}
"""


async def check_ollama_health() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{config.OLLAMA_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _format_history(conversation_history: list[dict]) -> str:
    """Format conversation history for the prompt."""
    lines = []
    for msg in conversation_history[-10:]:  # keep last 10 messages
        role = msg["role"].capitalize()
        lines.append(f"{role}: {msg['content']}")
    return "\n".join(lines)


async def translate_to_search_terms(
    user_message: str, conversation_history: list[dict]
) -> dict:
    """Send user message to Ollama and get back search terms or a response.

    Returns a dict with either:
        {"action": "search", "terms": ["term1", "term2"]}
        {"action": "question", "text": "answer text"}
    """
    history_text = _format_history(conversation_history)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    if history_text:
        messages.append(
            {"role": "user", "content": f"Conversation so far:\n{history_text}"}
        )
    messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            logger.info("Ollama response: %s", content)

            result = json.loads(content)

            if result.get("action") == "search" and isinstance(
                result.get("terms"), list
            ):
                # Filter out empty terms
                result["terms"] = [t for t in result["terms"] if t and t.strip()]
                if result["terms"]:
                    return result

            if result.get("action") == "question" and result.get("text"):
                return result

            # Fallback: if we got terms in some other format
            if isinstance(result.get("terms"), list):
                terms = [t for t in result["terms"] if t and t.strip()]
                if terms:
                    return {"action": "search", "terms": terms}

            return {
                "action": "question",
                "text": "I couldn't understand that request. Please describe the products you're looking for.",
            }

    except json.JSONDecodeError:
        # Try to extract Chinese text from the raw response
        logger.warning("Failed to parse Ollama JSON response: %s", content)
        return {
            "action": "question",
            "text": "I had trouble processing that. Could you rephrase your product request?",
        }
    except httpx.HTTPError as e:
        logger.error("Ollama API error: %s", e)
        return {
            "action": "question",
            "text": f"Could not reach Ollama ({e}). Make sure Ollama is running.",
        }
    except Exception as e:
        logger.error("Unexpected error calling Ollama: %s", e)
        return {
            "action": "question",
            "text": f"An error occurred: {e}",
        }
