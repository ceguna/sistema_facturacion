"""
Servicio de emision de facturas electronicas ante el SIN.

emitir_factura_sin(factura_enc) es el punto de entrada: toma una
FacturaEnc ya guardada (con su FacturaDet asociado), valida que todos
los prerrequisitos esten completos, y ejecuta el flujo completo
confirmado en prototipo/sin/: CUFD -> CUF -> XML -> firma -> validacion
XSD -> gzip -> hash -> envio -> guardado del resultado.

anular_factura_sin(factura_enc, codigo_motivo) anula ante el SIN una
factura ya validada, usando el servicio real confirmado en la Etapa VII
de certificacion (prototipo/sin/probar_anulacion_v2.py).

revertir_anulacion_sin(factura_enc) revierte una anulacion ya
confirmada por el SIN, usando el servicio real confirmado en la
Etapa VIII (prototipo/sin/probar_reversion.py).

Si algun prerrequisito falta (homologacion de producto pendiente,
Empresa sin configurar, etc.) lanza EmisionSinError con un mensaje
claro -- nunca intenta adivinar un valor faltante. Todas las llamadas
de red tienen un limite de tiempo explicito (ver TIMEOUT_CONEXION y
TIMEOUT_OPERACION) para que un SIN caido o sin respuesta nunca deje
al sistema esperando indefinidamente -- se convierte en un
EmisionSinError con mensaje claro despues del limite.
"""
import gzip
import hashlib
import os
import socket
import time

from decouple import config
from django.utils import timezone
from lxml import etree
from requests.exceptions import RequestException
from signxml import XMLSigner, XMLVerifier, methods
from signxml.algorithms import CanonicalizationMethod
from zeep import Client
from zeep.exceptions import Error as ZeepError
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

from .cuf import calcular_cuf
from .factura_xml import construir_factura_xml, construir_nota_credito_debito_xml
from .models import Empresa, Sucursal, PuntoVenta

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"

TIMEOUT_CONEXION = 15
TIMEOUT_OPERACION = 45

ARCHIVO_LLAVE = config(
    "SIN_ARCHIVO_LLAVE",
    default=os.path.join(os.path.dirname(__file__), "..", "..", "prototipo", "sin",
                          "certificado_real", "clave_privada_real.pem")
)
ARCHIVO_CERT = config(
    "SIN_ARCHIVO_CERT",
    default=os.path.join(os.path.dirname(__file__), "..", "..", "prototipo", "sin",
                          "certificado_real", "certificado_real.pem")
)
ARCHIVO_XSD = config(
    "SIN_ARCHIVO_XSD",
    default=os.path.join(os.path.dirname(__file__), "..", "..", "prototipo", "sin",
                          "facturaElectronicaCompraVenta.xsd")
)
ARCHIVO_XSD_NCD = config(
    "SIN_ARCHIVO_XSD_NCD",
    default=os.path.join(os.path.dirname(__file__), "..", "..", "prototipo", "sin",
                          "notaElectronicaCreditoDebito.xsd")
)

with open(ARCHIVO_LLAVE, "rb") as _f:
    _LLAVE_PRIVADA = _f.read()
with open(ARCHIVO_CERT, "rb") as _f:
    _CERTIFICADO = _f.read()
_XSD_SCHEMA = etree.XMLSchema(etree.parse(ARCHIVO_XSD))
_XSD_SCHEMA_NCD = etree.XMLSchema(etree.parse(ARCHIVO_XSD_NCD))

CODIGO_AMBIENTE_PILOTO = 2
CODIGO_AMBIENTE_PRODUCCION = 1
CODIGO_MODALIDAD = 1          # Electronica en Linea
CODIGO_TIPO_EMISION = 1       # En linea
CODIGO_DOCUMENTO_SECTOR = 1   # Compra y Venta
TIPO_FACTURA_DOCUMENTO = 1    # Con derecho a credito fiscal
TIPO_FACTURA_DOCUMENTO_AJUSTE = 3
CODIGO_DOCUMENTO_SECTOR_NCD = 24
CODIGO_TIPO_DOC_CI = 1
CODIGO_TIPO_DOC_NIT = 5
LEYENDA_DEFAULT = (
    "Ley N 453: Tienes derecho a recibir informacion sobre las "
    "caracteristicas y contenidos de los servicios que utilices."
)


