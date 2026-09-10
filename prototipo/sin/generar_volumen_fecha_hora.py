"""
prototipo/sin/generar_volumen_fecha_hora.py

Genera el volumen de pruebas para las 2 filas "FECHA Y HORA ACTUAL" de
la Etapa II (50 llamadas exitosas por punto de venta), usando la
operacion real sincronizarFechaHora -- confirmada 04/09/2026 (el
dashboard avanzo de 1700 a 1702 con solo 1 llamada exitosa por punto
de venta).

A diferencia de capturar_cufd_evidencia.py / probar_sincronizar_fecha_hora.py,
este script NO guarda REQUEST/RESPONSE en disco -- esos se armaron
especificamente como evidencia para el ticket del SIN, no hacen falta
para el volumen de rutina (el dashboard cuenta las llamadas exitosas
del lado del SIN, no necesita respaldo local).

Uso:
    python generar_volumen_fecha_hora.py                      # 50 x cada punto de venta
    python generar_volumen_fecha_hora.py --intentos 20         # 20 x cada punto de venta
    python generar_volumen_fecha_hora.py --solo-pv 1           # solo punto de venta 1
    python generar_volumen_fecha_hora.py --pausa 2             # 2 segundos entre llamadas
"""
import argparse
import time

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CODIGO_SUCURSAL = 0
OBJETIVO_EXITOS = 50

CUIS_POR_PUNTO_VENTA = {
    0: "31477C6C",
    1: "558F4FB7",
}

WSDL_SINCRONIZACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"


def _cliente():
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=WSDL_SINCRONIZACION, transport=Transport(session=session))


def generar_para_punto_venta(client, codigo_punto_venta, intentos, pausa):
    cuis = CUIS_POR_PUNTO_VENTA[codigo_punto_venta]
    solicitud = {
        "codigoAmbiente": 2,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cuis": cuis,
        "nit": NIT,
    }

    print(f"\n{'=' * 70}")
    print(f"Punto de venta {codigo_punto_venta} (CUIS {cuis}) -- objetivo: {OBJETIVO_EXITOS} exitosas")
    print("=" * 70)

    exitos = 0
    for intento in range(1, intentos + 1):
        if exitos >= OBJETIVO_EXITOS:
            print(f"Ya se alcanzaron {OBJETIVO_EXITOS} exitosas -- corte automático.")
            break

        try:
            resp = client.service.sincronizarFechaHora(SolicitudSincronizacion=solicitud)
            resp = serialize_object(resp)
            if resp.get("transaccion"):
                exitos += 1
                print(f"  [{intento}/{intentos}] OK ({exitos}/{OBJETIVO_EXITOS}) -- fechaHora={resp.get('fechaHora')}")
            else:
                print(f"  [{intento}/{intentos}] RECHAZADO: {resp.get('mensajesList')}")
        except Exception as e:
            print(f"  [{intento}/{intentos}] ERROR: {e}")

        if intento < intentos:
            time.sleep(pausa)

    print(f"\nPunto de venta {codigo_punto_venta}: {exitos} exitosas de {intento} intentos.")
    return exitos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intentos", type=int, default=60,
                         help="Máximo de intentos por punto de venta (default 60, con margen "
                              "sobre el objetivo de 50 por si algún intento falla).")
    parser.add_argument("--solo-pv", type=int, choices=[0, 1], default=None,
                         help="Correr solo para un punto de venta (0 o 1). Sin este flag, corre ambos.")
    parser.add_argument("--pausa", type=float, default=1.0,
                         help="Segundos de espera entre llamadas (default 1).")
    args = parser.parse_args()

    client = _cliente()

    puntos_venta = [args.solo_pv] if args.solo_pv is not None else [0, 1]
    resumen = {}
    for pv in puntos_venta:
        resumen[pv] = generar_para_punto_venta(client, pv, args.intentos, args.pausa)

    print(f"\n{'=' * 70}")
    print("RESUMEN")
    print("=" * 70)
    for pv, exitos in resumen.items():
        estado = "COMPLETO" if exitos >= OBJETIVO_EXITOS else "INCOMPLETO -- volver a correr"
        print(f"  Punto de venta {pv}: {exitos}/{OBJETIVO_EXITOS} -- {estado}")


if __name__ == "__main__":
    main()