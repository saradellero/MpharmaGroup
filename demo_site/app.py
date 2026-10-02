from __future__ import annotations

import argparse
from copy import deepcopy
from functools import wraps
from math import ceil
from typing import Callable
from urllib.parse import urlencode

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from .auth import authenticate_user, can_edit_table, is_admin_user, visible_nav_items
from .data import (
    BRAND,
    CALENDAR_EVENTS,
    NAV_ITEMS,
    ORDER_DETAIL,
    PROFILE,
    TABLES,
)
from .dashboard import build_dashboard_stats
from .excel_import import build_excel_template, parse_excel_records
from .validation import validate_login, validate_recovery
from .i18n import SUPPORTED_LANGUAGES, translate_html
from .storage import init_app as init_storage
from .storage import (
    append_records,
    delete_records,
    format_date_for_display,
    get_extra_fields,
    get_record_fields,
    list_invoice_products,
    list_order_products,
    list_records,
    replace_order_products,
    save_invoice_products,
    save_order_products,
    save_records,
    update_purchase_order,
    update_user_password,
)

DEFAULT_UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024
DEFAULT_FORM_MEMORY_LIMIT_BYTES = 64 * 1024 * 1024
DEFAULT_FORM_PARTS_LIMIT = 50000
TABLE_PAGE_SIZE = 25
EDITABLE_ROUTE_PATHS = {
    "/suppliers",
    "/contacts",
    "/products",
    "/offers",
    "/purchaseorders",
    "/purchaseorders/index/index/archived/true",
    "/users",
}