class EmisionSinError(Exception):
    """Error al emitir, anular o revertir una anulacion ante el SIN (prerrequisito faltante, timeout, o rechazo)."""
    pass


def _cliente_soap(wsdl, token):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {token}"})
    transport = Transport(
        session=session,
        timeout=TIMEOUT_CONEXION,
        operation_timeout=TIMEOUT_OPERACION,
    )
    try:
        return Client(wsdl=wsdl, transport=transport)
    except (RequestException, ZeepError, socket.timeout) as e:
        raise EmisionSinError(
            f"No se pudo conectar con el SIN (servicio no disponible o sin respuesta): {e}"
        )


def _llamar(descripcion, funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except (RequestException, ZeepError, socket.timeout) as e:
        raise EmisionSinError(
            f"No se pudo completar '{descripcion}' — el SIN no respondió a tiempo "
            f"o la conexión falló. Intente nuevamente en unos minutos. (Detalle: {e})"
        )


def _obtener_token():
    try:
        return config("SIN_TOKEN_DELEGADO")
    except Exception:
        raise EmisionSinError("Falta la variable de entorno SIN_TOKEN_DELEGADO (.env).")


def _obtener_empresa_y_sucursal(codigo_sucursal=0):
    empresa = Empresa.objects.first()
    if not empresa:
        raise EmisionSinError("No hay configuracion de Empresa cargada (completar en /fe/).")
    if not empresa.nit:
        raise EmisionSinError("La Empresa no tiene NIT cargado.")
    if not empresa.codigo_sistema:
        raise EmisionSinError("La Empresa no tiene codigo_sistema cargado "
                               "(Autorizacion de Sistemas pendiente ante el SIN).")

    sucursal = Sucursal.objects.filter(empresa=empresa, codigo_sucursal=codigo_sucursal).first()
    if not sucursal:
        raise EmisionSinError(f"No existe la Sucursal con codigo {codigo_sucursal}.")
    if not sucursal.codigo_cuis:
        raise EmisionSinError("La Sucursal no tiene CUIS cargado.")
    if not sucursal.municipio:
        raise EmisionSinError("La Sucursal no tiene 'municipio' cargado (obligatorio para el XML).")
    if not sucursal.direccion:
        raise EmisionSinError("La Sucursal no tiene 'direccion' cargada (obligatorio para el XML).")

    return empresa, sucursal


def _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta):
    if codigo_punto_venta == 0:
        return sucursal.codigo_cuis

    punto_venta = PuntoVenta.objects.filter(
        sucursal=sucursal, codigo_punto_venta=codigo_punto_venta
    ).first()
    if not punto_venta:
        raise EmisionSinError(
            f"No existe un PuntoVenta con código {codigo_punto_venta} "
            "registrado localmente para esta sucursal."
        )
    if not punto_venta.codigo_cuis:
        raise EmisionSinError(
            f"El PuntoVenta {codigo_punto_venta} ('{punto_venta.nombre}') "
            "no tiene CUIS propio cargado todavía."
        )
    return punto_venta.codigo_cuis


def _pedir_cufd(client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente):
    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cuis": cuis,
        "nit": empresa.nit,
    }
    resp = _llamar(
        "obtención de CUFD",
        lambda: serialize_object(client_codigos.service.cufd(SolicitudCufd=solicitud))
    )
    if not resp["transaccion"]:
        raise EmisionSinError(f"Error obteniendo CUFD: {resp['mensajesList']}")
    return resp["codigo"], resp["codigoControl"]


def _validar_homologacion(factura_det_qs):
    faltantes = []
    for det in factura_det_qs:
        prod = det.producto
        if not prod.actividad_economica_sin:
            faltantes.append(f"'{prod.descripcion}' sin actividad_economica_sin")
        if not prod.codigo_producto_sin:
            faltantes.append(f"'{prod.descripcion}' sin codigo_producto_sin")
        if not prod.unidad_medida.codigo_sin:
            faltantes.append(f"'{prod.descripcion}': unidad de medida "
                              f"'{prod.unidad_medida.descripcion}' sin codigo_sin")
    if faltantes:
        raise EmisionSinError(
            "Homologacion SIN incompleta. Faltan: " + "; ".join(faltantes)
        )


