"""
memory.py — Long-Term Memory (MongoDB)

Persistence layer with two collections:
  1. user_memory          — patient profile, preferences, & long-term summary (keyed by user_id + tenant_id)
  2. conversation_summary — per-workflow/session summary records

No LLM logic here — pure persistence.
Falls back gracefully to in-memory storage if MongoDB is unavailable.
"""

from datetime import datetime, timezone
import config


class MemoryService:
    """Loads and saves user memory and conversation summaries in MongoDB."""

    def __init__(self):
        self._user_memory_col = None
        self._conv_summary_col = None
        self._available = False
        self._fallback_user: dict = {}
        self._fallback_conv: list = []
        self._connect()

    def _connect(self) -> None:
        """Connect to MongoDB silently. Fallback if unreachable."""
        try:
            from pymongo import MongoClient
            client = MongoClient(config.MONGODB_URL, serverSelectionTimeoutMS=2000)
            client.server_info()
            db = client[config.MONGODB_DB]
            self._user_memory_col = db[config.MONGODB_USER_MEMORY_COLLECTION]
            self._conv_summary_col = db[config.MONGODB_CONV_SUMMARY_COLLECTION]
            self._available = True
        except Exception:
            self._available = False

    # ── Public API ─────────────────────────────────────────────────────────

    def load(self, user_id: str, tenant_id: str) -> dict:
        """Load profile memory and recent conversation summaries for a user in a tenant."""
        empty = {"preferences": {}, "summary": "", "booking_history": []}
        if not self._available:
            fb = self._fallback_user.get((user_id, tenant_id), empty)
            history = [c for c in self._fallback_conv if c.get("user_id") == user_id and c.get("tenant_id") == tenant_id]
            return {"preferences": fb.get("preferences", {}), "summary": fb.get("summary", ""), "booking_history": history}

        profile = self._user_memory_col.find_one({"user_id": user_id, "tenant_id": tenant_id}) or {}
        summaries = list(self._conv_summary_col.find(
            {"user_id": user_id, "tenant_id": tenant_id}, {"_id": 0}
        ).sort("created_at", -1).limit(10))

        return {
            "preferences": profile.get("preferences", {}),
            "summary":     profile.get("summary", ""),
            "booking_history": summaries,
        }

    def save_user_memory(self, user_id: str, tenant_id: str, preferences: dict, summary: str) -> None:
        """Update or create user profile memory for a tenant."""
        now = datetime.now(timezone.utc).isoformat()
        doc = {"user_id": user_id, "tenant_id": tenant_id, "preferences": preferences, "summary": summary, "updated_at": now}
        if not self._available:
            self._fallback_user[(user_id, tenant_id)] = doc
            return
        self._user_memory_col.update_one(
            {"user_id": user_id, "tenant_id": tenant_id},
            {"$set": doc},
            upsert=True,
        )

    def save_conversation_summary(
        self, session_id: str, user_id: str, tenant_id: str, workflow_type: str, summary: str, data: dict
    ) -> None:
        """Save a record of a completed conversation workflow."""
        doc = {
            "conversation_id": session_id,
            "user_id":         user_id,
            "tenant_id":       tenant_id,
            "workflow":        workflow_type,
            "summary":         summary,
            "data":            {k: v for k, v in data.items() if v is not None},
            "created_at":      datetime.now(timezone.utc).isoformat(),
        }
        if not self._available:
            self._fallback_conv.append(doc)
            return
        self._conv_summary_col.update_one(
            {"conversation_id": session_id},
            {"$set": doc},
            upsert=True,
        )
    