def create_app(config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="../static")
    app.jinja_env.filters["date_display"] = format_date_for_display
    app.config["SECRET_KEY"] = "dev-demo-secret-key"
    if config:
        app.config.update(config)
    apply_request_limits(app, config or {})
    init_storage(app)
    with app.app_context():
        sync_existing_purchase_order_totals()

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        current_user = session.get(
            "user",
            {
                "name": "Invitado",
                "email": "",
                "role": "",
                "pharmacy": "",
                "is_admin": False,
            },
        )
        return {
            "brand": BRAND,
            "language": session.get("language", "es"),
            "nav_items": visible_nav_items(current_user, NAV_ITEMS),
            "current_user": current_user,
            "upload_limit_label": format_bytes(int(app.config["MAX_CONTENT_LENGTH"])),
        }

    @app.after_request
    def localize_response(response: object) -> object:
        if getattr(response, "mimetype", "") == "text/html" and session.get("language") == "fr":
            response.set_data(translate_html(response.get_data(as_text=True), "fr"))
        return response

    @app.route("/set-language")
    def set_language() -> object:
        language = request.args.get("lang", "es").lower()
        if language not in SUPPORTED_LANGUAGES:
            language = "es"
        session["language"] = language
        next_url = request.args.get("next", "/")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        return redirect(next_url)

    @app.errorhandler(RequestEntityTooLarge)
    def request_entity_too_large(error: RequestEntityTooLarge) -> object:
        flash(
            (
                "El fichero o formulario es demasiado grande. "
                f"El limite configurado es {format_bytes(int(app.config['MAX_CONTENT_LENGTH']))}."
            ),
            "error",
        )
        if request.path in EDITABLE_ROUTE_PATHS:
            return redirect(f"{request.path}?edit=1", code=303)
        return redirect(request.referrer or url_for("dashboard"), code=303)

    def login_required(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args: object, **kwargs: object) -> object:
            if not session.get("authenticated"):
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for("login", redirect_url=next_url))
            return view(*args, **kwargs)

        return wrapped

    def admin_required(view: Callable) -> Callable:
        @wraps(view)
        @login_required
        def wrapped(*args: object, **kwargs: object) -> object:
            if not is_admin_user(session.get("user")):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    @app.route("/auth/login", methods=["GET", "POST"])
    def login() -> object:
        redirect_url = request.values.get("redirect_url", "/")
        errors: dict[str, str] = {}
        values = {"email": request.form.get("email", ""), "remember": "1"}

        if request.method == "POST":
            errors = validate_login(request.form)
            values["remember"] = "1" if request.form.get("remember_me") else "0"
            authenticated_user = None
            if not errors:
                authenticated_user = authenticate_user(
                    request.form.get("email", ""),
                    request.form.get("password", ""),
                )
            if authenticated_user:
                session["authenticated"] = True
                session["user"] = authenticated_user
                return redirect(redirect_url or url_for("dashboard"))
            if not errors:
                errors["password"] = "Usuario o contrasena incorrectos."
            flash("Revisa los datos de acceso de la demo.", "error")

        return render_template(
            "auth/login.html",
            title="Acceso",
            values=values,
            errors=errors,
            redirect_url=redirect_url,
        )

    @app.route("/auth/password-recovery", methods=["GET", "POST"])
    def password_recovery() -> object:
        errors: dict[str, str] = {}
        values = {"email": request.form.get("email", "")}
        sent = False
        if request.method == "POST":
            errors = validate_recovery(request.form)
            sent = not errors
        return render_template(
            "auth/recovery.html",
            title="Recuperacion",
            values=values,
            errors=errors,
            sent=sent,
        )

    @app.route("/auth/logout")
    def logout() -> object:
        session.clear()
        return redirect(url_for("login", redirect_url="/"))

    @app.route("/")
    @login_required
    def dashboard() -> object:
        return render_template(
            "dashboard.html",
            title="Panel",
            active="dashboard",
            stats=build_dashboard_stats(list_records),
            events=CALENDAR_EVENTS[:4],
            recent_orders=list_records("purchaseorders", archived=False)[:5],
        )

    def table_response(table_key: str, archived: bool = False) -> object:
        table = TABLES[table_key]
        user = session.get("user")
        table_can_edit = can_edit_table(user, table_key)
        if request.method == "POST":
            if not table_can_edit:
                abort(403)
            if request.form.get("bulk_action") == "import_excel":
                upload = request.files.get("excel_file")
                if not upload or not upload.filename:
                    flash("Selecciona un fichero Excel para cargar.", "error")
                    return redirect(f"{request.path}?edit=1")
                try:
                    imported_rows = parse_excel_records(table_key, upload.stream, archived)
                    inserted = append_records(table_key, imported_rows)
                except Exception:
                    flash("No se pudo leer el fichero Excel.", "error")
                    return redirect(f"{request.path}?edit=1")
                flash(f"Carga masiva completada: {inserted} registros anadidos.", "success")
                return redirect(request.path)
            if request.form.get("row_action") == "delete_selected":
                selected_ids = request.form.getlist("selected_record_id")
                deleted = delete_records(table_key, selected_ids)
                if deleted:
                    flash(f"{deleted} filas eliminadas.", "success")
                else:
                    flash("Selecciona al menos una fila para eliminar.", "error")
                return redirect(current_edit_url())

            fields = get_record_fields(table_key)
            existing_rows = []
            for record_id in request.form.getlist("record_id"):
                row = {"id": record_id}
                for field in fields:
                    row[field] = request.form.get(f"record_{record_id}_{field}", "")
                existing_rows.append(row)

            new_row = {field: request.form.get(f"new_{field}", "") for field in fields}
            for field in get_extra_fields(table_key):
                if not new_row.get(field):
                    new_row[field] = "1" if archived else "0"

            save_records(table_key, existing_rows, new_row)
            flash(f"{table['title']} guardados en la base de datos.", "success")
            return redirect(request.path)

        edit_requested = request.args.get("edit") == "1"
        if edit_requested and not table_can_edit:
            flash("No tienes permisos para editar este apartado.", "error")
            return redirect(request.path)

        rows = list_records(
            table_key,
            archived=archived if table_key == "purchaseorders" else None,
        )
        q = request.args.get("q", "").strip().lower()
        if q:
            rows = [
                row
                for row in rows
                if any(q in str(value).lower() for value in row.values())
            ]
        sort = request.args.get("sort", "")
        if sort:
            rows = sorted(rows, key=lambda row: str(row.get(sort, "")).lower())
            if request.args.get("direction") == "desc":
                rows = list(reversed(rows))
        paginated_rows, pagination = paginate_rows(rows)
        selected_order = request.args.get("selected_order", "").strip()
        order_summary = None
        if table_key == "purchaseorders" and selected_order and not edit_requested:
            order_summary = build_order_summary(selected_order)
        supplier_suggestions = sorted(
            {
                str(row.get("name", "")).strip()
                for row in list_records("suppliers")
                if str(row.get("name", "")).strip()
            },
            key=str.casefold,
        )
        product_suggestions = sorted(
            {
                str(row.get("name", "")).strip()
                for row in list_records("products")
                if str(row.get("name", "")).strip()
            },
            key=str.casefold,
        )
        return render_template(
            "table_page.html",
            title=table["title"],
            active=table["active"],
            table_key=table_key,
            table=table,
            rows=paginated_rows,
            q=q,
            archived=archived,
            pagination=pagination,
            edit_mode=edit_requested and table_can_edit,
            can_edit=table_can_edit,
            hidden_fields=get_extra_fields(table_key),
            edit_url=f"{request.path}?edit=1",
            edit_form_url=current_edit_url(),
            list_url=request.path,
            selected_order=selected_order,
            order_summary=order_summary,
            supplier_suggestions=supplier_suggestions,
            product_suggestions=product_suggestions,
        )

    @app.route("/imports/template/<table_key>.xlsx")
    @login_required
    def table_import_template(table_key: str) -> object:
        if table_key not in TABLES:
            abort(404)
        if not can_edit_table(session.get("user"), table_key):
            abort(403)
        labels = [label for _field, label in TABLES[table_key]["columns"]]
        output = build_excel_template(table_key, labels)
        filename = f"{table_key}-plantilla.xlsx"
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/suppliers", methods=["GET", "POST"])
    @login_required
    def suppliers() -> object:
        return table_response("suppliers")

    @app.route("/contacts", methods=["GET", "POST"])
    @login_required
    def contacts() -> object:
        return table_response("contacts")

    @app.route("/products", methods=["GET", "POST"])
    @login_required
    def products() -> object:
        return table_response("products")

    @app.route("/offers", methods=["GET", "POST"])
    @login_required
    def offers() -> object:
        return table_response("offers")

    @app.route("/purchaseorders", methods=["GET", "POST"])
    @login_required
    def purchaseorders() -> object:
        return table_response("purchaseorders", archived=False)

    @app.route("/purchaseorders/index/index/archived/true", methods=["GET", "POST"])
    @login_required
    def purchaseorders_archived() -> object:
        return table_response("purchaseorders", archived=True)

    @app.route("/users", methods=["GET", "POST"])
    @login_required
    def users() -> object:
        return table_response("users")

    @app.route("/events")
    @login_required
    def events() -> object:
        return render_template(
            "events.html",
            title="Planning",
            active="events",
            events=CALENDAR_EVENTS,
            can_edit=is_admin_user(session.get("user")),
        )

    @app.route("/reports")
    @login_required
    def reports() -> object:
        year = request.args.get("year", "2026").strip() or "2026"
        warehouse = normalize_report_warehouse(request.args.get("warehouse", ""))
        return render_template(
            "reports.html",
            title="Reportes",
            active="reports",
            year=year,
            warehouse=warehouse,
            balance=build_report_balance(year, warehouse),
            labs=build_report_labs(year, warehouse),
        )

    @app.route("/reports/index/details/type/<report_type>/year/<year>/warehouse/<warehouse>/user_id/<user_id>")
    @login_required
    def report_detail(report_type: str, year: str, warehouse: str, user_id: str) -> object:
        if report_type not in {"paid", "received"}:
            abort(404)
        label = "pagado" if report_type == "paid" else "recibido"
        return render_template(
            "report_detail.html",
            title="Detalle de reporte",
            active="reports",
            report_type=label,
            year=year,
            warehouse=warehouse,
            user_id=user_id,
            orders=build_report_detail_orders(
                report_type,
                year,
                normalize_report_warehouse(warehouse),
                user_id,
            ),
        )

    @app.route("/contact/create", methods=["GET", "POST"])
    @admin_required
    def contact_create() -> object:
        if request.method == "POST":
            flash("Contacto guardado en modo demo.", "success")
            if request.form.get("save_new"):
                return redirect(url_for("contact_create"))
            return redirect(url_for("contacts"))
        return render_template(
            "contact_form.html",
            title="Nuevo contacto",
            active="suppliers",
            values={},
        )

    @app.route("/event/create", methods=["GET", "POST"])
    @admin_required
    def event_create() -> object:
        if request.method == "POST":
            flash("Evento guardado en modo demo.", "success")
            if request.form.get("save_new"):
                return redirect(url_for("event_create"))
            return redirect(url_for("events"))
        return render_template(
            "event_form.html",
            title="Nuevo evento",
            active="events",
            values={"date": "2026-06-18", "assigned_to": "Sara Demo"},
        )

    @app.route("/purchaseorder/create", methods=["GET", "POST"])
    @login_required
    def purchaseorder_create() -> object:
        catalog = build_order_product_catalog()
        pharmacy_scope = order_product_scope_for_user(session.get("user"))
        default_manager = (
            str((session.get("user") or {}).get("pharmacy", "")).strip()
            or str((session.get("user") or {}).get("name", "")).strip()
        )
        manager_options = build_manager_options(default_manager)
        if request.method == "POST":
            order_number = next_order_number()
            selected_products = selected_products_from_form(catalog)
            selected_manager = request.form.get("owner_id", "").strip()
            append_records(
                "purchaseorders",
                [
                    {
                        "number": order_number,
                        "subject": request.form.get("subject", "").strip(),
                        "manager": selected_manager
                        or str(session.get("user", {}).get("pharmacy", "")).strip()
                        or str(session.get("user", {}).get("name", "")).strip(),
                        "supplier": request.form.get("supplier_id", "").strip(),
                        "deadline": request.form.get("deadline", "").strip(),
                        "updated": "",
                        "products": str(len(selected_products)),
                        "quantity": "",
                        "status": "Ouverte",
                        "archived": "0",
                        "warehouse": request.form.get("warehouse", "").strip(),
                        "contact": request.form.get("contact_id", "").strip(),
                        "terms_and_conditions": request.form.get(
                            "terms_and_conditions", ""
                        ).strip(),
                        "payment_timeframe": request.form.get(
                            "payment_timeframe", ""
                        ).strip(),
                        "delivery_timeframe": request.form.get(
                            "delivery_timeframe", ""
                        ).strip(),
                        "delivery_transporter": request.form.get(
                            "delivery_transporter", ""
                        ).strip(),
                        "payment_methods": ",".join(
                            request.form.getlist("accepted_payment_methods[]")
                        ),
                    }
                ],
            )
            save_order_products(order_number, selected_products, pharmacy_scope)
            sync_purchase_order_product_totals(order_number)
            flash("Pedido creado.", "success")
            return redirect(url_for("purchaseorder_edit", order_id=order_number))

        order = build_order_detail("", empty=True, pharmacy_scope=pharmacy_scope)
        order["owner_id"] = default_manager or (
            manager_options[0]["value"] if manager_options else ""
        )
        return render_template(
            "order_form.html",
            title="Nuevo pedido",
            active="purchaseorders",
            order=order,
            order_id="Nuevo",
            supplier_options=build_supplier_options(catalog, order["supplier"]),
            product_catalog=catalog,
            selected_product_ids=selected_order_product_ids(order, catalog),
            selected_product_quantities=selected_order_product_quantities(order, catalog),
            manager_options=manager_options,
            details_editable=True,
            pharmacy_mode=False,
        )

    @app.route("/purchaseorder/edit/<order_id>", methods=["GET", "POST"])
    @login_required
    def purchaseorder_edit(order_id: str) -> object:
        catalog = build_order_product_catalog()
        user = session.get("user")
        pharmacy_scope = order_product_scope_for_user(user)
        pharmacy_view = bool(pharmacy_scope)
        order_manager = is_order_manager(order_id, user)
        manager_mode = request.args.get("mode") == "manager"
        manager_pharmacy_mode = request.args.get("mode") == "manager_pharmacy"
        selected_manager_pharmacy = request.args.get("pharmacy", "").strip()
        if (manager_mode or manager_pharmacy_mode) and not order_manager:
            abort(403)
        edit_mode = (
            request.args.get("mode") == "edit"
            or manager_mode
            or manager_pharmacy_mode
            or not pharmacy_view
        )
        if request.method == "POST":
            if manager_pharmacy_mode:
                available_pharmacies = build_pharmacy_columns(
                    list_order_products(order_id)
                )
                if selected_manager_pharmacy not in available_pharmacies:
                    abort(404)
                selected_products = selected_products_from_form(catalog)
                save_order_products(
                    order_id,
                    selected_products,
                    selected_manager_pharmacy,
                )
                sync_purchase_order_product_totals(order_id)
                flash(
                    f"Pedido de {selected_manager_pharmacy} actualizado.",
                    "success",
                )
                return redirect(url_for("purchaseorder_edit", order_id=order_id))

            if manager_mode:
                matrix = build_order_manager_matrix(order_id)
                new_product_values = manager_new_product_values_from_form()
                new_product = None
                if any(new_product_values.values()):
                    missing_fields = [
                        label
                        for key, label in (
                            ("name", "Producto"),
                            ("ppv", "PPV"),
                            ("pph", "PPH"),
                            ("tax", "IVA"),
                        )
                        if not new_product_values.get(key)
                    ]
                    if missing_fields:
                        flash(
                            "Para crear un producto son obligatorios: "
                            + ", ".join(missing_fields)
                            + ".",
                            "error",
                        )
                        order = build_order_detail(order_id, pharmacy_scope=pharmacy_scope)
                        return render_template(
                            "order_manager_form.html",
                            title=f"Pedido {order_id} - Gestor",
                            active="purchaseorders",
                            order=order,
                            order_id=order_id,
                            manager_options=build_manager_options(
                                str(order.get("owner_id", ""))
                            ),
                            manager_matrix=matrix,
                            new_product_values=new_product_values,
                        )
                    supplier = request.form.get("supplier_id", "").strip()
                    append_records(
                        "products",
                        [
                            {
                                "supplier": supplier,
                                "name": new_product_values["name"],
                                "ppv": new_product_values["ppv"],
                                "pph": new_product_values["pph"],
                                "tax": new_product_values["tax"],
                                "barcode": new_product_values["barcode"],
                            }
                        ],
                    )
                    new_product = max(
                        (
                            row
                            for row in list_records("products")
                            if str(row.get("supplier", "")).strip() == supplier
                            and str(row.get("name", "")).strip()
                            == new_product_values["name"]
                        ),
                        key=lambda row: int(row.get("id", 0)),
                        default=None,
                    )
                update_manager_catalog_prices_from_form(matrix)
                manager_products = manager_products_from_form(matrix)
                if new_product:
                    pharmacies = matrix.get("pharmacies", [])
                    if isinstance(pharmacies, list):
                        for pharmacy_index, pharmacy in enumerate(pharmacies):
                            quantity = request.form.get(
                                f"manager_new_quantity_{pharmacy_index}", ""
                            ).strip()
                            if quantity_is_at_least_one(quantity):
                                manager_products.append(
                                    {
                                        "id": str(new_product.get("id", "")),
                                        "supplier": str(new_product.get("supplier", "")),
                                        "name": str(new_product.get("name", "")),
                                        "ppv": str(new_product.get("ppv", "")),
                                        "pph": str(new_product.get("pph", "")),
                                        "tax": str(new_product.get("tax", "")),
                                        "barcode": str(new_product.get("barcode", "")),
                                        "pharmacy": str(pharmacy),
                                        "quantity": quantity,
                                    }
                                )
                update_purchase_order(order_id, manager_order_values_from_form())
                replace_order_products(order_id, manager_products)
                sync_purchase_order_product_totals(order_id)
                flash("Pedido actualizado como gestor.", "success")
                return redirect(url_for("purchaseorder_edit", order_id=order_id))

            selected_products = selected_products_from_form(catalog)
            values = {"products": str(len(selected_products))}
            if is_admin_user(user) or order_manager:
                values.update(manager_order_values_from_form())
            update_purchase_order(order_id, values)
            save_order_products(order_id, selected_products, pharmacy_scope)
            sync_purchase_order_product_totals(order_id)
            flash("Pedido actualizado.", "success")
            if pharmacy_view:
                return redirect(url_for("purchaseorder_edit", order_id=order_id))

        if pharmacy_view and not edit_mode:
            order = build_order_detail(order_id, pharmacy_scope=pharmacy_scope)
            return render_template(
                "order_summary.html",
                title=f"Pedido {order_id}",
                active="purchaseorders",
                order=order,
                order_id=order_id,
                order_summary=build_order_summary(order_id),
                modify_url=url_for("purchaseorder_edit", order_id=order_id, mode="edit"),
                manager_url=(
                    url_for("purchaseorder_edit", order_id=order_id, mode="manager")
                    if order_manager
                    else None
                ),
                print_url=url_for("purchaseorder_print", order_id=order_id),
                current_pharmacy=pharmacy_scope,
            )

        if manager_pharmacy_mode:
            available_pharmacies = build_pharmacy_columns(
                list_order_products(order_id)
            )
            if selected_manager_pharmacy not in available_pharmacies:
                abort(404)
            order = build_order_detail(
                order_id,
                pharmacy_scope=selected_manager_pharmacy,
            )
            return render_template(
                "order_form.html",
                title=f"Pedido {order_id} - {selected_manager_pharmacy}",
                active="purchaseorders",
                order=order,
                order_id=order_id,
                supplier_options=build_supplier_options(catalog, order["supplier"]),
                product_catalog=catalog,
                selected_product_ids=selected_order_product_ids(order, catalog),
                selected_product_quantities=selected_order_product_quantities(order, catalog),
                pharmacy_mode=True,
                details_editable=False,
                manager_options=build_manager_options(str(order.get("owner_id", ""))),
                manager_return_url=url_for(
                    "purchaseorder_edit", order_id=order_id, mode="manager"
                ),
                selected_pharmacy=selected_manager_pharmacy,
            )

        if manager_mode:
            order = build_order_detail(order_id, pharmacy_scope=pharmacy_scope)
            return render_template(
                "order_manager_form.html",
                title=f"Pedido {order_id} - Gestor",
                active="purchaseorders",
                order=order,
                order_id=order_id,
                manager_options=build_manager_options(str(order.get("owner_id", ""))),
                manager_matrix=build_order_manager_matrix(order_id),
                new_product_values={},
            )

        order = build_order_detail(order_id, pharmacy_scope=pharmacy_scope)
        return render_template(
            "order_form.html",
            title=f"Pedido {order_id}",
            active="purchaseorders",
            order=order,
            order_id=order_id,
            supplier_options=build_supplier_options(catalog, order["supplier"]),
            product_catalog=catalog,
            selected_product_ids=selected_order_product_ids(order, catalog),
            selected_product_quantities=selected_order_product_quantities(order, catalog),
            pharmacy_mode=pharmacy_view,
            manager_options=build_manager_options(str(order.get("owner_id", ""))),
            details_editable=is_admin_user(user) or order_manager,
        )

    @app.route("/purchaseorder/print/<order_id>")
    @login_required
    def purchaseorder_print(order_id: str) -> object:
        user = session.get("user")
        requested_scope = request.args.get("scope", "").strip()
        requested_pharmacy = request.args.get("pharmacy", "").strip()
        manager = is_order_manager(order_id, user)
        if requested_scope in {"all", "pharmacy"} and not manager:
            abort(403)

        is_total_print = requested_scope == "all"
        if is_total_print:
            pharmacy_scope = None
            order = build_order_detail(order_id, pharmacy_scope=None)
            printable_products = build_aggregated_print_products(order_id)
            print_label = "Pedido total"
        else:
            pharmacy_scope = order_product_scope_for_user(user)
            if requested_scope == "pharmacy":
                available_pharmacies = build_pharmacy_columns(
                    list_order_products(order_id)
                )
                if requested_pharmacy not in available_pharmacies:
                    abort(404)
                pharmacy_scope = requested_pharmacy
            order = build_order_detail(order_id, pharmacy_scope=pharmacy_scope)
            printable_products = [
                product
                for product in order.get("products", [])
                if isinstance(product, dict)
                and quantity_is_at_least_one(str(product.get("quantity", "")))
            ]
            print_label = (
                f"Pedido de {pharmacy_scope}"
                if requested_scope == "pharmacy"
                else "Pedido"
            )
        return render_template(
            "order_print.html",
            title=f"Imprimir pedido {order_id}",
            active="purchaseorders",
            order=order,
            order_id=order_id,
            products=printable_products,
            pharmacy_totals=build_order_totals(order_id, pharmacy_scope),
            accumulated_totals=build_order_totals(order_id),
            is_total_print=is_total_print,
            print_label=print_label,
        )

    @app.route("/purchaseorder/invoices/<order_id>", methods=["GET", "POST"])
    @login_required
    def purchaseorder_invoices(order_id: str) -> object:
        if not is_order_manager(order_id, session.get("user")):
            abort(403)
        order = build_order_detail(order_id, pharmacy_scope=None)
        products = build_aggregated_print_products(order_id)
        if request.method == "POST":
            save_invoice_products(order_id, invoice_products_from_form(products))
            flash("Datos de factura guardados.", "success")
            return redirect(url_for("purchaseorder_invoices", order_id=order_id))
        products = build_invoice_rows(order_id, products)
        return render_template(
            "order_invoices.html",
            title=f"Facturas del pedido {order_id}",
            active="purchaseorders",
            order=order,
            order_id=order_id,
            products=products,
            quantity_total=format_quantity(
                sum(parse_quantity(product.get("quantity", "")) for product in products)
            ),
        )

    @app.route("/purchaseorder/recap/<order_id>")
    @login_required
    def purchaseorder_recap(order_id: str) -> object:
        manager_view = is_order_manager(order_id, session.get("user"))
        return render_template(
            "order_recap.html",
            title=f"Recapitulacion del pedido {order_id}",
            active="purchaseorders",
            order=build_order_detail(order_id, pharmacy_scope=None),
            order_id=order_id,
            recap=build_order_recap(order_id),
            back_url=(
                url_for("purchaseorder_edit", order_id=order_id, mode="manager")
                if manager_view
                else url_for("purchaseorder_edit", order_id=order_id)
            ),
            back_label="Volver al gestor" if manager_view else "Volver al pedido",
        )

    @app.route("/settings/usersettings/profile")
    @login_required
    def profile() -> object:
        profile_data = PROFILE | {
            "email": session["user"].get("email", PROFILE["email"]),
            "first_name": session["user"].get("first_name", PROFILE["first_name"]),
            "last_name": session["user"].get("last_name", PROFILE["last_name"]),
            "pharmacy_name": session["user"].get("pharmacy", PROFILE["pharmacy_name"]),
            "mobile": session["user"].get("phone", PROFILE["mobile"]),
        }
        return render_template(
            "profile.html",
            title="Perfil",
            active="settings",
            profile=profile_data,
        )

    @app.route("/settings/usersettings/edit-profile", methods=["GET", "POST"])
    @login_required
    def edit_profile() -> object:
        if request.method == "POST":
            flash("Perfil actualizado en modo demo.", "success")
            return redirect(url_for("profile"))
        return render_template(
            "edit_profile.html",
            title="Editar perfil",
            active="settings",
            profile=PROFILE,
        )

    @app.route("/settings/usersettings/change-password", methods=["GET", "POST"])
    @login_required
    def change_password() -> object:
        errors: dict[str, str] = {}
        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm = request.form.get("password_confirm", "")
            if new_password != confirm:
                errors["password_confirm"] = "Las contrasenas no coinciden."
            elif not new_password:
                errors["new_password"] = "Introduce una nueva contrasena."
            else:
                update_user_password(session["user"]["email"], new_password)
                flash("Contrasena actualizada.", "success")
                return redirect(url_for("profile"))
        return render_template(
            "change_password.html",
            title="Cambiar contrasena",
            active="settings",
            errors=errors,
        )

    @app.errorhandler(404)
    def not_found(error: object) -> object:
        return (
            render_template(
                "404.html",
                title="Pagina no encontrada",
                active="",
                path=request.path,
            ),
            404,
        )

    return app


