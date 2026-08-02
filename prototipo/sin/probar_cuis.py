"""
prototipo/sin/probar_cuis.py — v2
Corrigiendo el nombre/formato del header de autenticación.
"""

from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

WSDL = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"

TOKEN = config("SIN_TOKEN_DELEGADO")

NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"


def probar_con_header(nombre_header, valor_header, etiqueta):
    print(f"\n{'='*60}")
    print(f"Probando con header: {nombre_header}: {valor_header[:30]}...")
    print(f"({etiqueta})")
    print('='*60)

    session = Session()
    session.headers.update({nombre_header: valor_header})
    transport = Transport(session=session)

    try:
        client = Client(wsdl=WSDL, transport=transport)
    except Exception as e:
        print(f"ERROR al crear cliente: {e}")
        return False

    try:
        resp = client.service.verificarComunicacion()
        print(f"verificarComunicacion → Respuesta: {resp}")
    except Exception as e:
        print(f"verificarComunicacion → ERROR: {e}")
        return False

    try:
        solicitud = {
            "codigoAmbiente": 2,
            "codigoModalidad": 1,
            "codigoSistema": CODIGO_SISTEMA,
            "codigoSucursal": 0,
            "nit": NIT,
        }
        resp = client.service.cuis(SolicitudCuis=solicitud)
        print(f"cuis → Respuesta: {resp}")
        return True
    except Exception as e:
        print(f"cuis → ERROR: {e}")
        return False


if __name__ == "__main__":
    # Variante 1: apikey con prefijo "TokenApi "
    if probar_con_header("apikey", f"TokenApi {TOKEN}", "formato documentado en ejemplo Java"):
        exit()

    # Variante 2: apikey sin prefijo, solo el token
    if probar_con_header("apikey", TOKEN, "apikey plano, sin prefijo"):
        exit()

    # Variante 3: por si acaso, Authorization con prefijo TokenApi
    if probar_con_header("Authorization", f"TokenApi {TOKEN}", "Authorization + TokenApi"):
        exit()

    print("\n\nNinguna variante funcionó todavía. Revisar la salida de cada una arriba.")