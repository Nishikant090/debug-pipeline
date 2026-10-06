"""Runtime settings for ShopFlow, read from environment variables."""
import os

SECRET_KEY = os.getenv("SECRET_KEY")
DB_PARAMS = {
    "host": os.getenv("DB_HOST", "db-primary"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "shopflow"),
    "user": os.getenv("DB_USER", "shopflow"),
    "password": os.getenv("DB_PASSWORD", ""),
}
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STRIPE_URL = "https://api.stripe.com/v1/payment_intents"
STRIPE_KEY = os.getenv("STRIPE_KEY", "")
MAX_POOL = 20
QUERY_TIMEOUT_SEC = 30