def apply_request_limits(app: Flask, config: dict[str, object]) -> None:
    if "MAX_CONTENT_LENGTH" not in config:
        app.config["MAX_CONTENT_LENGTH"] = DEFAULT_UPLOAD_LIMIT_BYTES
    if "MAX_FORM_MEMORY_SIZE" not in config:
        app.config["MAX_FORM_MEMORY_SIZE"] = DEFAULT_FORM_MEMORY_LIMIT_BYTES
    if "MAX_FORM_PARTS" not in config:
        app.config["MAX_FORM_PARTS"] = DEFAULT_FORM_PARTS_LIMIT


def paginate_rows(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    total = len(rows)
    total_pages = max(1, ceil(total / TABLE_PAGE_SIZE))
    requested_page = request.args.get("page", "1")
    try:
        current_page = int(requested_page)
    except ValueError:
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)
    start = (current_page - 1) * TABLE_PAGE_SIZE
    end = min(start + TABLE_PAGE_SIZE, total)

    def page_url(page: int) -> str:
        args = request.args.to_dict(flat=True)
        if page <= 1:
            args.pop("page", None)
        else:
            args["page"] = str(page)
        query = urlencode(args)
        return f"{request.path}?{query}" if query else request.path

    pagination = {
        "page": current_page,
        "per_page": TABLE_PAGE_SIZE,
        "total": total,
        "total_pages": total_pages,
        "start": start + 1 if total else 0,
        "end": end,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "first_url": page_url(1),
        "prev_url": page_url(current_page - 1),
        "next_url": page_url(current_page + 1),
        "last_url": page_url(total_pages),
    }
    return rows[start:end], pagination


