from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from flask import current_app, g

from .data import TABLES, USER_PASSWORDS


EDITABLE_TABLE_KEYS = (
    "suppliers",
    "contacts",
    "products",
    "offers",
    "purchaseorders",
    "users",
)

DATE_FIELDS = frozenset({"date", "deadline", "updated", "birthdate"})
DATE_INPUT_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
)

TABLE_NAME_MAP = {
    "suppliers": "suppliers",
    "contacts": "contacts",
    "products": "products",
    "offers": "offers",
    "purchaseorders": "purchaseorders",
    "users": "users",
}

EXTRA_FIELDS = {
    "purchaseorders": (
        "archived",
        "warehouse",
        "contact",
        "terms_and_conditions",
        "payment_timeframe",
        "delivery_timeframe",
        "delivery_transporter",
        "payment_methods",
    ),
}


class PostgresConnection:
    """Small DB-API compatibility layer for the existing ? placeholders."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @staticmethod
    def _adapt_query(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params: object = ()) -> Any:
        return self._connection.execute(self._adapt_query(query), params)

    def executemany(self, query: str, params: object) -> Any:
        with self._connection.cursor() as cursor:
            cursor.executemany(self._adapt_query(query), params)
            return cursor

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


def get_database_url() -> str:
    return str(
        current_app.config.get("DATABASE_URL")
        or os.environ.get("DATABASE_URL", "")
    ).strip()


def uses_postgres() -> bool:
    return bool(get_database_url())


def get_database_path() -> Path:
    configured = current_app.config.get("DATABASE")
    if configured:
        return Path(configured)
    return Path(current_app.root_path).parent / "data" / "nova_groups.sqlite3"


def get_db() -> Any:
    if "db" not in g:
        database_url = get_database_url()
        if database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as error:
                raise RuntimeError(
                    "DATABASE_URL is configured, but psycopg is not installed."
                ) from error
            connection = psycopg.connect(
                database_url,
                connect_timeout=10,
                row_factory=dict_row,
            )
            g.db = PostgresConnection(connection)
            return g.db
        path = get_database_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        database_uri = "file:" + path.resolve().as_posix() + "?mode=rwc&nolock=1"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


def table_exists(db: Any, table_name: str) -> bool:
    if uses_postgres():
        return (
            db.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = ?
                """,
                (table_name,),
            ).fetchone()
            is not None
        )
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def table_columns(db: Any, table_name: str) -> set[str]:
    if uses_postgres():
        rows = db.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?
            """,
            (table_name,),
        ).fetchall()
        return {str(row["column_name"]) for row in rows}
    return {
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def close_db(error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    for table_key in EDITABLE_TABLE_KEYS:
        ensure_records_table(table_key)
    ensure_order_products_table()
    ensure_invoice_products_table()
    ensure_invoice_order_totals_table()
    ensure_report_opening_balances_table()


def validate_table_key(table_key: str) -> None:
    if table_key not in EDITABLE_TABLE_KEYS:
        raise ValueError(f"Unsupported editable table: {table_key}")


def get_table_name(table_key: str) -> str:
    validate_table_key(table_key)
    return TABLE_NAME_MAP[table_key]


def get_visible_fields(table_key: str) -> tuple[str, ...]:
    validate_table_key(table_key)
    return tuple(key for key, _label in TABLES[table_key]["columns"])


def get_extra_fields(table_key: str) -> tuple[str, ...]:
    validate_table_key(table_key)
    return EXTRA_FIELDS.get(table_key, ())


def get_record_fields(table_key: str) -> tuple[str, ...]:
    return get_visible_fields(table_key) + get_extra_fields(table_key)


def ensure_records_table(table_key: str) -> None:
    db = get_db()
    table_name = get_table_name(table_key)
    fields = get_record_fields(table_key)
    table_existed = table_exists(db, table_name)
    column_sql = ", ".join(f"{field} TEXT NOT NULL DEFAULT ''" for field in fields)
    id_definition = (
        "BIGSERIAL PRIMARY KEY" if uses_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id {id_definition},
            {column_sql}
        )
        """
    )
    existing_columns = table_columns(db, table_name)
    for field in fields:
        if field not in existing_columns:
            db.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {field} TEXT NOT NULL DEFAULT ''"
            )

    if not table_existed:
        placeholders = ", ".join("?" for _field in fields)
        columns = ", ".join(fields)
        db.executemany(
            f"""
            INSERT INTO {table_name} ({columns})
            VALUES ({placeholders})
            """,
            [
                tuple(serialize_value(row.get(field, "")) for field in fields)
                for row in TABLES[table_key]["rows"]
            ],
        )
    if table_key == "users":
        for email, password in USER_PASSWORDS.items():
            db.execute(
                f"""
                UPDATE {table_name}
                SET password = ?
                WHERE email = ? AND (password = '' OR password IS NULL)
                """,
                (password, email),
            )
    db.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def list_suppliers() -> list[dict[str, object]]:
    return list_records("suppliers")


