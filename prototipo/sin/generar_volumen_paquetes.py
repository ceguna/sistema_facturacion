"""
prototipo/sin/generar_volumen_paquetes.py

Generador completo para la Etapa VI (envio y validacion de paquetes de
facturas) de la certificacion Piloto. Cubre las 16 filas reales del
dashboard (confirmado 23/08/2026):

  - Filas 1-14: recepcionPaqueteFactura, 7 motivos de evento x 2 puntos
    de venta, 10 casos correctos cada una.
      * Punto de venta 1: exige cantidadFacturas = 500 EXACTO (dato
        literal del dashboard).
      * Punto de venta 0: exige cantidadFacturas < 500 (se usa un
        paquete chico, 3 facturas, para no cargar de mas sin necesidad).
  - Filas 15-16: validacionRecepcionPaqueteFactura, una por punto de
    venta, 70 casos correctos cada una. cantidadFacturas "no aplica"
    para estas filas -- se valida el MISMO codigoRecepcion que ya
    devolvio cada envio exitoso de las filas 1-14, sin generar
    paquetes nuevos aparte. Como cada punto de venta necesita
    exactamente 70 envios exitosos en las filas 1-14 (7 motivos x 10),
    y las filas 15/16 tambien piden 70 cada una, un envio exitoso +
    su validacion inmediata cubren las dos certificaciones a la vez.

OJO -- ESCALA REAL: un paquete de punto de venta 1 significa firmar y
validar 500 facturas EN LOCAL antes de enviarlas. Sin llamadas de red
por cada una, pero con costo real de computo: calcular unos 2-4
minutos solo para firmar, mas el envio en si. Con hasta 7 motivos x
varios intentos cada uno, la parte de punto de venta 1 puede llevar
VARIAS HORAS en total. El lado de punto de venta 0 es mucho mas
liviano y rapido.

RECOMENDADO: correr primero con --solo-pv 0 (rapido) para confirmar
que todo el mecanismo funciona de punta a punta, y recien despues
--solo-pv 1 por separado, sabiendo que va a tardar mucho mas.

Uso:
    python generar_volumen_paquetes.py --solo-pv 0 --intentos 3   # prueba chica, liviana
    python generar_volumen_paquetes.py --solo-pv 0 --intentos 15  # pv=0 completo
    python generar_volumen_paquetes.py --solo-pv 1 --intentos 2   # prueba chica de pv=1 (igual tarda varios minutos)
    python generar_volumen_paquetes.py --solo-pv 1 --intentos 15  # pv=1 completo -- HORAS
"""
import argparse
import datetime
import gzip
import hashlib
import io
import tarfile
import time

from decouple import config
from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods
from signxml.algorithms import CanonicalizationMethod
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

from factura_xml import construir_factura_xml
from cuf import calcular_cuf

TOKEN = config("SIN_TOKEN_DELEGADO")
NIT = 3852849010
CODIGO_SISTEMA = "373A0EA0FBA931B62586"
CODIGO_SUCURSAL = 0
CODIGO_MODALIDAD = 1
CODIGO_EMISION_OFFLINE = 2
CODIGO_DOCUMENTO_SECTOR = 1
TIPO_FACTURA_DOCUMENTO = 1

# Cada punto de venta tiene su PROPIO CUIS (mismo principio de siempre
# esta sesion: nunca reutilizar el de uno para el otro).
CUIS_POR_PUNTO_VENTA = {
    0: "31477C6C",
    1: "558F4FB7",
}

# cantidadFacturas exigida por el dashboard, por punto de venta.
CANTIDAD_FACTURAS_POR_PUNTO_VENTA = {
    0: 3,     # "menor a 500"
    1: 500,   # "igual a 500" -- literal
}

MOTIVOS = {
    1: "Corte de internet",
    2: "Inaccesibilidad al servicio web de Impuestos",
    3: "Ingreso a zona sin internet por despliegue de punto de venta",
    4: "Venta en lugar sin internet",
    5: "Virus informatico o falla de software",
    6: "Cambio de infraestructura o falla de hardware",
    7: "Corte de suministro de energia electrica",
}

CASOS_ENVIO_NECESARIOS = 10        # por combinacion motivo x punto de venta (filas 1-14)
CASOS_VALIDACION_NECESARIOS = 70   # por punto de venta (filas 15-16)

ARCHIVO_LLAVE = "certificado_real/clave_privada_real.pem"
ARCHIVO_CERT = "certificado_real/certificado_real.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"

