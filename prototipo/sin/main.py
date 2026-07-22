"""
Prototipo aislado (Paso 3): arma una factura de prueba, calcula su CUF,
la firma digitalmente, y valida el resultado contra el XSD oficial.

Correr con: python main.py

NADA de esto todavia se conecta al SIN (eso es el Paso 4). Este script solo
prueba que el MECANISMO de armado + firma + validacion funciona de punta a
punta, usando un certificado autofirmado de prueba.
"""
import datetime
import os

from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods
from signxml.algorithms import CanonicalizationMethod

from factura_xml import construir_factura_xml
from cuf import calcular_cuf
from generar_certificado_prueba import generar_certificado_prueba

ARCHIVO_LLAVE = "certificado_prueba_key.pem"
ARCHIVO_CERT = "certificado_prueba_cert.pem"
ARCHIVO_XSD = "facturaElectronicaCompraVenta.xsd"
ARCHIVO_SALIDA = "factura_firmada.xml"


def main():
    print("=" * 70)
    print("PROTOTIPO: generar + firmar + validar una factura de prueba")
    print("=" * 70)

    # 0. Certificado de prueba (autofirmado). Cuando llegue el real de ADSIB,
    #    solo hay que cambiar ARCHIVO_LLAVE y ARCHIVO_CERT.
    if not os.path.exists(ARCHIVO_LLAVE):
        print("\n[0] Generando certificado de prueba (autofirmado)...")
        generar_certificado_prueba(ARCHIVO_LLAVE, ARCHIVO_CERT)
    else:
        print(f"\n[0] Usando certificado de prueba existente: {ARCHIVO_CERT}")

    # 1. Datos de la factura (de prueba, con la libreria real como emisora)
    fecha_hora = datetime.datetime.now()
    numero_factura = 1
    codigo_sucursal = 0
    codigo_punto_venta = 0
    codigo_documento_sector = 1  # Compra y Venta

    print("\n[1] Calculando el CUF (algoritmo verificado contra el ejemplo oficial del SIN)...")
    # codigo_control: en la integracion real (Paso 4) viene de la respuesta
    # del servicio solicitudCufd. Por ahora, mientras no tenemos conexion al
    # SIN, se simula con un valor de ejemplo -- SOLO para probar el mecanismo.
    codigo_control_simulado = "A19E23EF34124CD"
    cuf = calcular_cuf(
        nit=3852849010,
        fecha_hora=fecha_hora,
        codigo_sucursal=codigo_sucursal,
        codigo_modalidad=1,  # Electronica en Linea
        codigo_tipo_emision=1,  # Online
        codigo_tipo_factura=1,  # Con derecho a credito fiscal
        codigo_documento_sector=codigo_documento_sector,
        numero_factura=numero_factura,
        codigo_punto_venta=codigo_punto_venta,
        codigo_control=codigo_control_simulado,
    )
    print(f"    CUF calculado: {cuf}")

    print("\n[2] Armando el XML de la factura...")
    cabecera = {
        "nitEmisor": "3852849010",
        "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra",
        "numeroFactura": numero_factura,
        "cuf": cuf,
        "cufd": "CUFD-DE-PRUEBA-000000000",  # en el Paso 4 vendra del SIN real
        "codigoSucursal": codigo_sucursal,
        "direccion": "Calle San Nicolas Este Nro 30",
        "codigoPuntoVenta": codigo_punto_venta,
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
        "codigoDocumentoSector": codigo_documento_sector,
    }
    detalle = [{
        "actividadEconomica": "476130",
        "codigoProductoSin": "49111",
        "codigoProducto": "ART-001",
        "descripcion": "Cuaderno universitario 100 hojas",
        "cantidad": 2,
        "unidadMedida": 1,
        "precioUnitario": 50.00,
        "subTotal": 100.00,
    }]
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)
    print("    XML armado (cabecera + detalle).")

    print("\n[3] Firmando digitalmente (XML-DSig, RSA-SHA256, C14N con comentarios)...")
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
    print("    Firmado.")

    print("\n[4] Verificando la firma criptograficamente...")
    try:
        XMLVerifier().verify(xml_firmado, x509_cert=cert)
        print("    Firma verificada correctamente.")
    except Exception as e:
        print(f"    ERROR: la firma no se pudo verificar: {e}")
        return

    print(f"\n[5] Validando el documento completo contra {ARCHIVO_XSD}...")
    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)
    xml_bytes = etree.tostring(xml_firmado)
    xml_reparsed = etree.fromstring(xml_bytes)
    es_valido = schema.validate(xml_reparsed)
    if es_valido:
        print("    VALIDO contra el XSD oficial.")
    else:
        print("    NO valido. Errores:")
        for error in schema.error_log:
            print("     -", error)
        return

    with open(ARCHIVO_SALIDA, "wb") as f:
        f.write(etree.tostring(xml_firmado, pretty_print=True))
    print(f"\nListo. Factura de prueba guardada en: {ARCHIVO_SALIDA}")
    print("\nRECORDATORIOS:")
    print(" - El CUF ya esta verificado contra el ejemplo oficial del SIN (ver cuf.py).")
    print("   Solo falta el 'codigoControl' real, que en el Paso 4 vendra de la")
    print("   respuesta del servicio solicitudCufd (aqui esta simulado).")
    print(" - El certificado usado es de PRUEBA (autofirmado), no valido ante el SIN.")
    print(" - Todavia no se conecta a ningun servicio del SIN (eso es el Paso 4).")


if __name__ == "__main__":
    main()
