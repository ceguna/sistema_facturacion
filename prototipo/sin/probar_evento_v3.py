"""
prototipo/sin/probar_evento_v3.py

Verifica si el error 981 (rango de fechas invalido) del intento
anterior se debio a demoras de tipeo en la consola interactiva, o a
un problema real -- corriendo todo de una sola vez, sin intervencion
manual entre pasos.
"""
import time
import datetime

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CUIS = "31477C6C"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def _pedir_cufd(client_codigos):
    solicitud = {
        "codigoAmbiente": 2, "codigoModalidad": 1, "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA, "codigoSucursal": 0, "cuis": CUIS, "nit": NIT,
    }
    resp = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud))
    if not resp["transaccion"]:
        raise RuntimeError(f"Error CUFD: {resp['mensajesList']}")
    return resp["codigo"]


def main():
    client_codigos = _cliente(WSDL_CODIGOS)
    client_operaciones = _cliente(WSDL_OPERACIONES)

    print("Pidiendo CUFD previo (simula el vigente durante el evento)...")
    cufd_previo = _pedir_cufd(client_codigos)
    inicio_evento = datetime.datetime.now()
    print(f"    Obtenido a las {inicio_evento}")

    print("Esperando 10 segundos...")
    time.sleep(10)
    fin_evento = datetime.datetime.now()
    print(f"    Fin evento: {fin_evento}")

    print("Pidiendo CUFD nuevo (para reportar el evento)...")
    cufd_nuevo = _pedir_cufd(client_codigos)
    print(f"    Obtenido a las {datetime.datetime.now()}")

    print("Registrando evento significativo (codigo 1 - Corte de Internet)...")
    solicitud_evento = {
        "codigoAmbiente": 2, "codigoMotivoEvento": 1, "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA, "codigoSucursal": 0,
        "cufd": cufd_nuevo, "cufdEvento": cufd_previo, "cuis": CUIS,
        "descripcion": "Corte de internet de prueba - verificacion de cupo diario",
        "fechaHoraFinEvento": fin_evento, "fechaHoraInicioEvento": inicio_evento, "nit": NIT,
    }
    resp = client_operaciones.service.registroEventoSignificativo(
        SolicitudEventoSignificativo=solicitud_evento
    )
    print("\nResultado:")
    print(serialize_object(resp))


if __name__ == "__main__":
    main()