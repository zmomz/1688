"""Configuration constants for 1688.com scraper."""

from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).parent
SESSION_DIR = BASE_DIR / "sessions"
DATA_DIR = BASE_DIR / "data"
SESSION_FILE = SESSION_DIR / "state.json"

# --- URLs ---
SEARCH_URL = "https://s.1688.com/selloffer/offer_search.htm"
LOGIN_URL = "https://login.1688.com/member/signin.htm"
DETAIL_URL_PATTERN = "https://detail.1688.com/offer/{offer_id}.html"

# --- Browser Settings ---
VIEWPORT = {"width": 1366, "height": 768}
LOCALE = "zh-CN"
TIMEZONE = "Asia/Shanghai"
CDP_PORT = 9222  # Chrome DevTools Protocol port for remote debugging

# --- Scraping Limits ---
MAX_PAGES = 5
MAX_PRODUCTS = 200
PAGE_TIMEOUT = 30000  # ms
NETWORK_IDLE_TIMEOUT = 15000  # ms

# --- Delays (seconds) ---
MIN_DELAY = 2.0
MAX_DELAY = 5.0
SCROLL_DELAY = 0.5
SCROLL_STEP = 400  # pixels per scroll step

# --- Output ---
OUTPUT_FORMAT = "json"  # "json" or "csv"

# --- Ollama ---
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT = 120  # seconds

# --- Web App ---
WEB_HOST = "0.0.0.0"
WEB_PORT = 8000
DEFAULT_SEARCH_PAGES = 2  # fewer pages per term in chat mode for speed

# --- CSS Selectors (update these when 1688.com changes markup) ---
SELECTORS = {
    # Search results page
    "product_card": (
        'div[data-offer-id], '
        '.sm-offer-item, '
        '.offer-list-row, '
        '.space-offer-card-box, '
        '[class*="offer-card"], '
        '[class*="OfferCard"]'
    ),
    "title": (
        '.title-text, '
        '.offer-title-text, '
        'h2 a, '
        '[class*="title"] a, '
        '[class*="Title"] a'
    ),
    "price": (
        '.sm-offer-priceNum, '
        '.price-text, '
        '[class*="price"] span, '
        '[class*="Price"] span'
    ),
    "moq": (
        '.sm-offer-moq, '
        '.moq-text, '
        '[class*="moq"], '
        '[class*="MOQ"]'
    ),
    "supplier": (
        '.sm-offer-companyName, '
        '.company-name a, '
        '[class*="company"] a, '
        '[class*="supplier"] a'
    ),
    "image": (
        '.offer-img img, '
        '.main-img img, '
        '[class*="offer"] img, '
        '[class*="card"] img'
    ),
    "next_page": (
        '.fui-next, '
        '.next, '
        'a.fui-next, '
        '[class*="next-page"], '
        '.pagination-next'
    ),

    # Detail page
    "detail_images": (
        '.detail-gallery-turn img, '
        '#dt-tab img, '
        '.tab-trigger img, '
        '[class*="gallery"] img, '
        '[class*="slider"] img'
    ),
    "detail_title": (
        '.title-text, '
        'h1[class*="title"], '
        '.d-title'
    ),
    "detail_price": (
        '.price-text, '
        '[class*="price-item"], '
        '.ladder-price-item'
    ),
    "detail_specs": (
        '.obj-sku .obj-content, '
        '#mod-detail-attributes, '
        '.attributes-list, '
        '[class*="attribute"] table'
    ),
    "detail_supplier_name": (
        '.company-name a, '
        '[class*="companyName"] a, '
        '.shop-name a'
    ),
    "detail_supplier_location": (
        '.company-location, '
        '[class*="location"], '
        '.region'
    ),
}
