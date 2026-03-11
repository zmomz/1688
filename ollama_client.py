"""Ollama API client for translating user requests into Chinese search terms."""

import json
import logging

import httpx

import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You translate product requests into Chinese search terms for 1688.com.

Output ONLY JSON: {"action": "search", "terms": ["term1", "term2", ...]}
Or for non-product questions: {"action": "question", "text": "answer"}

Rules:
- Terms MUST be in Simplified Chinese only
- One term per distinct product. Group similar items (e.g. all sandpaper grits → one term)
- Prefix each term with its industry domain to avoid wrong results (汽车 for auto, 医用 for medical, 工业 for industrial, etc.)
- Use specific 1688 product names, not vague translations
- Product lists → search immediately, never ask questions
- Max 15 terms even for large lists (group related items)
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
                    "options": {
                        "num_predict": 512,
                    },
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
