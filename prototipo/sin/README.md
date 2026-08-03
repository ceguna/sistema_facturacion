# Prototipo SIN — Notas de autenticación (PILOTO)

## Autenticación ante los servicios SOAP del SIN — CONFIRMADO (01/08/2026)

Todos los servicios SOAP del ambiente Piloto (`FacturacionCodigos`, y probablemente
`FacturacionOperaciones`, `FacturacionSincronizacion`, `ServicioFacturacionCompraVenta`,
`ServicioFacturacionDocumentoAjuste` — a confirmar en cada uno) usan el **Token Delegado**
generado desde SIAT en Línea → Gestor Token Delegado Piloto, vía un header HTTP con este
formato exacto:

```
Header:  apikey
Valor:   TokenApi <token_delegado_jwt>
```

**Importante:** NO es `Authorization: Token <token>` (esa convención aparece en foros
viejos de 2022 y en algunos ejemplos históricos, pero no es la que acepta el servicio
actualmente). Probamos varias combinaciones — el error real que devuelve el servicio si
el header está mal es `EL SERVICIO REQUIERE API KEY`.

### Cómo se generó el token en uso
- Portal: SIAT en Línea → `fman.impuestos.gob.bo/facturacionv2` → Gestor Token Delegado
  Piloto → Token Delegado Piloto → "Generar Nuevo Token"
- Vigencia: 01/08/2026 a 01/08/2027
- Se guarda en `.env` (raíz del proyecto Django) como `SIN_TOKEN_DELEGADO`, nunca en el repo.

### Descartado: ServicioAutenticacionSoap
Se investigó un servicio separado (`ServicioAutenticacionSoap`, login+password de SIAT
en Línea → devuelve JWT) documentado en `siatanexo.impuestos.gob.bo` (doc desactualizada,
de 2020). **No hace falta para nada de lo que usamos.** Además dio error
"Usuario no encontrado en OV" — probablemente porque la cuenta migró al sistema nuevo
Oficina Virtual Tributaria (OIDC/Keycloak) y ese servicio viejo valida contra el sistema
anterior. El reporte oficial de la Solicitud 9454 no lo lista entre los servicios
relevantes — confirmado que es una vía muerta para este proyecto.

### Ejemplo de cliente funcionando (zeep)

```python
from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
TOKEN = config("SIN_TOKEN_DELEGADO")

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
client = Client(wsdl=WSDL, transport=Transport(session=session))

resp = client.service.verificarComunicacion()  # confirma auth OK
resp = client.service.cuis(SolicitudCuis={
    "codigoAmbiente": 2,      # 2 = Pruebas (Piloto)
    "codigoModalidad": 1,     # 1 = Electrónica en línea
    "codigoSistema": "373A0EA0FBA931B62586",
    "codigoSucursal": 0,
    "nit": 3852849010,
})
```

## registroPuntoVenta — DESCARTADO para este caso (02/08/2026)

Se probó `registroPuntoVenta` con `codigoTipoPuntoVenta=1` y luego `0`: ambos
dieron `EL PARAMETRO TIPO DE PUNTO DE VENTA ES INVALIDO`. Se consultó el
catálogo real (`sincronizarParametricaTipoPuntoVenta`) y resultó que **todos**
los códigos válidos son categorías especiales:

| Código | Descripción |
|---|---|
| 1 | PUNTO VENTA COMISIONISTA |
| 2 | PUNTO VENTA VENTANILLA DE COBRANZA |
| 3 | PUNTO DE VENTA MÓVILES |
| 4 | PUNTO DE VENTA YPFB |
| 5 | PUNTO DE VENTA CAJEROS |
| 6 | PUNTO DE VENTA CONJUNTA |

Ninguna es "punto de venta físico estándar". Conclusión: para un negocio
normal (mostrador físico, sin ninguna de estas modalidades especiales),
**no hace falta registrar nada** — se usa `codigoPuntoVenta=0` directo en
`cufd` y en el CUF. Confirmado empíricamente: `cufd` con `codigoPuntoVenta=0`
funcionó sin problema (ver abajo).

## cufd (Etapa III) — CONFIRMADO (02/08/2026)

Mismo WSDL que `cuis` (`FacturacionCodigos`), mismo header `apikey`.
Objeto de solicitud: `SolicitudCufd` (codigoAmbiente, codigoModalidad,
codigoPuntoVenta, codigoSistema, codigoSucursal, cuis, nit).

**Importante — vigencia corta:** a diferencia del CUIS o el Token Delegado,
el CUFD vence rápido (~24-48hs). Hay que volver a pedirlo periódicamente,
no es un valor para hardcodear a largo plazo. `main.py` ahora incluye un
chequeo de vencimiento que avisa si el CUFD guardado ya expiró.

## Catálogos verificados contra servicio real (02/08/2026)

Para no asumir los valores de ejemplo de la documentación oficial sin
chequear, se confirmaron estos dos contra `sincronizarParametrica*`:

