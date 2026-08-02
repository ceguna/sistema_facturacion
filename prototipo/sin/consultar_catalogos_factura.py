"""
prototipo/sin/consultar_catalogos_factura.py

Confirma contra el servicio real los catalogos de Tipo de Emision
y Tipos de Factura, para no asumir los valores del ejemplo oficial
sin verificar que aplican al caso real.
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

print("=== sincronizarParametricaTipoEmision ===")
try:
    resp = client.service.sincronizarParametricaTipoEmision(SolicitudSincronizacion=solicitud_base)
    print(serialize_object(resp))
except Exception as e:
    print(f"ERROR: {e}")

print("\n=== sincronizarParametricaTiposFactura ===")
try:
    resp = client.service.sincronizarParametricaTiposFactura(SolicitudSincronizacion=solicitud_base)
    print(serialize_object(resp))
except Exception as e:
    print(f"ERROR: {e}")