def current_edit_url() -> str:
    args = request.args.to_dict(flat=True)
    args["edit"] = "1"
    query = urlencode(args)
    return f"{request.path}?{query}"


def build_order_summary(order_id: str) -> dict[str, object]:
    order_number = str(order_id).strip()
    saved_products = list_order_products(order_number)
    pharmacies = build_pharmacy_columns(saved_products)
    product_rows: list[dict[str, object]] = []
    product_index: dict[str, dict[str, object]] = {}

    for product in saved_products:
        pharmacy = str(product.get("pharmacy", "")).strip()
        if not pharmacy:
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if quantity <= 0:
            continue
        product_name = str(product.get("name", "")).strip()
        product_key = str(product.get("product_id", "") or product_name).strip()
        if not product_key or not product_name:
            continue
        if product_key not in product_index:
            product_index[product_key] = {
                "name": product_name,
                "quantities": {pharmacy_name: 0.0 for pharmacy_name in pharmacies},
                "total": 0.0,
            }
            product_rows.append(product_index[product_key])
        row = product_index[product_key]
        quantities = row["quantities"]
        if isinstance(quantities, dict):
            quantities[pharmacy] = float(quantities.get(pharmacy, 0.0)) + quantity
        row["total"] = float(row.get("total", 0.0)) + quantity

    totals = {pharmacy: 0.0 for pharmacy in pharmacies}
    grand_total = 0.0
    formatted_rows = []
    for row in product_rows:
        raw_quantities = row.get("quantities", {})
        formatted_quantities = {}
        for pharmacy in pharmacies:
            value = 0.0
            if isinstance(raw_quantities, dict):
                value = float(raw_quantities.get(pharmacy, 0.0))
            totals[pharmacy] += value
            formatted_quantities[pharmacy] = format_quantity_cell(value)
        row_total = float(row.get("total", 0.0))
        grand_total += row_total
        formatted_rows.append(
            {
                "name": row.get("name", ""),
                "quantities": formatted_quantities,
                "total": format_quantity(row_total),
            }
        )

    return {
        "order_number": order_number,
        "pharmacies": pharmacies,
        "rows": formatted_rows,
        "totals": {
            pharmacy: format_quantity(totals[pharmacy]) if totals[pharmacy] else ""
            for pharmacy in pharmacies
        },
        "grand_total": format_quantity(grand_total) if grand_total else "",
    }