def update_suppliers(existing_rows: Iterable[dict[str, str]], new_row: dict[str, str]) -> None:
    save_records("suppliers", existing_rows, new_row)


def find_user_by_email(email: str) -> dict[str, object] | None:
    normalized_email = email.strip().lower()
    for user in list_records("users"):
        if str(user.get("email", "")).strip().lower() == normalized_email:
            return user
    return None


def update_user_password(email: str, password: str) -> None:
    db = get_db()
    db.execute(
        "UPDATE users SET password = ? WHERE lower(email) = lower(?)",
        (password.strip(), email.strip()),
    )
    db.commit()


def ensure_order_products_table() -> None:
    db = get_db()
    id_definition = (
        "BIGSERIAL PRIMARY KEY" if uses_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS order_products (
            id ID_DEFINITION_PLACEHOLDER,
            order_number TEXT NOT NULL,
            pharmacy TEXT NOT NULL DEFAULT '',
            product_id TEXT NOT NULL DEFAULT '',
            supplier TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            ppv TEXT NOT NULL DEFAULT '',
            pph TEXT NOT NULL DEFAULT '',
            tax TEXT NOT NULL DEFAULT '',
            barcode TEXT NOT NULL DEFAULT '',
            quantity TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL DEFAULT 0
        )
        """
        .replace("ID_DEFINITION_PLACEHOLDER", id_definition)
    )
    existing_columns = table_columns(db, "order_products")
    required_columns = {
        "order_number": "TEXT NOT NULL DEFAULT ''",
        "pharmacy": "TEXT NOT NULL DEFAULT ''",
        "product_id": "TEXT NOT NULL DEFAULT ''",
        "supplier": "TEXT NOT NULL DEFAULT ''",
        "name": "TEXT NOT NULL DEFAULT ''",
        "ppv": "TEXT NOT NULL DEFAULT ''",
        "pph": "TEXT NOT NULL DEFAULT ''",
        "tax": "TEXT NOT NULL DEFAULT ''",
        "barcode": "TEXT NOT NULL DEFAULT ''",
        "quantity": "TEXT NOT NULL DEFAULT ''",
        "position": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in required_columns.items():
        if column not in existing_columns:
            db.execute(f"ALTER TABLE order_products ADD COLUMN {column} {definition}")
    db.commit()


def ensure_invoice_products_table() -> None:
    db = get_db()
    id_definition = (
        "BIGSERIAL PRIMARY KEY" if uses_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_products (
            id ID_DEFINITION_PLACEHOLDER,
            order_number TEXT NOT NULL,
            product_id TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            discount_pct TEXT NOT NULL DEFAULT '',
            ug_pct TEXT NOT NULL DEFAULT '',
            pph_discounted TEXT NOT NULL DEFAULT ''
        )
        """
        .replace("ID_DEFINITION_PLACEHOLDER", id_definition)
    )
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS invoice_products_order_product
        ON invoice_products (order_number, product_id, name)
        """
    )
    db.commit()


def ensure_invoice_order_totals_table() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS invoice_order_totals (
            order_number TEXT PRIMARY KEY,
            total_discount_pct TEXT NOT NULL DEFAULT ''
        )
        """
    )
    db.commit()


