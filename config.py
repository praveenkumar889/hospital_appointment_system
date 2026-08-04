"""
config.py — Application Configuration

Single source of truth. All values from environment.
Zero hardcoding. To configure a new tenant: update .env only.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    """Read from environment with a safe fallback."""
    return os.getenv(key, default)


# ── LLM (Azure OpenAI) ─────────────────────────────────────────────────────
LLM_ENDPOINT    = _env("AZURE_OPENAI_ENDPOINT")
LLM_API_KEY     = _env("AZURE_OPENAI_API_KEY")
LLM_DEPLOYMENT  = _env("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")
LLM_API_VERSION = _env("AZURE_OPENAI_API_VERSION",     "2024-12-01-preview")

# ── External APIs ──────────────────────────────────────────────────────────
KB_API_URL        = _env("KB_API_BASE_URL",
                         f"http://localhost:{_env('KB_API_PORT', '8000')}")
WORKFLOWS_API_URL = _env("WORKFLOWS_API_BASE_URL",
                         f"http://localhost:{_env('WORKFLOWS_API_PORT', '8001')}")

# ── MongoDB (Long-term User Memory & Conversation Summaries) ────────────────
MONGODB_URL                   = _env("MONGODB_URL",                  "mongodb://localhost:27017")
MONGODB_DB                    = _env("MONGODB_DATABASE",             "hospital_ai")
MONGODB_USER_MEMORY_COLLECTION= _env("MONGODB_USER_MEMORY_COLL",     "user_memory")
MONGODB_CONV_SUMMARY_COLLECTION=_env("MONGODB_CONV_SUMMARY_COLL",    "conversation_summary")

# ── FastAPI (Agent Server) ─────────────────────────────────────────────────
APP_HOST = _env("API_HOST",       "0.0.0.0")
APP_PORT = int(_env("AGENT_API_PORT", "8005"))

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_TENANT  = _env("TENANT_ID",            "glh-chn")
MAX_RESULTS     = int(_env("MAX_DOCTOR_RESULTS",   "6"))
REQUEST_TIMEOUT = int(_env("TOOL_REQUEST_TIMEOUT", "10"))
