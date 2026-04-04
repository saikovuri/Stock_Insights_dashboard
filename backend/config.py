import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")

# Stock defaults
DEFAULT_PERIOD = "6mo"
DEFAULT_INTERVAL = "1d"

# Portfolio file
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")

# Alert thresholds (configurable via env)
DEFAULT_PRICE_CHANGE_ALERT = float(os.getenv("PRICE_CHANGE_ALERT", "5.0"))  # percent
DEFAULT_VOLUME_SPIKE_ALERT = float(os.getenv("VOLUME_SPIKE_ALERT", "2.0"))  # multiplier vs avg volume
