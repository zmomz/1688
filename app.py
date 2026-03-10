"""FastAPI web application with chat-based product search interface."""

import asyncio
import logging
import random
import sys
from contextlib import asynccontextmanager

# On Windows, Playwright needs ProactorEventLoop for subprocess support.
# Must be set at module level before any event loop is created (including by uvicorn --reload).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from models import SessionExpiredError
from ollama_client import check_ollama_health, translate_to_search_terms
from scraper_search import scrape_search
from session_manager import BrowserSessionManager
from storage import save_products

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

session_mgr = BrowserSessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize browser on startup, shut down on exit."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SESSION_DIR.mkdir(parents=True, exist_ok=True)

    try:
        await session_mgr.initialize()
    except FileNotFoundError:
        logger.error(
            "No browser session found. Run 'python main.py --login' first to authenticate."
        )
    except Exception as e:
        logger.error("Failed to initialize browser: %s", e)

    yield

    await session_mgr.shutdown()


app = FastAPI(title="1688 Product Search Chat", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation_history: list[dict] = []

    # Send initial status
    if not session_mgr.is_initialized:
        await websocket.send_json({
            "type": "error",
            "text": "Browser session not loaded. Run 'python main.py --login' in terminal, then restart the app.",
        })

    ollama_ok = await check_ollama_health()
    if not ollama_ok:
        await websocket.send_json({
            "type": "error",
            "text": f"Cannot reach Ollama at {config.OLLAMA_URL}. Make sure Ollama is running ('ollama serve').",
        })

    try:
        while True:
            data = await websocket.receive_json()
            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            conversation_history.append({"role": "user", "content": user_text})

            # Translate via Ollama
            await websocket.send_json({
                "type": "progress",
                "text": "Thinking...",
            })

            result = await translate_to_search_terms(user_text, conversation_history)

            if result["action"] == "question":
                await websocket.send_json({
                    "type": "assistant_message",
                    "text": result["text"],
                })
                conversation_history.append({
                    "role": "assistant",
                    "content": result["text"],
                })
                continue

            # Search action
            terms = result["terms"]
            await websocket.send_json({
                "type": "assistant_message",
                "text": f"Searching for: {', '.join(terms)}",
            })

            if not session_mgr.is_initialized:
                await websocket.send_json({
                    "type": "error",
                    "text": "Browser session not available. Run 'python main.py --login' first.",
                })
                continue

            all_products = []
            session_lost = False
            try:
                for i, term in enumerate(terms):
                    await websocket.send_json({
                        "type": "progress",
                        "text": f"Scraping '{term}' ({i + 1}/{len(terms)})...",
                    })

                    # Add delay between search terms to reduce anti-bot detection
                    if i > 0:
                        delay = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
                        await asyncio.sleep(delay)

                    await session_mgr.acquire()
                    try:
                        ctx = await session_mgr.get_context()
                        products = await scrape_search(
                            ctx, term, max_pages=config.DEFAULT_SEARCH_PAGES
                        )
                        all_products.extend(products)
                    except SessionExpiredError:
                        session_lost = True
                        logger.warning(
                            "Session lost on term %d/%d ('%s'), keeping %d products from prior terms",
                            i + 1, len(terms), term, len(all_products),
                        )
                        break
                    finally:
                        session_mgr.release()

                # Deduplicate by product ID
                seen_ids = set()
                unique = []
                for p in all_products:
                    if p.id and p.id not in seen_ids:
                        seen_ids.add(p.id)
                        unique.append(p)

                if unique:
                    # Save to file
                    combined_keyword = "_".join(terms)
                    filepath = save_products(unique, combined_keyword, "json")

                    # Send results summary
                    await websocket.send_json({
                        "type": "results_summary",
                        "products": [p.to_dict() for p in unique[:10]],
                        "total": len(unique),
                        "file_path": str(filepath),
                        "terms_searched": terms,
                    })

                    conversation_history.append({
                        "role": "assistant",
                        "content": f"Found {len(unique)} products for terms: {terms}. Saved to {filepath}.",
                    })
                else:
                    await websocket.send_json({
                        "type": "assistant_message",
                        "text": "No products found. Try different terms or check if the session is still valid.",
                    })
                    conversation_history.append({
                        "role": "assistant",
                        "content": f"Searched for {terms} but found no products.",
                    })

                if session_lost:
                    await websocket.send_json({
                        "type": "error",
                        "text": "Session expired or CAPTCHA detected mid-search. Partial results were saved. Run 'python main.py --login' to re-authenticate, then restart the app.",
                    })
            except Exception as e:
                logger.error("Scraping error: %s", e, exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "text": f"Scraping error: {e}",
                })

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)


if __name__ == "__main__":
    import uvicorn

    # uvicorn reload mode forces SelectorEventLoop on Windows, which doesn't
    # support subprocesses (needed by Playwright). Disable reload on Windows.
    use_reload = sys.platform != "win32"

    uvicorn.run(
        "app:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        reload=use_reload,
    )