def _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora):
    cliente = factura_enc.cliente
    if cliente.nit:
        codigo_tipo_doc = CODIGO_TIPO_DOC_NIT
        numero_documento = cliente.nit
    elif cliente.ci:
        codigo_tipo_doc = CODIGO_TIPO_DOC_CI
        numero_documento = cliente.ci
    else:
        raise EmisionSinError(f"El cliente '{cliente}' no tiene CI ni NIT cargado.")

    return {
        "nitEmisor": str(empresa.nit),
        "razonSocialEmisor": empresa.razon_social,
        "municipio": sucursal.municipio,
        "numeroFactura": factura_enc.id,
        "cuf": cuf,
        "cufd": cufd,
        "codigoSucursal": sucursal.codigo_sucursal,
        "direccion": sucursal.direccion,
        "codigoPuntoVenta": codigo_punto_venta,
        "fechaEmision": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "nombreRazonSocial": cliente.razon or f"{cliente.nombres} {cliente.apellidos}",
        "codigoTipoDocumentoIdentidad": codigo_tipo_doc,
        "numeroDocumento": numero_documento,
        "codigoCliente": str(cliente.id),
        "codigoMetodoPago": int(factura_enc.codigo_metodo_pago),
        "numeroTarjeta": int(factura_enc.numero_tarjeta) if factura_enc.numero_tarjeta else None,
        "montoTotal": factura_enc.total,
        "montoTotalSujetoIva": factura_enc.total,
        "codigoMoneda": 1,
        "tipoCambio": 1,
        "montoTotalMoneda": factura_enc.total,
        "descuentoAdicional": 0,
        "leyenda": LEYENDA_DEFAULT,
        "usuario": "sistema",
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
    }


def _armar_detalle(factura_det_qs):
    detalle = []
    for det in factura_det_qs:
        prod = det.producto
        detalle.append({
            "actividadEconomica": prod.actividad_economica_sin,
            "codigoProductoSin": prod.codigo_producto_sin,
            "codigoProducto": prod.codigo,
            "descripcion": prod.descripcion,
            "cantidad": det.cantidad,
            "unidadMedida": prod.unidad_medida.codigo_sin,
            "precioUnitario": det.precio,
            "montoDescuento": det.descuento or 0,
            "subTotal": det.total,
        })
    return detalle

