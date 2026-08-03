"""
prototipo/sin/probar_paquete_factura.py

Arma un paquete de 2 facturas (modo "fuera de linea", codigoEmision=2),
las firma y valida individualmente, las empaqueta en TAR+GZIP, y las
envia via recepcionPaqueteFactura -- Etapa VI de certificacion Piloto.
"""

import datetime
import gzip
import hashlib
import io
import tarfile

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
CODIGO_EMISION_OFFLINE = 2      # "fuera de linea" -- el modo durante contingencia
CODIGO_DOCUMENTO_SECTOR = 1
TIPO_FACTURA_DOCUMENTO = 1
CODIGO_EVENTO = 9828970          # el que ya registramos en la Etapa V

ARCHIVO_LLAVE = "certificado_real/clave_privada_real.pem"
ARCHIVO_CERT = "certificado_real/certificado_real.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"


def _cliente(wsdl):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {TOKEN}"})
    return Client(wsdl=wsdl, transport=Transport(session=session))


def _armar_y_firmar_factura(numero_factura, fecha_hora, codigo_control, cufd):
    cuf = calcular_cuf(
        nit=NIT,
        fecha_hora=fecha_hora,
        codigo_sucursal=CODIGO_SUCURSAL,
        codigo_modalidad=CODIGO_MODALIDAD,
        codigo_tipo_emision=CODIGO_EMISION_OFFLINE,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO,
        codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=numero_factura,
        codigo_punto_venta=CODIGO_PUNTO_VENTA,
        codigo_control=codigo_control,
    )
    cabecera = {
        "nitEmisor": str(NIT),
        "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra",
        "numeroFactura": numero_factura,
        "cuf": cuf,
        "cufd": cufd,
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
        "actividadEconomica": "4761300",
        "codigoProductoSin": "1003646",
        "codigoProducto": "ART-001",
        "descripcion": "Cuaderno universitario 100 hojas",
        "cantidad": 2,
        "unidadMedida": 1,
        "precioUnitario": 50.00,
        "subTotal": 100.00,
    }]
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)

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

    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)
    xml_bytes = etree.tostring(xml_firmado)
    xml_reparsed = etree.fromstring(xml_bytes)
    if not schema.validate(xml_reparsed):
        raise RuntimeError(f"Factura {numero_factura} no valida contra XSD: {schema.error_log}")

    return xml_bytes


def main():
    print("=" * 70)
    print("ETAPA VI: EMISION DE PAQUETES (2 facturas, modo fuera de linea)")
    print("=" * 70)

    # --- 1. CUFD "offline" -- el que estaba vigente durante la contingencia ---
    print("\n[1] Pidiendo CUFD (simula el vigente durante el corte)...")
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
    resp_cufd = serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud_cufd))
    if not resp_cufd["transaccion"]:
        print("ERROR obteniendo CUFD:", resp_cufd["mensajesList"])
        return
    cufd = resp_cufd["codigo"]
    codigo_control = resp_cufd["codigoControl"]
    print(f"    CUFD obtenido.")
    print(f"    CUFD usado: {cufd}")

    # --- 2. Armar y firmar 2 facturas individualmente ---
    print("\n[2] Armando y firmando 2 facturas (numeros 100 y 101)...")
    ahora = datetime.datetime.now()
    facturas_xml = []
    for i, numero in enumerate([100, 101]):
        fecha_factura = ahora + datetime.timedelta(seconds=i)
        xml_bytes = _armar_y_firmar_factura(numero, fecha_factura, codigo_control, cufd)
        facturas_xml.append((f"factura_{numero}.xml", xml_bytes))
        print(f"    Factura {numero}: armada, firmada, validada contra XSD.")

    # --- 3. Empaquetar en TAR ---
    print("\n[3] Empaquetando en contenedor TAR...")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for nombre, contenido in facturas_xml:
            info = tarfile.TarInfo(name=nombre)
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))
    tar_bytes = tar_buffer.getvalue()
    print(f"    TAR armado: {len(tar_bytes)} bytes, {len(facturas_xml)} archivos.")

    # --- 4. Comprimir el TAR en gzip ---
    print("\n[4] Comprimiendo el TAR en gzip...")
    tar_gzip = gzip.compress(tar_bytes)
    print(f"    Comprimido: {len(tar_gzip)} bytes.")

    # --- 5. Hash SHA-256 del TAR.GZ ---
    print("\n[5] Calculando hash SHA-256...")
    hash_archivo = hashlib.sha256(tar_gzip).hexdigest().upper()
    print(f"    hashArchivo: {hash_archivo}")

    # --- 6. Enviar el paquete ---
    print("\n[6] Enviando via recepcionPaqueteFactura...")
    client_facturacion = _cliente(WSDL_FACTURACION)
    solicitud_paquete = {
        "codigoAmbiente": 2,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_EMISION_OFFLINE,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": CODIGO_PUNTO_VENTA,
        "codigoSistema": CODIGO_SISTEMA,
        "codigoSucursal": CODIGO_SUCURSAL,
        "cufd": cufd,
        "cuis": CUIS,
        "nit": NIT,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "archivo": tar_gzip,
        "fechaEnvio": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
        "cafc": "",  # no aplica -- es para facturas manuales de contingencia, no nuestro caso
        "cantidadFacturas": len(facturas_xml),
        "codigoEvento": CODIGO_EVENTO,
    }

    try:
        resp = client_facturacion.service.recepcionPaqueteFactura(
            SolicitudServicioRecepcionPaquete=solicitud_paquete
        )
        print("\nRespuesta del SIN:")
        print(serialize_object(resp))
    except Exception as e:
        print(f"\nERROR: {e}")


if __name__ == "__main__":
    main()