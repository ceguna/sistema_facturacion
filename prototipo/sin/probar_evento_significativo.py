"""
prototipo/sin/probar_evento_significativo.py -- v3
Corregido: se piden DOS CUFD distintos.
  - cufd_previo: el que "ya estaba vigente" cuando ocurrio el evento
    (cufdEvento en la solicitud)
  - cufd_nuevo: pedido recien ahora, especificamente para REPORTAR
    el evento (cufd en la solicitud)
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
    solicitud_cufd = {
        "codigoAmbiente": 2,
        "codigoModalidad": 1,
        "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cuis": CUIS,
        "nit": NIT,
    }
    resp = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud_cufd))
    if not resp["transaccion"]:
        raise RuntimeError(f"Error obteniendo CUFD: {resp['mensajesList']}")
    return resp["codigo"]


def main():
    client_codigos = _cliente(WSDL_CODIGOS)

    # --- 1. CUFD "previo" -- el que estaba vigente cuando "ocurrio" el evento ---
    print("[1] Pidiendo CUFD previo (simula el que estaba vigente durante la contingencia)...")
    cufd_previo = _pedir_cufd(client_codigos)
    inicio_evento = datetime.datetime.now()
    print(f"    Obtenido. Marca de inicio del evento: {inicio_evento}")

    # Esperamos unos segundos para que haya una ventana de tiempo real
    print("    Esperando 10 segundos (simulando duracion de la contingencia)...")
    time.sleep(10)
    fin_evento = datetime.datetime.now()

    # --- 2. CUFD "nuevo" -- pedido especificamente para REPORTAR el evento ---
    print("\n[2] Pidiendo CUFD nuevo (para reportar el evento, distinto del anterior)...")
    cufd_nuevo = _pedir_cufd(client_codigos)
    print(f"    Obtenido (distinto al previo: {cufd_nuevo != cufd_previo}).")

    # --- 3. Registrar el evento ---
    print("\n[3] Registrando evento significativo (codigo 1 - Corte de Internet)...")
    client_operaciones = _cliente(WSDL_OPERACIONES)
    solicitud_evento = {
        "codigoAmbiente": 2,
        "codigoMotivoEvento": 1,
        "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cufd": cufd_nuevo,        # CUFD nuevo, para el REPORTE
        "cufdEvento": cufd_previo,  # CUFD que estaba vigente DURANTE el evento
        "cuis": CUIS,
        "descripcion": "Corte de internet de prueba, ambiente Piloto - certificacion",
        "fechaHoraFinEvento": fin_evento,
        "fechaHoraInicioEvento": inicio_evento,
        "nit": NIT,
    }

    try:
        resp = client_operaciones.service.registroEventoSignificativo(
            SolicitudEventoSignificativo=solicitud_evento
        )
        print("Respuesta:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()