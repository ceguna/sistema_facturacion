"""
prototipo/sin/inspeccionar_catalogos_pendientes.py

Inspecciona la estructura real de respuesta de los 4 catalogos que
todavia no estan verificados (ACTIVIDADES, ACTIVIDADES_DOC_SECTOR,
LEYENDAS, MENSAJES) -- cada uno tiene un DTO propio, distinto al de
la familia "parametrica" ya confirmada.
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CUIS = "31477C6C"

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
transport = Transport(session=session)

client = Client(wsdl=WSDL, transport=transport)

solicitud_base = {
    "codigoAmbiente": 2,
    "codigoPuntoVenta": 0,
    "codigoSistema": CODIGO_SISTEMA,
    "codigoSucursal": 0,
    "cuis": CUIS,
    "nit": NIT,
}

operaciones = [
    "sincronizarActividades",
    "sincronizarListaActividadesDocumentoSector",
    "sincronizarListaLeyendasFactura",
    "sincronizarListaMensajesServicios",
]

for nombre_op in operaciones:
    print(f"\n{'='*70}")
    print(f"=== {nombre_op} ===")
    print('='*70)
    try:
        operacion = getattr(client.service, nombre_op)
        resp = operacion(SolicitudSincronizacion=solicitud_base)
        resp = serialize_object(resp)
        # Solo mostramos los primeros 3 items para no saturar la salida
        claves_lista = [k for k, v in resp.items() if isinstance(v, list) and k != "mensajesList"]
        print(f"Claves de nivel superior: {list(resp.keys())}")
        for clave in claves_lista:
            items = resp[clave]
            print(f"\n'{clave}' -- {len(items)} items. Primeros 3:")
            for item in items[:3]:
                print(f"  {item}")
    except Exception as e:
        print(f"ERROR: {e}")