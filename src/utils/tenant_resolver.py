"""
tenant_resolver.py — Dynamic Production Tenant Resolver

Resolves `tenant_id` (Hospital Group) BEFORE request enters LangGraph.
Supported resolution strategies:
  1. WhatsApp Business Phone Number mapping (e.g., +919000000001 -> 'gleneagles')
  2. HTTP Header ('X-Tenant-ID: gleneagles')
  3. Domain / Hostname (e.g., gleneagles.hospital.ai -> 'gleneagles')
  4. Explicit request parameter
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("tenant_resolver")

# Production Tenant Registry (Phone Number -> Tenant ID)
PHONE_TENANT_MAP = {
    "919000000001": "gleneagles",
    "919000000002": "apollo",
    "919000000003": "aster",
    "919000000004": "fortis",
}

# Hostname Registry (Domain -> Tenant ID)
DOMAIN_TENANT_MAP = {
    "gleneagles.hospital.ai": "gleneagles",
    "apollo.hospital.ai":     "apollo",
    "aster.hospital.ai":      "aster",
    "fortis.hospital.ai":     "fortis",
}


class TenantResolver:
    """Production-grade Tenant Resolver for Multi-Tenant Hospital Platform."""

    @staticmethod
    def resolve_from_whatsapp_phone(to_phone: str) -> Optional[str]:
        """Resolves tenant_id from incoming WhatsApp Business phone number."""
        clean_phone = "".join(filter(str.isdigit, str(to_phone)))
        tenant_id = PHONE_TENANT_MAP.get(clean_phone)
        if tenant_id:
            logger.info(f"[TENANT RESOLVER] Phone '{to_phone}' resolved -> tenant_id='{tenant_id}'")
        return tenant_id

    @staticmethod
    def resolve_from_host(hostname: str) -> Optional[str]:
        """Resolves tenant_id from web domain / HTTP Host header."""
        clean_host = hostname.split(":")[0].lower()
        tenant_id = DOMAIN_TENANT_MAP.get(clean_host)
        if tenant_id:
            logger.info(f"[TENANT RESOLVER] Host '{hostname}' resolved -> tenant_id='{tenant_id}'")
        return tenant_id

    @staticmethod
    def resolve(
        explicit_tenant: Optional[str] = None,
        to_phone: Optional[str] = None,
        header_tenant: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> str:
        """
        Master resolution chain order:
        1. Explicit parameter (if valid)
        2. HTTP Header 'X-Tenant-ID'
        3. WhatsApp Business Phone Number
        4. Hostname
        5. Environment variable fallback
        """
        if explicit_tenant:
            return explicit_tenant

        if header_tenant:
            return header_tenant

        if to_phone:
            resolved = TenantResolver.resolve_from_whatsapp_phone(to_phone)
            if resolved:
                return resolved

        if hostname:
            resolved = TenantResolver.resolve_from_host(hostname)
            if resolved:
                return resolved

        # Default fallback from .env
        fallback = os.getenv("DEFAULT_TENANT_ID", os.getenv("DEFAULT_TENANT", "gleneagles"))
        logger.info(f"[TENANT RESOLVER] Using configured fallback -> tenant_id='{fallback}'")
        return fallback
