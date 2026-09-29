import os
from dotenv import load_dotenv

load_dotenv()

# AI provider — supports "groq" (default/free), "gemini", or "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").lower()

# Groq (free tier — Llama models)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# OpenAI (legacy/fallback)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Resolved AI config
if AI_PROVIDER == "openai" and OPENAI_API_KEY:
    AI_API_KEY = OPENAI_API_KEY
    AI_MODEL = OPENAI_MODEL
    AI_BASE_URL = None  # default OpenAI endpoint
elif AI_PROVIDER == "gemini" and GEMINI_API_KEY:
    AI_API_KEY = GEMINI_API_KEY
    AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
elif GROQ_API_KEY:
    AI_API_KEY = GROQ_API_KEY
    AI_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    AI_BASE_URL = "https://api.groq.com/openai/v1"
elif GEMINI_API_KEY:
    AI_API_KEY = GEMINI_API_KEY
    AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
else:
    AI_API_KEY = OPENAI_API_KEY  # may be empty
    AI_MODEL = OPENAI_MODEL
    AI_BASE_URL = None

# Only sent to models that accept it; set to "" to disable.
AI_REASONING_EFFORT = os.getenv("AI_REASONING_EFFORT", "low")

# Tried in order when the primary model is overloaded, rate-limited or retired
_DEFAULT_FALLBACKS = {
    "https://generativelanguage.googleapis.com/v1beta/openai/": "gemini-flash-lite-latest",
    "https://api.groq.com/openai/v1": "openai/gpt-oss-20b",
}
AI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "AI_FALLBACK_MODELS", _DEFAULT_FALLBACKS.get(AI_BASE_URL or "", "")).split(",") if m.strip()]

# Every provider with a key, primary first: when one is overloaded or rate-limited the next takes over
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_GROQ_URL = "https://api.groq.com/openai/v1"
_ALL_PROVIDERS = [
    ("gemini", GEMINI_API_KEY, _GEMINI_URL,
     [os.getenv("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-lite-latest"]),
    ("groq", GROQ_API_KEY, _GROQ_URL,
     [os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), "openai/gpt-oss-20b"]),
    ("openai", OPENAI_API_KEY, None, [OPENAI_MODEL]),
]
AI_CHAIN = []
if AI_API_KEY:
    AI_CHAIN.append(("primary", AI_API_KEY, AI_BASE_URL, [AI_MODEL, *[m for m in AI_FALLBACK_MODELS if m != AI_MODEL]]))
    AI_CHAIN += [p for p in _ALL_PROVIDERS if p[1] and p[1] != AI_API_KEY]

# ── Market data providers (all have free tiers) ──────────────────────────
# Finnhub: quotes, profile, fundamentals, company news, analyst trends, peers, earnings calendar
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_RATE_PER_MIN = int(os.getenv("FINNHUB_RATE_PER_MIN", "55"))
# Twelve Data: OHLCV history fallback when Yahoo fails
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
# SEC EDGAR requires a descriptive User-Agent with contact info
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "StockInsights/2.0 admin@example.com")

# ── Notifications / scheduler ────────────────────────────────────────────
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1") == "1"
ALERT_SCAN_MINUTES = int(os.getenv("ALERT_SCAN_MINUTES", "15"))
BRIEFING_HOUR_ET = int(os.getenv("BRIEFING_HOUR_ET", "8"))
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")

# Stock defaults
DEFAULT_PERIOD = "6mo"
DEFAULT_INTERVAL = "1d"

# Alert thresholds (configurable via env)
DEFAULT_PRICE_CHANGE_ALERT = float(os.getenv("PRICE_CHANGE_ALERT", "5.0"))  # percent
DEFAULT_VOLUME_SPIKE_ALERT = float(os.getenv("VOLUME_SPIKE_ALERT", "2.0"))  # multiplier vs avg volume
