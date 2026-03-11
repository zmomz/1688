"""Ollama API client for translating user requests into Chinese search terms."""

import json
import logging

import httpx

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a product sourcing assistant for 1688.com (Chinese wholesale marketplace).

The user will describe products they want to find. Your job is to:
1. Identify the INDUSTRY/DOMAIN of the request (e.g. automotive, medical, electronics, food, clothing, industrial, etc.)
2. Count how many DISTINCT product categories are being requested
3. Generate SPECIFIC Chinese search terms for EACH distinct product category

CRITICAL RULES:
- Output ONLY valid JSON, nothing else
- For product search requests, output: {"action": "search", "terms": ["中文搜索词1", "中文搜索词2", ...]}
- ALL search terms MUST be in Chinese (Simplified Chinese characters only). NEVER include English, pinyin, or mixed-language terms.
- Generate ONE search term per distinct product/item requested. If the user lists 10 items, generate up to 10 search terms. No artificial limit.
- ALWAYS include the industry/domain qualifier in each term to avoid irrelevant results:
  - Automotive paint supplies → prefix with 汽车 (auto)
  - Medical equipment → prefix with 医用/医疗 (medical)
  - Industrial tools → prefix with 工业 (industrial)
  - etc.
- Use specific product names as they appear on Chinese wholesale marketplaces, NOT generic/vague translations
- If multiple items belong to the same narrow category, you may combine them into one term (e.g. "砂纸套装 80-2000目" instead of one term per grit)
- If the user is refining a previous search, adjust terms accordingly
- If the user asks a general question or wants help (NOT a product list), output: {"action": "question", "text": "your helpful answer"}
- When the user provides a detailed product list, ALWAYS search immediately. Do NOT ask clarifying questions.

"""


async def check_ollama_health() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{config.OLLAMA_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def warm_up_model() -> None:
    """Send a short request to pre-load the model into memory."""
    try:
        logger.info("Warming up Ollama model '%s'...", config.OLLAMA_MODEL)
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
        logger.info("Ollama model warm-up complete.")
    except Exception as e:
        logger.warning("Ollama warm-up failed (model will load on first request): %s", e)


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
        timeout = httpx.Timeout(10.0, read=config.OLLAMA_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
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
    except httpx.TimeoutException as e:
        logger.error("Ollama request timed out after %ss: %s", config.OLLAMA_TIMEOUT, e)
        return {
            "action": "error",
            "text": f"Ollama timed out after {config.OLLAMA_TIMEOUT}s. The model may be loading or overloaded.",
        }
    except httpx.HTTPError as e:
        logger.error("Ollama API error (%s): %s", type(e).__name__, e)
        return {
            "action": "error",
            "text": f"Could not reach Ollama ({type(e).__name__}: {e}). Make sure Ollama is running.",
        }
    except Exception as e:
        logger.error("Unexpected error calling Ollama: %s", e)
        return {
            "action": "error",
            "text": f"An error occurred: {e}",
        }
