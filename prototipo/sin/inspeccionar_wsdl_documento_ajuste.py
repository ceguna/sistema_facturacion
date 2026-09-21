"""
prototipo/sin/inspeccionar_wsdl_documento_ajuste.py

Script de DIAGNOSTICO -- SOLO LECTURA. Descarga y lista las operaciones
disponibles en el WSDL de Nota de Credito-Debito
(ServicioFacturacionDocumentoAjuste), confirmado el 12/09/2026 en el PDF
"Solicitud de Autorizacion de Sistema Informatico de Facturacion" como
el endpoint CORRECTO para NCD (distinto de ServicioFacturacionCompraVenta,
que se venia usando por error hasta ahora).

NO envia ninguna transaccion real al SIN -- solo baja el WSDL y lo
parsea localmente, exactamente lo mismo que ya hace Client(...) al
arrancar cualquiera de los otros scripts de esta carpeta.

Uso:
    python inspeccionar_wsdl_documento_ajuste.py
"""
from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
WSDL_DOCUMENTO_AJUSTE = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionDocumentoAjuste?wsdl"


def main():
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    transport = Transport(session=session, timeout=15, operation_timeout=45)

    print(f"Descargando WSDL desde: {WSDL_DOCUMENTO_AJUSTE}\n")
    client = Client(wsdl=WSDL_DOCUMENTO_AJUSTE, transport=transport)

    print("=" * 70)
    print("OPERACIONES DISPONIBLES EN ServicioFacturacionDocumentoAjuste")
    print("=" * 70)

    for service in client.wsdl.services.values():
        for port in service.ports.values():
            operaciones = sorted(
                port.binding._operations.values(),
                key=lambda operacion: operacion.name
            )
            for operacion in operaciones:
                print(f"\nOperacion: {operacion.name}")
                try:
                    print(f"  Entrada esperada: {operacion.input.signature()}")
                except Exception as e:
                    print(f"  (no se pudo leer la firma de entrada: {e})")

    print("\n" + "=" * 70)
    print("Fin del listado -- no se envio ninguna transaccion al SIN.")
    print("=" * 70)


if __name__ == "__main__":
    main()