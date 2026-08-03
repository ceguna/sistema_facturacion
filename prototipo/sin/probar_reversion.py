"""
prototipo/sin/probar_reversion.py

Etapa VIII: revierte la anulacion de la factura numero 400
(la misma que emitimos y anulamos en la prueba de la Etapa VII,
todo en la misma sesion de hoy).
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

# CUF de la factura 400, emitida y anulada hoy (03/08/2026)
CUF_A_REVERTIR = "1079F647BEC1A17E1A63B50532BDFFBC0EA9DFEDA0759C27E47D71BF74"


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

    print(f"\n[2] Revirtiendo anulacion (CUF: {CUF_A_REVERTIR[:20]}...)...")
    client_facturacion = _cliente(WSDL_FACTURACION)
    solicitud_reversion = {
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
        "cuf": CUF_A_REVERTIR,
    }

    try:
        resp = client_facturacion.service.reversionAnulacionFactura(
            SolicitudServicioReversionAnulacionFactura=solicitud_reversion
        )
        print("Respuesta:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()