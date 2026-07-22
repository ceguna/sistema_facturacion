"""
Firma el XML de la factura usando XML-DSig (enveloped signature), tal como
se confirmo contra el bloque <Signature> del XML oficial de ejemplo:
    - Canonicalizacion: xml-c14n-20010315 (con comentarios)
    - Metodo de firma: RSA-SHA256
    - Digest: SHA-256
    - Transform: enveloped-signature

Usa la libreria signxml, que implementa este estandar de fabrica.
"""
from signxml import XMLSigner, methods
from lxml import etree


def firmar_factura(xml_root, ruta_llave_privada, ruta_certificado):
    """
    xml_root: el elemento raiz (facturaElectronicaCompraVenta) ya con el CUF
    calculado e insertado, SIN firmar todavia.

    Devuelve el mismo documento con el bloque <Signature> agregado al final,
    tal como lo exige el XSD para la modalidad Electronica en Linea.
    """
    with open(ruta_llave_privada, "rb") as f:
        llave_privada = f.read()
    with open(ruta_certificado, "rb") as f:
        certificado = f.read()

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315#WithComments",
    )

    xml_firmado = signer.sign(
        xml_root,
        key=llave_privada,
        cert=certificado,
    )

    return xml_firmado


if __name__ == "__main__":
    import subprocess
    import sys
    import os

    # Genera un certificado de prueba si todavia no existe uno
    if not os.path.exists("certificado_prueba_key.pem"):
        from generar_certificado_prueba import generar_certificado_prueba
        generar_certificado_prueba()

    from factura_xml import construir_factura_xml

    cabecera = {
        "nitEmisor": "3852849010", "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra", "numeroFactura": 1,
        "cuf": "1A5CBD3F979C3406E69A3316C183C1554329B606A0",  # provisional, ver cuf.py
        "cufd": "CUFD-DE-PRUEBA-000000000", "codigoSucursal": 0,
        "direccion": "Calle San Nicolas Este Nro 30", "codigoPuntoVenta": 0,
        "fechaEmision": "2026-07-22T10:00:00.000", "codigoTipoDocumentoIdentidad": 1,
        "numeroDocumento": "1234567", "codigoCliente": "1", "codigoMetodoPago": 1,
        "montoTotal": 100.00, "montoTotalSujetoIva": 100.00, "codigoMoneda": 1,
        "tipoCambio": 1, "montoTotalMoneda": 100.00, "descuentoAdicional": 0,
        "leyenda": "Ley N 453", "usuario": "pruebas", "codigoDocumentoSector": 1,
    }
    detalle = [{
        "actividadEconomica": "476130", "codigoProductoSin": "49111",
        "codigoProducto": "ART-001", "descripcion": "Cuaderno universitario",
        "cantidad": 2, "unidadMedida": 1, "precioUnitario": 50.00, "subTotal": 100.00,
    }]

    xml_sin_firmar = construir_factura_xml(cabecera, detalle)
    xml_firmado = firmar_factura(
        xml_sin_firmar, "certificado_prueba_key.pem", "certificado_prueba_cert.pem"
    )

    with open("factura_firmada.xml", "wb") as f:
        f.write(etree.tostring(xml_firmado, pretty_print=True))

    print("Factura firmada guardada en factura_firmada.xml")
