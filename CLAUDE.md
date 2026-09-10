# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Django 5.2 point-of-sale / invoicing system for a Bolivian business (a librería / stationery
shop), whose defining feature is a real integration with the SIN (Servicio de Impuestos
Nacionales) electronic-invoicing SOAP services. Most of the domain complexity lives in that
integration and in the credit-sales / cash-closing business rules layered on top of a
conventional Django CRUD app. UI language and code comments are Spanish; keep that.

## Project context (business, certification, deployment)

- **Product / company name**: being renamed to **CGS Technology** (formerly *CGS System*
  / *CSG Sistemas*). Expect all three names in code, comments, and the SIN issuer config
  during the transition.
- **SIN Piloto certification**: in progress under **Solicitud 9454**, hard deadline
  **2026-10-30**. Certification-volume runs (the `generar_volumen_*` commands) exist to
  push the stage counters before that date; see `prototipo/sin/README.md` for stage
  status and the observed daily cap on recognized cases.
- **Legal blocker (current)**: the SIN system authorization is registered as
  **"Propietario"** under the *librería*'s NIT, not as **"Proveedor"**. The SIN confirmed
  this cannot be converted within the same registration. Selling the system to any third
  party (e.g. Agrotextil) requires starting a **new** registration as *Proveedor* and
  **repeating the entire Piloto certification** from scratch.
- **Multi-client architecture — "Silo Model"**: each client gets its **own Docker
  container + its own separate database**. Deliberately *not* shared multi-tenant — the
  code is not yet internally safe for tenant isolation, so `Empresa` is treated as a
  single row per installation (one NIT per deployment). Onboarding a client = new
  container + new DB + that client's own NIT / AGETIC certificate / Token Delegado /
  homologación.
- **Hosting**: Hetzner Cloud, plan **CPX22** (~$8/mo, US region). Deployment for now is
  manual: `git pull` + `docker compose` on the box (no CI/CD pipeline).
- **Pricing (under evaluation)**: 3 tiers at **Bs 120 / 250 / 420** per month.
- **Digital certificate**: CGS Technology's own costs **Bs 70**, renewed every 2 years.
  Each client buys and renews **their own** certificate separately.
- **The librería (pilot business)** still invoices for real using the SIN's own
  first-party system in **Computarizada en Línea** modality. Whether it migrates to
  CGS Technology (**Electrónica en Línea**) for real production use is **not yet decided**.

### Roles → permissions mapping (as designed)

- **Cajero** can register credit payments (abonos) but **cannot reverse** them — reversal
  is Supervisor-only.
- **`fac.ver_creditos`** is a separate read-only permission (Cartera de Créditos, Kardex,
  recibos), intended for an accountant-type role, decoupled from `gestionar_creditos`
  (which is the *action* of taking a payment).
- **"Eliminar factura"** (`fac.eliminar_facturaenc`) and **"forzar cierre de día"**
  (`fac.forzar_cierre_dia`) no longer key off `is_superuser` — they are now configurable
  Django permissions so each client can grant them to their own "Administrador" without
  making that person a technical superuser.

## Environment & common commands

- Virtualenv is committed at `entvirt/` (Windows). Activate: `entvirt\Scripts\activate`
  (PowerShell) — the OS here is Windows 11, primary shell PowerShell.
- **All `manage.py` commands run from the `app/` subdirectory**, not the repo root.
- Settings module: `app.settings`. Configuration is read from `.env` at the **repo root**
  (one level above `app/`) via `python-decouple`. There are no safe defaults for
  `SECRET_KEY` / DB creds — a missing `.env` fails loudly by design.
- Database: PostgreSQL only (`psycopg2`). DB name/host/user/pass/port come from `.env`.

```
cd app
python manage.py runserver
python manage.py migrate
python manage.py makemigrations
python manage.py test                     # test suite (tests.py files are currently stubs)
python manage.py test fac.tests.ClassName.test_method   # single test
python manage.py createsuperuser
python manage.py collectstatic            # whitenoise / production static
```

### Dependencies caveat

The root `requirements.txt` lists direct dependencies with loose (`>=`) bounds — enough
to install and run, but transitive packages are unpinned. The authoritative,
fully-frozen (exact-version) list is `prototipo/sin/requirements-prototipo.txt` (UTF-16);
prefer it for reproducing the committed `entvirt/` venv. Note `requirements.txt` was
historically missing the SIN stack (`zeep` / `lxml` / `signxml`, imported by
`app/fe/services.py` and `app/catalogos/services.py`) — now added.