def emitir_factura_sin(factura_enc, codigo_punto_venta=0):
    """
    Emite factura_enc (una FacturaEnc de app.fac) ante el SIN.
    Actualiza en el mismo objeto: cuf, cufd, estado_sin, codigo_recepcion_sin,
    mensaje_sin, fecha_hora_envio_sin. Guarda los cambios.

    Lanza EmisionSinError si falta algun prerrequisito (Empresa, Sucursal,
    homologacion de productos), si hay un problema de red/timeout, o si
    el SIN rechaza el envio.
    """
    from fac.models import FacturaDet

    empresa, sucursal = _obtener_empresa_y_sucursal(0)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )

    todos_los_detalles = list(FacturaDet.objects.filter(factura=factura_enc)
                               .select_related("producto", "producto__unidad_medida"))
    ids_excluidos = set()
    for det in todos_los_detalles:
        if det.cantidad < 0 and det.id not in ids_excluidos:
            original = next(
                (d for d in todos_los_detalles
                 if d.id not in ids_excluidos
                 and d.producto_id == det.producto_id
                 and d.cantidad == -det.cantidad
                 and d.id < det.id),
                None
            )
            ids_excluidos.add(det.id)
            if original:
                ids_excluidos.add(original.id)

    factura_det_qs = [d for d in todos_los_detalles if d.id not in ids_excluidos]
    if not factura_det_qs:
        raise EmisionSinError("La factura no tiene detalle (ningun producto cargado).")
    _validar_homologacion(factura_det_qs)

    token = _obtener_token()
    fecha_hora = timezone.localtime(timezone.now())

    tiempos = {}
    t_total = time.time()

    t0 = time.time()
    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, codigo_control = _pedir_cufd(
        client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente
    )
    tiempos["cufd"] = time.time() - t0

    cuf = calcular_cuf(
        nit=empresa.nit,
        fecha_hora=fecha_hora,
        codigo_sucursal=sucursal.codigo_sucursal,
        codigo_modalidad=CODIGO_MODALIDAD,
        codigo_tipo_emision=CODIGO_TIPO_EMISION,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO,
        codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=factura_enc.id,
        codigo_punto_venta=codigo_punto_venta,
        codigo_control=codigo_control,
    )

    t0 = time.time()
    cabecera = _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora)
    detalle = _armar_detalle(factura_det_qs)
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0_WITH_COMMENTS,
    )
    xml_firmado = signer.sign(xml_sin_firmar, key=_LLAVE_PRIVADA, cert=_CERTIFICADO)
    XMLVerifier().verify(xml_firmado, x509_cert=_CERTIFICADO)

    xml_bytes = etree.tostring(xml_firmado)
    if not _XSD_SCHEMA.validate(etree.fromstring(xml_bytes)):
        raise EmisionSinError(f"XML no valido contra XSD: {_XSD_SCHEMA.error_log}")
    tiempos["armar_firmar_validar"] = time.time() - t0

    xml_gzip = gzip.compress(xml_bytes)
    hash_archivo = hashlib.sha256(xml_gzip).hexdigest().upper()

    t0 = time.time()
    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)
    solicitud_envio = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_TIPO_EMISION,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": cufd,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "archivo": xml_gzip,
        "fechaEnvio": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
    }
    resp = _llamar(
        "envío de la factura",
        lambda: serialize_object(client_facturacion.service.recepcionFactura(
            SolicitudServicioRecepcionFactura=solicitud_envio
        ))
    )
    tiempos["envio_sin"] = time.time() - t0
    tiempos["total"] = time.time() - t_total
    print(
        f"[emitir_factura_sin] Factura {factura_enc.id}: "
        f"CUFD={tiempos['cufd']:.1f}s, "
        f"armar/firmar/validar={tiempos['armar_firmar_validar']:.1f}s, "
        f"envio_SIN={tiempos['envio_sin']:.1f}s, "
        f"TOTAL={tiempos['total']:.1f}s"
    )

    factura_enc.cuf = cuf
    factura_enc.cufd = cufd
    factura_enc.fecha_hora_envio_sin = timezone.now()
    factura_enc.codigo_recepcion_sin = resp.get("codigoRecepcion")
    factura_enc.mensaje_sin = str(resp.get("mensajesList") or "")
    factura_enc.xml_firmado = xml_bytes.decode('utf-8')

    if resp["transaccion"] and resp.get("codigoEstado") == 908:
        factura_enc.estado_sin = factura_enc.SIN_VALIDADA
    elif resp["transaccion"] and resp.get("codigoEstado") == 901:
        factura_enc.estado_sin = factura_enc.SIN_PENDIENTE
    else:
        factura_enc.estado_sin = factura_enc.SIN_OBSERVADA

    factura_enc.save()

    if not resp["transaccion"]:
        raise EmisionSinError(f"El SIN rechazo la factura: {resp['mensajesList']}")

    return factura_enc


