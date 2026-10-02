# Especificacion de la replica Mpharma Groups

## Alcance del analisis

Sitio observado: `https://groups.sobrus.com/`

Fecha de analisis: 2026-06-18

El recorrido se hizo en dos fases:

- Superficie publica: login, recuperacion y 404.
- Superficie autenticada: dashboard, modulos de gestion, formularios y reportes.

No se copiaron codigo fuente, marca, logo, imagenes ni datos reales. La implementacion usa contenido ficticio y una marca de ejemplo.

## Mapa del sitio observado

### Autenticacion

| Ruta | Funcion |
| --- | --- |
| `/` | Redirige al login si no hay sesion; dashboard si hay sesion. |
| `/auth/login` | Formulario de acceso. |
| `/auth/password-recovery` | Recuperacion de contrasena. |
| `/auth/logout` | Cierre de sesion. |

### Area autenticada

| Ruta | Funcion |
| --- | --- |
| `/` | Dashboard con resumen operativo. |
| `/suppliers` | Listado de proveedores. |
| `/contacts` | Listado de contactos. |
| `/contact/create` | Formulario de nuevo contacto. |
| `/products` | Catalogo de productos. |
| `/offers` | Listado de ofertas. |
| `/purchaseorders` | Pedidos actuales. |
| `/purchaseorders/index/index/archived/true` | Pedidos archivados. |
| `/purchaseorder/edit/:id` | Detalle y edicion de pedido. |
| `/events` | Planning/calendario. |
| `/event/create` | Formulario de evento. |
| `/reports` | Reportes y balances. |
| `/reports/index/details/type/:type/year/:year/warehouse/:warehouse/user_id/:id` | Detalle de reporte. |
| `/users` | Listado de farmacias/usuarios. |
| `/settings/usersettings/profile` | Perfil. |
| `/settings/usersettings/edit-profile` | Edicion de perfil. |
| `/settings/usersettings/change-password` | Cambio de contrasena. |

## Arquitectura detectada en la referencia

- Aplicacion server-rendered clasica.
- Navegacion por rutas HTML tradicionales.
- Formularios `POST`.
- CSS global minificado.
- jQuery, jQuery UI y graficos Highstock.
- Header fijo, aviso superior, menu lateral compacto por iconos y panel principal.
- Tablas con filtros por columna, ordenacion, recarga, impresion y paginacion.
- Responsive limitado en la referencia: `min-width: 960px` y scroll horizontal en movil.

## Componentes clave

- `AuthLayout`: pantalla de login/recuperacion con panel centrado y banda inferior turquesa.
- `AppLayout`: aviso superior, header, perfil, sidebar y contenido.
- `SidebarNav`: menu de modulos con modo compacto y expandido.
- `DataTable`: filtros, ordenacion, accion de impresion, paginacion simple y acciones por fila.
- `CalendarMonth`: grilla mensual con eventos.
- `FormGrid`: formularios densos de dos columnas.
- `SettingsNav`: navegacion secundaria de ajustes.
- `ReportTables`: balance por farmacia y estadisticas por proveedor.

## Flujos implementados

- Login demo con usuarios especificos por farmacia y contrasena propia.
- Permisos por rol: administrador edita catalogos y cuentas; usuarios de farmacia visualizan todos los modulos y editan solo pedidos.
- Recuperacion de contrasena simulada.
- Listados de proveedores, contactos, productos, ofertas, pedidos y usuarios.
- Dashboard con metricas dinamicas calculadas desde los registros persistidos.
- Edicion inline de proveedores, contactos, productos, ofertas, pedidos y farmacias con persistencia en SQLite.
- Botones y rutas `POST` protegidos segun permisos de administrador o usuario de farmacia.
- Alta rapida desde la ultima fila vacia de cada tabla editable.
- Carga masiva desde Excel `.xlsx` en las tablas editables con los campos visibles en el mismo orden de la pantalla.
- Descarga de plantilla Excel por modulo editable.
- Eliminacion de registros al guardar una fila existente con todos sus campos visibles vacios.
- Filtro textual y ordenacion por columna en tablas.
- Cambio entre pedidos actuales y archivados.
- Creacion demo de contacto.
- Creacion demo de evento.
- Edicion demo de pedido con lineas de producto, impuestos, descuentos y metodos de pago.
- Reportes con filtros y paginas de detalle.
- Perfil, edicion de perfil y cambio de contrasena con validacion local.

## Sustituciones realizadas

- Marca original sustituida por `Mpharma Groups`.
- Datos reales sustituidos por proveedores, productos, usuarios y pedidos ficticios.
- Enlaces externos reales sustituidos por acciones de demostracion.
- Iconografia original de sprites sustituida por simbolos CSS/textuales.
- Textos literales largos reescritos con contenido equivalente.

## Decisiones responsive

La referencia fuerza un ancho minimo de 960px. La replica conserva la densidad visual de escritorio, pero mejora movil:

- Sidebar colapsable.
- Tablas con scroll interno.
- Formularios a una columna.
- Dashboard en tarjetas apiladas.
- Calendario con scroll horizontal controlado.

## Stack final

- Python
- Flask
- Jinja2
- openpyxl
- CSS propio
- Datos de ejemplo iniciales
- Listados principales persistidos en SQLite local
- Autenticacion y permisos por rol desde la tabla de farmacias/usuarios
- Tests con `unittest`
