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
from .factura_xml import construir_factura_xml
from .models import Empresa, Sucursal

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"

# Limites de tiempo para las llamadas al SIN. TIMEOUT_CONEXION es cuanto
# esperar a que el servidor conteste al establecer la conexion (WSDL,
# handshake). TIMEOUT_OPERACION es cuanto esperar la respuesta de una
# operacion SOAP real (cuis, cufd, recepcionFactura, etc.) -- mas alto
# porque el SIN puede tardar en procesar, sobre todo en Piloto.
TIMEOUT_CONEXION = 15
TIMEOUT_OPERACION = 30

# Rutas del certificado real. Configurables por variable de entorno para
# no atar el codigo a la ubicacion actual (prototipo/sin/certificado_real).
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

# Constantes de negocio confirmadas en la certificacion Piloto -- no
# cambian de una factura a otra en este sistema (todas Compra-Venta,
# electronica en linea, con derecho a credito fiscal).
CODIGO_AMBIENTE_PILOTO = 2
CODIGO_AMBIENTE_PRODUCCION = 1
CODIGO_MODALIDAD = 1          # Electronica en Linea
CODIGO_TIPO_EMISION = 1       # En linea
CODIGO_DOCUMENTO_SECTOR = 1   # Compra y Venta
TIPO_FACTURA_DOCUMENTO = 1    # Con derecho a credito fiscal
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
        timeout=TIMEOUT_CONEXION,           # timeout para bajar el WSDL/XSD
        operation_timeout=TIMEOUT_OPERACION,  # timeout para cada llamada SOAP real
    )
    try:
        return Client(wsdl=wsdl, transport=transport)
    except (RequestException, ZeepError, socket.timeout) as e:
        raise EmisionSinError(
            f"No se pudo conectar con el SIN (servicio no disponible o sin respuesta): {e}"
        )


def _llamar(descripcion, funcion, *args, **kwargs):
    """
    Envuelve cualquier llamada de red al SIN (via zeep) para que un
    timeout, corte de conexion, o error de red se convierta en un
    EmisionSinError con mensaje claro -- en vez de que la operacion
    quede esperando indefinidamente o lance una excepcion generica
    que el resto del sistema no sepa interpretar.
    """
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


def _pedir_cufd(client_codigos, empresa, sucursal, codigo_punto_venta, codigo_ambiente):
    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cuis": sucursal.codigo_cuis,
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
    """
    Revisa que cada producto de la factura tenga su homologacion SIN
    completa (actividad economica, codigo de producto, y que su unidad
    de medida tenga codigo_sin). Si falta algo, error claro indicando
    exactamente que producto y que campo falta -- no se adivina nada.
    """
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
        "codigoMetodoPago": 1,  # Efectivo -- unico metodo modelado hoy
        "montoTotal": factura_enc.total,
        "montoTotalSujetoIva": factura_enc.total,
        "codigoMoneda": 1,      # Bolivianos -- unica moneda modelada hoy
        "tipoCambio": 1,
        "montoTotalMoneda": factura_enc.total,
        "descuentoAdicional": factura_enc.descuento or 0,
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
            "subTotal": det.sub_total,
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
    from fac.models import FacturaDet  # import local para evitar acoplar apps al importar el modulo

    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_punto_venta and 0 or 0)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )

    factura_det_qs = FacturaDet.objects.filter(factura=factura_enc).select_related(
        "producto", "producto__unidad_medida"
    )
    if not factura_det_qs.exists():
        raise EmisionSinError("La factura no tiene detalle (ningun producto cargado).")
    _validar_homologacion(factura_det_qs)

    token = _obtener_token()

    # Momento REAL de la emision -- no el de creacion del registro en BD
    # (que puede ser mucho mas viejo). El SIN exige que esta fecha este
    # muy cerca del momento de envio (tolerancia de unos pocos minutos).
    fecha_hora = timezone.localtime(timezone.now())

    # --- 1. CUFD fresco ---
    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, codigo_control = _pedir_cufd(
        client_codigos, empresa, sucursal, codigo_punto_venta, codigo_ambiente
    )

    # --- 2. Calcular el CUF ---
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

    # --- 3. Armar XML ---
    cabecera = _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora)
    detalle = _armar_detalle(factura_det_qs)
    xml_sin_firmar = construir_factura_xml(cabecera, detalle)

    # --- 4. Firmar ---
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

    # --- 5. Validar contra XSD ---
    xsd_doc = etree.parse(ARCHIVO_XSD)
    schema = etree.XMLSchema(xsd_doc)
    xml_bytes = etree.tostring(xml_firmado)
    if not schema.validate(etree.fromstring(xml_bytes)):
        raise EmisionSinError(f"XML no valido contra XSD: {schema.error_log}")

    # --- 6. Comprimir + hash ---
    xml_gzip = gzip.compress(xml_bytes)
    hash_archivo = hashlib.sha256(xml_gzip).hexdigest().upper()

    # --- 7. Enviar ---
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
        "cuis": sucursal.codigo_cuis,
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

    # --- 8. Guardar resultado en la factura ---
    factura_enc.cuf = cuf
    factura_enc.cufd = cufd
    factura_enc.fecha_hora_envio_sin = timezone.now()
    factura_enc.codigo_recepcion_sin = resp.get("codigoRecepcion")
    factura_enc.mensaje_sin = str(resp.get("mensajesList") or "")

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


