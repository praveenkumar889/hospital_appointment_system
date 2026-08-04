"""
api.py — Interface API Connector

Bridge between the WhatsApp Streamlit interface and the Agent FastAPI backend.
All defaults loaded from environment variables — zero hardcoding.
"""

import os
import httpx
from typing import Optional, Any, Dict

BACKEND_URL       = os.getenv("BACKEND_URL",       "http://localhost:8005")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "gleneagles")


def send_message_to_backend(
    phone:       str,
    message:     str,
    sender_name: str = "Patient",
    tenant_id:   str = DEFAULT_TENANT_ID,
) -> Optional[Dict[str, Any]]:
    """
    Sends a message to FastAPI /chat endpoint and converts response into UI format.
    """
    url = f"{BACKEND_URL}/chat"
    payload = {
        "message":    message,
        "session_id": f"session-{phone}",
        "user_id":    phone,
        "tenant_id":  tenant_id,
    }

    print("================================================================================")
    print(f"[TERMINAL 4: WHATSAPP WEB UI | File: src/interface/api.py]")
    print(f"  ↳ STEP 1: USER SENT MESSAGE: '{message}' (Phone: {phone}, Sender: {sender_name})")
    print(f"  ↳ ROUTING: Forwarding HTTP POST -> {url} (Terminal 3: Agent Server)")
    print(f"  ↳ REQUEST PAYLOAD: {payload}")

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                reply_text = data.get("reply", "No response received.")

                print(f"[TERMINAL 4: WHATSAPP WEB UI | File: src/interface/api.py]")
                print(f"  ↳ STEP FINAL: RECEIVED HTTP 200 OK FROM TERMINAL 3")
                print(f"  ↳ BOT REPLY RENDERED TO USER: '{reply_text}'")
                print(f"  ↳ TELEMETRY: Intent={data.get('intent')} | Needs={data.get('needs_info')}")
                print("================================================================================")

                return {
                    "replies": [{"type": "text", "body": reply_text}],
                    "debug": {
                        "intent":         data.get("intent", "UNKNOWN"),
                        "session_id":     data.get("session_id"),
                        "user_id":        data.get("user_id"),
                        "appointment_id": data.get("appointment_id"),
                        "needs_info":     data.get("needs_info", []),
                        "tenant_id":      tenant_id,
                    },
                }
            print(f"[TERMINAL 4 ERROR] HTTP Status {response.status_code}: {response.text}")
            return {
                "replies": [{"type": "text", "body": f"⚠️ Error: Backend returned status {response.status_code}"}],
                "debug":   {"intent": "ERROR", "tenant_id": tenant_id},
            }
    except Exception as e:
        print(f"[TERMINAL 4 CONNECTION ERROR] {e}")
        return {
            "replies": [{"type": "text", "body": f"⚠️ Connection Error: Is FastAPI running on {BACKEND_URL}?"}],
            "debug":   {"intent": "CONNECTION_ERROR", "tenant_id": tenant_id},
        }


def reset_session_on_backend(phone: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
    """
    Calls FastAPI backend /reset endpoint to reset conversation thread state.
    """
    url     = f"{BACKEND_URL}/reset"
    payload = {"user_id": phone, "tenant_id": tenant_id}
    print(f"[TERMINAL 4: WHATSAPP WEB UI | File: src/interface/api.py] Resetting session for phone: {phone}")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            return response.status_code == 200
    except Exception as e:
        print(f"[TERMINAL 4 RESET ERROR] {e}")
        return False