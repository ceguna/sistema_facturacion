# Prototipo SIN — Bitácora de investigación y certificación Piloto

> **Nota:** este archivo es la bitácora histórica de cómo se descubrió el
> protocolo del SIN y se avanzó en la certificación Piloto. La
> documentación del código real que usa el sistema en producción está en
> **`app/fe/README.md`** — empezar por ahí si lo que buscás es "cómo se
> emite una factura hoy", no "cómo se descubrió cómo hacerlo".

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

## Eventos Significativos (Etapa V) — CONFIRMADO (03/08/2026)

Servicio `registroEventoSignificativo` (WSDL `FacturacionOperaciones`,
mismo header `apikey: TokenApi`). Objeto de solicitud real:
`solicitudEventoSignificativo`, parámetro de la operación
`SolicitudEventoSignificativo`.

Campos confirmados vía `client.get_type`: `codigoAmbiente`,
`codigoMotivoEvento`, `codigoPuntoVenta`, `codigoSistema`,
`codigoSucursal`, `cufd`, `cufdEvento`, `cuis`, `descripcion`,
`fechaHoraFinEvento`, `fechaHoraInicioEvento`, `nit`.

`codigoMotivoEvento` sale del catálogo `EVENTOS_SIGNIFICATIVOS`, ya
sincronizado con datos reales en `app/catalogos` (7 códigos: corte de
internet, inaccesibilidad al SIN, zona sin internet, venta sin internet,
virus/falla de software, falla de hardware, corte de energía).

### Punto clave — dos CUFD distintos, no uno solo

