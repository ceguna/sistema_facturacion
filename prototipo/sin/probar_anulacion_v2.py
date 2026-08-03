"""
prototipo/sin/probar_anulacion_v2.py

Emite una factura NUEVA y la anula de inmediato -- para descartar que
el rechazo anterior se debiera a que el ambiente Piloto ya habia
purgado la factura de ayer, en vez de un problema real con el flujo
de anulacion.
"""

import datetime
import gzip
import hashlib

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
CODIGO_EMISION = 1
CODIGO_DOCUMENTO_SECTOR = 1
TIPO_FACTURA_DOCUMENTO = 1
CODIGO_MOTIVO_ANULACION = 1  # FACTURA MAL EMITIDA

ARCHIVO_LLAVE = "certificado_real/clave_privada_real.pem"
ARCHIVO_CERT = "certificado_real/certificado_real.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
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


def main():
    client_codigos = _cliente(WSDL_CODIGOS)
    client_facturacion = _cliente(WSDL_FACTURACION)

    # --- 1. Emitir una factura nueva ---
    print("[1] Pidiendo CUFD y emitiendo una factura nueva...")
    cufd, codigo_control = _pedir_cufd(client_codigos)
    fecha_hora = datetime.datetime.now()
    numero_factura = 400

    cuf = calcular_cuf(
        nit=NIT, fecha_hora=fecha_hora, codigo_sucursal=CODIGO_SUCURSAL,
        codigo_modalidad=CODIGO_MODALIDAD, codigo_tipo_emision=CODIGO_EMISION,
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
        print("NO valida contra XSD:", schema.error_log)
        return

    xml_gzip = gzip.compress(xml_bytes)
    hash_archivo = hashlib.sha256(xml_gzip).hexdigest().upper()

    solicitud_envio = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd, "cuis": CUIS, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO, "archivo": xml_gzip,
        "fechaEnvio": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
    }
    resp_envio = serialize_object(client_facturacion.service.recepcionFactura(
        SolicitudServicioRecepcionFactura=solicitud_envio
    ))
    print(f"    Envio: {resp_envio}")

    if not resp_envio["transaccion"]:
        print("La factura no se emitio correctamente, no se puede probar la anulacion.")
        return

    print(f"\n    CUF emitido: {cuf}")

    # --- 2. Anular esa MISMA factura, de inmediato ---
    print(f"\n[2] Anulando la factura recien emitida (motivo: FACTURA MAL EMITIDA)...")
    cufd_anulacion, _ = _pedir_cufd(client_codigos)
    solicitud_anulacion = {
        "codigoAmbiente": 2, "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION, "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA, "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL, "cufd": cufd_anulacion, "cuis": CUIS, "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "codigoMotivo": CODIGO_MOTIVO_ANULACION, "cuf": cuf,
    }
    resp_anulacion = serialize_object(client_facturacion.service.anulacionFactura(
        SolicitudServicioAnulacionFactura=solicitud_anulacion
    ))
    print("Respuesta:")
    print(resp_anulacion)


if __name__ == "__main__":
    main()