"""
prototipo/sin/inspeccionar_anulacion.py
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
transport = Transport(session=session)

client = Client(wsdl=WSDL, transport=transport)

print("=== Estructura de solicitudAnulacion ===")
print(client.get_type("ns0:solicitudAnulacion"))