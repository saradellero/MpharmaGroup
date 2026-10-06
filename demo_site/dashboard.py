from __future__ import annotations

from collections.abc import Callable


CLOSED_STATUSES = {"cloturee", "cloture", "cerrado", "cerrada", "closed", "archivado"}
INACTIVE_STATUSES = {"inactif", "inactivo", "inactive"}


def build_dashboard_stats(list_records: Callable) -> list[dict[str, str]]:
    suppliers = list_records("suppliers")
    contacts = list_records("contacts")
    products = list_records("products")
    offers = list_records("offers")
    users = list_records("users")
    current_orders = list_records("purchaseorders", archived=False)

    open_orders = [
        order
        for order in current_orders
        if normalize(order.get("status")) not in CLOSED_STATUSES
    ]
    active_users = [
        user
        for user in users
        if normalize(user.get("status")) not in INACTIVE_STATUSES
    ]
    total_quantity = sum(parse_int(order.get("quantity")) for order in open_orders)

    return [
        {
            "label": "Pedidos abiertos",
            "value": format_number(len(open_orders)),
            "trend": f"{format_number(total_quantity)} unidades en curso",
            "endpoint": "purchaseorders",
        },
        {
            "label": "Proveedores activos",
            "value": format_number(len(suppliers)),
            "trend": f"{format_number(len(contacts))} contactos registrados",
            "endpoint": "suppliers",
        },
        {
            "label": "Productos seguidos",
            "value": format_number(len(products)),
            "trend": f"{format_number(len(offers))} ofertas disponibles",
            "endpoint": "products",
        },
        {
            "label": "Farmacias activas",
            "value": format_number(len(active_users)),
            "trend": f"{format_number(len(users))} cuentas totales",
            "endpoint": "users",
        },
    ]


def normalize(value: object) -> str:
    return str(value or "").strip().lower()


def parse_int(value: object) -> int:
    text = str(value or "").replace(" ", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def format_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")
