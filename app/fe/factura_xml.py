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


# =====================================================================
# Nota de Credito-Debito (Electronica en Linea)
#
# CORREGIDO 26/08/2026: el documento real es 'notaFiscalElectronicaCreditoDebito'
# (XSD: notaElectronicaCreditoDebito.xsd), NO 'notaElectronicaCreditoDebitoDescuento'
# -- ese es un documento DISTINTO (variante especifica para bonificaciones/
# descuentos posteriores a la venta), confirmado comparando ambos XSD y
# XML de ejemplo reales bajados de siatinfo.impuestos.gob.bo. Se envia
# con el MISMO servicio recepcionFactura de siempre (no existe operacion
# SOAP separada) -- se distingue por tipoFacturaDocumento=3 y
# codigoDocumentoSector=24 (fijo segun el XSD -- NO 47, que corresponde
# a la variante Descuento).
#
# Mismo patron que construir_factura_xml de arriba: listas de orden +
# sets de nillable, reutilizando el mismo _agregar_campo().
# =====================================================================

ORDEN_CABECERA_NCD = [
    "nitEmisor", "razonSocialEmisor", "municipio", "telefono",
    "numeroNotaCreditoDebito", "cuf", "cufd", "codigoSucursal", "direccion",
    "codigoPuntoVenta", "fechaEmision", "nombreRazonSocial",
    "codigoTipoDocumentoIdentidad", "numeroDocumento", "complemento",
    "codigoCliente", "numeroFactura", "numeroAutorizacionCuf",
    "fechaEmisionFactura", "montoTotalOriginal",
    "montoTotalDevuelto", "montoDescuentoCreditoDebito",
    "montoEfectivoCreditoDebito", "codigoExcepcion", "leyenda", "usuario",
    "codigoDocumentoSector",
]

# Confirmados uno por uno contra el atributo nillable="true" del XSD --
# los demas campos son obligatorios, sin excepcion.
CAMPOS_NILLABLE_NCD = {
    "telefono", "codigoPuntoVenta", "nombreRazonSocial", "complemento",
    "montoDescuentoCreditoDebito", "codigoExcepcion",
}

ORDEN_DETALLE_NCD = [
    "actividadEconomica", "codigoProductoSin", "codigoProducto",
    "descripcion", "cantidad", "unidadMedida", "precioUnitario",
    "montoDescuento", "subTotal", "codigoDetalleTransaccion",
]

CAMPOS_NILLABLE_DETALLE_NCD = {"montoDescuento"}


def construir_nota_credito_debito_xml(datos_cabecera, lineas_detalle):
    """
    Arma el XML de una Nota de Credito-Debito. OJO: la logica exacta de
    como armar lineas_detalle (que representa cada codigoDetalleTransaccion
    1 y 2 -- si reconstruye TODA la factura original o solo resume el
    ajuste) todavia esta en revision al 26/08/2026 -- el ejemplo oficial
    de este documento muestra datos que no calzan con una simple
    reconstruccion linea a linea (ver conversacion). NO USAR esta
    funcion para emision real todavia sin confirmar ese punto.
    """
    nsmap = {"xsi": NS_XSI}
    root = etree.Element("notaFiscalElectronicaCreditoDebito", nsmap=nsmap)
    root.set("{%s}noNamespaceSchemaLocation" % NS_XSI,
             "notaElectronicaCreditoDebito.xsd")

    cab = etree.SubElement(root, "cabecera")
    for campo in ORDEN_CABECERA_NCD:
        _agregar_campo(cab, campo, datos_cabecera.get(campo),
                        nillable=campo in CAMPOS_NILLABLE_NCD)

    for linea in lineas_detalle:
        det = etree.SubElement(root, "detalle")
        for campo in ORDEN_DETALLE_NCD:
            valor = linea.get(campo, 0 if campo == "montoDescuento" else None)
            _agregar_campo(det, campo, valor,
                            nillable=campo in CAMPOS_NILLABLE_DETALLE_NCD)

    return root