def ensure_report_opening_balances_table() -> None:
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS report_opening_balances (
            pharmacy TEXT PRIMARY KEY,
            amount TEXT NOT NULL DEFAULT ''
        )
        """
    )
    db.commit()


def list_records(table_key: str, archived: bool | None = None) -> list[dict[str, object]]:
    table_name = get_table_name(table_key)
    fields = get_record_fields(table_key)
    selected_columns = ", ".join(("id",) + fields)
    rows = get_db().execute(
        f"SELECT {selected_columns} FROM {table_name} ORDER BY id"
    )
    records = [deserialize_row(table_key, dict(row)) for row in rows.fetchall()]
    if archived is not None:
        records = [
            record
            for record in records
            if bool(record.get("archived")) is bool(archived)
        ]
    return records


def update_purchase_order(order_number: str, values: dict[str, object]) -> int:
    db = get_db()
    fields = get_record_fields("purchaseorders")
    allowed_values = {
        field: serialize_value(normalize_field_value(field, values.get(field, "")))
        for field in fields
        if field in values
    }
    if not allowed_values:
        return 0
    assignments = ", ".join(f"{field} = ?" for field in allowed_values)
    cursor = db.execute(
        f"""
        UPDATE purchaseorders
        SET {assignments}
        WHERE number = ?
        """,
        tuple(allowed_values.values()) + (order_number,),
    )
    db.commit()
    return cursor.rowcount


def list_order_products(
    order_number: str,
    pharmacy: str | None = None,
) -> list[dict[str, object]]:
    where_clause = "WHERE order_number = ?"
    params = [str(order_number)]
    if pharmacy is not None:
        where_clause += " AND pharmacy = ?"
        params.append(str(pharmacy).strip())
    rows = get_db().execute(
        f"""
        SELECT pharmacy, product_id, supplier, name, ppv, pph, tax, barcode, quantity
        FROM order_products
        {where_clause}
        ORDER BY position, id
        """,
        tuple(params),
    )
    return [dict(row) for row in rows.fetchall()]


def list_invoice_products(order_number: str) -> list[dict[str, object]]:
    rows = get_db().execute(
        """
        SELECT order_number, product_id, name, discount_pct, ug_pct, pph_discounted
        FROM invoice_products
        WHERE order_number = ?
        ORDER BY id
        """,
        (str(order_number),),
    )
    return [dict(row) for row in rows.fetchall()]


def get_invoice_order_discount(order_number: str) -> str:
    row = get_db().execute(
        """
        SELECT total_discount_pct
        FROM invoice_order_totals
        WHERE order_number = ?
        """,
        (str(order_number).strip(),),
    ).fetchone()
    return str(row["total_discount_pct"] if row else "").strip()


def save_invoice_order_discount(order_number: str, value: object) -> None:
    order_value = str(order_number).strip()
    normalized = normalize_money_value(value)
    db = get_db()
    if not normalized:
        db.execute(
            "DELETE FROM invoice_order_totals WHERE order_number = ?",
            (order_value,),
        )
    else:
        db.execute(
            """
            INSERT INTO invoice_order_totals (order_number, total_discount_pct)
            VALUES (?, ?)
            ON CONFLICT(order_number) DO UPDATE SET total_discount_pct = excluded.total_discount_pct
            """,
            (order_value, normalized),
        )
    db.commit()


def list_report_opening_balances() -> dict[str, str]:
    rows = get_db().execute(
        "SELECT pharmacy, amount FROM report_opening_balances ORDER BY pharmacy"
    )
    return {
        str(row["pharmacy"]): str(row["amount"])
        for row in rows.fetchall()
        if str(row["pharmacy"]).strip()
    }


def save_report_opening_balances(values: dict[str, object]) -> None:
    db = get_db()
    for pharmacy, amount in values.items():
        pharmacy_value = str(pharmacy).strip()
        if not pharmacy_value:
            continue
        db.execute(
            """
            INSERT INTO report_opening_balances (pharmacy, amount)
            VALUES (?, ?)
            ON CONFLICT(pharmacy) DO UPDATE SET amount = excluded.amount
            """,
            (pharmacy_value, str(amount).strip()),
        )
    db.commit()


def save_invoice_products(
    order_number: str,
    products: Iterable[dict[str, object]],
) -> int:
    db = get_db()
    order_value = str(order_number).strip()
    db.execute(
        "DELETE FROM invoice_products WHERE order_number = ?",
        (order_value,),
    )
    values_to_insert = []
    for product in products:
        name = str(product.get("name", "")).strip()
        if not name:
            continue
        values_to_insert.append(
            (
                order_value,
                str(product.get("product_id", "")).strip(),
                name,
                str(product.get("discount_pct", "")).strip(),
                str(product.get("ug_pct", "")).strip(),
                str(product.get("pph_discounted", "")).strip(),
            )
        )
    if values_to_insert:
        db.executemany(
            """
            INSERT INTO invoice_products
                (order_number, product_id, name, discount_pct, ug_pct, pph_discounted)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            values_to_insert,
        )
    db.commit()
    return len(values_to_insert)


