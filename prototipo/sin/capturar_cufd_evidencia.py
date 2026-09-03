"""
prototipo/sin/capturar_cufd_evidencia.py

Llama a cufd() con datos reales -- exactamente la operacion que ya
esta al 100% en la Etapa III -- y captura el REQUEST y RESPONSE en
crudo, para adjuntar al ticket del SIN sobre las 2 filas de "Fecha y
Hora" de la Etapa II. Hipotesis: esas filas usan los mismos parametros
de entrada que cufd (incluye 'cuis' como CAMPO de entrada, no como
nombre de operacion), y su resultado esperado ("FECHA Y HORA ACTUAL")
coincide con el campo fechaVigencia que cufd ya devuelve en cada
respuesta exitosa.

Uso:
    python capturar_cufd_evidencia.py
"""
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

# Cada punto de venta tiene su PROPIO CUIS -- nunca se reutiliza el de
# uno para el otro (mismo criterio de siempre esta certificacion).
CUIS_POR_PUNTO_VENTA = {
    0: "31477C6C",
    1: "558F4FB7",
}

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--punto-venta", type=int, default=0, choices=[0, 1],
                         help="Punto de venta a usar (0 o 1) -- la fila del dashboard "
                              "para 'FECHA Y HORA ACTUAL' pide especificamente 1.")
    args = parser.parse_args()
    codigo_punto_venta = args.punto_venta
    cuis = CUIS_POR_PUNTO_VENTA[codigo_punto_venta]

    history = HistoryPlugin()
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    client = Client(wsdl=WSDL_CODIGOS, transport=Transport(session=session), plugins=[history])

    solicitud = {
        "codigoAmbiente": 2,
        "codigoModalidad": 1,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cuis": cuis,
        "nit": NIT,
    }

    print(f"Llamando cufd() con datos reales (punto de venta {codigo_punto_venta})...")
    resp = client.service.cufd(SolicitudCufd=solicitud)
    resp = serialize_object(resp)
    print("\nRespuesta (objeto Python):")
    print(resp)

    if "fechaVigencia" in resp:
        print(f"\n>>> Campo 'fechaVigencia' presente en la respuesta: {resp['fechaVigencia']}")

    ultimo_envio = history.last_sent
    ultimo_recibido = history.last_received

    sufijo = f"_pv{codigo_punto_venta}"
    if ultimo_envio:
        xml_request = etree.tostring(ultimo_envio["envelope"], pretty_print=True).decode()
        with open(f"REQUEST_cufd_evidencia{sufijo}.xml", "w", encoding="utf-8") as f:
            f.write(xml_request)
        print(f"\nREQUEST guardado en REQUEST_cufd_evidencia{sufijo}.xml")

    if ultimo_recibido:
        xml_response = etree.tostring(ultimo_recibido["envelope"], pretty_print=True).decode()
        with open(f"RESPONSE_cufd_evidencia{sufijo}.xml", "w", encoding="utf-8") as f:
            f.write(xml_response)
        print(f"RESPONSE guardado en RESPONSE_cufd_evidencia{sufijo}.xml")


if __name__ == "__main__":
    main()