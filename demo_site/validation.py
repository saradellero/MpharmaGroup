from __future__ import annotations


def is_email(value: str) -> bool:
    value = value.strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def validate_login(form: dict[str, str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    email = form.get("email", "").strip()
    password = form.get("password", "")

    if not email:
        errors["email"] = "Saisissez une adresse e-mail."
    elif not is_email(email):
        errors["email"] = "Saisissez une adresse e-mail valide."

    if not password:
        errors["password"] = "Saisissez un mot de passe."

    return errors


def validate_recovery(form: dict[str, str]) -> dict[str, str]:
    email = form.get("email", "").strip()

    if not email:
        return {"email": "Saisissez l’adresse e-mail associée au compte."}
    if not is_email(email):
        return {"email": "Saisissez une adresse e-mail valide."}
    return {}


def required_fields(form: dict[str, str], names: list[str]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for name in names:
        if not form.get(name, "").strip():
            errors[name] = "Champ obligatoire."
    return errors