def build_order_recap(order_id: str) -> dict[str, object]:
    saved_products = [
        product
        for product in list_order_products(str(order_id))
        if str(product.get("pharmacy", "")).strip()
        and parse_quantity(product.get("quantity", "")) > 0
    ]
    pharmacies = build_pharmacy_columns(saved_products)
    invoice_values = {
        invoice_product_key(row): row
        for row in list_invoice_products(order_id)
    }
    product_rows: list[dict[str, object]] = []
    product_index: dict[str, dict[str, object]] = {}

    for product in saved_products:
        product_name = str(product.get("name", "")).strip()
        if not product_name:
            continue
        key = invoice_product_key(product)
        if key not in product_index:
            invoice_row = invoice_values.get(key, {})
            discounted_pph = parse_optional_number(
                invoice_row.get("pph_discounted", "")
            )
            product_index[key] = {
                "name": product_name,
                "amounts": {pharmacy: 0.0 for pharmacy in pharmacies},
                "total": 0.0,
                "pph_discounted": discounted_pph or 0.0,
            }
            product_rows.append(product_index[key])
        row = product_index[key]
        quantity = parse_quantity(product.get("quantity", ""))
        amount = quantity * float(row.get("pph_discounted", 0.0))
        pharmacy = str(product.get("pharmacy", "")).strip()
        amounts = row.get("amounts", {})
        if isinstance(amounts, dict):
            amounts[pharmacy] = float(amounts.get(pharmacy, 0.0)) + amount
        row["total"] = float(row.get("total", 0.0)) + amount

    totals = {pharmacy: 0.0 for pharmacy in pharmacies}
    formatted_rows = []
    grand_total = 0.0
    for row in product_rows:
        raw_amounts = row.get("amounts", {})
        amounts = {}
        for pharmacy in pharmacies:
            value = 0.0
            if isinstance(raw_amounts, dict):
                value = float(raw_amounts.get(pharmacy, 0.0))
            totals[pharmacy] += value
            amounts[pharmacy] = format_invoice_number(value)
        row_total = float(row.get("total", 0.0))
        grand_total += row_total
        formatted_rows.append(
            {
                "name": row.get("name", ""),
                "amounts": amounts,
                "total": format_invoice_number(row_total),
            }
        )

    return {
        "order_number": str(order_id),
        "pharmacies": pharmacies,
        "rows": formatted_rows,
        "totals": {
            pharmacy: format_invoice_number(value)
            for pharmacy, value in totals.items()
        },
        "grand_total": format_invoice_number(grand_total),
    }


