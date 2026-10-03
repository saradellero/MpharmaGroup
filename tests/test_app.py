import unittest
import uuid
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook

from demo_site.app import build_order_manager_matrix, create_app
from demo_site.app import sync_purchase_order_product_totals
from demo_site.dashboard import build_dashboard_stats
from demo_site.storage import (
    append_records,
    format_date_for_display,
    get_db,
    list_invoice_products,
    list_order_products,
    list_records,
    list_suppliers,
    normalize_date_value,
    save_order_products,
)


class AppTests(unittest.TestCase):
    def setUp(self):
        test_data = Path(__file__).resolve().parents[1] / ".test-data"
        test_data.mkdir(exist_ok=True)
        safe_name = self.id().replace(".", "_").replace(" ", "_")
        self.database_path = test_data / f"{safe_name}_{uuid.uuid4().hex}.sqlite3"
        database = str(self.database_path)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": database})
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.database_path) + suffix)
            if candidate.exists():
                try:
                    candidate.unlink()
                except PermissionError:
                    pass

    def login(self):
        return self.client.post(
            "/auth/login",
            data={
                "email": "sara.demo@example.com",
                "password": "admin123",
                "redirect_url": "/",
            },
            follow_redirects=True,
        )

    def login_pharmacy(self):
        return self.client.post(
            "/auth/login",
            data={
                "email": "mina.test@example.com",
                "password": "atlas123",
                "redirect_url": "/",
            },
            follow_redirects=True,
        )

    def test_date_values_are_normalized_to_iso_format(self):
        self.assertEqual(normalize_date_value("30/09/2026"), "2026-09-30")
        self.assertEqual(normalize_date_value("30-09-2026"), "2026-09-30")
        self.assertEqual(normalize_date_value("2026/09/30"), "2026-09-30")
        self.assertEqual(normalize_date_value("2026-09-30"), "2026-09-30")
        self.assertEqual(format_date_for_display("2026-09-30"), "30/09/2026")
        self.assertEqual(format_date_for_display("30-09-2026"), "30/09/2026")

        with self.app.app_context():
            append_records(
                "offers",
                [
                    {
                        "number": "DATE-1",
                        "subject": "Oferta con fecha normalizada",
                        "supplier": "Proveedor Demo",
                        "deadline": "30/09/2026",
                        "products": "1",
                    }
                ],
            )
            offer = next(
                row for row in list_records("offers") if row["number"] == "DATE-1"
            )
        self.assertEqual(offer["deadline"], "2026-09-30")

    def test_empty_catalog_is_not_reseeded_after_restart(self):
        with self.app.app_context():
            database = get_db()
            database.execute("DELETE FROM products")
            database.commit()
            self.assertEqual(list_records("products"), [])

        restarted_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test",
                "DATABASE": str(self.database_path),
            }
        )
        with restarted_app.app_context():
            self.assertEqual(list_records("products"), [])

    def test_date_fields_use_calendar_controls(self):
        self.login()

        response = self.client.get("/purchaseorders?edit=1")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertRegex(
            html,
            r'name="record_\d+_deadline"\s+value="\d{2}/\d{2}/\d{4}"',
        )
        self.assertRegex(
            html,
            r'name="record_\d+_updated"\s+value="\d{2}/\d{2}/\d{4}"',
        )
        self.assertIn('name="new_deadline"', html)
        self.assertIn('placeholder="dd/mm/aaaa"', html)
        self.assertIn("data-date-open", html)
        self.assertIn("data-date-picker", html)

        response = self.client.get("/purchaseorder/create")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="deadline"', response.data)
        self.assertIn(b'placeholder="dd/mm/aaaa"', response.data)

        response = self.client.get("/event/create")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="date"', response.data)
        self.assertIn(b'value="18/06/2026"', response.data)

        response = self.client.get("/purchaseorders")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"28/06/2026", response.data)

    def excel_file(self, headers, rows, filename="import.xlsx"):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return output, filename

    def test_login_renders(self):
        response = self.client.get("/auth/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mpharma", response.data)

    def test_french_language_switch_translates_login_without_breaking_controls(self):
        response = self.client.get(
            "/set-language?lang=fr&next=/auth/login",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mpharma Groups", response.data)
        self.assertIn(b"Se connecter", response.data)
        self.assertIn(b"Se souvenir de moi", response.data)
        self.assertIn(b'type="checkbox"', response.data)
        self.assertNotIn(b">Recordarme<", response.data)

    def test_french_interface_translates_editing_and_manager_labels(self):
        self.login()
        self.client.get("/set-language?lang=fr&next=/")

        routes = (
            "/",
            "/suppliers",
            "/contacts",
            "/products",
            "/offers",
            "/purchaseorders",
            "/purchaseorders?edit=1",
            "/purchaseorder/create",
            "/purchaseorder/edit/105900",
            "/purchaseorder/edit/105900?mode=manager",
            "/purchaseorder/invoices/105900",
            "/purchaseorder/recap/105900",
            "/events",
            "/event/create",
            "/reports",
            "/users",
            "/settings/usersettings/profile",
            "/settings/usersettings/edit-profile",
            "/settings/usersettings/change-password",
        )
        rendered_pages = []
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                rendered_pages.append(response.data.decode())

        html = "\n".join(rendered_pages)
        untranslated_labels = (
            ">Editar<",
            "Editar pedidos",
            ">Gestor<",
            "Gestor / farmacia",
            "Opciones de gestor",
            "Guardar como gestor",
            ">Descuentos<",
            ">Actuales<",
            ">Archivados<",
            "Todavia no hay productos",
            "Estas cantidades son el resultado",
            "Productos del proveedor y cantidades",
            "Se muestran todos los productos",
            ">Junio 2026<",
            "Contrasena actual",
            "Nueva contrasena",
            "Confirmar contrasena",
        )
        for label in untranslated_labels:
            with self.subTest(label=label):
                self.assertNotIn(label, html)

        self.assertIn("Modifier les commandes", html)
        self.assertIn("Options du gestionnaire", html)
        self.assertIn("Enregistrer en tant que gestionnaire", html)
        self.assertIn("Remises", html)
        self.assertIn("Page 1 sur", html)
        self.assertNotRegex(html, r"Page \d+ de \d+")

    def test_login_rejects_unknown_credentials(self):
        response = self.client.post(
            "/auth/login",
            data={"email": "demo@example.com", "password": "secret"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Usuario o contrasena incorrectos", response.data)

    def test_dashboard_requires_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])

    def test_authenticated_products_page(self):
        self.login()
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Productos", response.data)
        self.assertIn(b"Gel apaisant", response.data)

    def test_dashboard_stats_reflect_database_records(self):
        with self.app.app_context():
            append_records(
                "suppliers",
                [
                    {
                        "name": "Proveedor Dashboard",
                        "phone": "05 00 00 00 00",
                        "email": "dashboard@example.com",
                        "address": "Rue Dashboard",
                        "city": "Rabat",
                    }
                ],
            )
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Dashboard",
                        "name": "Producto Dashboard",
                        "ppv": "10",
                        "pph": "7",
                        "tax": "7%",
                        "barcode": "123",
                    }
                ],
            )
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "106100",
                        "subject": "Pedido Dashboard",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Dashboard",
                        "deadline": "2026-08-01",
                        "updated": "2026-06-18",
                        "products": "1",
                        "quantity": "50",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            stats = build_dashboard_stats(list_records)

        self.assertEqual(stats[0]["label"], "Pedidos abiertos")
        self.assertEqual(stats[0]["value"], "3")
        self.assertIn("325 unidades", stats[0]["trend"])
        self.assertEqual(stats[1]["value"], "5")
        self.assertEqual(stats[2]["value"], "5")

        self.login()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Farmacias activas", response.data)
        self.assertIn(b"Pedido Dashboard", response.data)

    def test_contact_form_posts(self):
        self.login()
        response = self.client.post(
            "/contact/create",
            data={"first_name": "Ana", "last_name": "Demo"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Contactos", response.data)

    def test_authenticated_routes_render(self):
        self.login()
        routes = [
            "/",
            "/suppliers",
            "/contacts",
            "/contact/create",
            "/products",
            "/offers",
            "/purchaseorders",
            "/purchaseorders/index/index/archived/true",
            "/purchaseorder/create",
            "/purchaseorder/edit/105900",
            "/purchaseorder/print/105900",
            "/events",
            "/event/create",
            "/reports",
            "/reports/index/details/type/paid/year/2026/warehouse/0/user_id/1001",
            "/users",
            "/settings/usersettings/profile",
            "/settings/usersettings/edit-profile",
            "/settings/usersettings/change-password",
        ]
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_suppliers_inline_edit_persists_new_row(self):
        self.login()
        response = self.client.get("/suppliers?edit=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"new_name", response.data)
        self.assertIn(b"records-edit-form", response.data)

        response = self.client.post(
            "/suppliers",
            data={
                "record_id": ["1"],
                "record_1_name": "Atlas Distribution Updated",
                "record_1_phone": "05 00 00 00 00",
                "record_1_email": "updated@example.com",
                "record_1_address": "Rue Test",
                "record_1_city": "Fes",
                "new_name": "Nuevo Proveedor",
                "new_phone": "06 99 88 77 66",
                "new_email": "nuevo@example.com",
                "new_address": "Avenida Demo",
                "new_city": "Agadir",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Nuevo Proveedor", response.data)
        self.assertIn(b"Atlas Distribution Updated", response.data)

    def test_suppliers_inline_edit_deletes_empty_existing_row(self):
        self.login()
        response = self.client.post(
            "/suppliers",
            data={
                "record_id": ["1", "2"],
                "record_1_name": "",
                "record_1_phone": "",
                "record_1_email": "",
                "record_1_address": "",
                "record_1_city": "",
                "record_2_name": "Medica Nord",
                "record_2_phone": "05 39 22 40 90",
                "record_2_email": "hello@medicanord.example",
                "record_2_address": "Avenue des Laboratoires",
                "record_2_city": "Tanger",
                "new_name": "",
                "new_phone": "",
                "new_email": "",
                "new_address": "",
                "new_city": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            supplier_names = [row["name"] for row in list_suppliers()]
        self.assertNotIn("Atlas Distribution", supplier_names)
        self.assertIn("Medica Nord", supplier_names)

    def test_products_inline_edit_adds_and_deletes_rows(self):
        self.login()
        response = self.client.get("/products?edit=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"records-edit-form-products", response.data)

        response = self.client.post(
            "/products",
            data={
                "record_id": ["1"],
                "record_1_supplier": "",
                "record_1_name": "",
                "record_1_ppv": "",
                "record_1_pph": "",
                "record_1_tax": "",
                "record_1_barcode": "",
                "new_supplier": "Demo Labs",
                "new_name": "Producto Demo",
                "new_ppv": "12.00",
                "new_pph": "8.00",
                "new_tax": "7%",
                "new_barcode": "6110001999999",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            products = list_records("products")
        product_names = [row["name"] for row in products]
        self.assertNotIn("Gel apaisant 120 ml", product_names)
        self.assertIn("Producto Demo", product_names)

    def test_purchaseorder_create_has_supplier_product_selection_list(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Pedido",
                        "name": "Producto Pedido Alpha",
                        "ppv": "21.50",
                        "pph": "15.10",
                        "tax": "7%",
                        "barcode": "760001",
                    },
                    {
                        "supplier": "Proveedor Pedido",
                        "name": "Producto Pedido Beta",
                        "ppv": "22.50",
                        "pph": "16.10",
                        "tax": "20%",
                        "barcode": "760002",
                    },
                    {
                        "supplier": "Otro Proveedor",
                        "name": "Producto Externo",
                        "ppv": "30",
                        "pph": "20",
                        "tax": "0%",
                        "barcode": "760003",
                    },
                ],
            )

        self.login()
        response = self.client.get("/purchaseorder/create")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="order-supplier"', response.data)
        self.assertIn(b'list="supplier-options"', response.data)
        self.assertIn(b'id="supplier-options"', response.data)
        self.assertIn(b'id="product-search"', response.data)
        self.assertIn(b'id="product-suggestions"', response.data)
        self.assertIn(b"data-provider-products-body", response.data)
        self.assertIn(b"selected_product_id", response.data)
        self.assertIn(b"Pharmacie Atlas", response.data)
        self.assertIn(b"Proveedor Pedido", response.data)
        self.assertIn(b"Producto Pedido Alpha", response.data)
        self.assertIn(b"Producto Pedido Beta", response.data)

    def test_supplier_and_product_edit_fields_offer_live_suggestions(self):
        self.login()

        response = self.client.get("/suppliers?edit=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'list="supplier-name-options"', response.data)
        self.assertIn(b'id="supplier-name-options"', response.data)
        self.assertIn(b"Atlas Distribution", response.data)

        response = self.client.get("/products?edit=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'list="product-supplier-options"', response.data)
        self.assertIn(b'list="product-name-options"', response.data)
        self.assertIn(b'id="product-supplier-options"', response.data)
        self.assertIn(b'id="product-name-options"', response.data)
        self.assertIn(b"Atlas Distribution", response.data)
        self.assertIn(b"Gel apaisant 120 ml", response.data)

    def test_purchaseorder_create_persists_and_opens_new_order(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Pedido",
                        "name": "Producto Pedido Alpha",
                        "ppv": "21.50",
                        "pph": "15.10",
                        "tax": "7%",
                        "barcode": "760001",
                    }
                ],
            )
            product_id = str(
                [
                    row["id"]
                    for row in list_records("products")
                    if row["name"] == "Producto Pedido Alpha"
                ][0]
            )

        self.login()
        response = self.client.post(
            "/purchaseorder/create",
            data={
                "owner_id": "1001",
                "warehouse": "Principal",
                "subject": "Pedido nuevo con productos",
                "deadline": "2026-10-15",
                "supplier_id": "Proveedor Pedido",
                "selected_product_id": [product_id],
                f"product_quantity_{product_id}": "3",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/purchaseorder/edit/", response.headers["Location"])

        with self.app.app_context():
            orders = [
                row
                for row in list_records("purchaseorders")
                if row["subject"] == "Pedido nuevo con productos"
            ]
            order_products = list_order_products(str(orders[0]["number"]))
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["supplier"], "Proveedor Pedido")
        self.assertEqual(orders[0]["products"], "1")
        self.assertEqual(len(order_products), 1)
        self.assertEqual(order_products[0]["name"], "Producto Pedido Alpha")
        self.assertEqual(order_products[0]["quantity"], "3")

    def test_purchaseorder_edit_replaces_saved_products_with_selected_products(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Guardado",
                        "name": "Producto Guardado 1",
                        "ppv": "31",
                        "pph": "21",
                        "tax": "7%",
                        "barcode": "790001",
                    },
                    {
                        "supplier": "Proveedor Guardado",
                        "name": "Producto Guardado 2",
                        "ppv": "32",
                        "pph": "22",
                        "tax": "20%",
                        "barcode": "790002",
                    },
                ],
            )
            ids = [
                str(row["id"])
                for row in list_records("products")
                if row["supplier"] == "Proveedor Guardado"
            ]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109001",
                        "subject": "Pedido seleccion",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Guardado",
                        "deadline": "2026-10-20",
                        "updated": "",
                        "products": "0",
                        "quantity": "",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )

        self.login()
        response = self.client.post(
            "/purchaseorder/edit/109001",
            data={
                "subject": "Pedido seleccion actualizado",
                "deadline": "2026-10-21",
                "supplier_id": "Proveedor Guardado",
                "selected_product_id": ids[:2],
                f"product_quantity_{ids[0]}": "2",
                f"product_quantity_{ids[1]}": "0",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            orders = [
                row
                for row in list_records("purchaseorders")
                if row["number"] == "109001"
            ]
            saved_products = list_order_products("109001")
        self.assertEqual(orders[0]["products"], "1")
        self.assertEqual(orders[0]["subject"], "Pedido seleccion actualizado")
        self.assertEqual(len(saved_products), 1)
        self.assertEqual(saved_products[0]["name"], "Producto Guardado 1")
        self.assertEqual(saved_products[0]["quantity"], "2")
        self.assertIn(b"Producto Guardado 1", response.data)
        self.assertIn(b"Resumen acumulado por farmacia", response.data)
        self.assertNotIn(b"data-quantity-product-id", response.data)

        edit_response = self.client.get("/purchaseorder/edit/109001?mode=edit")
        self.assertIn(b"data-quantity-product-id", edit_response.data)
        self.assertIn(b"checked", edit_response.data)

        print_response = self.client.get("/purchaseorder/print/109001")
        self.assertEqual(print_response.status_code, 200)
        self.assertIn(b"Producto Guardado 1", print_response.data)
        self.assertIn(b"<td>2</td>", print_response.data)
        self.assertIn(b"<th>62,00</th>", print_response.data)
        self.assertIn(b"<th>42,00</th>", print_response.data)
        self.assertNotIn(b"Producto Guardado 2", print_response.data)

    def test_pharmacy_order_lines_are_saved_per_pharmacy(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Farmacia",
                        "name": "Producto Farmacia Atlas",
                        "ppv": "18",
                        "pph": "12",
                        "tax": "7%",
                        "barcode": "791001",
                    }
                ],
            )
            product_id = str(
                [
                    row["id"]
                    for row in list_records("products")
                    if row["name"] == "Producto Farmacia Atlas"
                ][0]
            )
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109002",
                        "subject": "Pedido farmacia",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Farmacia",
                        "deadline": "2026-10-22",
                        "updated": "",
                        "products": "0",
                        "quantity": "",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )

        self.login_pharmacy()
        response = self.client.post(
            "/purchaseorder/edit/109002",
            data={
                "subject": "Pedido farmacia",
                "deadline": "2026-10-22",
                "supplier_id": "Proveedor Farmacia",
                "selected_product_id": [product_id],
                f"product_quantity_{product_id}": "6",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            pharmacy_products = list_order_products("109002", "Pharmacie Atlas")
            all_products = list_order_products("109002")
        self.assertEqual(len(pharmacy_products), 1)
        self.assertEqual(pharmacy_products[0]["pharmacy"], "Pharmacie Atlas")
        self.assertEqual(pharmacy_products[0]["quantity"], "6")
        self.assertEqual(all_products[0]["pharmacy"], "Pharmacie Atlas")

    def test_purchaseorders_page_shows_selected_order_pharmacy_summary(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Resumen",
                        "name": "Producto Resumen A",
                        "ppv": "18",
                        "pph": "12",
                        "tax": "7%",
                        "barcode": "792001",
                    },
                    {
                        "supplier": "Proveedor Resumen",
                        "name": "Producto Resumen B",
                        "ppv": "24",
                        "pph": "17",
                        "tax": "20%",
                        "barcode": "792002",
                    },
                ],
            )
            products = [
                row
                for row in list_records("products")
                if row["supplier"] == "Proveedor Resumen"
            ]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109010",
                        "subject": "Pedido resumen",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Resumen",
                        "deadline": "2026-10-25",
                        "updated": "",
                        "products": "0",
                        "quantity": "",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products(
                "109010",
                [products[0] | {"quantity": "2"}],
                "Pharmacie Atlas",
            )
            save_order_products(
                "109010",
                [
                    products[0] | {"quantity": "3"},
                    products[1] | {"quantity": "4"},
                ],
                "Pharmacie Riviera",
            )

        self.login()
        response = self.client.get("/purchaseorders?selected_order=109010")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Resumen por farmacia", response.data)
        self.assertIn(b"Pedido 109010", response.data)
        self.assertIn(b"Pharmacie Atlas", response.data)
        self.assertIn(b"Pharmacie Riviera", response.data)
        self.assertIn(b"Producto Resumen A", response.data)
        self.assertIn(b"Producto Resumen B", response.data)
        self.assertIn(b"<td class=\"numeric-cell row-total\">5</td>", response.data)
        self.assertIn(b"<th class=\"numeric-cell\">9</th>", response.data)

        print_response = self.client.get("/purchaseorder/print/109010")
        self.assertEqual(print_response.status_code, 200)
        self.assertIn(b"Total farmacia", print_response.data)
        self.assertIn(b"Total acumulado (cantidad x precio unitario)", print_response.data)
        self.assertIn(b"<th>186,00</th>", print_response.data)
        self.assertIn(b"<th>128,00</th>", print_response.data)

    def test_purchase_order_total_ignores_unassigned_legacy_lines(self):
        with self.app.app_context():
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109013",
                        "subject": "Pedido legado",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Legado",
                        "deadline": "2026-10-28",
                        "updated": "",
                        "products": "2",
                        "quantity": "45",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Legado",
                        "name": "Producto Legado",
                        "ppv": "10",
                        "pph": "7",
                        "tax": "0%",
                        "barcode": "793201",
                    }
                ],
            )
            product = [
                row
                for row in list_records("products")
                if row["name"] == "Producto Legado"
            ][0]
            save_order_products("109013", [product | {"quantity": "41"}], "")
            save_order_products("109013", [product | {"quantity": "143"}], "Pharmacie Atlas")
            sync_purchase_order_product_totals("109013")
            order = [
                row
                for row in list_records("purchaseorders")
                if row["number"] == "109013"
            ][0]
        self.assertEqual(order["quantity"], "143")

    def test_assigned_manager_can_edit_all_pharmacy_lines_and_order_details(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Gestor",
                        "name": "Producto Gestor A",
                        "ppv": "20",
                        "pph": "12",
                        "tax": "0%",
                        "barcode": "793301",
                    },
                    {
                        "supplier": "Proveedor Gestor",
                        "name": "Producto Gestor B",
                        "ppv": "30",
                        "pph": "18",
                        "tax": "0%",
                        "barcode": "793302",
                    },
                ],
            )
            products = [
                row
                for row in list_records("products")
                if row["supplier"] == "Proveedor Gestor"
            ]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109014",
                        "subject": "Pedido del gestor",
                        "manager": "Pharmacie Atlas",
                        "supplier": "Proveedor Gestor",
                        "deadline": "2026-10-29",
                        "updated": "",
                        "products": "2",
                        "quantity": "6",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products("109014", [products[0] | {"quantity": "2"}], "Pharmacie Atlas")
            save_order_products("109014", [products[1] | {"quantity": "4"}], "Pharmacie Riviera")
            matrix = build_order_manager_matrix("109014")

        self.login_pharmacy()
        summary_response = self.client.get("/purchaseorder/edit/109014")
        self.assertIn(b"Modificar como gestor", summary_response.data)
        self.assertIn(b"Recapitulacion", summary_response.data)
        manager_response = self.client.get("/purchaseorder/edit/109014?mode=manager")
        self.assertEqual(manager_response.status_code, 200)
        self.assertIn(b"Edicion avanzada del gestor", manager_response.data)
        self.assertIn(b"Datos del pedido", manager_response.data)
        self.assertIn(b"Pago y entrega", manager_response.data)
        self.assertIn(b"manager-options-panel", manager_response.data)
        self.assertIn(b"manager_quantity_", manager_response.data)
        self.assertIn(b"manager_product_ppv_", manager_response.data)
        self.assertIn(b"manager_product_pph_", manager_response.data)
        self.assertIn(b"manager_product_tax_", manager_response.data)
        self.assertIn(b"Producto Gestor A", manager_response.data)
        self.assertIn(b"Producto Gestor B", manager_response.data)
        self.assertIn(b"new_product_name", manager_response.data)
        self.assertIn(b"new_product_ppv", manager_response.data)
        self.assertIn(b"new_product_pph", manager_response.data)
        self.assertIn(b"new_product_tax", manager_response.data)
        self.assertIn(b"Imprimir pedido total", manager_response.data)
        self.assertIn(b"Imprimir farmacia seleccionada", manager_response.data)
        self.assertIn(b"Modificar farmacia seleccionada", manager_response.data)
        self.assertIn(b"Recapitulacion", manager_response.data)

        invoices_response = self.client.get("/purchaseorder/invoices/109014")
        self.assertEqual(invoices_response.status_code, 200)
        self.assertIn(b"Facturas del pedido 109014", invoices_response.data)
        self.assertIn(b"Producto Gestor A", invoices_response.data)
        self.assertIn(b"Producto Gestor B", invoices_response.data)
        self.assertIn(b'data-field="discount"', invoices_response.data)
        self.assertIn(b'data-field="ug"', invoices_response.data)
        self.assertIn(b'data-field="pph-discounted"', invoices_response.data)
        self.assertIn(b"Cantidad total", invoices_response.data)
        self.assertIn(b"Total PPH descontado", invoices_response.data)
        self.assertIn(b'data-field="quantity"', invoices_response.data)
        self.assertIn(b'data-field="line-total"', invoices_response.data)
        self.assertIn(b'data-total="amount"', invoices_response.data)

        form_data = {
            "owner_id": "Pharmacie Atlas",
            "warehouse": "Secundario",
            "subject": "Pedido del gestor actualizado",
            "deadline": "2026-11-01",
            "supplier_id": "Proveedor Gestor",
            "contact_id": "Contacto gestor",
            "terms_and_conditions": "Entrega prioritaria",
            "payment_timeframe": "45 dias",
            "delivery_timeframe": "24 horas",
            "delivery_transporter": "Transporte gestor",
            "accepted_payment_methods[]": ["cash", "check"],
        }
        edited_prices = {
            "Producto Gestor A": ("21", "13", "7%"),
            "Producto Gestor B": ("31", "19", "10%"),
        }
        for row_index, row in enumerate(matrix["rows"]):
            ppv, pph, tax = edited_prices[row["name"]]
            form_data[f"manager_product_ppv_{row_index}"] = ppv
            form_data[f"manager_product_pph_{row_index}"] = pph
            form_data[f"manager_product_tax_{row_index}"] = tax
            for pharmacy_index, pharmacy in enumerate(matrix["pharmacies"]):
                form_data[f"manager_quantity_{row_index}_{pharmacy_index}"] = "0"
                if pharmacy in {"Pharmacie Atlas", "Pharmacie Riviera"}:
                    form_data[f"manager_quantity_{row_index}_{pharmacy_index}"] = "5"

        response = self.client.post(
            "/purchaseorder/edit/109014?mode=manager",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Pedido actualizado como gestor", response.data)

        with self.app.app_context():
            saved = list_order_products("109014")
            order = [
                row
                for row in list_records("purchaseorders")
                if row["number"] == "109014"
            ][0]
        self.assertEqual(
            sorted((row["pharmacy"], row["quantity"]) for row in saved),
            sorted(
                [
                    ("Pharmacie Atlas", "5"),
                    ("Pharmacie Riviera", "5"),
                    ("Pharmacie Atlas", "5"),
                    ("Pharmacie Riviera", "5"),
                ]
            ),
        )
        self.assertEqual(order["manager"], "Pharmacie Atlas")
        self.assertEqual(order["subject"], "Pedido del gestor actualizado")
        self.assertEqual(order["warehouse"], "Secundario")
        self.assertEqual(order["payment_timeframe"], "45 dias")
        self.assertEqual(order["delivery_timeframe"], "24 horas")
        self.assertEqual(order["delivery_transporter"], "Transporte gestor")
        self.assertEqual(order["terms_and_conditions"], "Entrega prioritaria")
        self.assertEqual(order["quantity"], "20")

        with self.app.app_context():
            catalog = [
                row
                for row in list_records("products")
                if row["supplier"] == "Proveedor Gestor"
            ]
        self.assertEqual(
            {(row["name"], row["ppv"], row["pph"], row["tax"]) for row in catalog},
            {
                ("Producto Gestor A", "21,00", "13,00", "7%"),
                ("Producto Gestor B", "31,00", "19,00", "10%"),
            },
        )

        saved_invoice_response = self.client.post(
            "/purchaseorder/invoices/109014",
            data={
                "invoice_pph_discounted_0": "10",
                "invoice_ug_1": "5",
            },
            follow_redirects=True,
        )
        self.assertEqual(saved_invoice_response.status_code, 200)
        self.assertIn(b"Datos de factura guardados", saved_invoice_response.data)
        with self.app.app_context():
            saved_invoice = list_invoice_products("109014")
        self.assertEqual(saved_invoice[0]["pph_discounted"], "10")
        self.assertEqual(saved_invoice[0]["discount_pct"], "-23,0769")
        self.assertEqual(saved_invoice[1]["ug_pct"], "5")
        self.assertEqual(saved_invoice[1]["pph_discounted"], "19,95")
        self.assertEqual(saved_invoice[1]["discount_pct"], "5")

        recap_response = self.client.get("/purchaseorder/recap/109014")
        self.assertEqual(recap_response.status_code, 200)
        self.assertIn(b"Recapitulacion del pedido 109014", recap_response.data)
        self.assertIn(b"Pharmacie Atlas", recap_response.data)
        self.assertIn(b"Pharmacie Riviera", recap_response.data)
        self.assertIn(b"Producto Gestor A", recap_response.data)
        self.assertIn(b"Total", recap_response.data)

        reports_response = self.client.get("/reports?year=2026")
        self.assertEqual(reports_response.status_code, 200)
        self.assertIn(b"Pharmacie Atlas", reports_response.data)
        self.assertIn(b"149,75 MAD", reports_response.data)
        self.assertIn(b"Proveedor Gestor", reports_response.data)
        self.assertIn(b"Estadisticas de pedidos por proveedor", reports_response.data)
        self.assertIn(b"Importe total PPH descontado", reports_response.data)

        total_print = self.client.get("/purchaseorder/print/109014?scope=all")
        self.assertEqual(total_print.status_code, 200)
        self.assertIn(b"Pedido total 109014", total_print.data)
        self.assertIn(b"Producto Gestor A", total_print.data)
        self.assertIn(b"Producto Gestor B", total_print.data)

        pharmacy_print = self.client.get(
            "/purchaseorder/print/109014?scope=pharmacy&pharmacy=Pharmacie%20Riviera"
        )
        self.assertEqual(pharmacy_print.status_code, 200)
        self.assertIn(b"Pedido de Pharmacie Riviera 109014", pharmacy_print.data)
        self.assertIn(b"Producto Gestor B", pharmacy_print.data)

    def test_manager_can_edit_one_selected_pharmacy(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Farmacia Gestor",
                        "name": "Producto Atlas",
                        "ppv": "10",
                        "pph": "6",
                        "tax": "0%",
                        "barcode": "793501",
                    },
                    {
                        "supplier": "Proveedor Farmacia Gestor",
                        "name": "Producto Riviera",
                        "ppv": "11",
                        "pph": "7",
                        "tax": "0%",
                        "barcode": "793502",
                    },
                ],
            )
            products = [
                row
                for row in list_records("products")
                if row["supplier"] == "Proveedor Farmacia Gestor"
            ]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109017",
                        "subject": "Pedido farmacia individual",
                        "manager": "Pharmacie Atlas",
                        "supplier": "Proveedor Farmacia Gestor",
                        "deadline": "2026-11-04",
                        "updated": "",
                        "products": "2",
                        "quantity": "5",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products("109017", [products[0] | {"quantity": "2"}], "Pharmacie Atlas")
            save_order_products("109017", [products[1] | {"quantity": "3"}], "Pharmacie Riviera")

        self.login_pharmacy()
        response = self.client.get(
            "/purchaseorder/edit/109017?mode=manager_pharmacy&pharmacy=Pharmacie%20Riviera"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Volver a edición del gestor".encode(), response.data)
        self.assertIn(b"Producto Riviera", response.data)

        product_id = str(products[1]["id"])
        saved_response = self.client.post(
            "/purchaseorder/edit/109017?mode=manager_pharmacy&pharmacy=Pharmacie%20Riviera",
            data={
                "supplier_id": "Proveedor Farmacia Gestor",
                "selected_product_id": [product_id],
                f"product_quantity_{product_id}": "9",
            },
            follow_redirects=True,
        )
        self.assertEqual(saved_response.status_code, 200)

        with self.app.app_context():
            atlas_lines = list_order_products("109017", "Pharmacie Atlas")
            riviera_lines = list_order_products("109017", "Pharmacie Riviera")
        self.assertEqual(atlas_lines[0]["quantity"], "2")
        self.assertEqual(riviera_lines[0]["quantity"], "9")

    def test_manager_can_add_product_to_supplier_catalog_and_order(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Nueva Linea",
                        "name": "Producto Inicial",
                        "ppv": "10",
                        "pph": "6",
                        "tax": "0%",
                        "barcode": "793401",
                    }
                ],
            )
            initial_product = [
                row
                for row in list_records("products")
                if row["name"] == "Producto Inicial"
            ][0]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109016",
                        "subject": "Pedido con alta",
                        "manager": "Pharmacie Atlas",
                        "supplier": "Proveedor Nueva Linea",
                        "deadline": "2026-11-03",
                        "updated": "",
                        "products": "1",
                        "quantity": "2",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products("109016", [initial_product | {"quantity": "2"}], "Pharmacie Atlas")
            matrix = build_order_manager_matrix("109016")

        self.login_pharmacy()
        form_data = {
            "owner_id": "Pharmacie Atlas",
            "warehouse": "Principal",
            "subject": "Pedido con alta",
            "deadline": "2026-11-03",
            "supplier_id": "Proveedor Nueva Linea",
            "new_product_name": "Producto Nuevo Gestor",
            "new_product_ppv": "25,50",
            "new_product_pph": "15,25",
            "new_product_tax": "7%",
            "new_product_barcode": "793402",
        }
        for row_index, _row in enumerate(matrix["rows"]):
            for pharmacy_index, pharmacy in enumerate(matrix["pharmacies"]):
                form_data[f"manager_quantity_{row_index}_{pharmacy_index}"] = (
                    "2" if pharmacy == "Pharmacie Atlas" else "0"
                )
        for pharmacy_index, pharmacy in enumerate(matrix["pharmacies"]):
            form_data[f"manager_new_quantity_{pharmacy_index}"] = (
                "3" if pharmacy == "Pharmacie Atlas" else "0"
            )

        response = self.client.post(
            "/purchaseorder/edit/109016?mode=manager",
            data=form_data,
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            new_products = [
                row
                for row in list_records("products")
                if row["name"] == "Producto Nuevo Gestor"
            ]
            order_lines = list_order_products("109016")
        self.assertEqual(len(new_products), 1)
        self.assertEqual(new_products[0]["supplier"], "Proveedor Nueva Linea")
        self.assertEqual(new_products[0]["ppv"], "25,50")
        self.assertEqual(new_products[0]["pph"], "15,25")
        self.assertEqual(new_products[0]["tax"], "7%")
        self.assertEqual(
            [(line["name"], line["pharmacy"], line["quantity"]) for line in order_lines],
            [
                ("Producto Inicial", "Pharmacie Atlas", "2"),
                ("Producto Nuevo Gestor", "Pharmacie Atlas", "3"),
            ],
        )

    def test_non_manager_cannot_open_manager_edit_mode(self):
        with self.app.app_context():
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109015",
                        "subject": "Pedido restringido",
                        "manager": "Pharmacie Riviera",
                        "supplier": "Proveedor Restriccion",
                        "deadline": "2026-11-02",
                        "updated": "",
                        "products": "0",
                        "quantity": "",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
        self.login_pharmacy()
        response = self.client.get("/purchaseorder/edit/109015?mode=manager")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/purchaseorder/invoices/109015")
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/purchaseorder/recap/109015")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Recapitulacion del pedido 109015", response.data)

    def test_pharmacy_order_view_has_side_actions_and_quantities(self):
        self.login_pharmacy()
        response = self.client.get("/purchaseorder/edit/105900")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Modificar pedido", response.data)
        self.assertIn(b"Imprimir pedido", response.data)
        self.assertIn(b"Resumen acumulado por farmacia", response.data)
        self.assertNotIn(b"data-quantity-product-id", response.data)

        edit_response = self.client.get("/purchaseorder/edit/105900?mode=edit")
        self.assertEqual(edit_response.status_code, 200)
        self.assertIn(b"Ver resumen del pedido", edit_response.data)
        self.assertIn(b"data-quantity-product-id", edit_response.data)
        self.assertIn(b"product_quantity_", edit_response.data)
        self.assertIn(b'selectedQuantities[productId] || "0"', edit_response.data)
        self.assertIn(b"data-live-total-ppv", edit_response.data)
        self.assertIn(b"data-live-total-ttc", edit_response.data)
        self.assertIn(b"updateLiveTotals", edit_response.data)

    def test_admin_pharmacy_scope_starts_at_zero_when_another_pharmacy_has_lines(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Sara",
                        "name": "Producto Sara A",
                        "ppv": "11",
                        "pph": "7",
                        "tax": "0%",
                        "barcode": "793101",
                    },
                    {
                        "supplier": "Proveedor Sara",
                        "name": "Producto Sara B",
                        "ppv": "12",
                        "pph": "8",
                        "tax": "0%",
                        "barcode": "793102",
                    },
                ],
            )
            products = [
                row
                for row in list_records("products")
                if row["supplier"] == "Proveedor Sara"
            ]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109012",
                        "subject": "Pedido Sara",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Sara",
                        "deadline": "2026-10-27",
                        "updated": "",
                        "products": "1",
                        "quantity": "8",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products("109012", [products[0] | {"quantity": "8"}], "Pharmacie Atlas")

        self.login()
        summary_response = self.client.get("/purchaseorder/edit/109012")
        self.assertIn(b"Productos acumulados", summary_response.data)
        self.assertIn(b"Pharmacie Atlas", summary_response.data)
        self.assertIn(b"Producto Sara A", summary_response.data)
        self.assertNotIn(b"data-quantity-product-id", summary_response.data)

        edit_response = self.client.get("/purchaseorder/edit/109012?mode=edit")
        self.assertIn(b"data-quantity-product-id", edit_response.data)
        self.assertIn(
            ('"%s": "0"' % products[0]["id"]).encode(),
            edit_response.data,
        )
        self.assertIn(
            ('"%s": "0"' % products[1]["id"]).encode(),
            edit_response.data,
        )

    def test_pharmacy_edit_returns_to_accumulated_summary_and_preserves_other_pharmacies(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Proveedor Acumulado",
                        "name": "Producto Acumulado",
                        "ppv": "18",
                        "pph": "12",
                        "tax": "7%",
                        "barcode": "793001",
                    }
                ],
            )
            product = [
                row
                for row in list_records("products")
                if row["name"] == "Producto Acumulado"
            ][0]
            append_records(
                "purchaseorders",
                [
                    {
                        "number": "109011",
                        "subject": "Pedido acumulado",
                        "manager": "Sara Demo",
                        "supplier": "Proveedor Acumulado",
                        "deadline": "2026-10-26",
                        "updated": "",
                        "products": "1",
                        "quantity": "9",
                        "status": "Ouverte",
                        "archived": "0",
                    }
                ],
            )
            save_order_products("109011", [product | {"quantity": "4"}], "Pharmacie Riviera")
            save_order_products("109011", [product | {"quantity": "2"}], "Pharmacie Atlas")

        self.login_pharmacy()
        summary_response = self.client.get("/purchaseorder/edit/109011")
        self.assertEqual(summary_response.status_code, 200)
        self.assertIn(b"Producto Acumulado", summary_response.data)
        self.assertIn(b"Modificar pedido", summary_response.data)
        self.assertIn(b"6", summary_response.data)

        edit_response = self.client.get("/purchaseorder/edit/109011?mode=edit")
        self.assertIn(b"product_quantity_", edit_response.data)
        response = self.client.post(
            "/purchaseorder/edit/109011?mode=edit",
            data={
                "subject": "Pedido acumulado",
                "deadline": "2026-10-26",
                "supplier_id": "Proveedor Acumulado",
                "selected_product_id": [str(product["id"])],
                f"product_quantity_{product['id']}": "5",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Resumen acumulado por farmacia", response.data)

        with self.app.app_context():
            atlas_lines = list_order_products("109011", "Pharmacie Atlas")
            riviera_lines = list_order_products("109011", "Pharmacie Riviera")
        self.assertEqual(atlas_lines[0]["quantity"], "5")
        self.assertEqual(riviera_lines[0]["quantity"], "4")
        self.assertIn(b">9<", response.data)

    def test_selected_rows_can_be_deleted_from_edit_mode(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Delete Lab",
                        "name": "Producto Seleccionado 1",
                        "ppv": "10",
                        "pph": "7",
                        "tax": "7%",
                        "barcode": "710001",
                    },
                    {
                        "supplier": "Delete Lab",
                        "name": "Producto Seleccionado 2",
                        "ppv": "11",
                        "pph": "8",
                        "tax": "7%",
                        "barcode": "710002",
                    },
                ],
            )
            selected_ids = [
                str(row["id"])
                for row in list_records("products")
                if str(row["name"]).startswith("Producto Seleccionado")
            ]

        self.login()
        response = self.client.post(
            "/products?edit=1",
            data={
                "row_action": "delete_selected",
                "selected_record_id": selected_ids,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2 filas eliminadas", response.data)

        with self.app.app_context():
            product_names = [row["name"] for row in list_records("products")]
        self.assertNotIn("Producto Seleccionado 1", product_names)
        self.assertNotIn("Producto Seleccionado 2", product_names)

    def test_delete_selected_requires_a_selection(self):
        self.login()
        response = self.client.post(
            "/products?edit=1",
            data={"row_action": "delete_selected"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Selecciona al menos una fila", response.data)
        self.assertIn(b"records-edit-form-products", response.data)

    def test_admin_can_bulk_import_products_from_excel(self):
        self.login()
        template = self.client.get("/imports/template/products.xlsx")
        self.assertEqual(template.status_code, 200)
        self.assertEqual(
            template.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        excel_stream, filename = self.excel_file(
            ["Proveedor", "Producto", "PPV", "PPH", "IVA", "Codigo"],
            [
                ["Carga Lab", "Producto Excel 1", "11.50", "8.10", "7%", "900001"],
                ["Carga Lab", "Producto Excel 2", "12.50", "9.10", "20%", "900002"],
            ],
        )
        response = self.client.post(
            "/products",
            data={
                "bulk_action": "import_excel",
                "excel_file": (excel_stream, filename),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Carga masiva completada: 2 registros", response.data)

        with self.app.app_context():
            product_names = [row["name"] for row in list_records("products")]
        self.assertIn("Producto Excel 1", product_names)
        self.assertIn("Producto Excel 2", product_names)

    def test_bulk_import_limits_are_configured_for_large_excels(self):
        self.assertGreaterEqual(self.app.config["MAX_CONTENT_LENGTH"], 64 * 1024 * 1024)
        self.assertGreaterEqual(self.app.config["MAX_FORM_MEMORY_SIZE"], 64 * 1024 * 1024)
        self.assertGreaterEqual(self.app.config["MAX_FORM_PARTS"], 50000)

    def test_products_edit_uses_separate_bulk_upload_form(self):
        self.login()
        response = self.client.get("/products?edit=1")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        bulk_start = html.index("bulk-upload-form")
        bulk_end = html.index("</form>", bulk_start)
        edit_start = html.index("records-edit-form-products")

        self.assertLess(bulk_end, edit_start)
        self.assertIn("Max. 64 MB", html)

    def test_admin_can_bulk_import_more_than_two_thousand_products(self):
        self.login()
        rows = [
            [
                f"Carga Lab {index}",
                f"Producto Masivo {index}",
                "11.50",
                "8.10",
                "7%",
                f"990{index:06d}",
            ]
            for index in range(1, 2501)
        ]
        excel_stream, filename = self.excel_file(
            ["Proveedor", "Producto", "PPV", "PPH", "IVA", "Codigo"],
            rows,
            "productos-masivos.xlsx",
        )
        response = self.client.post(
            "/products",
            data={
                "bulk_action": "import_excel",
                "excel_file": (excel_stream, filename),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            imported = [
                row
                for row in list_records("products")
                if str(row["name"]).startswith("Producto Masivo ")
            ]
        self.assertEqual(len(imported), 2500)

    def test_large_upload_limit_error_returns_to_edit_mode(self):
        self.login()
        self.app.config["MAX_CONTENT_LENGTH"] = 512
        excel_stream, filename = self.excel_file(
            ["Proveedor", "Producto", "PPV", "PPH", "IVA", "Codigo"],
            [["Carga Lab", "Producto Grande", "11.50", "8.10", "7%", "900001"]],
            "archivo-grande.xlsx",
        )

        response = self.client.post(
            "/products",
            data={
                "bulk_action": "import_excel",
                "excel_file": (excel_stream, filename),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"demasiado grande", response.data)
        self.assertIn(b"records-edit-form-products", response.data)

    def test_offers_and_users_inline_edit_render(self):
        self.login()
        for route, marker in [
            ("/offers?edit=1", b"records-edit-form-offers"),
            ("/users?edit=1", b"records-edit-form-users"),
            ("/purchaseorders?edit=1", b"records-edit-form-purchaseorders"),
        ]:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(marker, response.data)

    def test_users_inline_edit_persists_new_pharmacy(self):
        self.login()
        response = self.client.post(
            "/users",
            data={
                "record_id": ["1"],
                "record_1_pharmacy": "Pharmacie Horizon",
                "record_1_first_name": "Sara",
                "record_1_last_name": "Demo",
                "record_1_email": "sara.demo@example.com",
                "record_1_password": "admin123",
                "record_1_phone": "06 15 65 75 39",
                "record_1_admin": "Oui",
                "record_1_status": "Actif",
                "new_pharmacy": "Farmacia Nueva",
                "new_first_name": "Lucia",
                "new_last_name": "Demo",
                "new_email": "lucia@example.com",
                "new_password": "lucia123",
                "new_phone": "06 44 55 66 77",
                "new_admin": "Non",
                "new_status": "Actif",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            pharmacy_names = [row["pharmacy"] for row in list_records("users")]
        self.assertIn("Farmacia Nueva", pharmacy_names)

    def test_pharmacy_user_can_only_edit_purchaseorders(self):
        self.login_pharmacy()

        response = self.client.get("/purchaseorders?edit=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"records-edit-form-purchaseorders", response.data)

        response = self.client.post(
            "/purchaseorders",
            data={
                "record_id": ["1"],
                "record_1_number": "105900",
                "record_1_subject": "Pedido farmacia actualizado",
                "record_1_manager": "Mina Test",
                "record_1_supplier": "Atlas Distribution",
                "record_1_deadline": "2026-06-28",
                "record_1_updated": "2026-06-18",
                "record_1_products": "7",
                "record_1_quantity": "200",
                "record_1_status": "Ouverte",
                "record_1_archived": "0",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            order_subjects = [row["subject"] for row in list_records("purchaseorders")]
        self.assertIn("Pedido farmacia actualizado", order_subjects)

        excel_stream, filename = self.excel_file(
            [
                "N.",
                "Objeto",
                "Gestor",
                "Proveedor",
                "Fecha limite",
                "Actualizado",
                "Productos",
                "Cantidad",
                "Estado",
            ],
            [
                [
                    "106001",
                    "Pedido desde Excel",
                    "Mina Test",
                    "Medica Nord",
                    "2026-08-01",
                    "2026-06-18",
                    "3",
                    "40",
                    "Ouverte",
                ]
            ],
            "orders.xlsx",
        )
        response = self.client.post(
            "/purchaseorders",
            data={
                "bulk_action": "import_excel",
                "excel_file": (excel_stream, filename),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            order_subjects = [row["subject"] for row in list_records("purchaseorders")]
        self.assertIn("Pedido desde Excel", order_subjects)

        response = self.client.get("/products?edit=1", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"records-edit-form-products", response.data)
        self.assertIn(b"No tienes permisos", response.data)

        response = self.client.post(
            "/products",
            data={
                "record_id": ["1"],
                "record_1_supplier": "Demo Labs",
                "record_1_name": "No permitido",
                "record_1_ppv": "1",
                "record_1_pph": "1",
                "record_1_tax": "0%",
                "record_1_barcode": "0",
            },
        )
        self.assertEqual(response.status_code, 403)

        excel_stream, filename = self.excel_file(
            ["Proveedor", "Producto", "PPV", "PPH", "IVA", "Codigo"],
            [["No", "No permitido", "1", "1", "0%", "0"]],
        )
        response = self.client.post(
            "/products",
            data={
                "bulk_action": "import_excel",
                "excel_file": (excel_stream, filename),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/imports/template/products.xlsx")
        self.assertEqual(response.status_code, 403)

    def test_pharmacy_user_can_view_all_main_modules_readonly_except_orders(self):
        self.login_pharmacy()
        readonly_routes = [
            ("/suppliers", b"Editar proveedores"),
            ("/contacts", b"Editar contactos"),
            ("/products", b"Editar productos"),
            ("/offers", b"Editar ofertas"),
            ("/users", b"Editar farmacias"),
        ]

        for route, edit_label in readonly_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(edit_label, response.data)

        response = self.client.get("/products?edit=1", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"records-edit-form-products", response.data)

        response = self.client.get("/users?edit=1", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"records-edit-form-users", response.data)

    def test_pharmacy_user_sees_full_navigation(self):
        self.login_pharmacy()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for label in [b"Proveedores", b"Productos", b"Ofertas", b"Farmacias", b"Pedidos"]:
            with self.subTest(label=label):
                self.assertIn(label, response.data)

    def test_table_pages_show_twenty_five_rows_with_navigation(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Paginacion Lab",
                        "name": f"Producto Pag {index}",
                        "ppv": "10",
                        "pph": "7",
                        "tax": "7%",
                        "barcode": f"8800{index:04d}",
                    }
                    for index in range(1, 31)
                ],
            )
            total_products = len(list_records("products"))

        self.login()
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"Mostrando 1-25 de {total_products} registros".encode(), response.data)
        self.assertIn(b"Pagina 1 de 2", response.data)
        self.assertIn(b'href="/products?page=2"', response.data)
        self.assertNotIn(b"Producto Pag 30", response.data)

        response = self.client.get("/products?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f"Mostrando 26-{total_products} de {total_products} registros".encode(),
            response.data,
        )
        self.assertIn(b"Pagina 2 de 2", response.data)
        self.assertIn(b"Producto Pag 30", response.data)
        self.assertIn(b'href="/products"', response.data)

    def test_edit_mode_is_paginated(self):
        with self.app.app_context():
            append_records(
                "products",
                [
                    {
                        "supplier": "Edicion Lab",
                        "name": f"Producto Edit {index}",
                        "ppv": "10",
                        "pph": "7",
                        "tax": "7%",
                        "barcode": f"7700{index:04d}",
                    }
                    for index in range(1, 31)
                ],
            )
            total_products = len(list_records("products"))

        self.login()
        response = self.client.get("/products?edit=1")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertEqual(html.count('name="record_id"'), 25)
        self.assertEqual(html.count('name="selected_record_id"'), 25)
        self.assertIn("Seleccionar todo", html)
        self.assertIn("Eliminar seleccionados", html)
        self.assertIn("data-select-toggle", html)
        self.assertIn(f"Mostrando 1-25 de {total_products} registros", html)

        response = self.client.get("/products?edit=1&page=2")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertEqual(html.count('name="record_id"'), total_products - 25)
        self.assertEqual(html.count('name="selected_record_id"'), total_products - 25)
        self.assertIn(f"Mostrando 26-{total_products} de {total_products} registros", html)

    def test_pharmacy_user_cannot_create_event(self):
        self.login_pharmacy()
        response = self.client.get("/events")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Crear", response.data)

        response = self.client.get("/event/create")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
