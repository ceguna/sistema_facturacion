"""
prototipo/sin/consultar_productos_actividad.py

Busca productos/servicios asociados a la actividad economica real
de la libreria (4761300), para reemplazar el codigo de ejemplo (49111)
que uso el prototipo.
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

print("=== Firma de sincronizarListaProductosServicios ===")
print(client.service.sincronizarListaProductosServicios)

print("\n=== Intentando consulta ===")
solicitud = {
    "codigoAmbiente": 2,
    "codigoPuntoVenta": 0,
    "codigoSistema": CODIGO_SISTEMA,
    "codigoSucursal": 0,
    "cuis": CUIS,
    "nit": NIT,
}
try:
    resp = client.service.sincronizarListaProductosServicios(SolicitudSincronizacion=solicitud)
    resp = serialize_object(resp)
    print(f"Total productos recibidos: {len(resp.get('listaCodigos', []))}")
    # Filtramos por los que correspondan a la actividad real de la libreria
    for item in resp.get("listaCodigos", []):
        print(item)
except Exception as e:
    print(f"ERROR: {e}")