def save_order_products(
    order_number: str,
    products: Iterable[dict[str, object]],
    pharmacy: str = "",
) -> int:
    db = get_db()
    pharmacy_name = str(pharmacy).strip()
    db.execute(
        "DELETE FROM order_products WHERE order_number = ? AND pharmacy = ?",
        (str(order_number), pharmacy_name),
    )
    values_to_insert = []
    for position, product in enumerate(products, start=1):
        name = str(product.get("name", "")).strip()
        if not name:
            continue
        values_to_insert.append(
            (
                str(order_number),
                pharmacy_name,
                str(product.get("id", product.get("product_id", ""))).strip(),
                str(product.get("supplier", "")).strip(),
                name,
                str(product.get("ppv", product.get("sale_price", ""))).strip(),
                str(product.get("pph", product.get("unit_price", ""))).strip(),
                str(product.get("tax", "")).strip(),
                str(product.get("barcode", "")).strip(),
                str(product.get("quantity", "")).strip(),
                position,
            )
        )
    if values_to_insert:
        db.executemany(
            """
            INSERT INTO order_products
                (order_number, pharmacy, product_id, supplier, name, ppv, pph, tax, barcode, quantity, position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values_to_insert,
        )
    db.commit()
    return len(values_to_insert)


def replace_order_products(
    order_number: str,
    products: Iterable[dict[str, object]],
) -> int:
    """Replace every pharmacy line for an order, for manager-level edits."""
    db = get_db()
    db.execute(
        "DELETE FROM order_products WHERE order_number = ?",
        (str(order_number),),
    )
    values_to_insert = []
    for position, product in enumerate(products, start=1):
        name = str(product.get("name", "")).strip()
        pharmacy = str(product.get("pharmacy", "")).strip()
        if not name or not pharmacy:
            continue
        values_to_insert.append(
            (
                str(order_number),
                pharmacy,
                str(product.get("id", product.get("product_id", ""))).strip(),
                str(product.get("supplier", "")).strip(),
                name,
                str(product.get("ppv", product.get("sale_price", ""))).strip(),
                str(product.get("pph", product.get("unit_price", ""))).strip(),
                str(product.get("tax", "")).strip(),
                str(product.get("barcode", "")).strip(),
                str(product.get("quantity", "")).strip(),
                position,
            )
        )
    if values_to_insert:
        db.executemany(
            """
            INSERT INTO order_products
                (order_number, pharmacy, product_id, supplier, name, ppv, pph, tax, barcode, quantity, position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values_to_insert,
        )
    db.commit()
    return len(values_to_insert)


def save_records(
    table_key: str,
    existing_rows: Iterable[dict[str, str]],
    new_row: dict[str, str],
) -> None:
    db = get_db()
    table_name = get_table_name(table_key)
    visible_fields = get_visible_fields(table_key)
    fields = get_record_fields(table_key)
    for row in existing_rows:
        record_id = row.get("id", "").strip()
        if not record_id:
            continue
        cleaned = {
            field: normalize_field_value(field, row.get(field, ""))
            for field in fields
        }
        if not any(cleaned.get(field, "") for field in visible_fields):
            db.execute(f"DELETE FROM {table_name} WHERE id = ?", (record_id,))
            continue
        assignments = ", ".join(f"{field} = ?" for field in fields)
        db.execute(
            f"""
            UPDATE {table_name}
            SET {assignments}
            WHERE id = ?
            """,
            tuple(serialize_value(cleaned.get(field, "")) for field in fields)
            + (record_id,),
        )

    cleaned_new_row = {
        field: normalize_field_value(field, new_row.get(field, ""))
        for field in fields
    }
    if any(cleaned_new_row.get(field, "") for field in visible_fields):
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _field in fields)
        db.execute(
            f"""
            INSERT INTO {table_name} ({columns})
            VALUES ({placeholders})
            """,
            tuple(serialize_value(cleaned_new_row.get(field, "")) for field in fields),
        )
    db.commit()


