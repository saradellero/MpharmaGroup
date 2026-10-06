# Mpharma Groups

Aplicacion Python/Flask inspirada en una interfaz de gestion de compras agrupadas. Es una replica funcional de demostracion: no copia marca, codigo, textos, imagenes ni datos protegidos del sitio analizado.

## Requisitos

- Python 3.11+
- Flask
- openpyxl
- psycopg

Instalacion:

```bash
python -m pip install -r requirements.txt
```

## Ejecutar localmente

```bash
python app.py
```

Abre:

```text
http://127.0.0.1:8000
```

Opciones:

```bash
python app.py --host 127.0.0.1 --port 8080 --debug
```

## Acceso demo

El login valida usuarios guardados en SQLite. Credenciales iniciales:

| Rol | Email | Contrasena |
| --- | --- | --- |
| Administrador | `sara.demo@example.com` | `admin123` |
| Farmacia Atlas | `mina.test@example.com` | `atlas123` |
| Farmacia Riviera | `omar.example@example.com` | `riviera123` |

El administrador puede editar catalogos, farmacias, proveedores, ofertas y pedidos. Los usuarios de farmacia pueden visualizar todos los modulos, pero solo ven botones de edicion en pedidos.

## Rutas principales

- `/auth/login`
- `/auth/password-recovery`
- `/`
- `/suppliers`
- `/contacts`
- `/contact/create`
- `/products`
- `/offers`
- `/purchaseorders`
- `/purchaseorders/index/index/archived/true`
- `/purchaseorder/edit/105900`
- `/events`
- `/event/create`
- `/reports`
- `/users`
- `/settings/usersettings/profile`
- `/settings/usersettings/edit-profile`
- `/settings/usersettings/change-password`

## Panel de inicio

El dashboard calcula sus tarjetas desde SQLite en cada carga: pedidos abiertos y unidades en curso, proveedores/contactos, productos/ofertas y farmacias activas. Si se anaden, importan, editan o eliminan registros en los modulos, el panel lo refleja al volver a `/`.

## Modulos editables

Las rutas `/suppliers`, `/contacts`, `/products`, `/offers`, `/purchaseorders` y `/users` incluyen un boton **Editar ...** cuando el rol tiene permiso. En ese modo:

- las filas existentes son editables;
- la ultima fila queda vacia para anadir un registro nuevo;
- si se vacian todos los campos de una fila existente, se elimina al guardar;
- el boton **Guardar cambios** persiste los cambios en SQLite;
- el boton **Plantilla Excel** descarga un `.xlsx` con los campos en el mismo orden de la pantalla;
- el boton **Cargar Excel** permite crear registros en bloque desde un `.xlsx` con esa misma estructura y admite ficheros de hasta 64 MB;
- al volver al listado, el registro nuevo aparece directamente.

La carga Excel usa un formulario independiente para no reenviar todas las filas editables existentes. Esto permite importar listados grandes de productos sin disparar errores `Request Entity Too Large`.

En local, la base SQLite se crea automaticamente en:

```text
data/nova_groups.sqlite3
```

Si una base ya existia antes de esta version, al arrancar la app se anade automaticamente la columna de contrasena a farmacias y se rellenan las contrasenas demo iniciales cuando esten vacias.

## Base de datos PostgreSQL para produccion

La aplicacion usa SQLite cuando no existe `DATABASE_URL` y PostgreSQL cuando `DATABASE_URL` contiene una cadena de conexion de Supabase o Neon. No guardes esa cadena en GitHub: debe configurarse como variable de entorno en Render.

Para conservar los datos locales antes del primer despliegue, ejecuta desde Git Bash:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite "data/nova_groups.sqlite3" \
  --postgres-url "postgresql://USUARIO:CONTRASENA@HOST:5432/postgres?sslmode=require"
```

El migrador copia catalogos, usuarios, pedidos, lineas de pedido, descuentos de factura y balances iniciales. La migracion reemplaza los datos existentes en las tablas de la base PostgreSQL de destino.

En Render configura estas variables en **Environment**:

- `DATABASE_URL`: cadena PostgreSQL de Supabase o Neon.
- `SECRET_KEY`: una clave aleatoria; el `render.yaml` puede generarla automaticamente.

## Estructura

```text
.
├── app.py
├── demo_site/
│   ├── app.py
│   ├── data.py
│   ├── validation.py
│   └── templates/
│       ├── auth/
│       ├── base.html
│       ├── macros.html
│       └── ...
├── docs/
│   └── site-spec.md
├── static/
│   └── styles.css
├── tests/
│   └── test_app.py
└── requirements.txt
```

## Verificacion

```bash
python -m unittest discover -s tests
```

## Despliegue

Para produccion, ejecuta la app con un servidor WSGI como Gunicorn, uWSGI o Waitress, configura `SECRET_KEY` por entorno y reemplaza los datos en memoria por una base de datos real.

Ejemplo con Waitress:

```bash
waitress-serve --listen=0.0.0.0:8000 app:app
```
