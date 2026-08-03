"""
prototipo/sin/probar_paquete_completo.py -- v2
Corregido: se usan marcas de tiempo REALES (capturadas con datetime.now()
en cada paso), no offsets artificiales. Se replica la espera real de 10
segundos que funciono en la Etapa V, en vez de intentar todo instantaneo.
"""

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
CUIS = "31477C6C"
CODIGO_SUCURSAL = 0
CODIGO_PUNTO_VENTA = 0
CODIGO_MODALIDAD = 1
CODIGO_EMISION_OFFLINE = 2
CODIGO_DOCUMENTO_SECTOR = 1
TIPO_FACTURA_DOCUMENTO = 1
CODIGO_MOTIVO_EVENTO = 1

ARCHIVO_LLAVE = "certificado_real/clave_privada_real.pem"
ARCHIVO_CERT = "certificado_real/certificado_real.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def _pedir_cufd(client_codigos):
    solicitud = {
        "codigoAmbiente": 2, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cuis": CUIS, "nit": NIT,
    }
    resp = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud))
    if not resp["transaccion"]:
        raise RuntimeError(f"Error CUFD: {resp['mensajesList']}")
    return resp["codigo"], resp["codigoControl"]


def _armar_y_firmar_factura(numero_factura, fecha_hora, codigo_control, cufd):
    cuf = calcular_cuf(
        nit=NIT, fecha_hora=fecha_hora, codigo_sucursal=CODIGO_SUCURSAL,
        codigo_modalidad=CODIGO_MODALIDAD, codigo_tipo_emision=CODIGO_EMISION_OFFLINE,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO, codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=numero_factura, codigo_punto_venta=CODIGO_PUNTO_VENTA,
        codigo_control=codigo_control,
    )
    cabecera = {
        "nitEmisor": str(NIT), "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra", "numeroFactura": numero_factura,
        "cuf": cuf, "cufd": cufd, "codigoSucursal": CODIGO_SUCURSAL,
        "direccion": "Calle San Nicolas Este Nro 30", "codigoPuntoVenta": CODIGO_PUNTO_VENTA,
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
    with open(ARCHIVO_LLAVE, "rb") as f:
        llave = f.read()
    with open(ARCHIVO_CERT, "rb") as f:
        cert = f.read()
    xml_firmado = signer.sign(xml_sin_firmar, key=llave, cert=cert)
    XMLVerifier().verify(xml_firmado, x509_cert=cert)

    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)
    xml_bytes = etree.tostring(xml_firmado)
    if not schema.validate(etree.fromstring(xml_bytes)):
        raise RuntimeError(f"Factura {numero_factura} invalida: {schema.error_log}")
    return xml_bytes


def main():
    print("=" * 70)
    print("ETAPA VI (v2 - tiempos reales, sin offsets artificiales)")
    print("=" * 70)

    client_codigos = _cliente(WSDL_CODIGOS)
    client_operaciones = _cliente(WSDL_OPERACIONES)
    client_facturacion = _cliente(WSDL_FACTURACION)

    # --- 1. CUFD del evento (el que "estaba vigente durante la contingencia") ---
    print("\n[1] Pidiendo CUFD del evento...")
    cufd, codigo_control = _pedir_cufd(client_codigos)
    inicio_evento = datetime.datetime.now()
    print(f"    CUFD: {cufd}")
    print(f"    inicio_evento (real): {inicio_evento}")

    # --- 2. Espera real de 10 segundos (replica lo que funciono en Etapa V) ---
    print("\n[2] Esperando 10 segundos reales (simulando duracion del corte)...")
    time.sleep(10)

    # --- 3. Firmar las facturas con marcas de tiempo REALES, dentro de la ventana ---
    print("\n[3] Armando y firmando 2 facturas (con fecha real, dentro del evento)...")
    facturas_xml = []
    for numero in [300, 301]:
        fecha_factura = datetime.datetime.now()  # tiempo real, no offset inventado
        xml_bytes = _armar_y_firmar_factura(numero, fecha_factura, codigo_control, cufd)
        facturas_xml.append((f"factura_{numero}.xml", xml_bytes))
        print(f"    Factura {numero}: OK (fecha real {fecha_factura}).")

    fin_evento = datetime.datetime.now()
    print(f"    fin_evento (real): {fin_evento}")
    print(f"    duracion real: {(fin_evento - inicio_evento).total_seconds()} segundos")

    # --- 4. CUFD nuevo para reportar (distinto del usado en las facturas) ---
    print("\n[4] Pidiendo CUFD nuevo para reportar el evento...")
    cufd_reporte, _ = _pedir_cufd(client_codigos)
    print(f"    CUFD de reporte: {cufd_reporte}")

    # --- 5. Registrar el evento ---
    print("\n[5] Registrando el evento significativo...")
    solicitud_evento = {
        "codigoAmbiente": 2, "codigoMotivoEvento": CODIGO_MOTIVO_EVENTO,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd, "cufdEvento": cufd_reporte,
        "cuis": CUIS, "descripcion": "Corte de internet de prueba - Etapa VI",
        "fechaHoraFinEvento": fin_evento, "fechaHoraInicioEvento": inicio_evento, "nit": NIT,
    }
    resp_evento = serialize_object(client_operaciones.service.registroEventoSignificativo(
        SolicitudEventoSignificativo=solicitud_evento
    ))
    if not resp_evento["transaccion"]:
        print("ERROR registrando evento:", resp_evento["mensajesList"])
        return
    codigo_evento = resp_evento["codigoRecepcionEventoSignificativo"]
    print(f"    Evento registrado. codigoEvento: {codigo_evento}")

    # --- 6. Empaquetar en TAR+GZIP ---
    print("\n[6] Empaquetando en TAR+GZIP...")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for nombre, contenido in facturas_xml:
            info = tarfile.TarInfo(name=nombre)
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))
    tar_gzip = gzip.compress(tar_buffer.getvalue())
    hash_archivo = hashlib.sha256(tar_gzip).hexdigest().upper()
    print(f"    Empaquetado: {len(tar_gzip)} bytes.")

    # --- 7. Enviar el paquete ---
    print("\n[7] Enviando el paquete...")
    solicitud_paquete = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION_OFFLINE, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd, "cuis": CUIS, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO, "archivo": tar_gzip,
        "fechaEnvio": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo, "cafc": "", "cantidadFacturas": len(facturas_xml),
        "codigoEvento": codigo_evento,
    }
    resp_paquete = serialize_object(client_facturacion.service.recepcionPaqueteFactura(
        SolicitudServicioRecepcionPaquete=solicitud_paquete
    ))
    print("\nRespuesta del envio:")
    print(resp_paquete)

    if not resp_paquete["transaccion"]:
        return

    codigo_recepcion = resp_paquete["codigoRecepcion"]

    # --- 8. Esperar y validar ---
    print("\n[8] Esperando 5 segundos antes de validar...")
    time.sleep(5)
    solicitud_validacion = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION_OFFLINE, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd, "cuis": CUIS, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO, "codigoRecepcion": codigo_recepcion,
    }
    resp_validacion = serialize_object(client_facturacion.service.validacionRecepcionPaqueteFactura(
        SolicitudServicioValidacionRecepcionPaquete=solicitud_validacion
    ))
    print("\nRespuesta de la validacion:")
    print(resp_validacion)


if __name__ == "__main__":
    main()