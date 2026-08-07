# app/fe — Facturación Electrónica (integración real con el SIN)

Este es el módulo de producción que conecta el sistema de ventas
(`app/fac`) con los servicios del SIN. La investigación de protocolo que
dio origen a este código (headers de autenticación, formato exacto de
cada operación SOAP, errores encontrados y su solución) está documentada
por separado en `prototipo/sin/README.md` — ese README es una bitácora
histórica de certificación, este es la documentación viva del código real.

## Archivos

- **`cuf.py`** — cálculo del CUF (algoritmo Módulo 11), copia directa y
  sin cambios del validado en `prototipo/sin/cuf.py`.
- **`factura_xml.py`** — armado del XML de factura según el XSD oficial,
  copia directa y sin cambios de `prototipo/sin/factura_xml.py`.
- **`services.py`** — la orquestación real: `emitir_factura_sin(factura_enc)`.
- **`models.py`** — `Empresa`, `Sucursal`, `PuntoVenta` (configuración de
  la empresa emisora ante el SIN).

## `emitir_factura_sin(factura_enc, codigo_punto_venta=0)`

Punto de entrada único para emitir una factura ante el SIN. Toma una
`FacturaEnc` (de `app.fac`) ya guardada con su `FacturaDet` asociado, y:

1. Valida prerrequisitos — `Empresa` (NIT, código de sistema), `Sucursal`
   (CUIS, municipio, dirección), token en `.env`, y homologación SIN de
   cada producto de la factura. Si falta algo, lanza `EmisionSinError`
   con un mensaje claro indicando exactamente qué falta — nunca adivina
   ni sigue de largo con un valor inventado.
2. Pide un CUFD fresco.
3. Calcula el CUF con los datos reales de la factura.
4. Arma el XML, lo firma con el certificado real (AGETIC), lo valida
   contra el XSD oficial.
5. Comprime en gzip, calcula el hash SHA-256.
6. Envía vía `recepcionFactura`.
7. Guarda el resultado directo en el objeto `factura_enc`: `cuf`, `cufd`,
   `estado_sin`, `codigo_recepcion_sin`, `mensaje_sin`,
   `fecha_hora_envio_sin`. Si el SIN rechazó, además lanza
   `EmisionSinError` con el detalle.

### Uso básico

```python
from fac.models import FacturaEnc
from fe.services import emitir_factura_sin, EmisionSinError

factura = FacturaEnc.objects.get(id=123)

try:
    emitir_factura_sin(factura)
    # factura.cuf, factura.estado_sin, factura.codigo_recepcion_sin
    # ya quedaron actualizados y guardados
except EmisionSinError as e:
    # mostrar el error al usuario / loguearlo
    print(e)
```

## Prerrequisitos para que una factura pueda emitirse

- **`Empresa`**: un único registro, con `nit` y `codigo_sistema` cargados
  (se completan en `/fe/`, después de la Autorización de Sistemas ante
  el SIN).
- **`Sucursal`** casa matriz (`codigo_sucursal=0`): con `codigo_cuis`,
  `municipio`, y `direccion` cargados.
- **`.env`**: variable `SIN_TOKEN_DELEGADO` (Token Delegado generado en
  SIAT en Línea, nunca en el repo).
- **Homologación de cada `Producto`** de la factura:
  `actividad_economica_sin`, `codigo_producto_sin`, y que su
  `UnidadMedida` tenga `codigo_sin`. Ver sección de Homologación abajo.

## Homologación de Productos/Servicios (obligación normativa)

RND N° 102500000018 (abril 2025), plazo extendido hasta el 29/05/2026
(ya vencido — es obligatorio hoy). Exige que cada producto/servicio
facturado esté vinculado a un código oficial coherente con la actividad
económica registrada del contribuyente.

El proceso oficial descrito por el SIN es, en esencia, lo que ya está
implementado acá:
1. Descargar el listado de productos/servicios vía el servicio Web —
   esto es `sincronizarListaProductosServicios`, ya integrado en
   `app/catalogos` con datos reales.
2. Asignar a cada producto propio su código equivalente — esto son los
   campos `Producto.actividad_economica_sin` y `Producto.codigo_producto_sin`
   (en `app/inv`).

