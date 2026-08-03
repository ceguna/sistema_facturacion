"""
prototipo/sin/probar_anulacion.py

Etapa VII: anula la primera factura VALIDADA que ya emitimos
(la del 02/08/2026, codigoRecepcion a3d0a836-8ec8-11f1-a745-adb8279ff5dd),
usando el codigo de motivo real del catalogo sincronizado.
"""

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
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"

# CUF de la primera factura VALIDADA (02/08/2026, codigoRecepcion a3d0a836...)
CUF_A_ANULAR = "1079F647BEC1A17B1C51B5825E83B54E811F19E06A90E1F7C6D971BF74"
CODIGO_MOTIVO = 1  # FACTURA MAL EMITIDA


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def main():
    print("[1] Pidiendo CUFD fresco...")
    client_codigos = _cliente(WSDL_CODIGOS)
    solicitud_cufd = {
        "codigoAmbiente": 2,
        "codigoModalidad": 1,
        "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cuis": CUIS,
        "nit": NIT,
    }
    resp_cufd = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud_cufd))
    if not resp_cufd["transaccion"]:
        print("ERROR obteniendo CUFD:", resp_cufd["mensajesList"])
        return
    cufd = resp_cufd["codigo"]
    print(f"    CUFD obtenido.")

    print(f"\n[2] Anulando factura (CUF: {CUF_A_ANULAR[:20]}..., motivo: FACTURA MAL EMITIDA)...")
    client_facturacion = _cliente(WSDL_FACTURACION)
    solicitud_anulacion = {
        "codigoAmbiente": 2,
        "codigoDocumentoSector": 1,
        "codigoEmision": 1,
        "codigoModalidad": 1,
        "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cufd": cufd,
        "cuis": CUIS,
        "nit": NIT,
        "tipoFacturaDocumento": 1,
        "codigoMotivo": CODIGO_MOTIVO,
        "cuf": CUF_A_ANULAR,
    }

    try:
        resp = client_facturacion.service.anulacionFactura(SolicitudServicioAnulacionFactura=solicitud_anulacion)
        print("Respuesta:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()