- **Tipo de Emisión**: `1 = EN LINEA` (además: 2=Fuera de línea, 3=Masivo, 4=Contingencia)
- **Tipos de Factura**: `1 = FACTURA CON DERECHO A CREDITO FISCAL` (además: 2=Sin derecho a crédito fiscal, 3=Documento de ajuste, 4=Documento equivalente)

Ambos coinciden con los valores que ya traía el prototipo del ejemplo
oficial — confirmado que aplican también al caso real de la librería
(Régimen General, factura con derecho a crédito fiscal estándar).

## CUF real logrado — hito (02/08/2026)

`main.py` corrido con CUFD y `codigoControl` reales (ya no simulados):
CUF resultante `1079F647BEC1A17B1709528B3FCB31B22CB3B9E06A3968EA18C971BF74`
— firmado con el certificado real de AGETIC, firma verificada
criptográficamente, y válido contra `facturaElectronicaCompraVenta.xsd`.
Primera factura de punta a punta sin ningún dato simulado.

## recepcionFactura — CONFIRMADO, primera factura validada (02/08/2026)

### Objeto de solicitud
Nombre real del tipo según WSDL: `solicitudRecepcionFactura`. El parámetro
de la operación (el que espera `client.service.recepcionFactura(...)`) es
`SolicitudServicioRecepcionFactura`.

Campos (confirmados vía `client.get_type` contra el WSDL real, no adivinados):
`codigoAmbiente`, `codigoDocumentoSector`, `codigoEmision`, `codigoModalidad`,
`codigoPuntoVenta`, `codigoSistema`, `codigoSucursal`, `cufd`, `cuis`, `nit`,
`tipoFacturaDocumento`, `archivo` (base64Binary), `fechaEnvio`, `hashArchivo`.

### Flujo completo confirmado (documentación oficial + prueba real)

1. Armar el XML de la factura
2. Firmar (XMLDSig, RSA-SHA256, C14N con comentarios) — ya lo hacía el prototipo
3. Validar contra el XSD — ya lo hacía el prototipo
4. **Comprimir el XML firmado en gzip** → los bytes van en el campo `archivo`
   (zeep codifica a base64 solo, no hace falta hacerlo a mano)
5. **Calcular SHA-256 del archivo comprimido** (no del XML plano) → hex
   en mayúsculas va en `hashArchivo`
6. Enviar vía `recepcionFactura`

Los pasos 4 y 5 NO estaban en el prototipo original (`main.py` paraba en
el paso 3) — se agregaron en `enviar_factura.py`.

### Errores encontrados y resueltos en el camino

- **Error 1016/1017** ("actividad económica no asociada al contribuyente" /
  "producto no asociado a la actividad"): el prototipo usaba
  `actividadEconomica="476130"` y `codigoProductoSin="49111"`, ambos
  valores de EJEMPLO de la documentación oficial, nunca verificados contra
  los datos reales de la librería. Corrección:
  - Actividad económica real (confirmada en SIAT en Línea → Registro
    Nacional de Contribuyentes → Información del Contribuyente):
    **`4761300`** — "Venta al por menor de material de oficina y artículos
    de librería" (ojo: 7 dígitos, no 6 — el valor de ejemplo tenía un
    dígito menos).
  - Producto real (confirmado vía `sincronizarListaProductosServicios`,
    filtrando por `codigoActividad=4761300`): **`1003646`** — artículos de
    papelería (cuadernos, bolígrafos, etc. — coincide con el ítem de
    prueba usado). Alternativa disponible: `1004879` (Activos Fijos).

### Resultado final
```
codigoDescripcion: VALIDADA
codigoEstado: 908
codigoRecepcion: a3d0a836-8ec8-11f1-a745-adb8279ff5dd
transaccion: True
```

### Script de referencia: `enviar_factura.py`
Encadena: pedir CUFD fresco → calcular CUF → armar XML → firmar → validar
XSD → gzip → SHA-256 → enviar. Pide un CUFD nuevo en cada corrida (no
reutiliza uno guardado) porque la vigencia es corta — importante también
para producción: cada emisión debería pedir su propio CUFD si el
anterior venció.

## catalogos — MockSOAPClient reemplazado por cliente real (02/08/2026)

`app/catalogos/services.py` ahora usa `SOAPClienteSIN` (zeep real, mismo
header `apikey: TokenApi`) en vez de `MockSOAPClient`. El comando
`sincronizar_catalogos` valida que `Empresa` tenga NIT y `codigo_sistema`,
que exista una `Sucursal` casa matriz (`codigo_sucursal=0`) con
`codigo_cuis` cargado, y que `SIN_TOKEN_DELEGADO` esté en `.env` — falla
rápido y claro si falta alguno, en vez de generar datos corruptos.

**Resultado: 16/17 catálogos sincronizados con datos reales del SIN.**

Cada catálogo cae en una de tres categorías, todas confirmadas contra
respuestas reales en vivo (no adivinadas):