def emitir_nota_credito_debito_sin(nota_credito_debito, codigo_punto_venta=0):
    """
    Emite una Nota de Credito-Debito ante el SIN, para corregir/ajustar
    una factura ya validada -- unica version soportada por ahora:
    DEVOLUCION TOTAL (decision del 26/08/2026, ver docstring de
    NotaCreditoDebito en fac/models.py para el detalle completo).

    Usa el MISMO servicio recepcionFactura que una factura normal --
    no existe operacion SOAP separada para NCD. Se distingue por
    tipoFacturaDocumento=3 y codigoDocumentoSector=24 (fijo segun el
    XSD oficial notaElectronicaCreditoDebito.xsd).

    DESBLOQUEADO 07/09/2026: el soporte del SIN confirmo la formula
    real que valida el servicio --
        montoTotalOriginal = SUMA(subTotal) donde codigoDetalleTransaccion=1,
        y "el monto de subtotales con transaccion 1 debe ser igual a
        los subtotales de la factura original" -- confirma que hay que
        reconstruir TODAS las lineas de la factura original con
        codigoDetalleTransaccion=1 (no un resumen, no un item
        cualquiera). Para devolucion TOTAL (unica version soportada),
        esas mismas lineas se repiten identicas con
        codigoDetalleTransaccion=2 (la porcion devuelta = el total).
        La duda que motivo el bloqueo original (el ejemplo oficial
        confuso, con productos distintos entre las dos transacciones)
        queda resuelta: ese ejemplo no representaba la regla real.

    No se persiste un detalle propio para la NCD: se arma en el
    momento a partir de FacturaDet de la factura original, fuente
    unica de verdad.

    Actualiza nota_credito_debito con cuf, cufd, estado_sin,
    codigo_recepcion_sin, mensaje_sin, xml_firmado. Lanza
    EmisionSinError si falta un prerrequisito, hay un problema de
    red/timeout, o el SIN rechaza el envio -- mismo patron que
    emitir_factura_sin.
    """
    from fac.models import FacturaDet

    factura_original = nota_credito_debito.factura_original

    if not factura_original.cuf:
        raise EmisionSinError(
            "La factura original no tiene CUF -- nunca fue emitida ante el SIN."
        )

    detalles_originales = list(
        FacturaDet.objects.filter(factura=factura_original)
        .select_related("producto", "producto__unidad_medida")
    )
    if not detalles_originales:
        raise EmisionSinError("La factura original no tiene detalle (ningun producto cargado).")

    empresa, sucursal = _obtener_empresa_y_sucursal(0)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )

    cliente = factura_original.cliente
    if cliente.nit:
        codigo_tipo_doc = CODIGO_TIPO_DOC_NIT
        numero_documento = cliente.nit
    elif cliente.ci:
        codigo_tipo_doc = CODIGO_TIPO_DOC_CI
        numero_documento = cliente.ci
    else:
        raise EmisionSinError(f"El cliente '{cliente}' no tiene CI ni NIT cargado.")

    token = _obtener_token()
    fecha_hora = timezone.localtime(timezone.now())

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, codigo_control = _pedir_cufd(
        client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente
    )

    cuf = calcular_cuf(
        nit=empresa.nit,
        fecha_hora=fecha_hora,
        codigo_sucursal=sucursal.codigo_sucursal,
        codigo_modalidad=CODIGO_MODALIDAD,
        codigo_tipo_emision=CODIGO_TIPO_EMISION,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO_AJUSTE,
        codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR_NCD,
        numero_factura=nota_credito_debito.id,
        codigo_punto_venta=codigo_punto_venta,
        codigo_control=codigo_control,
    )

    cabecera = {
        "nitEmisor": str(empresa.nit),
        "razonSocialEmisor": empresa.razon_social,
        "municipio": sucursal.municipio,
        "telefono": None,
        "numeroNotaCreditoDebito": nota_credito_debito.id,
        "cuf": cuf,
        "cufd": cufd,
        "codigoSucursal": sucursal.codigo_sucursal,
        "direccion": sucursal.direccion,
        "codigoPuntoVenta": codigo_punto_venta,
        "fechaEmision": fecha_hora.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "nombreRazonSocial": cliente.razon or f"{cliente.nombres} {cliente.apellidos}",
        "codigoTipoDocumentoIdentidad": codigo_tipo_doc,
        "numeroDocumento": numero_documento,
        "complemento": None,
        "codigoCliente": str(cliente.id),
        "numeroFactura": factura_original.id,
        "numeroAutorizacionCuf": factura_original.cuf,
        "fechaEmisionFactura": timezone.localtime(factura_original.fecha).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "montoTotalOriginal": factura_original.total,
        "montoTotalDevuelto": nota_credito_debito.monto_total_devuelto,
        "montoDescuentoCreditoDebito": None,
        "montoEfectivoCreditoDebito": nota_credito_debito.monto_efectivo_credito_debito,
        "codigoExcepcion": None,
        "leyenda": LEYENDA_DEFAULT,
        "usuario": "sistema",
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR_NCD,
    }

    # Devolucion TOTAL (unica version soportada): cada linea de la
    # factura original aparece DOS VECES -- codigoDetalleTransaccion=1
    # (la operacion original, reconstruida completa -- confirmado por
    # el SIN que su suma debe igualar montoTotalOriginal) y
    # codigoDetalleTransaccion=2 (la porcion devuelta -- identica,
    # porque se devuelve todo).
    detalle = []
    for det in detalles_originales:
        prod = det.producto
        linea_base = {
            "actividadEconomica": prod.actividad_economica_sin,
            "codigoProductoSin": prod.codigo_producto_sin,
            "codigoProducto": prod.codigo,
            "descripcion": prod.descripcion,
            "cantidad": det.cantidad,
            "unidadMedida": prod.unidad_medida.codigo_sin,
            "precioUnitario": det.precio,
            "montoDescuento": det.descuento or 0,
            "subTotal": det.total,
        }
        detalle.append({**linea_base, "codigoDetalleTransaccion": 1})
        detalle.append({**linea_base, "codigoDetalleTransaccion": 2})

    xml_sin_firmar = construir_nota_credito_debito_xml(cabecera, detalle)

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0_WITH_COMMENTS,
    )
    xml_firmado = signer.sign(xml_sin_firmar, key=_LLAVE_PRIVADA, cert=_CERTIFICADO)
    XMLVerifier().verify(xml_firmado, x509_cert=_CERTIFICADO)

    xml_bytes = etree.tostring(xml_firmado)
    if not _XSD_SCHEMA_NCD.validate(etree.fromstring(xml_bytes)):
        raise EmisionSinError(f"XML de NCD no valido contra XSD: {_XSD_SCHEMA_NCD.error_log}")

    xml_gzip = gzip.compress(xml_bytes)
    hash_archivo = hashlib.sha256(xml_gzip).hexdigest().upper()

    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)
    solicitud_envio = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR_NCD,
        "codigoEmision": CODIGO_TIPO_EMISION,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": cufd,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO_AJUSTE,
        "archivo": xml_gzip,
        "fechaEnvio": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
    }
    resp = _llamar(
        "envío de la Nota de Crédito-Débito",
        lambda: serialize_object(client_facturacion.service.recepcionFactura(
            SolicitudServicioRecepcionFactura=solicitud_envio
        ))
    )

    nota_credito_debito.cuf = cuf
    nota_credito_debito.cufd = cufd
    nota_credito_debito.codigo_recepcion_sin = resp.get("codigoRecepcion")
    nota_credito_debito.mensaje_sin = str(resp.get("mensajesList") or "")
    nota_credito_debito.xml_firmado = xml_bytes.decode('utf-8')

    if resp["transaccion"] and resp.get("codigoEstado") == 908:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_VALIDADA
    elif resp["transaccion"] and resp.get("codigoEstado") == 901:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_PENDIENTE
    else:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_OBSERVADA

    nota_credito_debito.save()

    if not resp["transaccion"]:
        raise EmisionSinError(f"El SIN rechazo la Nota de Credito-Debito: {resp['mensajesList']}")

    return nota_credito_debito