Error 984 ("EL EVENTO SIGNIFICATIVO NO CORRESPONDE AL CUFD DEL EVENTO
REGISTRADO") apareció al usar el mismo CUFD en `cufd` y `cufdEvento`.
La documentación oficial (Contingencia y Eventos Significativos) aclara
la secuencia real:

1. **`cufdEvento`**: el CUFD que ya estaba vigente ANTES/DURANTE la
   contingencia (el que se usaba al momento de emitir, en modo
   contingencia u offline).
2. **`cufd`**: un CUFD NUEVO, pedido específicamente al momento de
   REPORTAR el evento — distinto del anterior.

Confirmado empíricamente: pedir dos CUFD por separado (uno para marcar
el inicio del evento, esperar unos segundos, pedir el segundo para el
reporte) resolvió el error. Con un solo CUFD repetido, siempre falla.

### Resultado
```
codigoRecepcionEventoSignificativo: 9828970
transaccion: True
```

### Script de referencia: `probar_evento_significativo.py`

## Emisión de paquetes (Etapa VI) — EN CURSO, bloqueado en un punto puntual (03/08/2026)

Servicio `recepcionPaqueteFactura` (WSDL `ServicioFacturacionCompraVenta`).
Objeto real: `solicitudRecepcionPaquete`, parámetro de la operación
`SolicitudServicioRecepcionPaquete`. Campos: los mismos de
`solicitudRecepcionFactura` (Etapa IV) más `cafc`, `cantidadFacturas`,
`codigoEvento`.

**Formato del archivo confirmado** (documentación oficial): cada factura
se firma/valida individualmente como siempre, pero varias facturas juntas
van dentro de un **contenedor TAR**, y recién ese TAR se comprime en gzip
(no gzip directo de un XML único). `hashArchivo` es el SHA-256 del
`.tar.gz`, no del TAR sin comprimir.

**`cafc`** (Código de Autorización de Facturas de Contingencia): solo
aplica a facturas MANUALES impresas por una imprenta autorizada. Para la
modalidad Electrónica en Línea pasando a "fuera de línea" (nuestro caso),
no aplica — queda vacío (`""`).

**`codigoEvento`**: es el `codigoRecepcionEventoSignificativo` que
devuelve `registroEventoSignificativo` (Etapa V) — conecta el paquete
con el evento de contingencia que lo justifica.

### Envío del paquete: funciona
`recepcionPaqueteFactura` responde `codigoEstado: 901 (PENDIENTE)` con
`codigoRecepcion` — confirmado, el envío en sí no tiene problema.

### Bloqueo puntual: registrar el evento vinculado a un paquete
Mismo patrón de dos CUFD que funcionó en la Etapa V aislada (CUFD previo
para `cufdEvento`, CUFD nuevo para `cufd`, ventana real de ~10 segundos)
da error **984** ("EL EVENTO SIGNIFICATIVO NO CORRESPONDE AL CUFD DEL
EVENTO REGISTRADO") cuando el evento acompaña un paquete de facturas.
Invertir los campos da error distinto (**914**, "CUFD INVALIDO"),
confirmando que la asignación original (cufd=nuevo, cufdEvento=previo)
es la estructuralmente correcta — el problema es otra cosa, no el orden
de los campos.

**Pendiente: consultar con soporte SIN** (`siat.facturacion@impuestos.gob.bo`
o `800-10-3444`) por qué el mismo patrón que funciona aislado falla al
acompañar un paquete — posible relación con frecuencia de solicitudes de
CUFD (existe un mensaje de catálogo "CUFD FUERA DE TOLERANCIA", código
123, sin confirmar si aplica acá) u otra validación no documentada.

### Scripts de referencia
`probar_paquete_factura.py` (envío aislado, confirmó 901/PENDIENTE),
`validar_paquete_factura.py` (consulta de estado), `probar_paquete_completo.py`
(flujo integrado evento+paquete, bloqueado en el paso del evento).

## Anulación (Etapa VII) — CONFIRMADO (03/08/2026)

Servicio `anulacionFactura` (mismo WSDL que `recepcionFactura`,
`ServicioFacturacionCompraVenta`). Objeto real: `solicitudAnulacion`,
parámetro de la operación `SolicitudServicioAnulacionFactura` (no
`SolicitudAnulacion` — mismo patrón de siempre, confirmado por el
mensaje de error de zeep).

Campos: los mismos de `solicitudRecepcionFactura` (sin `archivo` ni
`hashArchivo`) más `codigoMotivo` (del catálogo `MOTIVOS_ANULACION`,
ya sincronizado en `app/catalogos`: 1=Factura mal emitida, 2=Nota de
Crédito-Débito mal emitida, 3=Datos de emisión incorrectos, 4=Factura o
Nota devuelta) y `cuf` (el CUF de la factura a anular).

### Dato importante de infraestructura del ambiente Piloto
Intentar anular una factura del día anterior (02/08) dio error 924
("LA FACTURA O NOTA, NO EXISTE EN LA BASE DE DATOS DEL SIN") —
probablemente el ambiente Piloto purga datos de prueba periódicamente
(a diferencia de Producción). Confirmado al emitir una factura nueva y
anularla de inmediato en la misma corrida: funcionó sin problema. **Para
pruebas futuras de anulación/reversión, usar siempre una factura recién
emitida en la misma sesión, no una de días anteriores.**

### Resultado
```
codigoDescripcion: ANULACION CONFIRMADA
codigoEstado: 905
transaccion: True
```

### Script de referencia: `probar_anulacion_v2.py` (emite + anula en una sola corrida)

## Reversión (Etapa VIII) — CONFIRMADO (03/08/2026)

Servicio `reversionAnulacionFactura` (mismo WSDL,
`ServicioFacturacionCompraVenta`). Objeto real:
`solicitudReversionAnulacion`, parámetro de la operación
`SolicitudServicioReversionAnulacionFactura`.

Campos: los mismos de `solicitudAnulacion` pero SIN `codigoMotivo` — la
reversión no pide motivo, solo el `cuf` de la factura anulada a revertir.

### Reglas de negocio (confirmadas por normativa, no solo por el código)
- Solo se puede revertir **una vez** por factura.
- Plazo: hasta el día 9 del mes siguiente a la emisión original.
- No aplica a facturas emitidas en modo offline/contingencia.
- Estados de respuesta posibles: 907 (Conforme), 981 (no disponible —
  ya se revirtió antes), 924 (no existe en la base), 3011, 3012
  (fuera de plazo).
- Debe notificarse al comprador por correo u otro medio electrónico,
  informando Código de Autorización, número de factura y motivo —
  pendiente de implementar cuando se conecte al flujo real (hoy es
  solo la llamada SOAP, sin la notificación).

### Resultado
Probado sobre la factura Nº400 (emitida y anulada en la Etapa VII, misma
sesión):
```
codigoDescripcion: REVERSION DE ANULACION CONFIRMADA
codigoEstado: 907
transaccion: True
```

### Script de referencia: `probar_reversion.py`

## Estado de las 8 etapas de certificación Piloto (03/08/2026)
- ✅ I. Obtención de CUIS
- ✅ II. Sincronización de Catálogos (16/17)
- ✅ III. Obtención CUFD
- ✅ IV. Emisión individual (primera factura VALIDADA)
- ✅ V. Eventos Significativos (aislado)
- 🟡 VI. Emisión de paquetes — envío OK, evento vinculado a paquete bloqueado, pendiente consulta con SIN
- ✅ VII. Anulación
- ✅ VIII. Reversión

**7 de 8 etapas completadas.** Solo queda resolver el punto puntual de
la Etapa VI (evento vinculado a paquete) para cerrar la certificación
Piloto por completo.

---

**La integración a Django (Fases A-D), el servicio `emitir_factura_sin`,
la decisión de ambiente de pruebas, y el roadmap SaaS/multi-cliente se
documentan en `app/fe/README.md`, no acá.**

## Actualización — Fase D, generación de volumen (06/08/2026)

Se agregaron dos comandos de management nuevos para generar volumen de
"casos correctos" hacia la certificación Piloto, reutilizando los
servicios reales (sin duplicar lógica):

- `app/fac/management/commands/generar_volumen_sin.py` — ciclos de
  emisión + anulación + reversión, parametrizable (`--cantidad`, `--pausa`).
- `app/catalogos/management/commands/generar_volumen_catalogos.py` —
  corridas repetidas de sincronización de catálogos, parametrizable
  (`--veces`, `--pausa`).

### Descubrimiento importante: límite diario de casos correctos

Corriendo varias tandas grandes en un solo día, se detectó que el portal
de Seguimiento de Sistemas Informáticos **deja de sumar casos correctos**
después de cierto punto, aunque las operaciones sigan funcionando con
éxito técnico contra el SIN (sin ningún error, estado `validada`/`905`/
`907` normal en cada una).

Evidencia: se corrieron 10 ciclos adicionales de emisión+anulación+reversión
(confirmados exitosos por consola) y el contador no se movió ni un caso
en Etapas III, IV, VII, VIII, XI. Se probó también un llamado suelto a
`cuis` (Etapa I) — tampoco sumó. Un lote nuevo de Catálogos (Etapa II)
tampoco sumó, aunque esa misma etapa sí había sumado más temprano en el
día (37→801).

**Conclusión: existe un límite diario de casos que el SIN reconoce hacia
el contador de certificación**, aparentemente amplio (no exclusivo de
una sola etapa — parece ser por NIT/sistema en su totalidad, no
confirmado con certeza, es una hipótesis fuerte basada en el patrón
observado, no un hecho documentado oficialmente).

**Implicancia práctica:** la generación de volumen debe hacerse en
tandas moderadas repartidas en varios días — pasado cierto punto diario,
correr más no suma nada al progreso real, solo genera datos de prueba
de más sin beneficio.

### Estado de las 9 etapas al cierre del 06/08/2026 (el portal ahora
### muestra 9 etapas, no 8 — se agregó "VIII. Firma Digital" que no
### estaba en el conteo original de sesiones anteriores)
- I. CUIS: 1/2 (50%)
- II. Catálogos: 801/1800 (44%)
- III. CUFD: 100/200 (50%)
- IV. Emisión individual: 125/500 (25%)
- V. Eventos Significativos: 1/70 (1%) — sin volumen generado aún, pendiente
- VI. Paquetes: 2/280 (0%) — bloqueada, pendiente respuesta del SIN (correo
  sin respuesta hace 5 días; próximo paso: llamar al 800-10-3444)
- VII. Anulación: 125/500 (25%)
- VIII. Firma Digital: 115/460 (25%)
- XI. Reversión: 125/500 (25%)

### Próximos pasos al retomar
1. Llamar al 800-10-3444 por la Etapa VI (bug de evento+paquete), con el
   guión ya preparado (Nº Solicitud 9454, código de sistema, detalle del
   error 984/914).
2. Probar temprano en el día si el contador vuelve a sumar (confirmaría
   reseteo diario) y, de ser así, estimar cuántos casos por día acepta
   cada familia de servicios para planificar cuántos días de generación
   de volumen van a hacer falta en total.
3. Armar comando de volumen para Etapa V (Eventos Significativos) —
   nunca se probó en tandas, solo el caso aislado de una sesión anterior.
