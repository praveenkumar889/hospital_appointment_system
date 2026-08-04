"""
COMPLETE MINIMAL CONFIG.PY - Database-Driven Architecture
Location: C:\hospital_system\src\workflows\config.py

✅ ZERO hardcoding of branches
✅ ZERO hardcoding of messages
✅ All data fetches from SQLite database
✅ Easy to add new hospitals (DB only, no code changes)
✅ Production-ready
"""

from __future__ import annotations

import os
from src.knowledge_base.config import get_settings

settings = get_settings()

# ===== DATABASE PATH =====
# Gets from .env file DB_PATH, falls back to default
DEFAULT_DB_PATH = os.getenv("DB_PATH", "src/workflows/data/db/knowledge_base.db")

# ===== MINIMAL CLIENTS CONFIGURATION =====
# NO hardcoding of branches or messages!
# Everything fetches from database at runtime

CLIENTS = {
    # ===== GLENEAGLES HOSPITALS =====
    "gleneagles": {
        "name": "Gleneagles Hospitals",
        "db_path": DEFAULT_DB_PATH,
        "tenant_id": "gleneagles",
        # ✅ Branches: Loaded from hospitals table (WHERE tenant_id = 'gleneagles')
        # ✅ Messages: Loaded from message_templates table (WHERE tenant_id = 'gleneagles')
        # ✅ No hardcoding needed!
    },
    
    # ===== APOLLO HOSPITALS =====
    "apollo": {
        "name": "Apollo Hospitals",
        "db_path": DEFAULT_DB_PATH,
        "tenant_id": "apollo",
        # ✅ Branches: Loaded from hospitals table (WHERE tenant_id = 'apollo')
        # ✅ Messages: Loaded from message_templates table (WHERE tenant_id = 'apollo')
        # ✅ No hardcoding needed!
    },
    
    # ===== MAX HEALTHCARE =====
    "max_healthcare": {
        "name": "Max Healthcare",
        "db_path": DEFAULT_DB_PATH,
        "tenant_id": "max_healthcare",
        # ✅ Branches: Loaded from hospitals table (WHERE tenant_id = 'max_healthcare')
        # ✅ Messages: Loaded from message_templates table (WHERE tenant_id = 'max_healthcare')
        # ✅ No hardcoding needed!
    },
    
    # ===== FORTIS (Example: Add new hospital) =====
    # To add Fortis or any other hospital:
    # 1. Add a new entry here (OPTIONAL, even this is optional!)
    # 2. Add branches to hospitals table: 
    #    INSERT INTO hospitals (id, name, city, tenant_id) VALUES ('frt-delhi', 'Fortis Delhi', 'Delhi', 'fortis');
    # 3. Add messages to message_templates table:
    #    INSERT INTO message_templates (tenant_id, message_key, message_text) VALUES ('fortis', 'branch_selection_prompt', '...');
    # 4. Test with tenant_id = 'fortis'
    # ✅ NO code deployment needed!
}

# ===== HELPER FUNCTIONS =====

def get_client_config(tenant_id: str | None = None):
    """
    Get client configuration by tenant_id
    
    Args:
        tenant_id (str): Tenant ID (e.g., 'gleneagles', 'apollo')
    
    Returns:
        dict: Client configuration with db_path
    """
    tid = tenant_id or "gleneagles"
    if tid in CLIENTS:
        return CLIENTS[tid]
    else:
        # Default fallback
        return {
            "name": f"Unknown Hospital ({tid})",
            "db_path": DEFAULT_DB_PATH,
            "tenant_id": tid
        }


def get_all_tenants():
    """Get list of all configured tenants"""
    return list(CLIENTS.keys())


def get_db_path(tenant_id: str | None = None):
    """Get database path for a specific tenant"""
    client = get_client_config(tenant_id)
    return client.get("db_path", DEFAULT_DB_PATH)


def get_database_url(tenant_id: str | None = None) -> str:
    """Get SQLAlchemy SQLite database connection URL for a tenant."""
    path = get_db_path(tenant_id)
    if path.startswith("sqlite:///"):
        return path
    return f"sqlite:///{path}"


