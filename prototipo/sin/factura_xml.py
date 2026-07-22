"""
Arma el XML de una Factura de Compra y Venta (Electronica en Linea), siguiendo
EXACTAMENTE el orden de campos confirmado contra el XML de ejemplo oficial
(facturaElectronicaCompraVenta.xml) y su XSD. El orden importa: el XSD usa
xs:sequence, asi que un campo fuera de lugar hace que la validacion falle
aunque el dato en si sea correcto.

Este modulo SOLO arma el XML sin firmar. La firma va aparte (ver firmar.py):
el CUF se calcula antes de firmar, y ambos (CUF y firma) quedan dentro del
mismo documento final.
"""
from lxml import etree

NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

# Orden exacto de la cabecera, tal como aparece en el XML oficial de ejemplo.
ORDEN_CABECERA = [
    "nitEmisor", "razonSocialEmisor", "municipio", "telefono", "numeroFactura",
    "cuf", "cufd", "codigoSucursal", "direccion", "codigoPuntoVenta",
    "fechaEmision", "nombreRazonSocial", "codigoTipoDocumentoIdentidad",
    "numeroDocumento", "complemento", "codigoCliente", "codigoMetodoPago",
    "numeroTarjeta", "montoTotal", "montoTotalSujetoIva", "codigoMoneda",
    "tipoCambio", "montoTotalMoneda", "montoGiftCard", "descuentoAdicional",
    "codigoExcepcion", "cafc", "leyenda", "usuario", "codigoDocumentoSector",
]

# Campos que el XSD marca como nillable: si no hay valor, van con
# xsi:nil="true" en vez de omitirse.
CAMPOS_NILLABLE = {
    "telefono", "codigoPuntoVenta", "nombreRazonSocial", "complemento",
    "numeroTarjeta", "montoGiftCard", "codigoExcepcion", "cafc",
}

ORDEN_DETALLE = [
    "actividadEconomica", "codigoProductoSin", "codigoProducto", "descripcion",
    "cantidad", "unidadMedida", "precioUnitario", "montoDescuento", "subTotal",
    "numeroSerie", "numeroImei",
]

CAMPOS_NILLABLE_DETALLE = {"numeroSerie", "numeroImei"}


def _agregar_campo(parent, nombre, valor, nillable):
    el = etree.SubElement(parent, nombre)
    if valor is None:
        if nillable:
            el.set("{%s}nil" % NS_XSI, "true")
        else:
            raise ValueError(
                f"El campo '{nombre}' es obligatorio y no admite valor nulo."
            )
    else:
        el.text = str(valor)
    return el


def construir_factura_xml(datos_cabecera, lineas_detalle):
    """
    datos_cabecera: dict con las llaves de ORDEN_CABECERA (pueden faltar las
    nillable, se completan como None -> xsi:nil="true").
    lineas_detalle: lista de dicts, uno por linea de producto/servicio.
    """
    nsmap = {"xsi": NS_XSI}
    root = etree.Element("facturaElectronicaCompraVenta", nsmap=nsmap)
    root.set("{%s}noNamespaceSchemaLocation" % NS_XSI,
             "facturaElectronicaCompraVenta.xsd")

    cab = etree.SubElement(root, "cabecera")
    for campo in ORDEN_CABECERA:
        _agregar_campo(cab, campo, datos_cabecera.get(campo),
                        nillable=campo in CAMPOS_NILLABLE)

    for linea in lineas_detalle:
        det = etree.SubElement(root, "detalle")
        for campo in ORDEN_DETALLE:
            valor = linea.get(campo, 0 if campo == "montoDescuento" else None)
            _agregar_campo(det, campo, valor,
                            nillable=campo in CAMPOS_NILLABLE_DETALLE)

    return root


if __name__ == "__main__":
    cabecera = {
        "nitEmisor": "3852849010",
        "razonSocialEmisor": "Carla Cecilia Aguilera Tellez",
        "municipio": "Santa Cruz de la Sierra",
        "numeroFactura": 1,
        "cuf": "PENDIENTE",  # se completa en main.py, luego de calcularlo
        "cufd": "CUFD-DE-PRUEBA-000000000",
        "codigoSucursal": 0,
        "direccion": "Calle San Nicolas Este Nro 30",
        "codigoPuntoVenta": 0,
        "fechaEmision": "2026-07-22T10:00:00.000",
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
        "leyenda": "Ley N 453: Tienes derecho a recibir informacion...",
        "usuario": "pruebas",
        "codigoDocumentoSector": 1,
    }
    # Nota: unidadMedida=1 aca es un codigo de ejemplo (bienes), no el 58 de
    # servicios -- el codigo real sale del catalogo sincronizado.
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
    xml = construir_factura_xml(cabecera, detalle)
    print(etree.tostring(xml, pretty_print=True).decode())
