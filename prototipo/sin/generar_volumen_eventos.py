"""
prototipo/sin/generar_volumen_eventos.py

Genera volumen de "casos correctos" para la Etapa V (Registro de
Eventos Significativos) de la certificacion Piloto. Generalizado para
cubrir las 14 combinaciones reales que exige el dashboard: 7 motivos
de evento x 2 puntos de venta (0 y 1), 5 casos correctos cada una
(confirmado en vivo 23/08/2026 -- antes el script tenia el motivo y el
punto de venta fijos en 1/0, cubriendo solo 1 de las 14 filas).

Motivo 1 + punto de venta 0 ya esta en 5/5 desde una corrida anterior
-- este script lo intenta igual (no hace daño repetir, el SIN solo
deja de sumar una vez llegado al tope), simplemente por simplicidad de
no tener que trackear que combinaciones ya estaban resueltas antes de
esta version generalizada.

Uso:
    python generar_volumen_eventos.py [intentos_por_combinacion]

Sin argumento, intenta 8 veces por combinacion (margen sobre los 5
necesarios, para el ~15% de fallos intermitentes ya conocido -- error
966 "NO SE PUEDE RECUPERAR LOS DATOS DEL CONTRIBUYENTE"). Corta el
intento de una combinacion en cuanto llega a 5 exitosos, sin gastar
mas llamadas ahi de las necesarias.

OJO: esto tarda bastante -- 14 combinaciones, cada intento son 2 CUFD
+ 1 registro de evento + 10s de "duracion simulada del corte" + 5s de
pausa. Con la tasa de exito habitual, contar unos 25-35 minutos para
la corrida completa. No interrumpir a mitad de camino.
"""
import sys
import time
import datetime

from decouple import config
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"

# Cada punto de venta tiene su PROPIO CUIS -- nunca se reutiliza el de
# uno para el otro (confirmado con datos reales varias veces esta
# sesion: 31477C6C es el de punto de venta 0, 558F4FB7 el de punto de
# venta 1).
CUIS_POR_PUNTO_VENTA = {
    0: "31477C6C",
    1: "558F4FB7",
}

# Los 7 motivos reales del catalogo EVENTOS_SIGNIFICATIVOS ya
# sincronizado (confirmado 23/08/2026 via CatalogoSIN). La descripcion
# de cada uno es libre (campo de texto del evento puntual, no tiene
# que calzar textual con la del catalogo) -- se uso una frase acorde a
# cada motivo solo para que el log sea legible.
MOTIVOS = {
    1: "Corte de internet",
    2: "Inaccesibilidad al servicio web de Impuestos",
    3: "Ingreso a zona sin internet por despliegue de punto de venta",
    4: "Venta en lugar sin internet",
    5: "Virus informatico o falla de software",
    6: "Cambio de infraestructura o falla de hardware",
    7: "Corte de suministro de energia electrica",
}

PUNTOS_VENTA = [0, 1]

CASOS_NECESARIOS_POR_COMBINACION = 5

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"

PAUSA_DURACION_EVENTO = 10   # segundos -- duracion simulada del "corte"
PAUSA_ENTRE_ITERACIONES = 5  # segundos -- para no saturar el Piloto


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def _pedir_cufd(client_codigos, codigo_punto_venta):
    solicitud_cufd = {
        "codigoAmbiente": 2,
        "codigoModalidad": 1,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cuis": CUIS_POR_PUNTO_VENTA[codigo_punto_venta],
        "nit": NIT,
    }
    resp = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud_cufd))
    if not resp["transaccion"]:
        raise RuntimeError(f"Error obteniendo CUFD: {resp['mensajesList']}")
    return resp["codigo"]


def registrar_un_evento(client_codigos, client_operaciones, codigo_motivo, codigo_punto_venta, numero):
    print(f"\n--- Motivo {codigo_motivo} ({MOTIVOS[codigo_motivo]}) / "
          f"Punto de venta {codigo_punto_venta} -- intento {numero} ---")
    print("  Pidiendo CUFD previo (vigente durante el evento)...")
    cufd_previo = _pedir_cufd(client_codigos, codigo_punto_venta)
    inicio_evento = datetime.datetime.now()

    print(f"  Esperando {PAUSA_DURACION_EVENTO}s (duracion simulada del corte)...")
    time.sleep(PAUSA_DURACION_EVENTO)
    fin_evento = datetime.datetime.now()

    print("  Pidiendo CUFD nuevo (para reportar el evento)...")
    cufd_nuevo = _pedir_cufd(client_codigos, codigo_punto_venta)

    print(f"  Registrando evento significativo (codigo {codigo_motivo})...")
    solicitud_evento = {
        "codigoAmbiente": 2,
        "codigoMotivoEvento": codigo_motivo,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": 0,
        "cufd": cufd_nuevo,
        "cufdEvento": cufd_previo,
        "cuis": CUIS_POR_PUNTO_VENTA[codigo_punto_venta],
        "descripcion": f"{MOTIVOS[codigo_motivo]} (prueba certificacion #{numero})",
        "fechaHoraFinEvento": fin_evento,
        "fechaHoraInicioEvento": inicio_evento,
        "nit": NIT,
    }
    return serialize_object(
        client_operaciones.service.registroEventoSignificativo(
            SolicitudEventoSignificativo=solicitud_evento
        )
    )


def main():
    intentos_por_combinacion = int(sys.argv[1]) if len(sys.argv) > 1 else 8

    client_codigos = _cliente(WSDL_CODIGOS)
    client_operaciones = _cliente(WSDL_OPERACIONES)

    resumen = {}

    for codigo_punto_venta in PUNTOS_VENTA:
        for codigo_motivo in MOTIVOS:
            exitosos = 0
            fallidos = 0
            for intento in range(1, intentos_por_combinacion + 1):
                if exitosos >= CASOS_NECESARIOS_POR_COMBINACION:
                    print(f"\nMotivo {codigo_motivo} / PV {codigo_punto_venta}: ya llego a "
                          f"{CASOS_NECESARIOS_POR_COMBINACION} exitosos, se pasa a la siguiente combinacion.")
                    break
                try:
                    resp = registrar_un_evento(
                        client_codigos, client_operaciones, codigo_motivo, codigo_punto_venta, intento
                    )
                    if resp.get("transaccion"):
                        exitosos += 1
                        print(f"  OK (van {exitosos} exitosos, {fallidos} fallidos en esta combinacion)")
                    else:
                        fallidos += 1
                        print(f"  RECHAZADO: {resp.get('mensajesList')}")
                except Exception as e:
                    fallidos += 1
                    print(f"  ERROR: {e}")

                print(f"  Pausa de {PAUSA_ENTRE_ITERACIONES}s antes del siguiente...")
                time.sleep(PAUSA_ENTRE_ITERACIONES)

            resumen[(codigo_motivo, codigo_punto_venta)] = (exitosos, fallidos)

    print("\n" + "=" * 70)
    print("RESUMEN POR COMBINACION:")
    for (codigo_motivo, codigo_punto_venta), (exitosos, fallidos) in resumen.items():
        estado = "OK" if exitosos >= CASOS_NECESARIOS_POR_COMBINACION else "INCOMPLETO"
        print(f"  Motivo {codigo_motivo} ({MOTIVOS[codigo_motivo]}) / PV {codigo_punto_venta}: "
              f"{exitosos} exitosos, {fallidos} fallidos -- {estado}")


if __name__ == "__main__":
    main()