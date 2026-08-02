"""
prototipo/sin/probar_cufd.py
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")

NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CUIS = "31477C6C"

session = Session()
session.headers.update({"apikey": f"TokenApi {TOKEN}"})
transport = Transport(session=session)

client = Client(wsdl=WSDL, transport=transport)

# Primero inspeccionamos la firma real de cufd, para no adivinar nombres de campos
print("=== Firma de cufd ===")
print(client.service.cufd)

print("\n=== Probando cufd (codigoPuntoVenta=0, sin registro previo) ===")
solicitud = {
    "codigoAmbiente": 2,
    "codigoModalidad": 1,
    "codigoPuntoVenta": 0,
    "codigoSistema": CODIGO_SISTEMA,
    "codigoSucursal": 0,
    "cuis": CUIS,
    "nit": NIT,
}

try:
    resp = client.service.cufd(SolicitudCufd=solicitud)
    print("Respuesta:")
    print(serialize_object(resp))
except Exception as e:
    print(f"ERROR: {e}")