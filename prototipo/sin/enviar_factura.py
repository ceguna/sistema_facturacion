"""
prototipo/sin/enviar_factura.py

Paso 4 (final): pide un CUFD fresco, recalcula el CUF, arma y firma la
factura, la valida contra el XSD, la comprime en gzip, calcula su hash
SHA-256, y la envia al SIN via recepcionFactura (ambiente PILOTO).

Este es el primer envio REAL a un servicio de "escritura" del SIN.
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
CODIGO_MODALIDAD = 1          # Electronica en Linea
CODIGO_EMISION = 1            # EN LINEA (confirmado catalogo real)
CODIGO_DOCUMENTO_SECTOR = 1   # Compra y Venta
TIPO_FACTURA_DOCUMENTO = 1    # CON DERECHO A CREDITO FISCAL (confirmado catalogo real)

ARCHIVO_LLAVE = "certificado_real/clave_privada_real.pem"
ARCHIVO_CERT = "certificado_real/certificado_real.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"
ARCHIVO_SALIDA = "factura_enviada.xml"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def main():
    print("=" * 70)
    print("ENVIO REAL DE FACTURA AL SIN (ambiente PILOTO)")
    print("=" * 70)

    # --- 1. Pedir un CUFD fresco (no reusar el de ayer) ---
    print("\n[1] Pidiendo CUFD fresco...")
    client_codigos = _cliente(WSDL_CODIGOS)
    solicitud_cufd = {
        "codigoAmbiente": 2,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cuis": CUIS,
        "nit": NIT,
    }
    resp_cufd = client_codigos.service.cufd(SolicitudCufd=solicitud_cufd)
    resp_cufd = serialize_object(resp_cufd)
    if not resp_cufd["transaccion"]:
        print("    ERROR obteniendo CUFD:", resp_cufd["mensajesList"])
        return
    cufd_real = resp_cufd["codigo"]
    codigo_control_real = resp_cufd["codigoControl"]
    print(f"    CUFD obtenido. Vigente hasta: {resp_cufd['fechaVigencia']}")

    # --- 2. Calcular el CUF con el codigoControl fresco ---
    fecha_hora = datetime.datetime.now()
    numero_factura = 1

    print("\n[2] Calculando el CUF...")
    cuf = calcular_cuf(
        nit=NIT,
        fecha_hora=fecha_hora,
        codigo_sucursal=CODIGO_SUCURSAL,
        codigo_modalidad=CODIGO_MODALIDAD,
        codigo_tipo_emision=CODIGO_EMISION,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO,
        codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=numero_factura,
        codigo_punto_venta=CODIGO_PUNTO_VENTA,
        codigo_control=codigo_control_real,
    )
    print(f"    CUF: {cuf}")

    # --- 3. Armar el XML ---
    print("\n[3] Armando el XML de la factura...")
    cabecera = {
        "nitEmisor": str(NIT),
        "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra",
        "numeroFactura": numero_factura,
        "cuf": cuf,
        "cufd": cufd_real,
        "codigoSucursal": CODIGO_SUCURSAL,
        "direccion": "Calle San Nicolas Este Nro 30",
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA,
        "fechaEmision": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "codigoTipoDocumentoIdentidad": 1,
        "numeroDocumento": "1234567",
        "codigoCliente": "1",
        "codigoMetodoPago": 1,
        "montoTotal": 100.00,
        "montoTotalSujetoIva": 100.00,
        "codigoMoneda": 1,
        "tipoCambio": 1,
        "montoTotalMoneda": 100.00,
        "descuentoAdicional": 0,
        "leyenda": "Ley N 453: Tienes derecho a recibir informacion sobre las "
                   "caracteristicas y contenidos de los servicios que utilices.",
        "usuario": "pruebas",
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
    }
    detalle = [{
    "actividadEconomica": "4761300",      # antes: "476130" (faltaba el digito final)
    "codigoProductoSin": "1003646",        # antes: "49111" (no correspondia a la actividad real)
    "codigoProducto": "ART-001",           # este es tu codigo interno, se deja igual
    "descripcion": "Cuaderno universitario 100 hojas",
    "cantidad": 2,
    "unidadMedida": 1,
    "precioUnitario": 50.00,
    "subTotal": 100.00,
    }]
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)

    # --- 4. Firmar ---
    print("\n[4] Firmando digitalmente...")
    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0_WITH_COMMENTS,
    )
    with open(ARCHIVO_LLAVE, "rb") as f:
        llave = f.read()
    with open(ARCHIVO_CERT, "rb") as f:
        cert = f.read()
    xml_firmado = signer.sign(xml_sin_firmar, key=llave, cert=cert)

    XMLVerifier().verify(xml_firmado, x509_cert=cert)
    print("    Firmado y verificado.")

    # --- 5. Validar contra XSD ---
    print(f"\n[5] Validando contra {ARCHIVO_XSD}...")
    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)
    xml_bytes = etree.tostring(xml_firmado)
    xml_reparsed = etree.fromstring(xml_bytes)
    if not schema.validate(xml_reparsed):
        print("    NO valido. Errores:")
        for error in schema.error_log:
            print("     -", error)
        return
    print("    Valido.")

    with open(ARCHIVO_SALIDA, "wb") as f:
        f.write(xml_bytes)

    # --- 6. Comprimir en gzip ---
    print("\n[6] Comprimiendo en gzip...")
    xml_gzip = gzip.compress(xml_bytes)
    print(f"    Tamano original: {len(xml_bytes)} bytes -> comprimido: {len(xml_gzip)} bytes")

    # --- 7. Calcular hash SHA-256 ---
    print("\n[7] Calculando hash SHA-256 del archivo comprimido...")
    hash_archivo = hashlib.sha256(xml_gzip).hexdigest().upper()
    print(f"    hashArchivo: {hash_archivo}")

    # --- 8. Enviar via recepcionFactura ---
    print("\n[8] Enviando a recepcionFactura (SIN Piloto)...")
    client_facturacion = _cliente(WSDL_FACTURACION)
    solicitud_envio = {
        "codigoAmbiente": 2,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cufd": cufd_real,
        "cuis": CUIS,
        "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "archivo": xml_gzip,
        "fechaEnvio": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
    }

    try:
        resp = client_facturacion.service.recepcionFactura(SolicitudServicioRecepcionFactura=solicitud_envio)
        print("\nRespuesta del SIN:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"\nERROR: {e}")


if __name__ == "__main__":
    main()