def anular_factura_sin(factura_enc, codigo_motivo, codigo_punto_venta=0):
    """
    Anula ante el SIN una factura ya validada. Usa el servicio real
    confirmado en la Etapa VII de certificacion
    (prototipo/sin/probar_anulacion_v2.py): anulacionFactura, WSDL
    ServicioFacturacionCompraVenta.

    codigo_motivo: codigo del catalogo MOTIVOS_ANULACION (app.catalogos),
    1-4. Se pasa explicito desde la vista, NUNCA se adivina/hardcodea
    aca -- distintas anulaciones pueden tener distinto motivo real.

    Solo aplica a facturas que ya tienen CUF (fueron emitidas). Si el
    SIN confirma (codigoEstado 905), pasa estado_sin a SIN_ANULADA. Si
    rechaza (o hay timeout/error de red), lanza EmisionSinError con el
    detalle -- el campo local 'anulado' de FacturaEnc NO se toca aca,
    eso lo decide la vista de app.fac despues de confirmar que el SIN
    acepto.
    """
    if not factura_enc.cuf:
        raise EmisionSinError(
            "La factura no tiene CUF -- nunca fue emitida ante el SIN, no hay nada que anular."
        )

    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_punto_venta and 0 or 0)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    # CUFD fresco, igual que en la emision -- necesario para autenticar
    # esta operacion puntual ante el SIN.
    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, codigo_punto_venta, codigo_ambiente)

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
        "cuis": sucursal.codigo_cuis,
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

    Reglas de negocio (confirmadas por normativa, ver
    prototipo/sin/README.md):
      - Solo se puede revertir UNA VEZ por factura.
      - Plazo: hasta el dia 9 del mes siguiente a la emision original.
        Esa validacion de plazo se hace en la vista de app.fac (misma
        funcion _dentro_plazo_anulacion que ya se usa para anular),
        no aca -- este servicio solo habla con el SIN.
      - No aplica a facturas emitidas en modo offline/contingencia.

    Solo aplica a facturas con estado_sin == SIN_ANULADA. Si el SIN
    confirma (codigoEstado 907), pasa estado_sin a SIN_REVERTIDA. Si
    rechaza (o hay timeout/error de red), lanza EmisionSinError -- el
    flag local 'anulado' NO se toca aca, eso lo decide la vista
    despues de confirmar el exito.
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

    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_punto_venta and 0 or 0)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, codigo_punto_venta, codigo_ambiente)

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
        "cuis": sucursal.codigo_cuis,
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