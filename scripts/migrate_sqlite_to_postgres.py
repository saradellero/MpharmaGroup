from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demo_site.app import create_app
from demo_site.storage import (
    get_db,
    get_record_fields,
    table_columns,
)


TABLES = (
    "suppliers",
    "contacts",
    "products",
    "offers",
    "purchaseorders",
    "users",
    "order_products",
    "invoice_products",
    "invoice_order_totals",
    "report_opening_balances",
)


def columns_for(table_name: str) -> tuple[str, ...]:
    if table_name in {"suppliers", "contacts", "products", "offers", "purchaseorders", "users"}:
        return ("id",) + get_record_fields(table_name)
    if table_name == "order_products":
        return (
            "id", "order_number", "pharmacy", "product_id", "supplier", "name",
            "ppv", "pph", "tax", "barcode", "quantity", "position",
        )
    if table_name == "invoice_products":
        return (
            "id", "order_number", "product_id", "name", "discount_pct",
            "ug_pct", "pph_discounted",
        )
    if table_name == "invoice_order_totals":
        return ("order_number", "total_discount_pct")
    if table_name == "report_opening_balances":
        return ("pharmacy", "amount")
    raise ValueError(f"Unsupported table: {table_name}")


def sqlite_rows(connection: sqlite3.Connection, table_name: str) -> list[dict[str, object]]:
    available = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    columns = columns_for(table_name)
    selected = ", ".join(column for column in columns if column in available)
    if not selected:
        return []
    rows = connection.execute(f"SELECT {selected} FROM {table_name}").fetchall()
    return [dict(zip(selected.split(", "), row, strict=True)) for row in rows]


def migrate(sqlite_path: Path, postgres_url: str) -> None:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    parsed_url = urlparse(postgres_url)
    if parsed_url.scheme not in {"postgres", "postgresql"} or not parsed_url.hostname:
        raise ValueError(
            "La URL de Supabase debe ser la cadena de conexion PostgreSQL "
            "copiada desde Connect > Connection string > URI. "
            "Debe empezar por postgresql:// o postgres://, no por https://."
        )
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    try:
        app = create_app({"DATABASE_URL": postgres_url})
        with app.app_context():
            target = get_db()
            target_tables = {
                "suppliers", "contacts", "products", "offers", "purchaseorders",
                "users", "order_products", "invoice_products", "invoice_order_totals",
                "report_opening_balances",
            }
            for table_name in TABLES:
                if table_name not in target_tables:
                    continue
                target.execute(f"DELETE FROM {table_name}")

            for table_name in TABLES:
                rows = sqlite_rows(source, table_name)
                if not rows:
                    continue
                target_columns = set(table_columns(target, table_name))
                columns = tuple(
                    column for column in columns_for(table_name)
                    if column in target_columns and column in rows[0]
                )
                placeholders = ", ".join("?" for _ in columns)
                quoted_columns = ", ".join(columns)
                target.executemany(
                    f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({placeholders})",
                    [tuple(row.get(column, "") for column in columns) for row in rows],
                )
                if "id" in columns:
                    target.execute(
                        """
                        SELECT setval(
                            pg_get_serial_sequence(?, 'id'),
                            COALESCE(MAX(id), 1),
                            MAX(id) IS NOT NULL
                        )
                        FROM 
                        """ + table_name,
                        (table_name,),
                    )
            target.commit()
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy the Sobrus SQLite database into a PostgreSQL database."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=PROJECT_ROOT / "data" / "nova_groups.sqlite3",
        help="Path to the source SQLite database.",
    )
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="PostgreSQL connection string from Supabase or Neon.",
    )
    args = parser.parse_args()
    migrate(args.sqlite, args.postgres_url)
    print("Migration completed successfully.")


if __name__ == "__main__":
    main()
