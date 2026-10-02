from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Brand:
    strong: str
    light: str


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    endpoint: str
    icon: str


BRAND = Brand(strong="Mpharma", light="Groups")

SUPPORT_EMAIL = "support@example.com"

NAV_ITEMS = (
    NavItem("dashboard", "Inicio", "dashboard", "home"),
    NavItem("suppliers", "Proveedores", "suppliers", "truck"),
    NavItem("products", "Productos", "products", "box"),
    NavItem("offers", "Ofertas", "offers", "tag"),
    NavItem("purchaseorders", "Pedidos", "purchaseorders", "file"),
    NavItem("events", "Eventos", "events", "calendar"),
    NavItem("reports", "Reportes", "reports", "chart"),
    NavItem("users", "Farmacias", "users", "users"),
    NavItem("settings", "Ajustes", "profile", "gear"),
)

DASHBOARD_STATS = [
    {"label": "Pedidos abiertos", "value": "18", "trend": "+4 esta semana"},
    {"label": "Proveedores activos", "value": "42", "trend": "6 nuevos"},
    {"label": "Productos seguidos", "value": "1 284", "trend": "catalogo demo"},
    {"label": "Importe estimado", "value": "236K MAD", "trend": "periodo actual"},
]

SUPPLIERS = [
    {
        "name": "Atlas Distribution",
        "phone": "05 20 10 12 30",
        "email": "contact@atlas.example",
        "address": "14 rue des Industries",
        "city": "Casablanca",
    },
    {
        "name": "Medica Nord",
        "phone": "05 39 22 40 90",
        "email": "hello@medicanord.example",
        "address": "Avenue des Laboratoires",
        "city": "Tanger",
    },
    {
        "name": "Sante Plus",
        "phone": "05 37 90 44 11",
        "email": "sales@santeplus.example",
        "address": "Zone commerciale Ouest",
        "city": "Rabat",
    },
    {
        "name": "Green Care Labs",
        "phone": "05 24 66 18 72",
        "email": "orders@greencare.example",
        "address": "Parc industriel Menara",
        "city": "Marrakech",
    },
]

CONTACTS = [
    {
        "first_name": "Nadia",
        "last_name": "Kabbaj",
        "phone": "06 01 11 22 33",
        "title": "Responsable comptes",
        "supplier": "Atlas Distribution",
    },
    {
        "first_name": "Youssef",
        "last_name": "Amrani",
        "phone": "06 02 22 33 44",
        "title": "Commercial",
        "supplier": "Medica Nord",
    },
    {
        "first_name": "Leila",
        "last_name": "Bennis",
        "phone": "06 03 44 55 66",
        "title": "Support commandes",
        "supplier": "Sante Plus",
    },
]

PRODUCTS = [
    {
        "supplier": "Atlas Distribution",
        "name": "Gel apaisant 120 ml",
        "ppv": "48.90",
        "pph": "32.30",
        "tax": "7%",
        "barcode": "6110001000012",
    },
    {
        "supplier": "Medica Nord",
        "name": "Vitamine C 30 comprimes",
        "ppv": "72.00",
        "pph": "50.40",
        "tax": "20%",
        "barcode": "6110001000029",
    },
    {
        "supplier": "Sante Plus",
        "name": "Solution hygiene 250 ml",
        "ppv": "36.00",
        "pph": "24.10",
        "tax": "10%",
        "barcode": "6110001000036",
    },
    {
        "supplier": "Green Care Labs",
        "name": "Creme mains protectrice",
        "ppv": "59.50",
        "pph": "41.60",
        "tax": "20%",
        "barcode": "6110001000043",
    },
]

OFFERS = [
    {
        "number": "2401",
        "subject": "Pack hiver pharmacie",
        "supplier": "Atlas Distribution",
        "deadline": "2026-07-15",
        "products": 12,
    },
    {
        "number": "2402",
        "subject": "Operation hygiene familiale",
        "supplier": "Sante Plus",
        "deadline": "2026-07-30",
        "products": 8,
    },
    {
        "number": "2403",
        "subject": "Selection dermo-cosmetique",
        "supplier": "Green Care Labs",
        "deadline": "2026-08-10",
        "products": 18,
    },
]

PURCHASE_ORDERS = [
    {
        "number": "105900",
        "subject": "Commande groupe juin",
        "manager": "Sara Demo",
        "supplier": "Atlas Distribution",
        "deadline": "2026-06-28",
        "updated": "2026-06-18",
        "products": 7,
        "quantity": 180,
        "status": "Ouverte",
        "archived": False,
    },
    {
        "number": "105901",
        "subject": "Selection vitamines",
        "manager": "Mina Test",
        "supplier": "Medica Nord",
        "deadline": "2026-07-04",
        "updated": "2026-06-16",
        "products": 4,
        "quantity": 95,
        "status": "Sauvegardee",
        "archived": False,
    },
    {
        "number": "104820",
        "subject": "Operation printemps",
        "manager": "Sara Demo",
        "supplier": "Sante Plus",
        "deadline": "2026-04-12",
        "updated": "2026-04-14",
        "products": 11,
        "quantity": 310,
        "status": "Cloturee",
        "archived": True,
    },
]

USERS = [
    {
        "pharmacy": "Pharmacie Horizon",
        "first_name": "Sara",
        "last_name": "Demo",
        "email": "sara.demo@example.com",
        "password": "admin123",
        "phone": "06 15 65 75 39",
        "admin": "Oui",
        "status": "Actif",
    },
    {
        "pharmacy": "Pharmacie Atlas",
        "first_name": "Mina",
        "last_name": "Test",
        "email": "mina.test@example.com",
        "password": "atlas123",
        "phone": "06 20 20 20 20",
        "admin": "Non",
        "status": "Actif",
    },
    {
        "pharmacy": "Pharmacie Riviera",
        "first_name": "Omar",
        "last_name": "Example",
        "email": "omar.example@example.com",
        "password": "riviera123",
        "phone": "06 33 44 55 66",
        "admin": "Non",
        "status": "Actif",
    },
]