No existe un "trámite de envío" separado ante el SIN — la verificación
es automática cada vez que se emite una factura. Si un producto no está
bien homologado, el SIN rechaza con error 1016/1017 ("actividad
económica no asociada" / "producto no asociado a la actividad").

**Pendiente**: pantalla de homologación en la UI (hoy se hace por shell
de Django). Ver Fase B.1 en el roadmap más abajo.

## Bugs encontrados al integrar (y su corrección)

Estos no aparecían en el prototipo porque los scripts sueltos se corrían
siempre "al toque" — al integrar a un flujo real donde puede pasar
tiempo entre crear la venta y emitirla, salieron a la luz:

- **`fechaEnvio` en UTC en vez de hora local** (Bolivia es UTC-4): error
  935 "PARAMETRO FECHA DE ENVIO INVALIDO". Corregido con
  `timezone.localtime(timezone.now())`.
- **Fecha de emisión tomada de `factura_enc.fecha`** (momento de
  creación del registro en BD) **en vez del momento real del envío**:
  si pasa tiempo entre crear la venta y emitirla, el CUF y el XML quedan
  con una fecha vieja, fuera de la tolerancia del SIN (~5 min, error
  1009). Corregido: se captura `fecha_hora = timezone.localtime(timezone.now())`
  una sola vez al principio de `emitir_factura_sin`, usada tanto para el
  CUF como para la cabecera del XML.

## Ambiente de pruebas

Todo el desarrollo y las pruebas de volumen (para subir el porcentaje de
las etapas de certificación Piloto) se hacen contra la base de datos
LOCAL existente (`db_djfull`), confirmada sin datos reales de la
librería — no contra Render ni contra ningún ambiente con datos de
producción. Motivo: los servicios del SIN son externos, da igual desde
dónde se los llame, y así se evita ensuciar reportes/contabilidad reales
con facturas de prueba. Cuando el sistema esté certificado y estable:
renombrar la base a un nombre comercial y migrar a Render recién ahí.

## Roadmap de integración

- ✅ **Fase A** — Modelo de datos (`FacturaEnc`, `Producto`,
  `UnidadMedida`, `Sucursal` extendidos con los campos SIN necesarios).
- ✅ **Fase B** — Servicio reutilizable `emitir_factura_sin`. Primera
  factura emitida con éxito desde Django real: `codigoRecepcion:
  c6f79b6c-905d-11f1-a745-adb8279ff5dd`, estado `validada` (04/08/2026).
- ⏳ **Fase B.1** — Pantalla de homologación de productos en la UI.
- ⏳ **Fase C** — Disparo automático: que emitir una venta en `app/fac`
  llame a `emitir_factura_sin` como parte del flujo normal, no manual.
- ⏳ **Fase D** — Generación de volumen de "casos correctos" (reutilizando
  el servicio real, no scripts aparte) para subir el porcentaje de cada
  etapa de certificación Piloto ante el SIN.

## Roadmap SaaS / multi-cliente (no urgente, para cuando haya un segundo cliente)

El código (`emitir_factura_sin`, `cuf.py`, `factura_xml.py`) es genérico
y no cambia por cliente. Lo que sí es específico de cada uno: NIT,
certificado AGETIC, Token Delegado, actividad económica registrada, y
su propia homologación de productos — exigencia del SIN, no evitable
con mejor código.

Dos tareas pendientes para cuando llegue ese momento:
1. Registrar CSG Sistemas como **Proveedor** (no Propietario) ante el
   SIN, con NIT propio — habilita el trámite liviano de "Asociación de
   Sistemas" por cliente nuevo, en vez de una Autorización completa
   desde cero.
2. Automatizar el onboarding: cargar NIT + certificado + credenciales de
   SIAT en Línea de un cliente nuevo → consultar su actividad económica
   real → sincronizar su catálogo de productos → guardar en `Empresa`.

## Ver también

`prototipo/sin/README.md` — bitácora completa de la investigación de
protocolo y del proceso de certificación Piloto ante el SIN (las 8
etapas, headers de autenticación, formato exacto de cada operación
SOAP, errores encontrados en el camino y su solución). Consultar ahí
para entender el "por qué" de cualquier decisión de `services.py`.