PAUSA_DURACION_EVENTO = 10
PAUSA_ENTRE_INTENTOS = 5
PAUSA_ANTES_DE_VALIDAR = 5
# Un paquete de 500 facturas es un payload mucho mas grande que una
# factura sola -- mas margen que el resto del sistema (que usa 45s).
TIMEOUT_OPERACION_PAQUETE = 120

_contador_numero_factura = [900000]  # numeracion alta a proposito, para no chocar con facturas reales


def _siguiente_numero_factura():
    _contador_numero_factura[0] += 1
    return _contador_numero_factura[0]


def _cliente(wsdl, timeout_operacion=45):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    transport = Transport(session=session, timeout=15, operation_timeout=timeout_operacion)
    return Client(wsdl=wsdl, transport=transport)


def _pedir_cufd(client_codigos, codigo_punto_venta):
    solicitud = {
        "codigoAmbiente": 2,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cuis": CUIS_POR_PUNTO_VENTA[codigo_punto_venta],
        "nit": NIT,
    }
    resp = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud))
    if not resp["transaccion"]:
        raise RuntimeError(f"Error CUFD: {resp['mensajesList']}")
    return resp["codigo"], resp["codigoControl"]


def _armar_y_firmar_factura(numero_factura, fecha_hora, codigo_control, cufd,
                             codigo_punto_venta, llave, cert, schema):
    """
    llave/cert/schema se cargan UNA SOLA VEZ en main() y se pasan aca --
    releerlos de disco y reconstruir el validador XSD en cada llamada
    (como hacia el script original de 2 facturas) es innecesario y, a
    escala de 500 facturas por paquete, suma un costo evitable.
    """
    cuf = calcular_cuf(
        nit=NIT, fecha_hora=fecha_hora, codigo_sucursal=CODIGO_SUCURSAL,
        codigo_modalidad=CODIGO_MODALIDAD, codigo_tipo_emision=CODIGO_EMISION_OFFLINE,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO, codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=numero_factura, codigo_punto_venta=codigo_punto_venta,
        codigo_control=codigo_control,
    )
    cabecera = {
        "nitEmisor": str(NIT), "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra", "numeroFactura": numero_factura,
        "cuf": cuf, "cufd": cufd, "codigoSucursal": CODIGO_SUCURSAL,
        "direccion": "Calle San Nicolas Este Nro 30", "codigoPuntoVenta": codigo_punto_venta,
        "fechaEmision": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "codigoTipoDocumentoIdentidad": 1, "numeroDocumento": "1234567", "codigoCliente": "1",
        "codigoMetodoPago": 1, "montoTotal": 100.00, "montoTotalSujetoIva": 100.00,
        "codigoMoneda": 1, "tipoCambio": 1, "montoTotalMoneda": 100.00, "descuentoAdicional": 0,
        "leyenda": "Ley N 453: Tienes derecho a recibir informacion sobre las "
                   "caracteristicas y contenidos de los servicios que utilices.",
        "usuario": "pruebas", "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
    }
    detalle = [{
        "actividadEconomica": "4761300", "codigoProductoSin": "1003646", "codigoProducto": "ART-001",
        "descripcion": "Cuaderno universitario 100 hojas", "cantidad": 2, "unidadMedida": 1,
        "precioUnitario": 50.00, "subTotal": 100.00,
    }]
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)

    signer = XMLSigner(
        method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256",
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0_WITH_COMMENTS,
    )
    xml_firmado = signer.sign(xml_sin_firmar, key=llave, cert=cert)
    xml_bytes = etree.tostring(xml_firmado)
    if not schema.validate(etree.fromstring(xml_bytes)):
        raise RuntimeError(f"Factura {numero_factura} invalida: {schema.error_log}")
    return xml_bytes


