"""
prototipo/sin/validar_paquete_factura.py

Consulta el estado final de un paquete enviado (pasa de PENDIENTE a
VALIDADA u OBSERVADA una vez que el SIN termina de procesar cada
factura dentro del paquete).
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

# Datos del paquete que ya enviamos
CODIGO_RECEPCION = "b9fb9091-8f6b-11f1-9529-99195bea1679"
CUFD_USADO = "VBQUFBQnhjLkRBE5MzFCNjI1ODY=QsKhUUZ2T0VJYVMzczQTBFQTBGQk"

WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"


def main():
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    client = Client(wsdl=WSDL_FACTURACION, transport=Transport(session=session))

    solicitud = {
        "codigoAmbiente": 2,
        "codigoDocumentoSector": 1,
        "codigoEmision": 2,
        "codigoModalidad": 1,
        "codigoPuntoVenta": 0,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cufd": CUFD_USADO,
        "cuis": CUIS,
        "nit": NIT,
        "tipoFacturaDocumento": 1,
        "codigoRecepcion": CODIGO_RECEPCION,
    }

    try:
        resp = client.service.validacionRecepcionPaqueteFactura(
            SolicitudServicioValidacionRecepcionPaquete=solicitud
        )
        print("Respuesta:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()