### Project-specific management commands

```
python manage.py crear_grupos_permisos      # (bases) create/refresh the standard role groups
python manage.py limpiar_datos_prueba        # (bases) wipe test data
python manage.py sincronizar_catalogos       # (catalogos) pull SIN parametric catalogs (real SOAP)
python manage.py generar_volumen_sin         # (fac) emit+annul+revert cycles for SIN Piloto certification
python manage.py generar_volumen_catalogos   # (catalogos) repeated catalog syncs for certification volume
python manage.py generar_volumen_cufd        # (fe) repeated CUFD requests for certification volume
```

## Django apps and how they fit together

URL prefixes are wired in `app/app/urls.py`; each app owns a namespaced `urls.py`.

- **`bases`** — auth, dashboard (`Home`), user/role management UI (replaces the Django
  admin for day-to-day use), and the cross-app reports (Libro de Ventas / Compras,
  Facturas Anuladas). Defines `bases/models.py::ClaseModelo` and `ClaseModelo2`, the
  abstract audit base every other model inherits (`estado` boolean = **soft-delete**
  flag, `fc`/`fm` timestamps, `uc`/`um` user refs). `ClaseModelo2` uses
  `django_userforeignkey` to auto-populate `uc`/`um` from the request user — but that
  captures the *session* user, so places that authenticate a supervisor inside a
  confirmation dialog store the real actor in an explicit `usuario_*` field instead
  (see `FacturaDet.usuario_reversion`, `Pago.usuario_reversion`).
- **`inv`** — catalog: Categoria/SubCategoria/Marca/UnidadMedida/Producto, plus
  TipoCambio, price-review workflow, and **SIN homologación** (`Producto.actividad_economica_sin`,
  `Producto.codigo_producto_sin`, `UnidadMedida.codigo_sin`; `Producto.homologado_sin`
  gates whether a product can be invoiced electronically).
- **`cmp`** — purchasing: Proveedor, ComprasEnc/ComprasDet, purchase reports. Increments
  stock.
- **`fac`** — sales, the core app. `FacturaEnc`/`FacturaDet`, `Cliente`, `Pago` (abonos),
  `NotaCreditoDebito`, `CierreDia`. Signals on `FacturaDet`/`Pago` recompute header
  totals, stock, and credit `saldo_pendiente`. Handles credit sales (`forma_pago='CREDITO'`,
  due dates, credit limits, overdue blocking), cash closing (`CierreDia`), and all the
  SIN lifecycle actions (emit / annul / revert / NCD) by calling into `fe`.
- **`fe`** — *Facturación Electrónica*: the production SIN integration. `Empresa` /
  `Sucursal` / `PuntoVenta` hold the issuer config (NIT, `codigo_sistema`, CUIS).
  `fe/services.py` is the orchestrator; `fe/cuf.py` and `fe/factura_xml.py` are
  verbatim copies of the validated prototipo versions. **Start with `app/fe/README.md`.**
- **`catalogos`** — syncs the SIN parametric catalogs (`CatalogoSIN`) via
  `FacturacionSincronizacion` SOAP.
- **`api`** — small DRF read API (`/api/v1/productos/`, `/api/v1/clientes/`).

## The SIN integration — the part that needs reading multiple files

Two layers, deliberately separate:

1. **`prototipo/sin/`** — a research log + throwaway scripts documenting how the SIN SOAP
   protocol was reverse-engineered and how the 8/9-stage "Piloto" certification was
   advanced. `prototipo/sin/README.md` is the *bitácora* — the "why" behind every
   decision in `services.py` (auth header format `apikey: TokenApi <jwt>`, the exact
   request type names, CUFD short lifetime, the two-CUFD event pattern, error codes
   935 / 1009 / 1016 / 1017 / 984 / 924, etc.). It also holds the XSD/XML samples that
   `fe/services.py` validates against by relative path.
