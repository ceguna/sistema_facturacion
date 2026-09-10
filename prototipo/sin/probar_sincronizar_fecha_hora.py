"""
prototipo/sin/probar_sincronizar_fecha_hora.py

Encontrada la operacion real para las 2 filas de "FECHA Y HORA ACTUAL"
de la Etapa II: sincronizarFechaHora, del mismo WSDL de sincronizacion
de catalogos que ya usa catalogos/services.py con exito (confirmado
02/09/2026 -- mismo prefijo "sincronizar", mismo tipo de solicitud
'solicitudSincronizacion' que las otras 17 operaciones ya usadas).

FASE 1 (siempre se ejecuta, no llama a nada real): imprime la
estructura COMPLETA del tipo respuestaFechaHora -- no solo el resumen
corto de antes -- para confirmar el nombre exacto del campo de fecha
antes de escribir cualquier codigo que dependa de el.

FASE 2 (solo con --llamar): llama de verdad con datos reales (mismo
patron de credenciales que ya usa SOAPClienteSIN en
catalogos/services.py) y captura REQUEST/RESPONSE en crudo con el
HistoryPlugin de zeep, listos para el dashboard/ticket.

Uso:
    python probar_sincronizar_fecha_hora.py              # solo Fase 1
    python probar_sincronizar_fecha_hora.py --llamar      # Fase 1 + Fase 2
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
CODIGO_SUCURSAL = 0

CUIS_POR_PUNTO_VENTA = {
    0: "31477C6C",
    1: "558F4FB7",
}

WSDL_SINCRONIZACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"


def _cliente(history=None):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    plugins = [history] if history else []
    return Client(wsdl=WSDL_SINCRONIZACION, transport=Transport(session=session), plugins=plugins)


def fase1_inspeccionar():
    print("=" * 70)
    print("FASE 1 -- Estructura completa de sincronizarFechaHora")
    print("=" * 70)
    client = _cliente()

    # respuestaFechaHora es un TIPO anidado dentro de la respuesta de
    # la operacion, no un elemento independiente del namespace -- por
    # eso get_element() fallo. La forma correcta es pedirle a la firma
    # de la propia OPERACION que se expanda pasandole el schema, mismo
    # patron que ya funciono en explorar_wsdl_sincronizacion.py pero
    # con el argumento schema= para ver los campos internos, no solo
    # el nombre del tipo.
    service = list(client.wsdl.services.values())[0]
    port = list(service.ports.values())[0]
    operacion = port.binding._operations["sincronizarFechaHora"]

    print("\nEntrada completa:")
    print(operacion.input.body.type.signature(schema=client.wsdl.types))
    print("\nSalida completa:")
    print(operacion.output.body.type.signature(schema=client.wsdl.types))


def fase2_llamar_y_capturar(codigo_punto_venta):
    print("=" * 70)
    print(f"FASE 2 -- Llamando sincronizarFechaHora de verdad (punto de venta {codigo_punto_venta})")
    print("=" * 70)

    cuis = CUIS_POR_PUNTO_VENTA[codigo_punto_venta]
    history = HistoryPlugin()
    client = _cliente(history=history)

    solicitud = {
        "codigoAmbiente": 2,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cuis": cuis,
        "nit": NIT,
    }

    llamada_ok = False
    try:
        resp = client.service.sincronizarFechaHora(SolicitudSincronizacion=solicitud)
        resp = serialize_object(resp)
        print("\nRespuesta (objeto Python):")
        print(resp)
        llamada_ok = True
    except Exception as e:
        print(f"\nERROR al llamar: {e}")

    if not llamada_ok and not history._buffer:
        print("\n(No se registro ningun REQUEST/RESPONSE -- nada para guardar.)")
        return

    sufijo = f"_pv{codigo_punto_venta}"
    ultimo_envio = history.last_sent
    ultimo_recibido = history.last_received

    if ultimo_envio:
        xml_request = etree.tostring(ultimo_envio["envelope"], pretty_print=True).decode()
        with open(f"REQUEST_fecha_hora_real{sufijo}.xml", "w", encoding="utf-8") as f:
            f.write(xml_request)
        print(f"\nREQUEST guardado en REQUEST_fecha_hora_real{sufijo}.xml")

    if ultimo_recibido:
        xml_response = etree.tostring(ultimo_recibido["envelope"], pretty_print=True).decode()
        with open(f"RESPONSE_fecha_hora_real{sufijo}.xml", "w", encoding="utf-8") as f:
            f.write(xml_response)
        print(f"RESPONSE guardado en RESPONSE_fecha_hora_real{sufijo}.xml")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llamar", action="store_true",
                         help="Ademas de inspeccionar, llama de verdad a sincronizarFechaHora "
                              "para los 2 puntos de venta y captura REQUEST/RESPONSE reales.")
    args = parser.parse_args()

    fase1_inspeccionar()

    if args.llamar:
        print()
        fase2_llamar_y_capturar(codigo_punto_venta=0)
        print()
        fase2_llamar_y_capturar(codigo_punto_venta=1)
    else:
        print("\n(Solo se corrio la Fase 1. Correr de nuevo con --llamar para "
              "probarla de verdad en los 2 puntos de venta.)")


if __name__ == "__main__":
    main()