- **Familia "parametrica"** (mismo formato `codigoClasificador` +
  `descripcion` dentro de `listaCodigos`): EVENTOS_SIGNIFICATIVOS,
  MOTIVOS_ANULACION, PAIS_ORIGEN, TIPO_DOC_IDENTIDAD, TIPO_DOC_SECTOR,
  TIPO_EMISION, TIPO_HABITACION, TIPO_METODO_PAGO, TIPO_MONEDA,
  TIPO_PUNTO_VENTA, TIPO_FACTURA, TIPO_UNIDAD_MEDIDA, MENSAJES (13 en
  total — MENSAJES comparte el formato aunque su DTO se llame distinto).
- **DTO propio, mapeado individualmente**: ACTIVIDADES (`listaActividades`,
  campos `codigoCaeb`+`descripcion`), LEYENDAS (`listaLeyendas`, campos
  `codigoActividad`+`descripcionLeyenda`), PRODUCTOS_SERVICIOS
  (`listaCodigos`, campos `codigoProducto`+`descripcionProducto`).
- **Fuera del modelo genérico, no sincronizado**: ACTIVIDADES_DOC_SECTOR
  — es una tabla de relación actividad↔documento sector
  (`codigoActividad`+`codigoDocumentoSector`+`tipoDocumentoSector`), sin
  campo de descripción real. No encaja en `CatalogoSIN` (código/
  descripción genérico). Aparece como "error" intencional en el log del
  comando — si hace falta más adelante, requiere un modelo propio.

### Nota de arquitectura pendiente — modelo PuntoVenta
`app/fe/models.py::PuntoVenta` asume que todo punto de venta pasa por
`registroPuntoVenta` y exige elegir uno de los 6 tipos especiales
(Comisionista, Ventanilla, Móviles, YPFB, Cajeros, Conjunta). Pero lo
confirmado el 02/08/2026 es que un punto de venta estándar (como el de
la librería) NO pasa por ese registro — usa `codigoPuntoVenta=0` directo.
Revisar este modelo cuando se conecte la emisión de facturas real, para
contemplar el caso estándar como opción válida y no forzar siempre uno
de los tipos especiales.

## Pendiente — Roadmap SaaS / multi-cliente (no urgente, anotado 02/08/2026)

Pregunta que surgió al cierre de esta sesión: ¿hay que repetir todo este
proceso de descubrimiento por cada cliente nuevo que compre el sistema
bajo modalidad SaaS? Respuesta corta: el código (autenticación, CUF,
firma, XML, gzip, hash, envío) es genérico y no se repite — pero cada
cliente sí necesita su propia identidad fiscal (NIT, certificado AGETIC,
Token Delegado, actividad económica registrada, catálogo de productos
asociado a su actividad). Eso es exigencia del SIN, no algo evitable con
mejor código.

Dos cosas a desarrollar más adelante (cuando haya un segundo cliente
real, no antes):

1. **Registrar CSG Sistemas como Proveedor** (no Propietario) ante el SIN,
   con NIT propio — habilita el trámite liviano de "Asociación de
   Sistemas" para cada cliente nuevo, en vez de una Solicitud de
   Autorización completa desde cero como la que se hizo para la librería
   (Solicitud 9454).
2. **Automatizar el onboarding de cada cliente nuevo** dentro de la app
   Django: cargar NIT + certificado + credenciales de SIAT en Línea →
   consultar automáticamente su actividad económica real (como se hizo
   hoy a mano vía "Información del Contribuyente") → sincronizar el
   catálogo de productos asociado a esa actividad → guardar todo en el
   modelo `Empresa`. Así el proceso manual de hoy se convierte en una
   función reutilizable, no en trabajo repetido por cliente.

## Estado actual (02/08/2026)
- ✅ CUIS obtenido: `31477C6C`, vigente hasta 01/08/2027
- ✅ CUFD real obtenido (vigencia corta — pedir uno nuevo por sesión de trabajo)
- ✅ CUF real calculado, factura firmada y validada contra XSD
- ❌ `registroPuntoVenta` descartado — no aplica al caso (ver arriba)
- ✅ **`recepcionFactura` — PRIMERA FACTURA VALIDADA POR EL SIN** (`codigoRecepcion: a3d0a836-8ec8-11f1-a745-adb8279ff5dd`)
- ⏳ Próximo paso: integrar este flujo al Django real (reemplazar el
  prototipo aislado por la app de facturación), y/o seguir con las
  siguientes etapas de certificación Piloto (Eventos Significativos,
  Emisión de paquetes, Anulación, Reversión)
- ⏳ Pendiente en paralelo: conectar la app `catalogos` con cliente `zeep`
  real (reemplazar `MockSOAPClient`) — ya se tienen confirmados en esta
  sesión los catálogos de Tipo de Punto de Venta, Tipo de Emisión, Tipos
  de Factura, y Productos/Servicios por actividad; faltaría repetir el
  patrón para el resto.

