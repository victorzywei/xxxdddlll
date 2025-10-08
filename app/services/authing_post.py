import os
import requests
from typing import Any, Dict


def update_preferred_username(
    user_id: str,
    preferred_username: str,
    token: str
) -> Dict[str, Any]:
    if not user_id or not preferred_username or not token:
        return {"ok": False, "error": "Missing Authing parameters"}

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Authorization": token,
    }

    userpool_id = os.getenv("AUTHING_USERPOOL_ID")
    if not userpool_id:
        return {"ok": False, "error": "AUTHING_USERPOOL_ID is not configured"}

    headers["x-authing-userpool-id"] = userpool_id

    endpoint = f"https://api.authing.cn/api/v2/users/{user_id}"
    response = requests.post(
        endpoint,
        headers=headers,
        json={"preferredUsername": preferred_username},
        timeout=10,
    )

    if response.status_code == 201:
        return {"ok": True, "status": response.status_code}

    return {
        "ok": False,
        "status": response.status_code,
        "statusText": response.reason,
    }




