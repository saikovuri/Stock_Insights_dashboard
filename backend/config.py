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
    AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
    AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
elif GROQ_API_KEY:
    AI_API_KEY = GROQ_API_KEY
    AI_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    AI_BASE_URL = "https://api.groq.com/openai/v1"
else:
    AI_API_KEY = GEMINI_API_KEY or OPENAI_API_KEY  # may be empty
    AI_MODEL = OPENAI_MODEL
    AI_BASE_URL = None

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")

# Stock defaults
DEFAULT_PERIOD = "6mo"
DEFAULT_INTERVAL = "1d"

# Alert thresholds (configurable via env)
DEFAULT_PRICE_CHANGE_ALERT = float(os.getenv("PRICE_CHANGE_ALERT", "5.0"))  # percent
DEFAULT_VOLUME_SPIKE_ALERT = float(os.getenv("VOLUME_SPIKE_ALERT", "2.0"))  # multiplier vs avg volume