def intentar_un_paquete(client_codigos, client_operaciones, client_facturacion,
                         codigo_motivo, codigo_punto_venta, intento, llave, cert, schema):
    cantidad_facturas = CANTIDAD_FACTURAS_POR_PUNTO_VENTA[codigo_punto_venta]
    cuis = CUIS_POR_PUNTO_VENTA[codigo_punto_venta]

    print(f"\n--- Motivo {codigo_motivo} ({MOTIVOS[codigo_motivo]}) / PV {codigo_punto_venta} "
          f"({cantidad_facturas} facturas) -- intento {intento} ---")

    print("  [1] CUFD del evento...")
    cufd_evento, codigo_control = _pedir_cufd(client_codigos, codigo_punto_venta)
    inicio_evento = datetime.datetime.now()

    print(f"  [2] Esperando {PAUSA_DURACION_EVENTO}s...")
    time.sleep(PAUSA_DURACION_EVENTO)

    print(f"  [3] Firmando {cantidad_facturas} factura(s)...")
    t0 = time.time()
    facturas_xml = []
    for _ in range(cantidad_facturas):
        numero = _siguiente_numero_factura()
        fecha_factura = datetime.datetime.now()
        xml_bytes = _armar_y_firmar_factura(
            numero, fecha_factura, codigo_control, cufd_evento, codigo_punto_venta, llave, cert, schema
        )
        facturas_xml.append((f"factura_{numero}.xml", xml_bytes))
    print(f"      {cantidad_facturas} facturas firmadas en {time.time() - t0:.1f}s.")
    fin_evento = datetime.datetime.now()

    print("  [4] CUFD nuevo para reportar el evento...")
    cufd_reporte, _ = _pedir_cufd(client_codigos, codigo_punto_venta)

    print("  [5] Registrando el evento significativo...")
    solicitud_evento = {
        "codigoAmbiente": 2, "codigoMotivoEvento": codigo_motivo,
        "codigoPuntoVenta": codigo_punto_venta, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd_reporte, "cufdEvento": cufd_evento,
        "cuis": cuis, "descripcion": f"{MOTIVOS[codigo_motivo]} (paquete cert. #{intento})",
        "fechaHoraFinEvento": fin_evento, "fechaHoraInicioEvento": inicio_evento, "nit": NIT,
    }
    try:
        resp_evento = serialize_object(client_operaciones.service.registroEventoSignificativo(
            SolicitudEventoSignificativo=solicitud_evento
        ))
    except Exception as e:
        return {"envio_ok": False, "motivo_falla": f"error de red en evento: {e}"}
    if not resp_evento.get("transaccion"):
        return {"envio_ok": False, "motivo_falla": f"evento rechazado: {resp_evento.get('mensajesList')}"}
    codigo_evento = resp_evento["codigoRecepcionEventoSignificativo"]

    print("  [6] Empaquetando en TAR+GZIP...")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for nombre, contenido in facturas_xml:
            info = tarfile.TarInfo(name=nombre)
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))
    tar_gzip = gzip.compress(tar_buffer.getvalue())
    hash_archivo = hashlib.sha256(tar_gzip).hexdigest().upper()
    print(f"      Empaquetado: {len(tar_gzip)} bytes.")

    print("  [7] Enviando el paquete...")
    solicitud_paquete = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION_OFFLINE, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd_evento, "cuis": cuis, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO, "archivo": tar_gzip,
        "fechaEnvio": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo, "cantidadFacturas": cantidad_facturas,
        "codigoEvento": codigo_evento,
        # cafc NO se manda -- se probo con "" (string vacio) y el SIN
        # empezo a rechazar con "Cafc no encontrado" despues de varios
        # envios exitosos (motivo 5 en adelante, 23/08/2026). El
        # mensaje sugiere que intenta BUSCAR un cafc real, no que
        # rechaza un campo vacio -- omitir el campo del todo es la
        # forma mas limpia de decir "no aplica" y la primera hipotesis
        # a descartar antes de asumir que es degradacion del SIN.
    }
    try:
        resp_paquete = serialize_object(client_facturacion.service.recepcionPaqueteFactura(
            SolicitudServicioRecepcionPaquete=solicitud_paquete
        ))
    except Exception as e:
        return {"envio_ok": False, "motivo_falla": f"error de red en envio: {e}"}
    if not resp_paquete.get("transaccion"):
        return {"envio_ok": False, "motivo_falla": f"paquete rechazado: {resp_paquete.get('mensajesList')}"}

    codigo_recepcion = resp_paquete["codigoRecepcion"]
    print(f"      Enviado OK. codigoRecepcion: {codigo_recepcion}")

    print(f"  [8] Esperando {PAUSA_ANTES_DE_VALIDAR}s antes de validar...")
    time.sleep(PAUSA_ANTES_DE_VALIDAR)
    solicitud_validacion = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION_OFFLINE, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd_evento, "cuis": cuis, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO, "codigoRecepcion": codigo_recepcion,
    }
    try:
        resp_validacion = serialize_object(client_facturacion.service.validacionRecepcionPaqueteFactura(
            SolicitudServicioValidacionRecepcionPaquete=solicitud_validacion
        ))
        validacion_ok = bool(resp_validacion.get("transaccion"))
        print("      Validacion OK." if validacion_ok else
              f"      Validacion RECHAZADA: {resp_validacion.get('mensajesList')}")
    except Exception as e:
        validacion_ok = False
        print(f"      ERROR en validacion: {e}")

    return {"envio_ok": True, "validacion_ok": validacion_ok, "codigo_recepcion": codigo_recepcion}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intentos", type=int, default=3,
                         help="Intentos maximos por combinacion motivo x punto de venta (default 3, EMPEZAR CHICO).")
    parser.add_argument("--solo-pv", type=int, default=None, choices=[0, 1],
                         help="Correr solo un punto de venta (0 = liviano, 1 = 500 facturas). "
                              "Por defecto corre los dos -- NO RECOMENDADO sin probar antes por separado.")
    parser.add_argument("--solo-motivo", type=int, default=None, choices=list(MOTIVOS.keys()),
                         help="Correr solo un motivo especifico (1-7), para cerrar un caso puntual "
                              "sin repetir combinaciones que ya llegaron a su tope.")
    args = parser.parse_args()

    puntos_venta = [args.solo_pv] if args.solo_pv is not None else [0, 1]
    motivos_a_correr = {args.solo_motivo: MOTIVOS[args.solo_motivo]} if args.solo_motivo is not None else MOTIVOS

    print("Cargando llave, certificado y XSD (una sola vez)...")
    with open(ARCHIVO_LLAVE, "rb") as f:
        llave = f.read()
    with open(ARCHIVO_CERT, "rb") as f:
        cert = f.read()
    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)

    client_codigos = _cliente(WSDL_CODIGOS)
    client_operaciones = _cliente(WSDL_OPERACIONES)
    client_facturacion = _cliente(WSDL_FACTURACION, timeout_operacion=TIMEOUT_OPERACION_PAQUETE)

    resumen = {}
    validaciones_por_pv = {0: 0, 1: 0}

    for codigo_punto_venta in puntos_venta:
        for codigo_motivo in motivos_a_correr:
            envios_ok = 0
            envios_fallidos = 0
            for intento in range(1, args.intentos + 1):
                if envios_ok >= CASOS_ENVIO_NECESARIOS:
                    print(f"\nMotivo {codigo_motivo} / PV {codigo_punto_venta}: ya llego a "
                          f"{CASOS_ENVIO_NECESARIOS} envios exitosos, se pasa a la siguiente combinacion.")
                    break
                try:
                    resultado = intentar_un_paquete(
                        client_codigos, client_operaciones, client_facturacion,
                        codigo_motivo, codigo_punto_venta, intento, llave, cert, schema
                    )
                    if resultado["envio_ok"]:
                        envios_ok += 1
                        if resultado.get("validacion_ok"):
                            validaciones_por_pv[codigo_punto_venta] += 1
                        print(f"  RESULTADO: envio OK (van {envios_ok}/{CASOS_ENVIO_NECESARIOS} en esta combinacion)")
                    else:
                        envios_fallidos += 1
                        print(f"  RESULTADO: envio fallido -- {resultado.get('motivo_falla')}")
                except Exception as e:
                    envios_fallidos += 1
                    print(f"  ERROR INESPERADO: {e}")

                print(f"  Pausa de {PAUSA_ENTRE_INTENTOS}s antes del siguiente...")
                time.sleep(PAUSA_ENTRE_INTENTOS)

            resumen[(codigo_motivo, codigo_punto_venta)] = (envios_ok, envios_fallidos)

    print("\n" + "=" * 70)
    print("RESUMEN DE ENVIOS POR COMBINACION (filas 1-14):")
    for (codigo_motivo, codigo_punto_venta), (ok, fallidos) in resumen.items():
        estado = "OK" if ok >= CASOS_ENVIO_NECESARIOS else "INCOMPLETO"
        print(f"  Motivo {codigo_motivo} ({MOTIVOS[codigo_motivo]}) / PV {codigo_punto_venta}: "
              f"{ok} exitosos, {fallidos} fallidos -- {estado}")

    print("\nVALIDACIONES EXITOSAS ACUMULADAS EN ESTA CORRIDA (filas 15-16, meta 70 cada una):")
    for pv in puntos_venta:
        print(f"  Punto de venta {pv}: {validaciones_por_pv[pv]}/{CASOS_VALIDACION_NECESARIOS}")


if __name__ == "__main__":
    main()