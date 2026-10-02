from __future__ import annotations

from typing import Mapping

from .storage import find_user_by_email


def authenticate_user(email: str, password: str) -> dict[str, object] | None:
    user = find_user_by_email(email)
    if not user:
        return None
    if str(user.get("password", "")) != password:
        return None
    if str(user.get("status", "")).strip().lower() in {"inactif", "inactivo", "inactive"}:
        return None
    return build_session_user(user)


def build_session_user(user: Mapping[str, object]) -> dict[str, object]:
    is_admin = is_admin_record(user)
    first_name = str(user.get("first_name", "")).strip()
    last_name = str(user.get("last_name", "")).strip()
    name = " ".join(part for part in (first_name, last_name) if part).strip()
    return {
        "name": name or str(user.get("pharmacy", "Usuario")),
        "email": str(user.get("email", "")),
        "role": "Administrador" if is_admin else "Farmacia",
        "pharmacy": str(user.get("pharmacy", "")),
        "first_name": first_name,
        "last_name": last_name,
        "phone": str(user.get("phone", "")),
        "is_admin": is_admin,
    }


def is_admin_record(user: Mapping[str, object] | None) -> bool:
    if not user:
        return False
    value = str(user.get("admin", user.get("is_admin", ""))).strip().lower()
    return value in {"1", "true", "yes", "oui", "si", "admin", "administrador"}


def is_admin_user(user: Mapping[str, object] | None) -> bool:
    if not user:
        return False
    return bool(user.get("is_admin")) or str(user.get("role", "")).lower() in {
        "admin",
        "administrador",
        "administradora",
    }


def can_edit_table(user: Mapping[str, object] | None, table_key: str) -> bool:
    return is_admin_user(user) or table_key == "purchaseorders"


def visible_nav_items(user: Mapping[str, object] | None, nav_items: tuple) -> tuple:
    return nav_items