def anular_factura_sin(factura_enc, codigo_motivo, codigo_punto_venta=0):
    """
    Anula ante el SIN una factura ya validada. Usa el servicio real
    confirmado en la Etapa VII de certificacion
    (prototipo/sin/probar_anulacion_v2.py): anulacionFactura, WSDL
    ServicioFacturacionCompraVenta.
    """
    if not factura_enc.cuf:
        raise EmisionSinError(
            "La factura no tiene CUF -- nunca fue emitida ante el SIN, no hay nada que anular."
        )

    empresa, sucursal = _obtener_empresa_y_sucursal(0)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente)

    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)
    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_TIPO_EMISION,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": cufd,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "codigoMotivo": codigo_motivo,
        "cuf": factura_enc.cuf,
    }
    resp = _llamar(
        "anulación de la factura",
        lambda: serialize_object(client_facturacion.service.anulacionFactura(
            SolicitudServicioAnulacionFactura=solicitud
        ))
    )

    factura_enc.codigo_motivo_anulacion_sin = codigo_motivo
    factura_enc.fecha_anulacion_sin = timezone.now()
    factura_enc.mensaje_sin = str(resp.get("mensajesList") or "")

    if resp.get("transaccion") and resp.get("codigoEstado") == 905:
        factura_enc.estado_sin = factura_enc.SIN_ANULADA
        factura_enc.save()
        return factura_enc

    factura_enc.save()
    raise EmisionSinError(f"El SIN rechazo la anulacion: {resp.get('mensajesList')}")


