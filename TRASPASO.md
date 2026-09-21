# Traspaso — Sistema de Compras y Facturación (CGS Technology)

Documento de contexto para continuar el trabajo en Claude Code. Todo lo que sigue está confirmado en las sesiones de trabajo previas — no hay nada inventado ni supuesto.

---

## 1. Qué es este proyecto

Sistema propio de facturación electrónica y compras/inventario para pequeños negocios en Bolivia, integrado con el SIN (Servicio de Impuestos Nacionales). El negocio piloto es la **librería** de la familia (Millennium). El producto se está renombrando de "CGS System" a **"CGS Technology"**, con la intención de ofrecerlo comercialmente a otros negocios (ej. Agrotextil, una empresa agro-textil) además de la librería.

- Repo: `github.com/ceguna/sistema_facturacion`
- Local: `D:\Python\Sistema Facturacion\djfull\prod\app\`
- Certificación Piloto ante el SIN: **Solicitud 9454, plazo hasta el 30/10/2026**
- La esposa de Carlos sigue facturando de verdad con el sistema de escritorio del propio SIN (Computarizada en Línea) — todavía no decidió si adopta CGS Technology para uso real.

## 2. Stack técnico

- Django 5.2, Python 3.13, PostgreSQL (`db_djfull`), virtualenv `entvirt`
- Apps: `fac` (facturación), `fe` (servicios SIN), `inv` (inventario/productos), `cmp` (compras), `catalogos` (catálogos SIN), `bases` (usuarios, roles, reportes transversales)
- `prototipo/sin/`: scripts standalone para la certificación (fuera de la app Django)

## 3. Datos reales del SIN Piloto

- NIT: `3852849010` — codigoSistema: `373A0EA0FBA931B62586`
- Sucursal 0 (Casa Matriz): CUIS `31477C6C` (codigoPuntoVenta=0)
- PuntoVenta 1: CUIS `558F4FB7` (codigoPuntoVenta=1)
- Código Actividad Económica: `4761300` (venta al por menor de material de oficina y librería)
- Token Delegado Piloto: válido hasta 2027-08-01
- CAFC real (motivos 5/6/7): `1016EBC6A6D4E`, rango asignado 1-1000

## 4. Estado de la certificación Piloto (al cierre de esta sesión)

| Etapa | Estado | Notas |
|---|---|---|
| I — CUIS | ✅ 100% | |
| II — Catálogos | ✅ 100% | Resuelto usando `sincronizarFechaHora`, una operación del WSDL que no se estaba usando |
| III — CUFD | ✅ 100% | |
| IV — Emisión Individual | ⚠️ 50%, bloqueada | El 50% restante depende de la NCD (ver sección 6) |
| V — Eventos Significativos | ✅ 100% | |
| VI — Paquetes | ✅ **100%, completada esta sesión** | Ver sección 5 — se resolvió reciclando el mismo CAFC |
| VII — Anulación | ⚠️ 50%, bloqueada | Mismo bloqueo que IV |
| VIII — Firma Digital | ⚠️ 50%, bloqueada | Mismo bloqueo que IV |
| XI — Reversión | ⚠️ 50%, bloqueada | Mismo bloqueo que IV |

**IV, VII, VIII y XI dependen todas de la Nota de Crédito-Débito (NCD)** — son la prioridad número uno para seguir la certificación.

## 5. Etapa VI — cómo se resolvió (por si sirve de referencia para otro caso similar)

El rango del CAFC (1-1000) no alcanzaba para los 3 motivos pendientes en punto de venta 1 (14.000 números necesarios). El soporte del SIN respondió que **se puede reutilizar el mismo CAFC en distintos escenarios de prueba, respetando el rango numérico en cada envío** — una respuesta ambigua que se confirmó con **dos pruebas controladas reales** (no solo matemática):

1. Motivo 6 (nunca tocado), reusando el número 1 (ya usado en motivo 5) → **aceptado y validado**, con REQUEST/RESPONSE reales guardados.
2. Mismo motivo 6, mismo número 1, un segundo intento → también aceptado.

Conclusión confirmada: **el mismo número se puede reciclar tanto entre motivos distintos como dentro del mismo motivo.** El script `generar_volumen_paquetes.py` tiene un flag `--numero-cafc-fijo N` agregado para esto — se usó para completar el volumen restante sin pedir ampliación de rango al SIN.

**Nota sobre el conteo:** el script reporta "fallido" cuando hay timeout de la infraestructura del SIN (errores tipo `java.util.concurrent.TimeoutException` o `Marshalling Error`), pero el dashboard real del SIN a veces avanza igual — el envío se procesó del lado del SIN aunque la confirmación no llegó a tiempo al script. **Conviene mirar el dashboard real del SIN, no solo el resumen que imprime el script**, para saber el estado exacto.

## 6. Ticket abierto — Nota de Crédito-Débito (bloqueador activo)

### Lo que el SIN confirmó sobre la estructura del detalle

El soporte del SIN dio la fórmula real que valida el servicio:
```
montoTotalOriginal   = Σ(subTotal) donde codigoDetalleTransaccion=1
                       (debe igualar los subtotales de la factura original)
