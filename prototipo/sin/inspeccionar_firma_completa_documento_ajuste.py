"""
prototipo/sin/inspeccionar_firma_completa_documento_ajuste.py

Script de DIAGNOSTICO -- SOLO LECTURA, igual que
inspeccionar_wsdl_documento_ajuste.py (no envia ninguna transaccion al
SIN, solo baja el WSDL/XSD y los parsea localmente). Amplia ese script
para imprimir la firma COMPLETA (cada campo, recursivo) de las
operaciones que ese primer listado solo mostraba por el nombre de su
tipo complejo, sin desglosar -- necesario para construir
anular_nota_credito_debito_sin() sin adivinar nombres de campo contra
un servicio real del SIN.

Uso:
    python inspeccionar_firma_completa_documento_ajuste.py
"""
from decouple import config
from zeep import Client
from zeep.transports import Transport
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
WSDL_DOCUMENTO_AJUSTE = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionDocumentoAjuste?wsdl"

OPERACIONES_A_DESGLOSAR = [
    "anulacionDocumentoAjuste",
    "reversionAnulacionDocumentoAjuste",
    "verificacionEstadoDocumentoAjuste",
]


def desglosar_elemento(elemento, prefijo="", visitados=None):
    if visitados is None:
        visitados = set()
    tipo = elemento.type
    nombre_tipo = getattr(tipo, "name", None) or type(tipo).__name__

    if hasattr(tipo, "elements") and nombre_tipo not in visitados:
        visitados = visitados | {nombre_tipo}
        for sub_nombre, sub_elemento in tipo.elements:
            ocurrencia = ""
            if getattr(sub_elemento, "max_occurs", 1) not in (1, None):
                ocurrencia = f" (max_occurs={sub_elemento.max_occurs})"
            print(f"{prefijo}{sub_nombre}: {sub_elemento.type}{ocurrencia}")
            if hasattr(sub_elemento.type, "elements"):
                desglosar_elemento(sub_elemento, prefijo=prefijo + "    ", visitados=visitados)
    else:
        print(f"{prefijo}(tipo simple: {nombre_tipo})")


def main():
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    transport = Transport(session=session, timeout=15, operation_timeout=45)

    print(f"Descargando WSDL desde: {WSDL_DOCUMENTO_AJUSTE}\n")
    client = Client(wsdl=WSDL_DOCUMENTO_AJUSTE, transport=transport)

    for service in client.wsdl.services.values():
        for port in service.ports.values():
            operaciones = {op.name: op for op in port.binding._operations.values()}
            for nombre_op in OPERACIONES_A_DESGLOSAR:
                operacion = operaciones.get(nombre_op)
                if not operacion:
                    print(f"\n(operacion '{nombre_op}' no encontrada en este puerto)")
                    continue
                print("\n" + "=" * 70)
                print(f"Operacion: {nombre_op}")
                print("=" * 70)
                try:
                    partes = operacion.input.body.type.elements
                    for nombre_parte, elemento_parte in partes:
                        print(f"{nombre_parte}: {elemento_parte.type}")
                        desglosar_elemento(elemento_parte, prefijo="  ")
                except Exception as e:
                    print(f"  (no se pudo desglosar: {e})")
                    try:
                        print(f"  Firma resumida: {operacion.input.signature()}")
                    except Exception as e2:
                        print(f"  (tampoco se pudo leer la firma resumida: {e2})")

    print("\n" + "=" * 70)
    print("Fin del desglose -- no se envio ninguna transaccion al SIN.")
    print("=" * 70)


if __name__ == "__main__":
    main()