# ===== HOW AGENT USES THIS =====
"""
In agent.py (agent_FETCHES_FROM_DATABASE.py):

1. Agent receives tenant_id from API request
   Example: tenant_id = "gleneagles"

2. Agent calls: config.get_client_config("gleneagles")
   Returns: {"name": "Gleneagles Hospitals", "db_path": "..."}

3. Agent connects to database at db_path

4. Agent fetches branches:
   SELECT * FROM hospitals WHERE tenant_id = 'gleneagles'
   
5. Agent fetches messages:
   SELECT * FROM message_templates WHERE tenant_id = 'gleneagles'

6. Agent generates response with live data from database

7. User sees branches and messages from DATABASE, not hardcoded!

✅ ZERO hardcoding in code!
✅ All data from database!
✅ Easy to add hospitals!
"""

# ===== ENVIRONMENT VARIABLES REQUIRED =====
"""
Your .env file should have:

DB_PATH=src/workflows/data/db/knowledge_base.db

Example full .env:
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_AI_API_VERSION=2024-12-01-preview
DB_PATH=src/workflows/data/db/knowledge_base.db
MONGODB_URL=...
TENANT_ID=gleneagles
KB_API_PORT=8000
WORKFLOWS_API_PORT=8001
AGENT_API_PORT=8002
"""

# ===== DATABASE SCHEMA REQUIRED =====
"""
Your SQLite database should have these tables:

1. hospitals table:
   ├── id (TEXT) - Branch ID (e.g., 'glh-chn')
   ├── name (TEXT) - Branch name (e.g., 'Gleneagles HealthCity, Chennai')
   ├── city (TEXT) - City (e.g., 'Chennai')
   ├── phone (TEXT) - Phone number
   ├── email (TEXT) - Email
   ├── address (TEXT) - Address
   ├── tenant_id (TEXT) - Tenant ID (e.g., 'gleneagles')
   └── ... other columns

2. message_templates table:
   ├── id (INTEGER) - Message ID
   ├── tenant_id (TEXT) - Tenant ID (e.g., 'gleneagles')
   ├── message_key (TEXT) - Message key (e.g., 'branch_selection_prompt')
   ├── message_text (TEXT) - Message text with {variables}
   ├── created_at (TIMESTAMP)
   └── updated_at (TIMESTAMP)

Run database_setup.sql to create message_templates table with initial data.
"""

# ===== QUICK REFERENCE: ADDING DATA TO DATABASE =====
"""
To add a new Gleneagles branch:
INSERT INTO hospitals (id, name, city, phone, tenant_id) VALUES
('glh-new', 'Gleneagles New City', 'New City', '123-456-7890', 'gleneagles');

To change a message:
UPDATE message_templates 
SET message_text = 'New message' 
WHERE tenant_id = 'gleneagles' AND message_key = 'branch_selection_prompt';

To add a new hospital (Apollo):
-- Add branches
INSERT INTO hospitals (id, name, city, phone, tenant_id) VALUES
('apl-delhi', 'Apollo Delhi', 'Delhi', '011-4159-1111', 'apollo');

-- Add messages
INSERT INTO message_templates (tenant_id, message_key, message_text) VALUES
('apollo', 'branch_selection_prompt', '👏 Welcome to Apollo...');

-- Test
# tenant_id = 'apollo' in API request
"""

# ===== NOTES =====
"""
✅ This config is MINIMAL and CLEAN
✅ NO hardcoded branches (7 lines of config vs 50+ lines of data)
✅ NO hardcoded messages (0 lines vs 100+ lines of text)
✅ All data lives in database where it belongs
✅ Easy to modify without restarting code
✅ Easy to add new hospitals without code changes
✅ Production-ready architecture
✅ Truly scalable system

If you need to add hardcoded data for some reason (NOT RECOMMENDED):
Don't add it to config.py - add it to the database instead!
"""