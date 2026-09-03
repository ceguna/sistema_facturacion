"""
prototipo/sin/explorar_wsdl_ncd.py

Nunca investigamos el lado tecnico de la Nota de Credito-Debito en
este proyecto -- todo lo hecho hasta ahora fue investigacion de
normativa/negocio (que es, para que sirve, requisitos de Proveedor).
Este script NO manda nada al SIN -- solo introspecciona el WSDL de
facturacion (el mismo que ya usa emitir_factura_sin/anular_factura_sin)
para descubrir el nombre real de la operacion SOAP de NCD y que campos
espera, antes de disenar o escribir codigo de emision real.

Uso:
    python explorar_wsdl_ncd.py
"""
from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"

PALABRAS_CLAVE_NCD = ['credito', 'debito', 'ajuste', 'nota']


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def explorar(nombre_wsdl, url_wsdl):
    print("=" * 70)
    print(f"WSDL: {nombre_wsdl}")
    print("=" * 70)

    client = _cliente(url_wsdl)
    service = list(client.wsdl.services.values())[0]
    port = list(service.ports.values())[0]
    operaciones = port.binding._operations

    print(f"\nOperaciones disponibles ({len(operaciones)}):")
    for op_nombre in operaciones:
        print(f"  - {op_nombre}")

    encontradas = [
        op_nombre for op_nombre in operaciones
        if any(palabra in op_nombre.lower() for palabra in PALABRAS_CLAVE_NCD)
    ]

    if not encontradas:
        print("\n(Ninguna operacion de este WSDL coincide con 'credito', "
              "'debito', 'ajuste' o 'nota'.)")
        return

    print(f"\n--- Operaciones relacionadas a NCD encontradas en {nombre_wsdl} ---")
    for op_nombre in encontradas:
        operacion = operaciones[op_nombre]
        print(f"\n>>> {op_nombre}")
        print("Estructura de entrada esperada:")
        try:
            print(operacion.input.body.type.signature())
        except Exception as e:
            print(f"  (no se pudo obtener la firma: {e})")


def main():
    explorar("ServicioFacturacionCompraVenta", WSDL_FACTURACION)
    print()
    explorar("FacturacionOperaciones", WSDL_OPERACIONES)


if __name__ == "__main__":
    main()