def append_records(table_key: str, new_rows: Iterable[dict[str, str]]) -> int:
    db = get_db()
    table_name = get_table_name(table_key)
    visible_fields = get_visible_fields(table_key)
    fields = get_record_fields(table_key)
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _field in fields)
    values_to_insert = []

    for row in new_rows:
        cleaned = {
            field: normalize_field_value(field, row.get(field, ""))
            for field in fields
        }
        if not any(cleaned.get(field, "") for field in visible_fields):
            continue
        values_to_insert.append(
            tuple(serialize_value(cleaned.get(field, "")) for field in fields)
        )

    if values_to_insert:
        db.executemany(
            f"""
            INSERT INTO {table_name} ({columns})
            VALUES ({placeholders})
            """,
            values_to_insert,
        )
    db.commit()
    return len(values_to_insert)


def delete_records(table_key: str, record_ids: Iterable[str]) -> int:
    db = get_db()
    table_name = get_table_name(table_key)
    cleaned_ids = sorted(
        {
            int(record_id)
            for record_id in record_ids
            if str(record_id).strip().isdigit()
        }
    )
    if not cleaned_ids:
        return 0

    placeholders = ", ".join("?" for _record_id in cleaned_ids)
    cursor = db.execute(
        f"DELETE FROM {table_name} WHERE id IN ({placeholders})",
        tuple(cleaned_ids),
    )
    db.commit()
    return cursor.rowcount


def serialize_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def normalize_date_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    for input_format in DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(raw_value, input_format).date().isoformat()
        except ValueError:
            continue
    return raw_value


def format_date_for_display(value: object) -> str:
    normalized = normalize_date_value(value)
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return normalized


def normalize_field_value(field: str, value: object) -> object:
    if field in DATE_FIELDS:
        return normalize_date_value(value)
    if field in {"ppv", "pph"}:
        return normalize_money_value(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    return str(value).strip()


def normalize_money_value(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = raw.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return raw
    return format(amount, ".2f").replace(".", ",")


def deserialize_row(table_key: str, row: dict[str, object]) -> dict[str, object]:
    for field in DATE_FIELDS.intersection(row):
        row[field] = normalize_date_value(row.get(field, ""))
    if table_key == "purchaseorders":
        row["archived"] = str(row.get("archived", "")).lower() in ("1", "true", "yes")
    return row
