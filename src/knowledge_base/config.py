from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Tenant Configuration ────────────────────────────────────────────────────────
# Each tenant = one hospital branch.
# Tenant ID matches the hospital ID (e.g. "glh-chn" for Gleneagles Chennai).
# Define tenants in tenants.json at the project root (see tenants.json for format).
# The hardcoded dict below serves as a fallback when the file is missing.


@dataclass
class TenantConfig:
    """Identity and branding for a hospital branch tenant."""

    tenant_id: str = "glh-chn"
    brand_name: str = "Gleneagles HealthCity Chennai"
    brand_description: str = "a multi-specialty hospital in Chennai"
    currency_symbol: str = "₹"
    item_noun: str = "doctor"
    item_noun_plural: str = "doctors"
    contact_phone: str = "044 4624 2424"
    booking_base_url: str = "https://www.gleneagleshospitals.co.in/book-an-appointment"
    location_id: int = 80
    loc_short: str = "chn"
    city: str = "Chennai"
    state: str = "Tamil Nadu"
    hospital_id: str = "glh-chn"

    def format(self, template: str) -> str:
        """Render a template string with tenant variables."""
        return (
            template
            .replace("{brand_name}", self.brand_name)
            .replace("{brand_description}", self.brand_description)
            .replace("{brand}", self.brand_name)
            .replace("{currency}", self.currency_symbol)
            .replace("{item_noun}", self.item_noun)
            .replace("{item_noun_plural}", self.item_noun_plural)
            .replace("{contact_phone}", self.contact_phone)
            .replace("{tenant_id}", self.tenant_id)
        )


# ── Tenant topology ─────────────────────────────────────────────────────────────
# Minimal mapping of location_id → tenant identity.
# This defines WHICH tenants exist and is needed at build time before the DB is populated.
# All display/branding data (name, phone, description, etc.) is loaded from SQLite at runtime.

TENANT_META: dict[str, dict] = {
    "glh-chn":     {"location_id": 80,  "loc_short": "chn",     "city": "Chennai",    "state": "Tamil Nadu",    "hospital_id": "glh-chn"},
    "glh-adyar":   {"location_id": 81,  "loc_short": "adyar",   "city": "Chennai",    "state": "Tamil Nadu",    "hospital_id": "glh-adyar"},
    "glh-kengeri": {"location_id": 82,  "loc_short": "kengeri", "city": "Bengaluru",  "state": "Karnataka",     "hospital_id": "glh-kengeri"},
    "glh-richmond":{"location_id": 83,  "loc_short": "richmond","city": "Bengaluru",  "state": "Karnataka",     "hospital_id": "glh-richmond"},
    "glh-parel":   {"location_id": 84,  "loc_short": "parel",   "city": "Mumbai",     "state": "Maharashtra",   "hospital_id": "glh-parel"},
    "glh-lkp":     {"location_id": 85,  "loc_short": "lkp",     "city": "Hyderabad",  "state": "Telangana",     "hospital_id": "glh-lkp"},
    "glh-lbn":     {"location_id": 86,  "loc_short": "lbn",     "city": "Hyderabad",  "state": "Telangana",     "hospital_id": "glh-lbn"},
}

LOCATION_TO_TENANT: dict[int, str] = {
    meta["location_id"]: tid
    for tid, meta in TENANT_META.items()
}

TENANTS: tuple[str, ...] = tuple(TENANT_META.keys())

_currency = "₹"
_item_noun = "doctor"
_item_noun_plural = "doctors"
_booking_base_url = "https://www.gleneagleshospitals.co.in/book-an-appointment"


def tenant_id_for_location(location_id: int) -> str:
    """Map a location_id to the tenant_id that owns it."""
    return LOCATION_TO_TENANT.get(location_id, "glh-chn")


def get_tenant_config(tenant_id: Optional[str] = None) -> TenantConfig:
    """Resolve a TenantConfig by id from TENANT_META."""
    tid = tenant_id or get_settings().tenant_id
    meta = TENANT_META.get(tid)
    if not meta:
        meta = TENANT_META.get("glh-chn", {})
        tid = "glh-chn"

    return TenantConfig(
        tenant_id=tid,
        brand_name=tid.replace("-", " ").title().replace("Glh", "Gleneagles"),
        brand_description=f"a hospital in {meta['city']}",
        currency_symbol=_currency,
        item_noun=_item_noun,
        item_noun_plural=_item_noun_plural,
        contact_phone="",
        booking_base_url=_booking_base_url,
        location_id=meta["location_id"],
        loc_short=meta["loc_short"],
        city=meta["city"],
        state=meta["state"],
        hospital_id=meta["hospital_id"],
    )


# ── Application Settings ────────────────────────────────────────────────────────


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Default tenant (used when no tenant_id is explicitly provided)
    tenant_id: str

    # Neo4j AuraDB  (env vars: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE)
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str

    # ChromaDB
    chroma_persist_dir: str

    # Azure OpenAI
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str
    azure_openai_deployment_name: str

    # Embeddings
    embedding_model: str
    embedding_device: str

    # API
    api_host: str
    api_port: int

    # SQL — SQLite (structured facts: doctors, hospitals, schedules, slots)
    sqlite_path: str

    # Scraper / build (optional — only needed when running data import)
    gleneagles_base_url: Optional[str] = None
    scrape_hospital_id: Optional[int] = None
    scrape_delay_seconds: Optional[float] = None
    scrape_max_pages: Optional[int] = None
    raw_data_dir: Optional[str] = None
    processed_data_dir: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
