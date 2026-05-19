import os

# ─── Database ─────────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5434"))
DB_NAME     = os.getenv("DB_NAME",     "rag_database")
DB_USER     = os.getenv("DB_USER",     "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin1234")
DB_DSN      = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

DB_POOL_MIN = 2
DB_POOL_MAX = 10

# ─── Server ───────────────────────────────────────────────────────────────────
API_PORT        = int(os.getenv("PORT", "8000"))
REQUEST_TIMEOUT = 60.0   # seconds before 504

# ─── Models ───────────────────────────────────────────────────────────────────
DEVICE = os.getenv("DEVICE", "cuda")   # "cuda" | "cpu"