2. **`app/fe/`** — the live code. `emitir_factura_sin(factura_enc)` is the single entry
   point: validates prerequisites (Empresa, Sucursal CUIS, `SIN_TOKEN_DELEGADO` in
   `.env`, per-product homologación) → fresh CUFD → compute CUF → build XML → sign with
   the real AGETIC certificate → validate against XSD → gzip → SHA-256 → `recepcionFactura`
   → write `cuf`/`cufd`/`estado_sin`/`codigo_recepcion_sin`/`mensaje_sin` back onto the
   `FacturaEnc`. On any missing prerequisite or SIN rejection it raises `EmisionSinError`
   with a specific message — it never guesses a value. `anular_factura_sin` and
   `revertir_anulacion_sin` follow the same pattern. All network calls have explicit
   timeouts (`TIMEOUT_CONEXION` / `TIMEOUT_OPERACION`).

Key operational facts:

- **Environment**: `Empresa.ambiente` is `Piloto` or `Producción`; the code targets the
  Piloto WSDLs (`pilotosiatservicios.impuestos.gob.bo`). Development and certification
  volume runs go against the **local** `db_djfull` database but hit the **real** SIN
  Piloto services (they're external — origin doesn't matter — and this keeps test
  invoices out of real accounting).
- **Real certificate & credentials** live under `prototipo/sin/certificado_real/`
  (`*.p12`, `*.pem`) and are gitignored. Paths are overridable via env vars
  `SIN_ARCHIVO_LLAVE` / `SIN_ARCHIVO_CERT` / `SIN_ARCHIVO_XSD` / `SIN_ARCHIVO_XSD_NCD`.
  The cert/key/XSD are loaded once at module import, not per invoice.
- **Time**: `TIME_ZONE = 'America/La_Paz'` (UTC-4). The SIN rejects UTC timestamps and
  enforces a ~5-minute tolerance, so `emitir_factura_sin` captures
  `timezone.localtime(timezone.now())` once and uses it for both the CUF and the XML
  header — never `factura_enc.fecha` (row-creation time).
- **Token**: `SIN_TOKEN_DELEGADO` in `.env` is a long-lived JWT from SIAT en Línea.
  CUFD, by contrast, expires in ~24–48h and is fetched fresh on every emission.

## Conventions

- **Soft delete everywhere**: models carry `estado` (from `ClaseModelo`); "deleting"
  sets `estado=False`. Queries that must exclude deleted rows filter `estado=True`
  explicitly. `FacturaEnc.puede_editarse` centralizes the "is this invoice still
  mutable?" check (not deleted, not annulled, not yet reported to SIN).
- **Model `save()` does real work**: `Cliente`/`Categoria`/etc. upper-case text fields;
  `FacturaEnc.save()` derives `total`, maps `forma_pago` → SIN payment code, and
  manages `fecha_vencimiento` / `saldo_pendiente` for credit sales. Read the `save()`
  before changing field semantics.
- **Signals keep aggregates in sync**: `fac/models.py` has `post_save`/`post_delete`
  receivers on `FacturaDet` and `Pago` that recompute header subtotal/discount, product
  `existencia`, and credit `saldo_pendiente`. Bulk operations that bypass signals will
  desync these.
- **Permissions/roles**: class-based views mix in `bases.views.SinPrivilegios`
  (LoginRequired + PermissionRequired, redirecting to `bases:sin_privilegios` on
  missing perms); function views use `@permission_required(..., login_url='bases:sin_privilegios')`.
  Roles are Django groups created by `crear_grupos_permisos` (Supervisor / Cajero /
  Almacenero / Solo Lectura; "Administrador" = `is_superuser`). `fac` defines custom
  permissions (`anular_facturaenc`, `gestionar_creditos`, `ver_creditos`,
  `eliminar_facturaenc`, `ver_reportes_financieros`, `gestionar_cierre_dia`,
  `forzar_cierre_dia`); supervisor-gated actions also check `fac.views._es_supervisor`.
- **Locale**: `LANGUAGE_CODE = 'es-bo'`, `USE_THOUSAND_SEPARATOR = True`, and a custom
  `FORMAT_MODULE_PATH` (`app/formats/es_BO/`) forcing a `.` decimal separator for
  table-export compatibility.
- **PDFs** are generated with reportlab / xhtml2pdf / pyHanko (see each app's
  `reportes.py`).

## Notes

- No CI config, no linter/formatter config, no pre-commit — none is set up.
- `app/revertir_pendientes.py` and `app/verificar_571_572.py` are ad-hoc one-off
  scripts, not part of the app.
