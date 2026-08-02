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

## Estado actual (02/08/2026)
- ✅ CUIS obtenido: `31477C6C`, vigente hasta 01/08/2027
- ✅ CUFD real obtenido (ver arriba, vigencia corta — pedir uno nuevo por sesión de trabajo)
- ✅ CUF real calculado, factura firmada y validada contra XSD
- ❌ `registroPuntoVenta` descartado — no aplica al caso (ver arriba)
- ⏳ Próximo paso: `recepcionFactura` (envío real de la factura al SIN)
- ⏳ Pendiente en paralelo: conectar la app `catalogos` con cliente `zeep`
  real (reemplazar `MockSOAPClient`) — ya se tienen confirmados en esta
  sesión los catálogos de Tipo de Punto de Venta, Tipo de Emisión y Tipos
  de Factura; faltaría repetir el patrón para el resto.
