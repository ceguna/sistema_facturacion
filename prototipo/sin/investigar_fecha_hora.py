"""
prototipo/sin/investigar_fecha_hora.py

Investiga las 2 filas "Fecha y Hora" pendientes de la Etapa II, con
una sospecha concreta: el nombre del resultado esperado
("FECHA Y HORA ACTUAL") encaja mucho mas con una operacion de
verificacion de comunicacion (un "ping" que devuelve la hora del
servidor) que con 'cuis' -- que es la operacion que GENERA la
credencial de sucursal, ya certificada al 100% en la Etapa I. Llamar
a cuis() de nuevo solo para conseguir un ejemplo tiene riesgo real
(podria reemplazar o invalidar el CUIS actual); verificarComunicacion
esta pensada justamente para llamarse repetidas veces sin efecto
secundario.

DOS FASES, para no arriesgar nada sin confirmar antes:

  FASE 1 (siempre se ejecuta, no llama a nada real): imprime la firma
  de entrada/salida de verificarComunicacion en los dos WSDL. Mira
  vos mismo si los parametros coinciden con lo que ya viste en el
  dashboard antes de seguir.

  FASE 2 (solo si confirmas con --llamar): llama de verdad a
  verificarComunicacion con datos reales, y usa el HistoryPlugin de
  zeep para capturar el REQUEST y el RESPONSE en crudo -- exactamente
  lo que pide el soporte del SIN. Se guardan en dos archivos de texto
  listos para copiar y pegar en el ticket.

Uso:
    python investigar_fecha_hora.py              # solo Fase 1 (segura, no llama nada)
    python investigar_fecha_hora.py --llamar      # Fase 1 + Fase 2 (llama de verdad)
"""
import argparse

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
from zeep.helpers import serialize_object
from lxml import etree
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CUIS = "31477C6C"  # sucursal 0 -- el mismo CUIS de siempre, NUNCA se pide uno nuevo aca
CODIGO_SUCURSAL = 0
CODIGO_PUNTO_VENTA = 0

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"


def _cliente(wsdl, history=None):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    plugins = [history] if history else []
    return Client(wsdl=wsdl, transport=Transport(session=session), plugins=plugins)


def fase1_inspeccionar(nombre_wsdl, url_wsdl):
    print("=" * 70)
    print(f"FASE 1 -- Inspeccionando verificarComunicacion en {nombre_wsdl}")
    print("=" * 70)
    client = _cliente(url_wsdl)

    if "verificarComunicacion" not in dir(client.service):
        print("(Esta operacion no existe en este WSDL.)\n")
        return

    service = list(client.wsdl.services.values())[0]
    port = list(service.ports.values())[0]
    operacion = port.binding._operations["verificarComunicacion"]

    print("\nEntrada esperada:")
    print(operacion.input.body.type.signature())
    print("\nSalida esperada:")
    print(operacion.output.body.type.signature())
    print()


def fase2_llamar_y_capturar(url_wsdl, nombre_wsdl):
    print("=" * 70)
    print(f"FASE 2 -- Llamando verificarComunicacion de verdad en {nombre_wsdl}")
    print("=" * 70)

    history = HistoryPlugin()
    client = _cliente(url_wsdl, history=history)

    # Confirmado en la Fase 1: verificarComunicacion() no recibe NINGUN
    # parametro -- ni siquiera credenciales. Coincide con lo esperable
    # de un "ping" de verificacion de comunicacion.
    llamada_ok = False
    try:
        resp = client.service.verificarComunicacion()
        print("\nRespuesta (objeto Python):")
        print(serialize_object(resp))
        llamada_ok = True
    except Exception as e:
        print(f"\nERROR al llamar: {e}")

    if not llamada_ok and not history._buffer:
        print("\n(No se registro ningun REQUEST/RESPONSE -- la llamada nunca "
              "llego a salir. Nada para guardar.)")
        return

    ultimo_envio = history.last_sent
    ultimo_recibido = history.last_received

    if ultimo_envio:
        xml_request = etree.tostring(ultimo_envio["envelope"], pretty_print=True).decode()
        with open("REQUEST_fecha_hora.xml", "w", encoding="utf-8") as f:
            f.write(xml_request)
        print("\nREQUEST guardado en REQUEST_fecha_hora.xml")

    if ultimo_recibido:
        xml_response = etree.tostring(ultimo_recibido["envelope"], pretty_print=True).decode()
        with open("RESPONSE_fecha_hora.xml", "w", encoding="utf-8") as f:
            f.write(xml_response)
        print("RESPONSE guardado en RESPONSE_fecha_hora.xml")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llamar", action="store_true",
                         help="Ademas de inspeccionar, llama de verdad a verificarComunicacion "
                              "y captura REQUEST/RESPONSE reales. Sin este flag, solo inspecciona.")
    args = parser.parse_args()

    fase1_inspeccionar("FacturacionCodigos", WSDL_CODIGOS)
    fase1_inspeccionar("FacturacionOperaciones", WSDL_OPERACIONES)

    if args.llamar:
        print("\n¿Los parametros de arriba coinciden con lo que viste en el dashboard?")
        print("Si no, edita 'solicitud' en fase2_llamar_y_capturar() antes de continuar.\n")
        fase2_llamar_y_capturar(WSDL_CODIGOS, "FacturacionCodigos")
    else:
        print("\n(Solo se corrio la Fase 1 -- no se llamo a nada real. "
              "Correr de nuevo con --llamar cuando confirmes que los parametros calzan.)")


if __name__ == "__main__":
    main()