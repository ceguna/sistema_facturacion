"""
prototipo/sin/probar_registro_punto_venta.py — v2
Probando codigoTipoPuntoVenta=0 (estándar, no listado en el catálogo de excepciones)
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")

NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CUIS = "31477C6C"

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
transport = Transport(session=session)

client = Client(wsdl=WSDL, transport=transport)

print("=== registroPuntoVenta (codigoTipoPuntoVenta=0) ===")
solicitud = {
    "codigoAmbiente": 2,
    "codigoModalidad": 1,
    "codigoSistema": CODIGO_SISTEMA,
    "codigoSucursal": 0,
    "codigoTipoPuntoVenta": 0,
    "cuis": CUIS,
    "descripcion": "Punto de venta principal - Libreria Millennium",
    "nit": NIT,
    "nombrePuntoVenta": "Casa Matriz",
}

try:
    resp = client.service.registroPuntoVenta(SolicitudRegistroPuntoVenta=solicitud)
    print("Respuesta:", resp)
except Exception as e:
    print(f"ERROR: {e}")