"""
Arma el XML de una Factura de Compra y Venta (Electronica en Linea).
Ver prototipo/sin/factura_xml.py para el historial de validacion contra
el XSD y ejemplo oficial.
"""
from lxml import etree

NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

ORDEN_CABECERA = [
    "nitEmisor", "razonSocialEmisor", "municipio", "telefono", "numeroFactura",
    "cuf", "cufd", "codigoSucursal", "direccion", "codigoPuntoVenta",
    "fechaEmision", "nombreRazonSocial", "codigoTipoDocumentoIdentidad",
    "numeroDocumento", "complemento", "codigoCliente", "codigoMetodoPago",
    "numeroTarjeta", "montoTotal", "montoTotalSujetoIva", "codigoMoneda",
    "tipoCambio", "montoTotalMoneda", "montoGiftCard", "descuentoAdicional",
    "codigoExcepcion", "cafc", "leyenda", "usuario", "codigoDocumentoSector",
]

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