USER_PASSWORDS = {user["email"]: user["password"] for user in USERS}

CALENDAR_EVENTS = [
    {"day": 2, "title": "Relance fournisseurs", "supplier": "Atlas Distribution"},
    {"day": 8, "title": "Cloture commande vitamines", "supplier": "Medica Nord"},
    {"day": 15, "title": "Reunion groupement", "supplier": "Interne"},
    {"day": 23, "title": "Validation offres hygiene", "supplier": "Sante Plus"},
]

REPORT_BALANCE = [
    {
        "pharmacist": "Sara Demo",
        "supported": "18 200 MAD",
        "consumed": "14 900 MAD",
        "diff": "3 300 MAD",
        "user_id": "1001",
    },
    {
        "pharmacist": "Mina Test",
        "supported": "9 700 MAD",
        "consumed": "11 200 MAD",
        "diff": "-1 500 MAD",
        "user_id": "1002",
    },
    {
        "pharmacist": "Omar Example",
        "supported": "4 100 MAD",
        "consumed": "2 800 MAD",
        "diff": "1 300 MAD",
        "user_id": "1003",
    },
]

REPORT_LABS = [
    {"supplier": "Atlas Distribution", "quantity": 420, "amount": "82 400 MAD"},
    {"supplier": "Medica Nord", "quantity": 260, "amount": "55 100 MAD"},
    {"supplier": "Sante Plus", "quantity": 190, "amount": "31 800 MAD"},
]

PROFILE = {
    "email": "sara.demo@example.com",
    "first_name": "Sara",
    "last_name": "Demo",
    "pharmacy_name": "Pharmacie Horizon",
    "mobile": "06 15 65 75 39",
    "phone": "05 39 68 89 07",
    "address": "Boulevard Central",
    "city": "Tetouan",
    "country": "Maroc",
    "language": "fr",
    "time_zone": "Africa/Casablanca",
}

ORDER_DETAIL = {
    "owner_id": "1001",
    "warehouse": "Principal",
    "subject": "Commande groupe juin",
    "deadline": "2026-06-28",
    "supplier": "Atlas Distribution",
    "contact": "Nadia Kabbaj",
    "payment_timeframe": "30 jours",
    "delivery_timeframe": "72 heures",
    "delivery_transporter": "Transport local",
    "payment_methods": ["cash", "check"],
    "products": [
        {
            "name": "Gel apaisant 120 ml",
            "sale_price": "48.90",
            "unit_price": "32.30",
            "discount": "1U = 12%",
            "tax": "7%",
        },
        {
            "name": "Vitamine C 30 comprimes",
            "sale_price": "72.00",
            "unit_price": "50.40",
            "discount": "1U = 18%",
            "tax": "20%",
        },
        {
            "name": "Creme mains protectrice",
            "sale_price": "59.50",
            "unit_price": "41.60",
            "discount": "Aucune remise",
            "tax": "20%",
        },
    ],
}

TABLES: dict[str, dict[str, Any]] = {
    "suppliers": {
        "title": "Proveedores",
        "active": "suppliers",
        "create_endpoint": None,
        "columns": [
            ("name", "Nombre"),
            ("phone", "Telefono"),
            ("email", "Email"),
            ("address", "Direccion"),
            ("city", "Ciudad"),
        ],
        "rows": SUPPLIERS,
    },
    "contacts": {
        "title": "Contactos",
        "active": "suppliers",
        "create_endpoint": "contact_create",
        "columns": [
            ("first_name", "Nombre"),
            ("last_name", "Apellido"),
            ("phone", "Telefono"),
            ("title", "Cargo"),
            ("supplier", "Proveedor"),
        ],
        "rows": CONTACTS,
    },
    "products": {
        "title": "Productos",
        "active": "products",
        "create_endpoint": None,
        "columns": [
            ("supplier", "Proveedor"),
            ("name", "Producto"),
            ("ppv", "PPV"),
            ("pph", "PPH"),
            ("tax", "IVA"),
            ("barcode", "Codigo"),
        ],
        "rows": PRODUCTS,
    },
    "offers": {
        "title": "Ofertas",
        "active": "offers",
        "create_endpoint": None,
        "columns": [
            ("number", "N."),
            ("subject", "Objeto"),
            ("supplier", "Proveedor"),
            ("deadline", "Fecha limite"),
            ("products", "Productos"),
        ],
        "rows": OFFERS,
    },
    "purchaseorders": {
        "title": "Pedidos",
        "active": "purchaseorders",
        "create_endpoint": "purchaseorder_create",
        "columns": [
            ("number", "N."),
            ("subject", "Objeto"),
            ("manager", "Gestor"),
            ("supplier", "Proveedor"),
            ("deadline", "Fecha limite"),
            ("updated", "Actualizado"),
            ("products", "Productos"),
            ("quantity", "Cantidad"),
            ("status", "Estado"),
        ],
        "rows": PURCHASE_ORDERS,
    },
    "users": {
        "title": "Farmacias",
        "active": "users",
        "create_endpoint": None,
        "columns": [
            ("pharmacy", "Farmacia"),
            ("first_name", "Nombre"),
            ("last_name", "Apellido"),
            ("email", "Email"),
            ("password", "Contrasena"),
            ("phone", "Telefono"),
            ("admin", "Admin"),
            ("status", "Estado"),
        ],
        "rows": USERS,
    },
}
