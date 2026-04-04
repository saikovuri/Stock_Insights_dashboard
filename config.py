import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# Stock defaults
DEFAULT_PERIOD = "6mo"
DEFAULT_INTERVAL = "1d"

# Portfolio file
PORTFOLIO_FILE = "portfolio.json"

# Alert thresholds
DEFAULT_PRICE_CHANGE_ALERT = 5.0  # percent
DEFAULT_VOLUME_SPIKE_ALERT = 2.0  # multiplier vs avg volume
