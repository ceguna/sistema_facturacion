"""
prototipo/sin/inspeccionar_evento_significativo.py -- v2
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
transport = Transport(session=session)

client = Client(wsdl=WSDL, transport=transport)

print("=== Estructura de solicitudEventoSignificativo (para REGISTRAR) ===")
print(client.get_type("ns0:solicitudEventoSignificativo"))

print("\n=== Estructura de solicitudConsultaEvento (para CONSULTAR) ===")
print(client.get_type("ns0:solicitudConsultaEvento"))

print("\n=== Estructura de eventosSignificativosDto (posible catalogo de tipos de evento) ===")
print(client.get_type("ns0:eventosSignificativosDto"))