montoTotalDevuelto   = Σ(subTotal) - montoDescuentoCreditoDebito
                       donde codigoDetalleTransaccion=2
montoEfectivoCreditoDebito = montoTotalDevuelto × 0.13
subTotal             = (cantidad × precioUnitario) − montoDescuento
```

Esto confirmó la hipótesis original (para devolución TOTAL, único caso soportado): reconstruir **todas** las líneas de la factura original con `codigoDetalleTransaccion=1`, y repetirlas idénticas con `codigoDetalleTransaccion=2`. El ejemplo oficial confuso del SIN (con productos distintos entre las dos transacciones) no representaba la regla real.

**Se desbloqueó el código**: se sacó el `raise EmisionSinError(...)` que bloqueaba a propósito `emitir_nota_credito_debito_sin()` en `fe/services.py`, desde el 26/08/2026.

### El bloqueador actual

Al probar en la factura real 777 (3 intentos), el SIN devolvió consistentemente:
```
codigo: 995
descripcion: SERVICIO NO DISPONIBLE: Para la modalidad 1 y/o sector 24.
```
No es un error de datos — la estructura del XML es correcta (confirmado por todo lo de arriba). Es un rechazo de **disponibilidad del servicio** para esa combinación específica (`codigoModalidad=1` + `codigoDocumentoSector=24`).

**Se envió un ticket nuevo al SIN preguntando**: si existe algún paso de habilitación pendiente para sector 24 bajo modalidad Electrónica en Línea, o si es indisponibilidad temporal. **Respuesta pendiente al cierre de esta sesión.**

### Bug de UI encontrado en el camino (ya corregido, pero dejó una lección importante)

Al emitir la NCD, el sistema mostraba "Registro Guardado Satisfactoriamente" incluso en los 3 intentos, sin importar el resultado real — esto hizo parecer que el sistema no estaba bloqueando nada. La causa real: **`abrir_modal()` (el JS genérico de este sistema para popups) trata cualquier respuesta HTTP 200 como éxito, sin mirar el contenido.** El helper `_modal_error()` (pensado para bloquear ANTES de mostrar un formulario, en el GET inicial) devuelve 200 — así que usarlo para rechazar un **POST de un formulario que ya estaba abierto** produce un falso "éxito".

**Se corrigió** con un helper nuevo, `_rechazar_envio_modal()`, que imita el formato JSON de error que ya usa `MixinFormInvalid` (status 400 con `{"errors": "<json>"}`) — aplicado en `cmp/views.py` (`CompraDetDelete`) y en `fac/views.py` (`emitir_ncd`, el chequeo de "falta el motivo").

**⚠️ Pendiente de auditar**: no se revisó el resto del sistema buscando más ocurrencias de este mismo patrón (`_modal_error()` usado dentro de un bloque `POST` de un formulario ya abierto vía `abrir_modal()`). Vale la pena una pasada dedicada a esto.

## 7. Trabajo de esta sesión — Compras / Inventario

Se hizo un banco de pruebas completo sobre Compras/Inventario, con varios hallazgos reales corregidos:

- **Menú**: dos bugs de permisos — el menú chequeaba `perms.inv.view_compras` y `perms.inv.view_proveedor`, pero esos modelos viven en `cmp`, no en `inv` (el permiso correcto nunca existía, por eso nunca se cumplía para nadie salvo superusuarios, que Django siempre les da todo por válido). Corregido a `perms.cmp.view_comprasenc` / `perms.cmp.view_proveedor`. También se separó "Cierre de Ventas/Caja" del permiso de "Facturas Anuladas" en el menú (usaban el mismo, pero la vista real ya exigía uno más específico).
- **Menú (submenús)**: el acordeón se cerraba solo al abrir otro, y se reseteaba cerrado en cada navegación. Corregido sacando `data-parent`, agregando persistencia vía `localStorage`.
- **Producto**: Costo Referencial y Margen Deseado ahora son realmente obligatorios (>0, no solo "presentes" — el valor por defecto 0 pasaba la validación de "requerido" de Django sin que el usuario escribiera nada). Asteriscos automáticos en los campos obligatorios del formulario. Ancho del campo Descripción corregido (bug de Bootstrap `form-inline` que forzaba `width:auto`).
- **Compras — UX del formulario**: TAB ya no se detiene en Sub Total/Descuento/Total ni en encabezados de columna (DataTables les pone `tabindex=0` a los headers ordenables por defecto). Tabla de selección de productos reducida a 5 filas por página (con `lengthMenu` corregido, si no el desplegable queda en blanco). Precio acepta decimales. Mensaje específico si no se ingresó el precio (hubo que reordenar las validaciones — el chequeo genérico interceptaba antes que el específico). Unidad de medida mostrada junto a la descripción del producto elegido, y como columna nueva en la tabla de Detalle.
- **Compras — reglas de negocio nuevas**:
  - Bloqueo de crear/editar/eliminar en un día ya cerrado — se reusa el mismo `CierreDia` de Facturación (Compras nunca tuvo su propio concepto de cierre). Permiso nuevo: `cmp.editar_compra_dia_cerrado` (bypass, solo Administrador).
  - Bloqueo de eliminar si dejaría el stock en negativo — investigado y confirmado como práctica estándar (SAP Business One, Dynamics 365 Business Central, NetSuite todos bloquean esto por defecto).
  - **Decisión de diseño final sobre "compra sin detalle"**: se permite eliminar la última línea de una compra (ya no se bloquea a nivel de "mínimo 1 producto"). En cambio, si una compra existente queda en cero detalle, el botón **Cancelar** de esa pantalla queda bloqueado hasta que se cargue al menos un producto nuevo — con un botón de escape ("Eliminar Compra") para poder abandonarla del todo si así se prefiere.
  - **Ventana de tiempo escalonada por rol para eliminar** (investigado y confirmado como práctica estándar — "period locking" en Sage, ERPNext, etc.): Almacenero solo puede eliminar el mismo día; Supervisor (permiso nuevo `cmp.eliminar_compra_mes_vigente`) todo el mes en curso; Administrador sin límite.
- **Facturas**: el listado tardaba mucho en cargar (traía todo el histórico sin filtro — había miles de facturas de prueba generadas durante la certificación). Se agregó un filtro de fecha real en la cabecera (mes actual por defecto), que ahora también alimenta los botones de descarga PDF/Excel/XML (antes cada uno calculaba su propio rango por separado, podían desincronizarse).

## 8. Costeo — Costo Promedio Ponderado (agregado, con una limitación pendiente de decisión)

Se agregó `costo_promedio` a `Producto` (`inv/models.py`), recalculado automáticamente en cada compra nueva (señal `detalle_compra_guardar` en `cmp/models.py`), usando la fórmula estándar de Promedio Ponderado — se mueve solo con entradas (compras), nunca con salidas (ventas).

**Limitación conocida, confirmada en vivo**: los productos que ya tenían compras **antes** de este cambio quedan con `costo_promedio = 0` hasta su próxima compra real — la lógica nueva no corre retroactivamente sobre datos viejos. Se diseñó (pero no se construyó del todo) un comando de recálculo retroactivo que reconstruye el historial completo mezclando compras y ventas en orden cronológico. **Carlos decidió NO aplicarlo por ahora** ("es una base de pruebas, dejémoslo como está") — queda pendiente si en algún momento se retoma.

## 9. Reportes nuevos

Agregados a `bases/views.py` / `bases/urls.py` / `base.html` (como snippets para agregar — nunca se tuvo el archivo completo de `bases/views.py` ni `bases/urls.py` en esta sesión, así que **hay que confirmar que se integraron bien**, sin colisión de nombres):

- **Estado de Inventario** (`bases:estado_inventario`): foto del momento actual — existencia, precio, costo promedio, valor a precio de venta y a costo, filtro por categoría y búsqueda.
- **Kardex con Valorización** (`bases:kardex_inventario`): rango de fecha elegible (mes actual por defecto). Sin producto elegido → resumen por producto (saldo inicial/entradas/salidas/saldo final). Con un producto elegido → detalle línea por línea. **Limitación conocida**: las entradas se valorizan al precio real de cada compra (exacto), pero las salidas y el saldo inicial se valorizan al costo promedio **actual** (no hay una foto histórica del costo en cada momento pasado) — es una aproximación, no costeo contable estricto.
- **Menú de Reportes reorganizado** en 4 grupos: Libros IVA (Ventas, Compras) / Ventas (Facturas Anuladas, Cierre de Ventas) / Caja (Cierre de Caja) / Inventario (Estado de Inventario, Kardex con Valorización).

## 10. Roles y permisos — mapeo completo vigente

| Permiso | Administrador | Supervisor | Cajero | Almacenero | Solo Lectura |
|---|:---:|:---:|:---:|:---:|:---:|
| Facturas: ver / editar / anular | ✅ | ✅/✅/✅ | ✅/✅/— | — | ✅/—/— |
| `eliminar_facturaenc` | ✅ | — | — | — | — |
| `forzar_cierre_dia` | ✅ | — | — | — | — |
| `gestionar_cierre_dia` | ✅ | ✅ | — | — | — |
| `gestionar_creditos` (cobrar) | ✅ | ✅ | ✅ | — | — |
| `ver_creditos` | ✅ | ✅ | ✅ | — | ✅ |
| `ver_reportes_financieros` | ✅ | ✅ | — | — | ✅ |
| Compras: ver / editar | ✅ | ✅ | — | ✅/✅ | ✅/— |
| `eliminar_comprasenc` | ✅ | — | — | — | — |
| `editar_compra_dia_cerrado` | ✅ | — | — | — | — |
| `eliminar_compra_mes_vigente` | ✅ (implícito) | ✅ | — | — | — |
| Producto/Catálogos: ver / editar | ✅ | — | — | ✅ | ✅/— |
| `gestionar_precios_tc` | ✅ | — | — | — | — |

*(Administrador tiene todos los permisos vía Django; se listan explícitamente los dedicados para claridad de qué existe.)*

## 11. Decisiones de negocio y arquitectura (de sesiones previas, siguen vigentes)

- **Bloqueador legal para vender a terceros**: el sistema está registrado ante el SIN como **Propietario** bajo el NIT de la librería, no como **Proveedor**. El SIN confirmó que no se puede convertir de Propietario a Proveedor dentro del mismo registro — para poder ofrecer el sistema a otro negocio (ej. Agrotextil), hace falta un **registro nuevo completo bajo modalidad Proveedor**, repitiendo toda la certificación Piloto para ese registro.
- **Arquitectura multi-cliente**: modelo Silo (un contenedor Docker + una base de datos separada por cliente), no multi-tenant compartido — el código no es multi-tenant seguro hoy. Hosting elegido: Hetzner Cloud, plan CPX22 (~$8/mes, región US).
- **Certificado digital**: Bs 70 cada 2 años; cada cliente paga y renueva el suyo, no es un costo de CGS Technology.
- **Plan de precios**: tres niveles de suscripción (Bs 120/250/420 por mes), con análisis de competencia ya hecho.

## 12. Pendientes concretos, en orden de prioridad

1. **Esperar respuesta del SIN** sobre el error 995 (NCD, sector 24) — bloqueador activo de 4 etapas de certificación.
2. Una vez resuelto: agregar la **devolución de stock** al validar una NCD (todavía no está escrita — condicionarla a que `estado_sin` sea realmente "Validada", mismo criterio que ya usa Anular).
3. Auditar el resto del sistema buscando más casos del patrón `_modal_error()` mal usado dentro de un POST de formulario ya abierto (ver sección 6).
4. Decidir si se ampli el Django admin en modo **solo lectura** para `FacturaEnc`, `Pago`, `CierreDia`, `ComprasEnc` (se registró `NotaCreditoDebito` de lectura/escritura normal por ahora, sin restringir).
5. Decidir si se retoma el recálculo retroactivo del Costo Promedio Ponderado (pausado a propósito).
6. Confirmar que los dos reportes nuevos y sus rutas se integraron bien en `bases/views.py` y `bases/urls.py` (se entregaron como snippets, no como archivos completos).
7. Deployment real: armar `Dockerfile` / `docker-compose.yml` / config de `nginx` cuando se esté listo para producción (arquitectura ya decidida, ver sección 11).
8. Limpieza pendiente de `prototipo/sin/` (archivos de certificación que ya cumplieron su función).

## 13. Nota sobre cómo se trabajó en esta sesión de chat (para contexto, no aplica igual en Claude Code)

Esta conversación se dio en un chat regular de Claude, cuyo entorno de trabajo (sandbox) se reinicia entre turnos — varios archivos grandes (`base.html`, `fac/views.py`, `cmp/views.py`, etc.) se perdieron y tuvieron que volver a pedirse más de una vez. Por eso algunas entregas de esta sesión son **snippets para agregar** a un archivo existente, no el archivo completo — en particular `bases/views.py`, `bases/urls.py` y `fac/admin.py`, que nunca se tuvieron completos. Claude Code, al tener acceso directo al filesystem real del proyecto, no debería tener esta limitación — pero vale la pena que la primera tarea ahí sea confirmar que esos snippets efectivamente quedaron bien integrados, sin nada duplicado ni a medio aplicar.