def normalize_report_warehouse(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized in {"", "0", "Todos", "todos"}:
        return ""
    if normalized == "1":
        return "Principal"
    return normalized


def report_order_year(order: dict[str, object]) -> str:
    for field in ("deadline", "updated"):
        value = str(order.get(field, "")).strip()
        for token in value.replace("/", "-").split("-"):
            if len(token) == 4 and token.isdigit() and token.startswith("20"):
                return token
    return ""


def report_orders(year: str, warehouse: str) -> list[dict[str, object]]:
    selected_warehouse = normalize_report_warehouse(warehouse)
    return [
        order
        for order in list_records("purchaseorders")
        if report_order_year(order) == str(year).strip()
        and (
            not selected_warehouse
            or str(order.get("warehouse", "")).strip() == selected_warehouse
        )
    ]


def report_invoice_values(order_id: str) -> dict[str, dict[str, object]]:
    return {
        invoice_product_key(row): row
        for row in list_invoice_products(order_id)
    }


def report_line_pph_discounted(
    product: dict[str, object],
    invoice_values: dict[str, dict[str, object]],
) -> float:
    invoice_row = invoice_values.get(invoice_product_key(product), {})
    discounted = parse_optional_number(invoice_row.get("pph_discounted", ""))
    if discounted is not None:
        return discounted
    return parse_quantity(product.get("pph", ""))


def report_order_amount(
    order_id: str,
    pharmacies: set[str] | None = None,
) -> float:
    products = list_order_products(str(order_id))
    invoice_values = report_invoice_values(order_id)
    total = 0.0
    for product in products:
        pharmacy = str(product.get("pharmacy", "")).strip()
        if not pharmacy or (pharmacies is not None and pharmacy not in pharmacies):
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if quantity <= 0:
            continue
        total += quantity * report_line_pph_discounted(product, invoice_values)
    return total


def report_user_identity(user_id: str) -> dict[str, object]:
    for user in list_records("users"):
        if str(user.get("id", "")).strip() != str(user_id).strip():
            continue
        pharmacy = str(user.get("pharmacy", "")).strip()
        name = " ".join(
            part
            for part in (
                str(user.get("first_name", "")).strip(),
                str(user.get("last_name", "")).strip(),
            )
            if part
        )
        return {
            "label": pharmacy or name or str(user.get("email", "")).strip(),
            "manager_values": {
                value
                for value in (pharmacy, name, str(user.get("email", "")).strip())
                if value
            },
            "pharmacy_values": {pharmacy} if pharmacy else set(),
        }
    return {
        "label": str(user_id),
        "manager_values": {str(user_id)},
        "pharmacy_values": {str(user_id)},
    }


def report_number(value: float) -> str:
    return f"{round(value, 2):.2f}".replace(".", ",")


def report_money(value: float) -> str:
    return f"{report_number(value)} MAD"


def build_report_balance(year: str, warehouse: str) -> list[dict[str, str]]:
    orders = report_orders(year, warehouse)
    entries: list[dict[str, object]] = []
    seen_labels: set[str] = set()
    for user in list_records("users"):
        user_id = str(user.get("id", "")).strip()
        identity = report_user_identity(user_id)
        label = str(identity.get("label", "")).strip()
        if not label or label in seen_labels:
            continue
        entries.append({"user_id": user_id, **identity})
        seen_labels.add(label)

    for order in orders:
        manager = str(order.get("manager", "")).strip()
        if not manager or any(
            manager in entry.get("manager_values", set()) for entry in entries
        ):
            continue
        entries.append(
            {
                "user_id": manager,
                "label": manager,
                "manager_values": {manager},
                "pharmacy_values": {manager},
            }
        )

    balance = []
    for entry in entries:
        manager_values = entry.get("manager_values", set())
        pharmacy_values = entry.get("pharmacy_values", set())
        supported = sum(
            report_order_amount(str(order.get("number", "")))
            for order in orders
            if str(order.get("manager", "")).strip() in manager_values
        )
        consumed = sum(
            report_order_amount(
                str(order.get("number", "")),
                pharmacy_values if isinstance(pharmacy_values, set) else set(),
            )
            for order in orders
        )
        balance.append(
            {
                "pharmacist": str(entry.get("label", "")),
                "user_id": str(entry.get("user_id", "")),
                "supported": report_money(supported),
                "consumed": report_money(consumed),
                "diff": report_money(supported - consumed),
            }
        )
    return balance


def build_report_labs(year: str, warehouse: str) -> list[dict[str, object]]:
    totals: dict[str, dict[str, object]] = {}
    for order in report_orders(year, warehouse):
        order_id = str(order.get("number", "")).strip()
        invoice_values = report_invoice_values(order_id)
        for product in list_order_products(order_id):
            if not str(product.get("pharmacy", "")).strip():
                continue
            quantity = parse_quantity(product.get("quantity", ""))
            if quantity <= 0:
                continue
            supplier = str(product.get("supplier", "")).strip() or "Sin proveedor"
            row = totals.setdefault(
                supplier,
                {"quantity": 0.0, "amount": 0.0, "orders": set()},
            )
            row["quantity"] = float(row.get("quantity", 0.0)) + quantity
            row["amount"] = float(row.get("amount", 0.0)) + quantity * report_line_pph_discounted(
                product, invoice_values
            )
            order_ids = row.get("orders")
            if isinstance(order_ids, set):
                order_ids.add(order_id)
    return [
        {
            "supplier": supplier,
            "orders": len(values.get("orders", set())),
            "quantity": format_quantity(float(values.get("quantity", 0.0))),
            "amount": report_money(float(values.get("amount", 0.0))),
        }
        for supplier, values in sorted(totals.items(), key=lambda item: item[0].casefold())
    ]


def build_report_detail_orders(
    report_type: str,
    year: str,
    warehouse: str,
    user_id: str,
) -> list[dict[str, object]]:
    identity = report_user_identity(user_id)
    manager_values = identity.get("manager_values", set())
    pharmacy_values = identity.get("pharmacy_values", set())
    details = []
    for order in report_orders(year, warehouse):
        order_id = str(order.get("number", "")).strip()
        if report_type == "paid":
            if str(order.get("manager", "")).strip() not in manager_values:
                continue
            amount = report_order_amount(order_id)
        else:
            if not isinstance(pharmacy_values, set):
                pharmacy_values = set()
            amount = report_order_amount(order_id, pharmacy_values)
            if amount <= 0:
                continue
        details.append(order | {"report_total": report_number(amount)})
    return details


def build_pharmacy_columns(products: list[dict[str, object]]) -> list[str]:
    pharmacies: list[str] = []
    for user in list_records("users"):
        pharmacy = str(user.get("pharmacy", "")).strip()
        if pharmacy and pharmacy not in pharmacies:
            pharmacies.append(pharmacy)
    for product in products:
        pharmacy = str(product.get("pharmacy", "")).strip()
        if pharmacy and pharmacy not in pharmacies:
            pharmacies.append(pharmacy)
    return pharmacies


def build_manager_options(current: str = "") -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for user in list_records("users"):
        pharmacy = str(user.get("pharmacy", "")).strip()
        name = " ".join(
            part
            for part in (
                str(user.get("first_name", "")).strip(),
                str(user.get("last_name", "")).strip(),
            )
            if part
        )
        value = pharmacy or name or str(user.get("email", "")).strip()
        if not value or value in seen:
            continue
        options.append({"value": value, "label": pharmacy or name or value})
        seen.add(value)
    current_value = str(current).strip()
    if current_value and current_value not in seen:
        options.insert(0, {"value": current_value, "label": current_value})
    return options


def is_order_manager(order_id: str, user: dict[str, object] | None) -> bool:
    if not user:
        return False
    if is_admin_user(user):
        return True
    order_manager = ""
    for row in list_records("purchaseorders"):
        if str(row.get("number", "")).strip() == str(order_id).strip():
            order_manager = str(row.get("manager", "")).strip()
            break
    if not order_manager:
        return False
    identities = {
        str(user.get("pharmacy", "")).strip(),
        str(user.get("name", "")).strip(),
        str(user.get("email", "")).strip(),
    }
    return order_manager in {identity for identity in identities if identity}


def build_order_manager_matrix(order_id: str) -> dict[str, object]:
    saved_products = list_order_products(str(order_id))
    order_supplier = ""
    for order in list_records("purchaseorders"):
        if str(order.get("number", "")).strip() == str(order_id).strip():
            order_supplier = str(order.get("supplier", "")).strip()
            break
    pharmacies = build_pharmacy_columns(saved_products)
    product_rows: list[dict[str, object]] = []
    product_index: dict[str, dict[str, object]] = {}

    def product_key(product: dict[str, object]) -> str:
        product_id = str(product.get("id", product.get("product_id", ""))).strip()
        if product_id:
            return f"id:{product_id}"
        supplier = str(product.get("supplier", "")).strip().casefold()
        name = str(product.get("name", "")).strip().casefold()
        return f"name:{supplier}:{name}"

    def add_product(product: dict[str, object]) -> dict[str, object]:
        key = product_key(product)
        if key not in product_index:
            product_index[key] = {
                "id": str(product.get("id", product.get("product_id", ""))).strip(),
                "name": str(product.get("name", "")).strip(),
                "supplier": str(product.get("supplier", "")).strip(),
                "ppv": str(product.get("ppv", product.get("sale_price", ""))).strip(),
                "pph": str(product.get("pph", product.get("unit_price", ""))).strip(),
                "tax": str(product.get("tax", "")).strip(),
                "barcode": str(product.get("barcode", "")).strip(),
                "quantities": {pharmacy_name: "0" for pharmacy_name in pharmacies},
            }
            product_rows.append(product_index[key])
        return product_index[key]

    if order_supplier:
        for product in build_order_product_catalog():
            if product.get("supplier", "") == order_supplier:
                add_product(product)

    for product in saved_products:
        pharmacy = str(product.get("pharmacy", "")).strip()
        supplier = str(product.get("supplier", "")).strip()
        if order_supplier and supplier and supplier != order_supplier:
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if not str(product.get("name", "")).strip():
            continue
        row = add_product(product)
        quantities = row["quantities"]
        if pharmacy and quantity > 0 and isinstance(quantities, dict):
            quantities[pharmacy] = format_quantity(quantity)

    return {"pharmacies": pharmacies, "rows": product_rows}


def manager_products_from_form(matrix: dict[str, object]) -> list[dict[str, str]]:
    pharmacies = matrix.get("pharmacies", [])
    rows = matrix.get("rows", [])
    if not isinstance(pharmacies, list) or not isinstance(rows, list):
        return []
    products: list[dict[str, str]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        product_values = manager_product_values_from_form(row, row_index)
        for pharmacy_index, pharmacy in enumerate(pharmacies):
            quantity = request.form.get(
                f"manager_quantity_{row_index}_{pharmacy_index}", ""
            ).strip()
            if not quantity_is_at_least_one(quantity):
                continue
            products.append(
                {
                    **product_values,
                    "pharmacy": str(pharmacy),
                    "quantity": quantity,
                }
            )
    return products


def manager_product_values_from_form(
    row: dict[str, object], row_index: int
) -> dict[str, str]:
    values = {
        "id": str(row.get("id", "")).strip(),
        "supplier": str(row.get("supplier", "")).strip(),
        "name": str(row.get("name", "")).strip(),
        "ppv": str(row.get("ppv", "")).strip(),
        "pph": str(row.get("pph", "")).strip(),
        "tax": str(row.get("tax", "")).strip(),
        "barcode": str(row.get("barcode", "")).strip(),
    }
    for field in ("ppv", "pph", "tax"):
        field_name = f"manager_product_{field}_{row_index}"
        if field_name in request.form:
            values[field] = request.form.get(field_name, "").strip()
    return values


def update_manager_catalog_prices_from_form(matrix: dict[str, object]) -> None:
    rows = matrix.get("rows", [])
    if not isinstance(rows, list):
        return
    existing_rows = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or not str(row.get("id", "")).strip():
            continue
        existing_rows.append(manager_product_values_from_form(row, row_index))
    if existing_rows:
        save_records("products", existing_rows, {})


def manager_order_values_from_form() -> dict[str, str]:
    return {
        "manager": request.form.get("owner_id", "").strip(),
        "warehouse": request.form.get("warehouse", "").strip(),
        "subject": request.form.get("subject", "").strip(),
        "supplier": request.form.get("supplier_id", "").strip(),
        "deadline": request.form.get("deadline", "").strip(),
        "contact": request.form.get("contact_id", "").strip(),
        "terms_and_conditions": request.form.get("terms_and_conditions", "").strip(),
        "payment_timeframe": request.form.get("payment_timeframe", "").strip(),
        "delivery_timeframe": request.form.get("delivery_timeframe", "").strip(),
        "delivery_transporter": request.form.get("delivery_transporter", "").strip(),
        "payment_methods": ",".join(
            request.form.getlist("accepted_payment_methods[]")
        ),
    }


def manager_new_product_values_from_form() -> dict[str, str]:
    return {
        "name": request.form.get("new_product_name", "").strip(),
        "ppv": request.form.get("new_product_ppv", "").strip(),
        "pph": request.form.get("new_product_pph", "").strip(),
        "tax": request.form.get("new_product_tax", "").strip(),
        "barcode": request.form.get("new_product_barcode", "").strip(),
    }


def sync_purchase_order_product_totals(order_id: str) -> None:
    saved_products = list_order_products(str(order_id))
    product_keys = set()
    total_quantity = 0.0
    for product in saved_products:
        if not str(product.get("pharmacy", "")).strip():
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if quantity <= 0:
            continue
        product_key = str(product.get("product_id", "") or product.get("name", "")).strip()
        if product_key:
            product_keys.add(product_key)
        total_quantity += quantity
    update_purchase_order(
        str(order_id),
        {
            "products": str(len(product_keys)),
            "quantity": format_quantity(total_quantity) if total_quantity else "",
        },
    )


def sync_existing_purchase_order_totals() -> None:
    """Align stored order totals with pharmacy-owned order lines on startup."""
    for order in list_records("purchaseorders"):
        order_number = str(order.get("number", "")).strip()
        if order_number and list_order_products(order_number):
            sync_purchase_order_product_totals(order_number)


def build_order_totals(
    order_id: str,
    pharmacy: str | None = None,
) -> dict[str, str]:
    total_quantity = 0.0
    total_ppv = 0.0
    total_ttc = 0.0
    for product in list_order_products(str(order_id), pharmacy):
        if pharmacy is None and not str(product.get("pharmacy", "")).strip():
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if quantity <= 0:
            continue
        total_quantity += quantity
        total_ppv += quantity * parse_quantity(product.get("ppv", ""))
        total_ttc += quantity * parse_quantity(product.get("pph", ""))
    total_ppv = round(total_ppv, 2)
    total_ttc = round(total_ttc, 2)
    return {
        "quantity": format_quantity(total_quantity) if total_quantity else "0",
        "ppv": format_quantity(total_ppv) if total_ppv else "0",
        "ttc": format_quantity(total_ttc) if total_ttc else "0",
    }


def build_aggregated_print_products(order_id: str) -> list[dict[str, str]]:
    aggregated: dict[str, dict[str, str]] = {}
    order_keys: list[str] = []
    for product in list_order_products(str(order_id)):
        if not str(product.get("pharmacy", "")).strip():
            continue
        quantity = parse_quantity(product.get("quantity", ""))
        if quantity <= 0:
            continue
        product_key = str(
            product.get("product_id", "") or product.get("name", "")
        ).strip()
        if not product_key:
            continue
        if product_key not in aggregated:
            aggregated[product_key] = normalize_order_product(product)
            order_keys.append(product_key)
            aggregated[product_key]["quantity"] = format_quantity(quantity)
            continue
        current_quantity = parse_quantity(aggregated[product_key].get("quantity", ""))
        aggregated[product_key]["quantity"] = format_quantity(
            current_quantity + quantity
        )
    return [aggregated[key] for key in order_keys]


def invoice_product_key(product: dict[str, object]) -> str:
    product_id = str(
        product.get("product_id", product.get("id", ""))
    ).strip()
    if product_id:
        return f"id:{product_id}"
    return f"name:{str(product.get('name', '')).strip().casefold()}"


def build_invoice_rows(
    order_id: str,
    products: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    current_products = products or build_aggregated_print_products(order_id)
    saved_values = {
        invoice_product_key(row): row
        for row in list_invoice_products(order_id)
    }
    return [
        product | {"invoice": saved_values.get(invoice_product_key(product), {})}
        for product in current_products
    ]


def parse_optional_number(value: object) -> float | None:
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def format_invoice_number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def invoice_products_from_form(
    products: list[dict[str, str]],
) -> list[dict[str, str]]:
    invoice_products = []
    for index, product in enumerate(products):
        pph_discounted = request.form.get(
            f"invoice_pph_discounted_{index}", ""
        ).strip()
        ug = request.form.get(f"invoice_ug_{index}", "").strip()
        pph_value = parse_optional_number(product.get("unit_price", ""))
        discounted_value = parse_optional_number(pph_discounted)
        ug_value = parse_optional_number(ug)

        if (
            discounted_value is None
            and not pph_discounted
            and ug_value is not None
            and pph_value
        ):
            discounted_value = pph_value * (1 + (ug_value / 100))
            pph_discounted = format_invoice_number(discounted_value)

        if discounted_value is not None and pph_value:
            discount = format_invoice_number(
                ((discounted_value / pph_value) - 1) * 100
            )
        else:
            discount = ""

        invoice_products.append(
            {
                "product_id": str(
                    product.get("product_id", product.get("id", ""))
                ).strip(),
                "name": str(product.get("name", "")).strip(),
                "discount_pct": discount,
                "ug_pct": ug,
                "pph_discounted": pph_discounted,
            }
        )
    return invoice_products


def order_product_scope_for_user(user: dict[str, object] | None) -> str:
    return str((user or {}).get("pharmacy", "")).strip()


def build_order_detail(
    order_id: str,
    empty: bool = False,
    pharmacy_scope: str | None = "",
) -> dict[str, object]:
    order = deepcopy(ORDER_DETAIL)
    if empty:
        order.update(
            {
                "owner_id": "1001",
                "warehouse": "Principal",
                "subject": "",
                "deadline": "",
                "supplier": "",
                "contact": "",
                "payment_timeframe": "",
                "delivery_timeframe": "",
                "delivery_transporter": "",
                "payment_methods": [],
                "products": [],
                "manager": "",
            }
        )
        return order

    for row in list_records("purchaseorders"):
        if str(row.get("number", "")) == str(order_id):
            order["manager"] = str(row.get("manager", "")).strip()
            order["owner_id"] = order["manager"] or order.get("owner_id", "")
            order["warehouse"] = str(row.get("warehouse", "")).strip() or order.get(
                "warehouse", ""
            )
            order["subject"] = str(row.get("subject", ""))
            order["supplier"] = str(row.get("supplier", ""))
            order["deadline"] = str(row.get("deadline", ""))
            order["contact"] = str(row.get("contact", "")).strip()
            order["terms_and_conditions"] = str(
                row.get("terms_and_conditions", "")
            )
            order["payment_timeframe"] = str(row.get("payment_timeframe", "")).strip()
            order["delivery_timeframe"] = str(row.get("delivery_timeframe", "")).strip()
            order["delivery_transporter"] = str(
                row.get("delivery_transporter", "")
            ).strip()
            order["payment_methods"] = [
                method.strip()
                for method in str(row.get("payment_methods", "")).split(",")
                if method.strip()
            ]
            saved_products = list_order_products(str(order_id), pharmacy_scope)
            if saved_products:
                order["products"] = [normalize_order_product(product) for product in saved_products]
            elif str(order_id) != "105900":
                order["products"] = []
            return order
    return order


def normalize_order_product(product: dict[str, object]) -> dict[str, str]:
    return {
        "id": str(product.get("id", product.get("product_id", ""))).strip(),
        "pharmacy": str(product.get("pharmacy", "")).strip(),
        "product_id": str(product.get("product_id", product.get("id", ""))).strip(),
        "supplier": str(product.get("supplier", "")).strip(),
        "name": str(product.get("name", "")).strip(),
        "sale_price": str(product.get("ppv", product.get("sale_price", ""))).strip(),
        "unit_price": str(product.get("pph", product.get("unit_price", ""))).strip(),
        "discount": str(product.get("discount", "Aucune remise")).strip() or "Aucune remise",
        "tax": str(product.get("tax", "")).strip(),
        "barcode": str(product.get("barcode", "")).strip(),
        "quantity": str(product.get("quantity", "")).strip(),
    }


def build_order_product_catalog() -> list[dict[str, str]]:
    catalog = []
    for row in list_records("products"):
        supplier = str(row.get("supplier", "")).strip()
        name = str(row.get("name", "")).strip()
        if not supplier or not name:
            continue
        catalog.append(
            {
                "id": str(row.get("id", "")).strip(),
                "supplier": supplier,
                "name": name,
                "ppv": str(row.get("ppv", "")).strip(),
                "pph": str(row.get("pph", "")).strip(),
                "tax": str(row.get("tax", "")).strip(),
                "barcode": str(row.get("barcode", "")).strip(),
            }
        )
    return catalog


def build_supplier_options(catalog: list[dict[str, str]], current_supplier: object) -> list[str]:
    current = str(current_supplier or "").strip()
    suppliers = sorted({item["supplier"] for item in catalog if item.get("supplier")})
    if current and current not in suppliers:
        suppliers.insert(0, current)
    return suppliers


def next_order_number() -> str:
    numbers = []
    for row in list_records("purchaseorders"):
        value = str(row.get("number", "")).strip()
        if value.isdigit():
            numbers.append(int(value))
    return str((max(numbers) if numbers else 105900) + 1)


def selected_products_from_form(catalog: list[dict[str, str]]) -> list[dict[str, str]]:
    selected_ids = request.form.getlist("selected_product_id")
    supplier = request.form.get("supplier_id", "").strip()
    catalog_by_id = {item["id"]: item for item in catalog if item.get("id")}
    selected_products = []
    seen = set()
    for product_id in selected_ids:
        if product_id in seen:
            continue
        product = catalog_by_id.get(product_id)
        if not product:
            continue
        if supplier and product.get("supplier") != supplier:
            continue
        quantity = request.form.get(f"product_quantity_{product_id}", "1").strip() or "1"
        if not quantity_is_at_least_one(quantity):
            continue
        product_with_quantity = product | {"quantity": quantity}
        selected_products.append(product_with_quantity)
        seen.add(product_id)
    return selected_products


def selected_order_product_ids(
    order: dict[str, object],
    catalog: list[dict[str, str]],
) -> list[str]:
    ids = []
    catalog_by_name_supplier = {
        (item.get("supplier", ""), item.get("name", "")): item.get("id", "")
        for item in catalog
    }
    supplier = str(order.get("supplier", ""))
    for product in order.get("products", []):
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("product_id") or product.get("id") or "").strip()
        if not product_id:
            product_id = str(
                catalog_by_name_supplier.get((supplier, str(product.get("name", "")).strip()), "")
            ).strip()
        if product_id and product_id not in ids:
            ids.append(product_id)
    return ids


def selected_order_product_quantities(
    order: dict[str, object],
    catalog: list[dict[str, str]],
) -> dict[str, str]:
    supplier = str(order.get("supplier", ""))
    quantities = {
        str(item.get("id", "")).strip(): "0"
        for item in catalog
        if item.get("id") and item.get("supplier") == supplier
    }
    catalog_by_name_supplier = {
        (item.get("supplier", ""), item.get("name", "")): item.get("id", "")
        for item in catalog
    }
    for product in order.get("products", []):
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("product_id") or product.get("id") or "").strip()
        if not product_id:
            product_id = str(
                catalog_by_name_supplier.get((supplier, str(product.get("name", "")).strip()), "")
            ).strip()
        if product_id:
            quantities[product_id] = str(product.get("quantity", "")).strip()
    return quantities


def quantity_is_at_least_one(value: str) -> bool:
    return parse_quantity(value) >= 1


def parse_quantity(value: object) -> float:
    normalized = (
        str(value)
        .strip()
        .replace(" ", "")
        .replace("\xa0", "")
        .replace(",", ".")
    )
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def format_quantity(value: float) -> str:
    if abs(value - round(value)) < 0.000001:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_quantity_cell(value: float) -> str:
    if value <= 0:
        return ""
    return format_quantity(value)


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if value.is_integer():
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Mpharma Groups demo app.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port, debug=args.debug)
