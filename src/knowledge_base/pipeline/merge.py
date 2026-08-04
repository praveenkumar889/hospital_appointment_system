"""
src/pipeline/merge.py

Merge all data sources into a clean, deduplicated canonical dataset:

Sources:
  data/raw/api_doctors.json           — 465 doctors from selfregistration.co.in API
                                         (all Gleneagles locations, authoritative IDs)
  data/processed/doctors.json         — 103 web-scraped CHN doctors
                                         (bio, languages, experience, detailed qualifications)
  data/raw/schedule_api_checkpoint.json — 314 doctors' slot availability

Output:
  hospitals  : 7 Gleneagles locations (built from API location data)
  doctors    : 465 clean records with enrichment from web-scraper where matched
  schedules  : 314 schedule records keyed by new clean doctor slugs
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from loguru import logger

from src.knowledge_base.config import get_tenant_config, tenant_id_for_location, TenantConfig


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _normalize_name(raw: str) -> str:
    """Strip 'Dr ' prefix and any suffix after ' - ' / ' – '."""
    name = raw.strip()
    name = re.sub(r"^Dr\.?\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*[-–—]\s*.+$", "", name)  # drop " - Specialty" suffixes
    return name.lower().strip()


def _parse_qualifications(raw: str) -> list[str]:
    """
    Parse qualification string from API into list of degree abbreviations.
    Input:  "MBBS, MS (Gen Surgery), DrNB (Surgical Gastroenterology)"
    Output: ["MBBS", "MS", "DrNB"]
    """
    degrees = []
    for part in raw.split(","):
        part = part.strip()
        # Take only the abbreviation before any parenthetical
        deg = re.sub(r"\s*\(.*?\)", "", part).strip()
        if deg:
            degrees.append(deg)
    return degrees


# ── Hospital builder ───────────────────────────────────────────────────────────

def build_hospitals(api_doctors: list[dict], tenant_config: TenantConfig | None = None) -> list[dict]:
    """
    Derive one Hospital record per unique location_id from the API doctors list.
    Each record is tagged with its branch tenant_id via tenant_id_for_location().
    If tenant_config is provided, only hospitals for that tenant's location_id are built.
    """
    from src.knowledge_base.config import TENANT_META, _booking_base_url

    seen: dict[int, dict] = {}
    for doc in api_doctors:
        lid = doc.get("location_id")
        if lid is None or lid in seen:
            continue
        if tenant_config and lid != tenant_config.location_id:
            continue

        tid = tenant_id_for_location(lid)
        meta = TENANT_META.get(tid, TENANT_META.get("glh-chn", {}))
        loc_short = meta["loc_short"]
        city, state = meta["city"], meta["state"]

        seen[lid] = {
            "id": meta["hospital_id"],
            "name": doc.get("location_description") or tid.replace("-", " ").title().replace("Glh", "Gleneagles"),
            "branch": doc.get("location_name") or loc_short.upper(),
            "brand_description": doc.get("speciality_description") or f"a multi-specialty hospital in {city}",
            "city": city,
            "state": state,
            "location_id": lid,
            "loc_short": loc_short,
            "phone": doc.get("customer_care_number_portal"),
            "emergency_phone": doc.get("customer_care_number_portal"),
            "booking_base_url": _booking_base_url,
            "tenant_id": tid,
        }
    return sorted(seen.values(), key=lambda h: h["location_id"])


# ── Doctor merger ──────────────────────────────────────────────────────────────

def build_doctors(
    api_doctors: list[dict],
    scraped_doctors: list[dict],
    tenant_config: TenantConfig | None = None,
) -> tuple[list[dict], dict[int, str]]:
    """
    Merge API doctors (master, 465) with web-scraped profiles (enrichment, 103).

    Returns:
        doctors     — list of clean merged doctor dicts
        numeric_to_slug — {numeric_doctor_id: slug} lookup for schedule matching
    """

    # Build name-based lookup for web-scraped CHN doctors
    scraped_by_name: dict[str, dict] = {}
    for doc in scraped_doctors:
        key = _normalize_name(doc.get("name", ""))
        if key:
            scraped_by_name[key] = doc

    # Determine which tenants to process
    if tenant_config:
        tenant_ids_to_process = [tenant_config.tenant_id]
    else:
        from src.knowledge_base.config import TENANTS
        tenant_ids_to_process = list(TENANTS)

    # Pre-resolve tenant configs for each location_id
    loc_tc: dict[int, TenantConfig] = {}
    for tid in tenant_ids_to_process:
        t = get_tenant_config(tid)
        loc_tc[t.location_id] = t

    # Track slugs to detect collisions; track seen numeric IDs to merge multi-location doctors
    slug_used: set[str] = set()
    doctors: list[dict] = []
    numeric_to_slug: dict[int, str] = {}
    numeric_to_record: dict[int, dict] = {}  # detect same doctor at multiple locations

    for api_doc in api_doctors:
        num_id: int = api_doc["doctor_id"]
        first: str = (api_doc.get("first_name") or "").strip()
        last: str = (api_doc.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip()
        lid: int = api_doc.get("location_id", 0)

        # Skip records not belonging to the requested tenant(s)
        tc = loc_tc.get(lid)
        if tc is None:
            continue

        loc_short = tc.loc_short
        hospital_id = tc.hospital_id
        booking_base = tc.booking_base_url

        # Unique, readable slug
        base_slug = f"dr-{_slugify(first)}-{_slugify(last)}-{loc_short}" if (first or last) else f"dr-{num_id}"
        slug = base_slug
        if slug in slug_used:
            slug = f"{base_slug}-{num_id}"
        slug_used.add(slug)

        # If this numeric_doctor_id was already processed, just add the extra hospital
        if num_id in numeric_to_record:
            existing_rec = numeric_to_record[num_id]
            if hospital_id not in existing_rec["hospital_ids"]:
                existing_rec["hospital_ids"].append(hospital_id)
            continue

        # Try to enrich from web-scraped data (CHN doctors only)
        scraped: Optional[dict] = None
        if tc.tenant_id == "glh-chn" and lid == 80:
            api_name_key = _normalize_name(full_name)
            scraped = scraped_by_name.get(api_name_key)

        # Parse qualifications
        api_qual_str = api_doc.get("qualification") or ""
        api_degrees = _parse_qualifications(api_qual_str) if api_qual_str else []
        if scraped:
            scraped_degrees = [
                q["degree"] for q in (scraped.get("qualifications") or [])
                if isinstance(q, dict) and q.get("degree")
            ]
        else:
            scraped_degrees = []
        # Merge: scraped degrees first (more structured), then add any unique API degrees
        seen_degs = set(scraped_degrees)
        qualifications = list(scraped_degrees)
        for d in api_degrees:
            if d not in seen_degs:
                qualifications.append(d)
                seen_degs.add(d)

        # Specializations
        api_spec = api_doc.get("speciality") or api_doc.get("department_name") or ""
        specs_set: set[str] = set()
        if api_spec:
            specs_set.add(api_spec.strip())
        if scraped:
            for s in (scraped.get("specializations") or []):
                clean = re.sub(r"^Speciality", "", s).strip()
                if clean:
                    specs_set.add(clean)
        specializations = sorted(specs_set)

        # Profile image URL
        raw_img = api_doc.get("profile_image") or api_doc.get("profile_image_v1") or ""
        profile_image_url = raw_img if raw_img and raw_img != "NO_IMAGE" else None

        doc_record: dict = {
            "id": slug,
            "name": full_name,
            "first_name": first,
            "last_name": last,
            "gender": api_doc.get("Gender"),
            "numeric_doctor_id": num_id,
            "department_id": api_doc.get("department_id"),
            "location_id": lid,
            "appointment_type": api_doc.get("appointment_type"),
            "designation": api_doc.get("designation") or (scraped.get("designation") if scraped else None),
            "speciality": api_spec or None,
            "specializations": specializations,
            "qualifications": qualifications,
            "languages": scraped.get("languages", []) if scraped else [],
            "experience_years": scraped.get("experience_years") if scraped else None,
            "consultation_fee": scraped.get("consultation_fee") if scraped else None,
            "bio": ((scraped.get("bio") if scraped else None) or api_doc.get("description") or "").strip() or None,
            "phone": scraped.get("phone") if scraped else None,
            "profile_url": scraped.get("profile_url") if scraped else None,
            "profile_image_url": profile_image_url,
            "booking_url": (
                f"{booking_base}?location_name={loc_short}&doctor_id={num_id}"
                if api_doc.get("appointment_type") == "SELF_BOOK" and booking_base
                else None
            ),
            "hospital_ids": [hospital_id],
            "tenant_id": tc.tenant_id,
            # Enrichment metadata
            "expertise_areas": scraped.get("expertise_areas", []) if scraped else [],
            "procedures": scraped.get("procedures", []) if scraped else [],
        }
        doctors.append(doc_record)
        numeric_to_slug[num_id] = slug
        numeric_to_record[num_id] = doc_record

    logger.info(f"Merged {len(doctors)} doctors ({len(scraped_by_name)} web-scraped enrichments applied)")
    return doctors, numeric_to_slug


# ── Schedule builder ───────────────────────────────────────────────────────────

def build_schedules(
    checkpoint: dict[str, dict],
    numeric_to_slug: dict[int, str],
) -> list[dict]:
    """
    Re-key checkpoint schedules using clean doctor slugs from the merge.

    checkpoint keys are string numeric doctor_ids ("860085").
    """
    schedules = []
    missing = 0
    for num_str, sched in checkpoint.items():
        try:
            num_id = int(num_str)
        except ValueError:
            continue
        slug = numeric_to_slug.get(num_id)
        if slug is None:
            missing += 1
            continue
        clean = dict(sched)
        clean["doctor_id"] = slug
        clean["numeric_doctor_id"] = num_id
        schedules.append(clean)

    if missing:
        logger.warning(f"build_schedules: {missing} checkpoint entries had no matching doctor slug")
    logger.info(f"Built {len(schedules)} schedules from checkpoint")
    return schedules


# ── Top-level entry point ──────────────────────────────────────────────────────

def load_and_merge(
    api_file: str | None = None,
    scraped_file: str | None = None,
    checkpoint_file: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """
    Load all raw data files and return merged canonical dicts.

    Returns:
        {
          "hospitals": [...],
          "doctors":   [...],
          "schedules": [...],
        }
    """
    raw_dir = Path("data/raw")
    proc_dir = Path("data/processed")

    api_path = Path(api_file or raw_dir / "api_doctors.json")
    scraped_path = Path(scraped_file or proc_dir / "doctors.json")
    chk_path = Path(checkpoint_file or raw_dir / "schedule_api_checkpoint.json")

    api_doctors: list[dict] = json.loads(api_path.read_text(encoding="utf-8"))
    scraped_doctors: list[dict] = json.loads(scraped_path.read_text(encoding="utf-8")) if scraped_path.exists() else []
    checkpoint: dict = json.loads(chk_path.read_text(encoding="utf-8")) if chk_path.exists() else {}

    logger.info(f"Source counts — API: {len(api_doctors)}, scraped: {len(scraped_doctors)}, checkpoint: {len(checkpoint)}")

    # When tenant_id is provided, scope the merge to that tenant.
    # When None, process all configured tenants.
    merge_tc = get_tenant_config(tenant_id) if tenant_id else None
    hospitals = build_hospitals(api_doctors, merge_tc)
    doctors, numeric_to_slug = build_doctors(api_doctors, scraped_doctors, merge_tc)
    schedules = build_schedules(checkpoint, numeric_to_slug)

    logger.success(f"Merge complete: {len(hospitals)} hospitals, {len(doctors)} doctors, {len(schedules)} schedules")
    return {"hospitals": hospitals, "doctors": doctors, "schedules": schedules}