def revertir_anulacion_sin(factura_enc, codigo_punto_venta=0):
    """
    Revierte ante el SIN la anulacion de una factura. Usa el servicio
    real confirmado en la Etapa VIII de certificacion
    (prototipo/sin/probar_reversion.py): reversionAnulacionFactura,
    WSDL ServicioFacturacionCompraVenta.
    """
    if not factura_enc.cuf:
        raise EmisionSinError(
            "La factura no tiene CUF -- nunca fue emitida ante el SIN."
        )
    if factura_enc.estado_sin != factura_enc.SIN_ANULADA:
        raise EmisionSinError(
            "Solo se puede revertir la anulacion de una factura que este "
            f"anulada ante el SIN (estado actual: {factura_enc.get_estado_sin_display()})."
        )

    empresa, sucursal = _obtener_empresa_y_sucursal(0)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente)

    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)
    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_TIPO_EMISION,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": cufd,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "cuf": factura_enc.cuf,
    }
    resp = _llamar(
        "reversión de la anulación",
        lambda: serialize_object(client_facturacion.service.reversionAnulacionFactura(
            SolicitudServicioReversionAnulacionFactura=solicitud
        ))
    )

    factura_enc.mensaje_sin = str(resp.get("mensajesList") or "")

    if resp.get("transaccion") and resp.get("codigoEstado") == 907:
        factura_enc.estado_sin = factura_enc.SIN_REVERTIDA
        factura_enc.fecha_reversion_sin = timezone.now()
        factura_enc.save()
        return factura_enc

    factura_enc.save()
    raise EmisionSinError(f"El SIN rechazo la reversion: {resp.get('mensajesList')}")


def registrar_punto_venta_sin(sucursal, nombre_punto_venta, descripcion, codigo_tipo_punto_venta):
    """
    Registra un Punto de Venta ante el SIN (servicio registroPuntoVenta,
    WSDL FacturacionOperaciones) y devuelve el codigoPuntoVenta que
    ASIGNA el SIN como respuesta -- nunca se elige a mano.
    """
    empresa = Empresa.objects.first()
    if not empresa:
        raise EmisionSinError("No hay configuracion de Empresa cargada (completar en /fe/).")
    if not empresa.nit:
        raise EmisionSinError("La Empresa no tiene NIT cargado.")
    if not empresa.codigo_sistema:
        raise EmisionSinError("La Empresa no tiene codigo_sistema cargado "
                               "(Autorizacion de Sistemas pendiente ante el SIN).")
    if not sucursal.codigo_cuis:
        raise EmisionSinError(
            f"La Sucursal '{sucursal}' no tiene CUIS cargado -- "
            "necesario para registrar un punto de venta dentro de ella."
        )

    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()
    client = _cliente_soap(WSDL_OPERACIONES, token)

    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "codigoTipoPuntoVenta": codigo_tipo_punto_venta,
        "cuis": sucursal.codigo_cuis,
        "descripcion": descripcion,
        "nit": empresa.nit,
        "nombrePuntoVenta": nombre_punto_venta,
    }

    resp = _llamar(
        "registro de punto de venta",
        lambda: serialize_object(client.service.registroPuntoVenta(
            SolicitudRegistroPuntoVenta=solicitud
        ))
    )

    if not resp.get("transaccion"):
        raise EmisionSinError(f"El SIN rechazo el registro del punto de venta: {resp.get('mensajesList')}")

    return resp.get("codigoPuntoVenta")