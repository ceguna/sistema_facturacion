"""
prototipo/sin/explorar_wsdl_sincronizacion.py

El soporte del SIN confirmo que las 2 filas de "FECHA Y HORA ACTUAL"
de la Etapa II corresponden al MUNDO de sincronizacion de catalogos
(no a cufd, que fue una hipotesis equivocada -- ver conversacion del
02/09/2026). Este script NO llama a nada real -- solo lee la
definicion del WSDL de sincronizacion (el mismo que ya usa
catalogos/services.py con exito para 1700/1800 casos) y compara la
lista completa de operaciones contra las 17 que ya se usan, para
resaltar cualquier operacion NUEVA que el WSDL ofrezca y que todavia
no se este consumiendo -- esa es la candidata fuerte para las 2 filas
pendientes.

Uso:
    python explorar_wsdl_sincronizacion.py
"""
from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
WSDL_SINCRONIZACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"

# Las 17 operaciones que catalogos/services.py (MAPEO_CATALOGOS) ya usa
# con exito hoy -- confirmado 1700/1800 en el dashboard.
OPERACIONES_YA_USADAS = {
    "sincronizarActividades",
    "sincronizarListaActividadesDocumentoSector",
    "sincronizarListaLeyendasFactura",
    "sincronizarListaMensajesServicios",
    "sincronizarParametricaEventosSignificativos",
    "sincronizarParametricaMotivoAnulacion",
    "sincronizarParametricaPaisOrigen",
    "sincronizarParametricaTipoDocumentoIdentidad",
    "sincronizarParametricaTipoDocumentoSector",
    "sincronizarParametricaTipoEmision",
    "sincronizarParametricaTipoHabitacion",
    "sincronizarParametricaTipoMetodoPago",
    "sincronizarParametricaTipoMoneda",
    "sincronizarParametricaTipoPuntoVenta",
    "sincronizarParametricaTiposFactura",
    "sincronizarParametricaUnidadMedida",
    "sincronizarListaProductosServicios",
}

PALABRAS_CLAVE_FECHA_HORA = ['fecha', 'hora', 'hor', 'tiempo', 'reloj']


def _cliente():
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=WSDL_SINCRONIZACION, transport=Transport(session=session))


def main():
    print("=" * 70)
    print("WSDL: FacturacionSincronizacion")
    print("=" * 70)

    client = _cliente()
    service = list(client.wsdl.services.values())[0]
    port = list(service.ports.values())[0]
    operaciones = port.binding._operations

    print(f"\nTotal de operaciones en el WSDL: {len(operaciones)}")
    print(f"Ya usadas por catalogos/services.py: {len(OPERACIONES_YA_USADAS)}")

    nuevas = sorted(set(operaciones.keys()) - OPERACIONES_YA_USADAS)

    print(f"\n{'=' * 70}")
    if not nuevas:
        print("(Ninguna operacion nueva -- el WSDL solo tiene las 17 ya conocidas. "
              "Si es asi, el problema no es una operacion faltante y hay que "
              "reconsiderar la hipotesis desde cero.)")
    else:
        print(f"OPERACIONES DEL WSDL QUE TODAVIA NO SE USAN ({len(nuevas)}):")
        print("=" * 70)
        for op_nombre in nuevas:
            print(f"\n>>> {op_nombre}")
            operacion = operaciones[op_nombre]
            print("Entrada esperada:")
            try:
                print(operacion.input.body.type.signature())
            except Exception as e:
                print(f"  (no se pudo obtener la firma: {e})")
            print("Salida esperada:")
            try:
                print(operacion.output.body.type.signature())
            except Exception as e:
                print(f"  (no se pudo obtener la firma: {e})")

        candidatas = [
            op for op in nuevas
            if any(palabra in op.lower() for palabra in PALABRAS_CLAVE_FECHA_HORA)
        ]
        if candidatas:
            print(f"\n{'=' * 70}")
            print("CANDIDATAS FUERTES (nombre relacionado a fecha/hora):")
            print("=" * 70)
            for c in candidatas:
                print(f"  - {c}")


if __name__ == "__main__":
    main()