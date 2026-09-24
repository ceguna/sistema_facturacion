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
import io
import os
import socket
import tarfile
import time
from datetime import timedelta

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
from django.db.models import F

from .cuf import calcular_cuf
from .factura_xml import construir_factura_xml, construir_nota_credito_debito_xml
from .models import Empresa, Sucursal, PuntoVenta, CUFDVigente

WSDL_CODIGOS = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionCodigos?wsdl"
WSDL_FACTURACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionCompraVenta?wsdl"
WSDL_OPERACIONES = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionOperaciones?wsdl"
# CORREGIDO 12/09/2026 -- confirmado en el PDF "Solicitud de Autorizacion
# de Sistema Informatico de Facturacion" (Nº 9454) que la Nota de
# Credito-Debito usa un WSDL COMPLETAMENTE DISTINTO al de facturas
# normales -- nunca se habia usado este, por eso el error 995
# ("servicio no disponible") persistia sin importar que otro dato se
# corrigiera. Operaciones confirmadas dentro de este WSDL (via script
# de inspeccion, 12/09/2026): recepcionDocumentoAjuste,
# anulacionDocumentoAjuste, reversionAnulacionDocumentoAjuste,
# verificacionEstadoDocumentoAjuste, verificarComunicacion.
WSDL_DOCUMENTO_AJUSTE = "https://pilotosiatservicios.impuestos.gob.bo/v2/ServicioFacturacionDocumentoAjuste?wsdl"

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
CODIGO_TIPO_EMISION_OFFLINE = 2   # Fuera de linea (contingencia, Fase A)
# Vigencia que se le da al CUFD cacheado (CUFDVigente) para firmar
# offline -- conservador, mas corto que el maximo real documentado
# (~24-48h) para no arriesgarse a firmar con uno que el SIN ya
# considere vencido del otro lado si la contingencia se extiende.
HORAS_VIGENCIA_CUFD_OFFLINE = 20
CODIGO_DOCUMENTO_SECTOR = 1   # Compra y Venta
TIPO_FACTURA_DOCUMENTO = 1    # Con derecho a credito fiscal
# REVERTIDO 12/09/2026 -- el cambio del 10/09/2026 (poner esto en 24,
# "confirmado" por el soporte) resulto ser INCORRECTO. Con el WSDL
# correcto (ServicioFacturacionDocumentoAjuste, ver WSDL_DOCUMENTO_AJUSTE
# mas abajo) el propio SIN respondio explicito: "EL PARAMETRO TIPO
# FACTURA DOCUMENTO ES INVALIDO Tipo de factura esperado 3, enviado 24"
# (codigo 915). El consejo de "24 en ambos" probablemente se referia
# solo a codigoDocumentoSector (que nunca cambio, siempre fue 24) -- se
# interpreto mal como que TAMBIEN aplicaba a este campo. Ese error
# quedo OCULTO todo este tiempo porque el 995 (WSDL equivocado) pasaba
# primero y nunca dejaba llegar la solicitud tan lejos como para
# validar este dato.
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


class SinConexionError(EmisionSinError):
    """
    Subclase especifica (Fase A, contingencia, 21/09/2026) para cuando
    el SIN esta genuinamente INALCANZABLE (timeout, DNS, conexion
    rechazada) -- a diferencia de un EmisionSinError generico, que
    tambien cubre rechazos de DATOS (el SIN respondio, pero no acepto
    la factura). Todo el codigo que ya hace "except EmisionSinError"
    sigue funcionando igual (es subclase), pero el nuevo flujo de
    emision automatica (fac/views.py) puede distinguir este caso
    puntual y mandar la factura a la cola offline en vez de solo
    mostrar un error.
    """
    pass


def _cliente_soap(wsdl, token, history=None):
    session = Session()
    session.headers.update({"apikey": f"TokenApi {token}"})
    transport = Transport(
        session=session,
        timeout=TIMEOUT_CONEXION,
        operation_timeout=TIMEOUT_OPERACION,
    )
    plugins = [history] if history else []
    try:
        return Client(wsdl=wsdl, transport=transport, plugins=plugins)
    except (RequestException, ZeepError, socket.timeout) as e:
        raise SinConexionError(
            f"No se pudo conectar con el SIN (servicio no disponible o sin respuesta): {e}"
        )


def _llamar(descripcion, funcion, *args, **kwargs):
    try:
        return funcion(*args, **kwargs)
    except (RequestException, ZeepError, socket.timeout) as e:
        raise SinConexionError(
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

    # Cachea el CUFD (Fase A, contingencia, 21/09/2026): efecto
    # secundario de CUALQUIER pedido de CUFD exitoso -- es lo que
    # permite seguir firmando facturas OFFLINE mas adelante si el SIN
    # se vuelve inalcanzable, sin depender de haber tenido que pedir un
    # CUFD justo en ese momento (ver _obtener_cufd_offline).
    CUFDVigente.objects.update_or_create(
        sucursal=sucursal, codigo_punto_venta=codigo_punto_venta,
        defaults={'cufd': resp["codigo"], 'codigo_control': resp["codigoControl"]}
    )

    return resp["codigo"], resp["codigoControl"]


def _obtener_cufd_offline(sucursal, codigo_punto_venta):
    """
    Devuelve (cufd, codigo_control) del ultimo CUFD cacheado para esta
    Sucursal+punto de venta, si todavia esta dentro de la ventana de
    vigencia que le damos (HORAS_VIGENCIA_CUFD_OFFLINE) -- None si no
    hay cache, o si es demasiado viejo para confiar en el sin
    confirmarlo con el SIN (lo cual, si estamos offline, no se puede
    hacer de todas formas).
    """
    cache = CUFDVigente.objects.filter(
        sucursal=sucursal, codigo_punto_venta=codigo_punto_venta
    ).first()
    if not cache:
        return None
    limite = timezone.now() - timedelta(hours=HORAS_VIGENCIA_CUFD_OFFLINE)
    if cache.fecha_obtencion < limite:
        return None
    return cache.cufd, cache.codigo_control


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


def _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora, leyenda):
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
        "leyenda": leyenda,
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
    # Fase 2 (20/09/2026): usa la sucursal REAL de esta factura, no
    # Casa Matriz fijo -- antes el sistema solo podia emitir contra
    # codigo_sucursal=0 sin importar cuantas Sucursal hubiera cargadas.
    # None (dato viejo sin migrar) cae en 0 -- mismo comportamiento de
    # siempre.
    codigo_sucursal = factura_enc.sucursal.codigo_sucursal if factura_enc.sucursal else 0
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )

    factura_det_qs = _detalle_neto(factura_enc)
    if not factura_det_qs:
        raise EmisionSinError("La factura no tiene detalle (ningun producto cargado).")
    _validar_homologacion(factura_det_qs)

    # Leyenda (checklist SIN Fase II, punto 4): se elige UNA sola vez por
    # emision, priorizando la actividad economica del primer producto de
    # la factura, y se guarda en factura_enc -- asi el texto mandado al
    # SIN y el que se imprime despues en la representacion grafica son
    # siempre el mismo (ver comentario del campo en fac/models.py).
    from catalogos.services import elegir_leyenda_aleatoria
    actividad_primera_linea = factura_det_qs[0].producto.actividad_economica_sin
    leyenda = elegir_leyenda_aleatoria(actividad_primera_linea) or LEYENDA_DEFAULT
    factura_enc.leyenda = leyenda

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
    cabecera = _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora, leyenda)
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
    # codigo_control ya se calculaba (se necesita para derivar el CUF)
    # pero nunca se guardaba -- agregado 17/09/2026, lo exige el
    # verificador publico del SIN junto al resto de los datos impresos.
    factura_enc.codigo_control = codigo_control
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


def _detalle_neto(factura_enc):
    """
    Mismo filtro de lineas de reversion que emitir_factura_sin -- se
    extrajo aca porque emitir_factura_offline tambien lo necesita, y no
    tiene sentido reproducir la logica de exclusion de a mano en dos
    lugares (a diferencia del bloque de firmado/validacion XSD, que se
    deja duplicado a proposito por estabilidad, este filtro es puro
    calculo sin efectos secundarios -- extraerlo no arriesga nada).
    """
    from fac.models import FacturaDet
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
    return [d for d in todos_los_detalles if d.id not in ids_excluidos]


MOTIVO_EVENTO_INACCESIBILIDAD_SIN = 2  # "Inaccesibilidad al servicio web de la Administración Tributaria"


def emitir_factura_offline(factura_enc, codigo_punto_venta=0):
    """
    Firma factura_enc en modo CONTINGENCIA (codigoTipoEmision=2), sin
    contactar al SIN -- para cuando emitir_factura_sin fallo con
    SinConexionError (Fase A, checklist SIN Fase II puntos 8/12/14).

    No envia nada todavia: solo calcula el CUF offline (usando el
    ultimo CUFD cacheado, ver CUFDVigente/_obtener_cufd_offline), firma
    y valida el XML contra el XSD igual que en linea, y agrupa la
    factura bajo un EventoSignificativo abierto (uno por
    sucursal+punto de venta -- se reutiliza el mismo evento mientras
    siga abierto, en vez de crear uno nuevo por cada factura offline).
    Reportar el evento y enviar el paquete al SIN es la Fase B.

    Deja estado_sin=SIN_PENDIENTE -- eso ya alcanza para que
    FacturaEnc.reportada_ante_sin/puede_editarse bloqueen edicion y
    eliminacion (la factura ya tiene un CUF real, borrarla dejaria un
    hueco en la numeracion correlativa).

    Lanza EmisionSinError (no SinConexionError -- este es terminal, no
    tiene sentido que el llamador lo reintente como si fuera offline
    de nuevo) si ni siquiera hay un CUFD cacheado utilizable -- ahi no
    hay forma segura de continuar en contingencia.
    """
    from fac.models import EventoSignificativo

    codigo_sucursal = factura_enc.sucursal.codigo_sucursal if factura_enc.sucursal else 0
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)

    factura_det_qs = _detalle_neto(factura_enc)
    if not factura_det_qs:
        raise EmisionSinError("La factura no tiene detalle (ningun producto cargado).")
    _validar_homologacion(factura_det_qs)

    cache_cufd = _obtener_cufd_offline(sucursal, codigo_punto_venta)
    if not cache_cufd:
        raise EmisionSinError(
            "No hay un CUFD offline disponible para continuar en modo contingencia "
            "(contingencia demasiado prolongada, o todavía no hubo ninguna emisión "
            "exitosa hoy que lo haya guardado). Reintente cuando vuelva la conexión."
        )
    cufd, codigo_control = cache_cufd

    from catalogos.services import elegir_leyenda_aleatoria
    actividad_primera_linea = factura_det_qs[0].producto.actividad_economica_sin
    leyenda = elegir_leyenda_aleatoria(actividad_primera_linea) or LEYENDA_DEFAULT

    fecha_hora = timezone.localtime(timezone.now())
    cuf = calcular_cuf(
        nit=empresa.nit,
        fecha_hora=fecha_hora,
        codigo_sucursal=sucursal.codigo_sucursal,
        codigo_modalidad=CODIGO_MODALIDAD,
        codigo_tipo_emision=CODIGO_TIPO_EMISION_OFFLINE,
        codigo_tipo_factura=TIPO_FACTURA_DOCUMENTO,
        codigo_documento_sector=CODIGO_DOCUMENTO_SECTOR,
        numero_factura=factura_enc.id,
        codigo_punto_venta=codigo_punto_venta,
        codigo_control=codigo_control,
    )

    cabecera = _armar_cabecera(factura_enc, empresa, sucursal, cuf, cufd, codigo_punto_venta, fecha_hora, leyenda)
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
        raise EmisionSinError(f"XML offline no valido contra XSD: {_XSD_SCHEMA.error_log}")

    evento = EventoSignificativo.objects.filter(
        sucursal=factura_enc.sucursal, codigo_punto_venta=codigo_punto_venta,
        estado_evento=EventoSignificativo.ABIERTO,
    ).first()
    if not evento:
        evento = EventoSignificativo.objects.create(
            sucursal=factura_enc.sucursal, codigo_punto_venta=codigo_punto_venta,
            codigo_motivo=MOTIVO_EVENTO_INACCESIBILIDAD_SIN,
            descripcion="Inaccesibilidad al servicio web del SIN detectada automáticamente "
                        f"al intentar emitir la factura {factura_enc.id}.",
            fecha_hora_inicio=fecha_hora,
            cufd_evento=cufd,
        )

    factura_enc.cuf = cuf
    factura_enc.cufd = cufd
    factura_enc.codigo_control = codigo_control
    factura_enc.leyenda = leyenda
    factura_enc.xml_firmado = xml_bytes.decode('utf-8')
    factura_enc.mensaje_sin = (
        "Emitida en modo contingencia (sin conexión al SIN) — pendiente de reportar "
        "y transmitir automáticamente en cuanto vuelva la conexión."
    )
    factura_enc.estado_sin = factura_enc.SIN_PENDIENTE
    factura_enc.evento_significativo = evento
    factura_enc.save()

    return factura_enc


def cerrar_evento_y_enviar_paquete(evento):
    """
    Fase B (contingencia, 21/09/2026): cierra un EventoSignificativo
    ABIERTO reportandolo de verdad al SIN, y envia en un solo paquete
    todas las facturas offline que quedaron agrupadas bajo el (las que
    ya tienen estado_sin=SIN_PENDIENTE y todavia no estan en ningun
    PaqueteFacturas). Reutiliza el patron ya validado en
    prototipo/sin/generar_volumen_paquetes.py: CUFD nuevo para
    reportar -> registroEventoSignificativo -> TAR+gzip de los XML ya
    firmados (Fase A) -> recepcionPaqueteFactura.

    NO valida la recepcion todavia -- el SIN devuelve el paquete como
    "pendiente de revision" al enviarlo, la confirmacion real llega
    con validar_paquete_sin() en una corrida posterior (Fase C decide
    cuando). Se llama solo cuando ya se confirmo que hay conexion de
    nuevo -- si vuelve a fallar aca, el evento sigue abierto y el
    llamador (Fase C) simplemente reintenta en el siguiente ciclo.

    Lanza EmisionSinError/SinConexionError igual que el resto de las
    funciones de este modulo -- no atrapa nada, el llamador decide que
    hacer con la falla.
    """
    from fac.models import FacturaEnc, PaqueteFacturas

    if evento.estado_evento == evento.CERRADO:
        raise EmisionSinError(f"El evento #{evento.id} ya esta cerrado.")

    facturas_del_evento = list(
        FacturaEnc.objects.filter(evento_significativo=evento, paquete__isnull=True)
        .order_by('id')
    )
    if not facturas_del_evento:
        raise EmisionSinError(
            f"El evento #{evento.id} no tiene ninguna factura pendiente de empaquetar."
        )

    empresa, sucursal = _obtener_empresa_y_sucursal(evento.sucursal.codigo_sucursal)
    cuis = _obtener_cuis_para_punto_venta(sucursal, evento.codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    # --- 1. CUFD nuevo para REPORTAR (distinto del que ya se uso para
    # firmar las facturas offline, evento.cufd_evento -- el SIN exige
    # los dos CUFD distintos, confirmado en prototipo/sin/README.md). ---
    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd_reporte, _ = _pedir_cufd(
        client_codigos, empresa, sucursal, cuis, evento.codigo_punto_venta, codigo_ambiente
    )

    # --- 2. Registrar el evento significativo ---
    fecha_fin = timezone.now()
    client_operaciones = _cliente_soap(WSDL_OPERACIONES, token)
    solicitud_evento = {
        "codigoAmbiente": codigo_ambiente,
        "codigoMotivoEvento": evento.codigo_motivo,
        "codigoPuntoVenta": evento.codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": cufd_reporte,
        "cufdEvento": evento.cufd_evento,
        "cuis": cuis,
        "descripcion": evento.descripcion,
        "fechaHoraFinEvento": fecha_fin,
        "fechaHoraInicioEvento": evento.fecha_hora_inicio,
        "nit": empresa.nit,
    }
    resp_evento = _llamar(
        "registro del evento significativo",
        lambda: serialize_object(client_operaciones.service.registroEventoSignificativo(
            SolicitudEventoSignificativo=solicitud_evento
        ))
    )
    if not resp_evento.get("transaccion"):
        raise EmisionSinError(f"El SIN rechazo el evento significativo: {resp_evento.get('mensajesList')}")

    evento.cufd_reporte = cufd_reporte
    evento.codigo_recepcion_evento_significativo = resp_evento.get("codigoRecepcionEventoSignificativo")
    evento.fecha_hora_fin = fecha_fin
    evento.estado_evento = evento.CERRADO
    evento.save()

    # --- 3. Empaquetar los XML ya firmados (Fase A) en TAR+gzip ---
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for enc in facturas_del_evento:
            contenido = enc.xml_firmado.encode('utf-8')
            info = tarfile.TarInfo(name=f"factura_{enc.id}.xml")
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))
    tar_gzip = gzip.compress(tar_buffer.getvalue())
    hash_archivo = hashlib.sha256(tar_gzip).hexdigest().upper()

    paquete = PaqueteFacturas.objects.create(
        evento=evento,
        cantidad_facturas=len(facturas_del_evento),
        hash_archivo=hash_archivo,
        fecha_limite_envio=fecha_fin + timedelta(hours=48),
        estado_paquete=PaqueteFacturas.EN_ARMADO,
    )
    FacturaEnc.objects.filter(pk__in=[e.pk for e in facturas_del_evento]).update(paquete=paquete)

    # --- 4. Enviar el paquete (CAFC nunca aplica en nuestra modalidad
    # -- ver prototipo/sin/README.md: es exclusivo de facturas MANUALES
    # impresas por una imprenta autorizada, no de Electronica en Linea
    # pasando a fuera de linea, que es siempre nuestro caso). ---
    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)
    solicitud_paquete = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_TIPO_EMISION_OFFLINE,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": evento.codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": evento.cufd_evento,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "archivo": tar_gzip,
        "fechaEnvio": timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "hashArchivo": hash_archivo,
        "cantidadFacturas": len(facturas_del_evento),
        "codigoEvento": evento.codigo_recepcion_evento_significativo,
    }
    try:
        resp_paquete = _llamar(
            "envío del paquete de contingencia",
            lambda: serialize_object(client_facturacion.service.recepcionPaqueteFactura(
                SolicitudServicioRecepcionPaquete=solicitud_paquete
            ))
        )
    except EmisionSinError:
        # El evento ya quedo cerrado y reportado (paso 2) -- si el envio
        # del paquete en si falla, el paquete se guarda igual en estado
        # EN_ARMADO, para que Fase C lo reintente sin tener que volver a
        # registrar el evento (eso ya no se puede repetir).
        raise

    if not resp_paquete.get("transaccion"):
        paquete.mensaje_sin = str(resp_paquete.get("mensajesList") or "")
        paquete.save()
        raise EmisionSinError(f"El SIN rechazo el paquete: {resp_paquete.get('mensajesList')}")

    paquete.codigo_recepcion = resp_paquete.get("codigoRecepcion")
    paquete.fecha_envio = timezone.now()
    paquete.estado_paquete = PaqueteFacturas.ENVIADO
    paquete.save()

    return paquete


def validar_paquete_sin(paquete):
    """
    Fase B (segunda mitad): confirma ante el SIN si un PaqueteFacturas
    ya ENVIADO fue validado o no -- se llama en una corrida POSTERIOR a
    cerrar_evento_y_enviar_paquete (Fase C decide cuando, no hace falta
    esperar un tiempo fijo aca). Actualiza el paquete y CADA factura
    que agrupa: VALIDADA si el SIN confirma, OBSERVADA si la rechaza
    (mismo criterio que emitir_factura_sin para una factura individual).
    """
    from fac.models import FacturaEnc, PaqueteFacturas

    if paquete.estado_paquete != PaqueteFacturas.ENVIADO:
        raise EmisionSinError(
            f"El paquete #{paquete.id} no esta en estado ENVIADO "
            f"(estado actual: {paquete.get_estado_paquete_display()})."
        )

    evento = paquete.evento
    empresa, sucursal = _obtener_empresa_y_sucursal(evento.sucursal.codigo_sucursal)
    cuis = _obtener_cuis_para_punto_venta(sucursal, evento.codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()
    client_facturacion = _cliente_soap(WSDL_FACTURACION, token)

    solicitud_validacion = {
        "codigoAmbiente": codigo_ambiente,
        "codigoDocumentoSector": CODIGO_DOCUMENTO_SECTOR,
        "codigoEmision": CODIGO_TIPO_EMISION_OFFLINE,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoPuntoVenta": evento.codigo_punto_venta,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "cufd": evento.cufd_evento,
        "cuis": cuis,
        "nit": empresa.nit,
        "tipoFacturaDocumento": TIPO_FACTURA_DOCUMENTO,
        "codigoRecepcion": paquete.codigo_recepcion,
    }
    resp = _llamar(
        "validación de recepción del paquete",
        lambda: serialize_object(client_facturacion.service.validacionRecepcionPaqueteFactura(
            SolicitudServicioValidacionRecepcionPaquete=solicitud_validacion
        ))
    )

    paquete.fecha_validacion = timezone.now()
    paquete.mensaje_sin = str(resp.get("mensajesList") or "")

    if resp.get("transaccion"):
        paquete.estado_paquete = PaqueteFacturas.VALIDADO
        FacturaEnc.objects.filter(paquete=paquete).update(estado_sin=FacturaEnc.SIN_VALIDADA)
    else:
        paquete.estado_paquete = PaqueteFacturas.RECHAZADO
        FacturaEnc.objects.filter(paquete=paquete).update(estado_sin=FacturaEnc.SIN_OBSERVADA)

    paquete.save()
    return paquete


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

    # Fase 2 (20/09/2026): sucursal de la factura ORIGINAL -- la NCD la
    # corrige, tiene que emitirse desde la misma sucursal.
    codigo_sucursal = factura_original.sucursal.codigo_sucursal if factura_original.sucursal else 0
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
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

    # RESUELTO 12/09/2026 -- confirmado con una emision real
    # (codigoEstado=908, VALIDADA): la NCD usa el WSDL
    # WSDL_DOCUMENTO_AJUSTE (ServicioFacturacionDocumentoAjuste) con la
    # operacion recepcionDocumentoAjuste -- NUNCA recepcionFactura del
    # WSDL de facturas normales, que es lo que se uso por error hasta
    # esta fecha (causaba el error 995 "SERVICIO NO DISPONIBLE").
    # tipoFacturaDocumento=3 (con derecho a credito fiscal, igual que
    # una factura normal) y codigoDocumentoSector=24 son los valores
    # correctos, confirmados por el propio SIN.
    client_documento_ajuste = _cliente_soap(WSDL_DOCUMENTO_AJUSTE, token)
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
        lambda: serialize_object(client_documento_ajuste.service.recepcionDocumentoAjuste(
            SolicitudServicioRecepcionDocumentoAjuste=solicitud_envio
        ))
    )

    nota_credito_debito.cuf = cuf
    nota_credito_debito.cufd = cufd
    nota_credito_debito.codigo_control = codigo_control
    nota_credito_debito.codigo_recepcion_sin = resp.get("codigoRecepcion")
    nota_credito_debito.mensaje_sin = str(resp.get("mensajesList") or "")
    nota_credito_debito.xml_firmado = xml_bytes.decode('utf-8')

    if resp["transaccion"] and resp.get("codigoEstado") == 908:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_VALIDADA
        # NUEVO 12/09/2026: la NCD (devolucion total, unica version
        # soportada) devuelve el stock al inventario -- mismo
        # tratamiento que ya usa anular_factura en fac/views.py (es el
        # mismo evento de negocio, la venta se revierte; solo se
        # documenta distinto porque Anular ya no era una opcion una
        # vez que la factura quedo reportada al SIN). Se hace SOLO
        # aca, condicionado a Validada de verdad (908) -- nunca en
        # Pendiente ni Observada, para no devolver stock por una NCD
        # que el SIN todavia no confirmo.
        # CORREGIDO 16/09/2026 -- revision de seguridad/bugs (Etapa A):
        # antes era read-modify-write en Python (leer existencia, sumar,
        # guardar), no atomico -- con caja/sucursal concurrente
        # vendiendo el mismo producto, se puede perder un ajuste en
        # silencio. F() lo hace atomico en la base de datos.
        # AMPLIADO 20/09/2026 (Fase 2): ajustar_stock_sucursal devuelve
        # el stock a la sucursal REAL de la factura original, no a un
        # pozo global.
        from inv.models import ajustar_stock_sucursal
        for det in detalles_originales:
            ajustar_stock_sucursal(det.producto_id, factura_original.sucursal, det.cantidad)

        # NUEVO 15/09/2026: mismo hueco que tenia anular_factura antes
        # de corregirse -- una NCD (devolucion TOTAL) es, en los
        # hechos, el mismo evento de negocio que anular una factura
        # (la venta se revierte). Si la factura original era a
        # credito, hay que limpiar saldo_pendiente igual que ya hace
        # anular_factura en fac/views.py -- si no, queda un saldo
        # fantasma cobrable sobre un documento que el SIN ya acepto
        # como credito fiscal devuelto en su totalidad. Confirmado en
        # vivo: la factura 777 (a credito) quedo con saldo_pendiente=80
        # despues de una NCD validada por el SIN.
        if factura_original.forma_pago == factura_original.FORMA_PAGO_CREDITO:
            factura_original.saldo_pendiente = 0
            factura_original.save()
    elif resp["transaccion"] and resp.get("codigoEstado") == 901:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_PENDIENTE
    else:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_OBSERVADA

    nota_credito_debito.save()

    if not resp["transaccion"]:
        raise EmisionSinError(f"El SIN rechazo la Nota de Credito-Debito: {resp['mensajesList']}")

    return nota_credito_debito


def anular_nota_credito_debito_sin(nota_credito_debito, codigo_motivo, codigo_punto_venta=0):
    """
    Anula ante el SIN una Nota de Credito-Debito ya validada (Etapa VII
    de certificacion, ver instructivo NCD Etapas IV/VII/VIII/XI).

    Mismo patron que anular_factura_sin, con las mismas dos diferencias
    de fondo que emitir_nota_credito_debito_sin tiene respecto a
    emitir_factura_sin: WSDL distinto (WSDL_DOCUMENTO_AJUSTE, no
    WSDL_FACTURACION) y operacion distinta (anulacionDocumentoAjuste,
    no anulacionFactura). El 'cuf' que viaja en la solicitud es el de
    la NCD, NO el de la factura original -- se esta anulando el
    documento de ajuste en si, no la factura que corrige.

    Firma de anulacionDocumentoAjuste confirmada por inspeccion directa
    del WSDL real (14-15/09/2026, prototipo/sin/
    inspeccionar_firma_completa_documento_ajuste.py, solo lectura, sin
    enviar nada al SIN): identica a SolicitudServicioAnulacionFactura
    (mismos 13 campos) salvo que viaja por el WSDL de Documento Ajuste.
    """
    if not nota_credito_debito.cuf:
        raise EmisionSinError(
            "La Nota de Credito-Debito no tiene CUF -- nunca fue emitida ante el SIN."
        )
    # CORREGIDO 17/09/2026: Validada y Revertida son, a estos efectos,
    # el mismo estado -- la NCD esta vigente ahora mismo en ambos
    # casos (revertir una anulacion deja la correccion en efecto de
    # nuevo). Antes solo aceptaba Validada, asi que no se podia volver
    # a anular una NCD despues de revertir su anulacion.
    if nota_credito_debito.estado_sin not in (
        nota_credito_debito.SIN_VALIDADA, nota_credito_debito.SIN_REVERTIDA
    ):
        raise EmisionSinError(
            "Solo se puede anular una Nota de Credito-Debito que este vigente (Validada o con "
            f"una anulacion revertida) por el SIN (estado actual: {nota_credito_debito.get_estado_sin_display()})."
        )

    # Fase 2 (20/09/2026): sucursal de la factura original que esta NCD corrige.
    codigo_sucursal = (
        nota_credito_debito.factura_original.sucursal.codigo_sucursal
        if nota_credito_debito.factura_original.sucursal else 0
    )
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente)

    client_documento_ajuste = _cliente_soap(WSDL_DOCUMENTO_AJUSTE, token)
    solicitud = {
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
        "codigoMotivo": codigo_motivo,
        "cuf": nota_credito_debito.cuf,
    }
    resp = _llamar(
        "anulación de la Nota de Crédito-Débito",
        lambda: serialize_object(client_documento_ajuste.service.anulacionDocumentoAjuste(
            SolicitudServicioAnulacionDocumentoAjuste=solicitud
        ))
    )

    nota_credito_debito.codigo_motivo_anulacion_sin = codigo_motivo
    nota_credito_debito.fecha_anulacion_sin = timezone.now()
    nota_credito_debito.mensaje_sin = str(resp.get("mensajesList") or "")

    # Mismo codigoEstado=905 que confirma una anulacion de factura
    # normal (anulacionFactura) -- las dos operaciones comparten el
    # mismo catalogo de codigoEstado del SIN.
    if resp.get("transaccion") and resp.get("codigoEstado") == 905:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_ANULADA

        # CORREGIDO 15/09/2026 (hallazgo de Carlos probando contra el
        # SIN real, factura 778): anular la NCD deshace la devolucion
        # que hizo emitir_nota_credito_debito_sin -- si no se revierte
        # el stock aca, el producto queda "de mas" en inventario
        # (entro por la NCD y nunca volvio a salir al anularla). Mismo
        # criterio inverso al de la emision: se saca del inventario la
        # misma cantidad que en su momento se devolvio, linea por
        # linea de la factura original. Idem saldo_pendiente: si la
        # NCD lo habia dejado en 0 (factura a credito), anularla
        # revive la deuda original -- la correccion que la habia
        # saldado ya no existe.
        from fac.models import FacturaDet
        from inv.models import ajustar_stock_sucursal
        factura_original = nota_credito_debito.factura_original
        detalles_originales = FacturaDet.objects.filter(factura=factura_original).select_related('producto')
        for det in detalles_originales:
            # Atomico + sucursal (Fase 2) -- ver comentario en emitir_nota_credito_debito_sin.
            ajustar_stock_sucursal(det.producto_id, factura_original.sucursal, -det.cantidad)
        if factura_original.forma_pago == factura_original.FORMA_PAGO_CREDITO:
            factura_original.saldo_pendiente = factura_original.total
            factura_original.save()

        nota_credito_debito.save()
        return nota_credito_debito

    nota_credito_debito.save()
    raise EmisionSinError(f"El SIN rechazo la anulacion de la NCD: {resp.get('mensajesList')}")


def revertir_anulacion_nota_credito_debito_sin(nota_credito_debito, codigo_punto_venta=0):
    """
    Revierte ante el SIN la anulacion de una Nota de Credito-Debito
    (Etapa XI de certificacion, confirmada en el dashboard real del SIN
    el 15/09/2026 -- la fila especifica de NCD, con
    codigoDocumentoSector=24/tipoFacturaDocumento=3, pide esta
    reversion igual que la de una factura normal).

    Mismo patron que revertir_anulacion_sin, con las mismas dos
    diferencias de fondo que el resto de las operaciones de NCD: WSDL
    distinto (WSDL_DOCUMENTO_AJUSTE) y operacion distinta
    (reversionAnulacionDocumentoAjuste). El 'cuf' es el de la NCD.

    Firma confirmada por inspeccion directa del WSDL real
    (prototipo/sin/inspeccionar_firma_completa_documento_ajuste.py,
    solo lectura): identica a SolicitudServicioReversionAnulacionFactura
    (sin codigoMotivo), salvo el WSDL.
    """
    if not nota_credito_debito.cuf:
        raise EmisionSinError(
            "La Nota de Credito-Debito no tiene CUF -- nunca fue emitida ante el SIN."
        )
    if nota_credito_debito.estado_sin != nota_credito_debito.SIN_ANULADA:
        raise EmisionSinError(
            "Solo se puede revertir la anulacion de una Nota de Credito-Debito que este "
            f"anulada ante el SIN (estado actual: {nota_credito_debito.get_estado_sin_display()})."
        )

    # Fase 2 (20/09/2026): sucursal de la factura original que esta NCD corrige.
    codigo_sucursal = (
        nota_credito_debito.factura_original.sucursal.codigo_sucursal
        if nota_credito_debito.factura_original.sucursal else 0
    )
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
    cuis = _obtener_cuis_para_punto_venta(sucursal, codigo_punto_venta)
    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    token = _obtener_token()

    client_codigos = _cliente_soap(WSDL_CODIGOS, token)
    cufd, _ = _pedir_cufd(client_codigos, empresa, sucursal, cuis, codigo_punto_venta, codigo_ambiente)

    client_documento_ajuste = _cliente_soap(WSDL_DOCUMENTO_AJUSTE, token)
    solicitud = {
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
        "cuf": nota_credito_debito.cuf,
    }
    resp = _llamar(
        "reversión de la anulación de la Nota de Crédito-Débito",
        lambda: serialize_object(client_documento_ajuste.service.reversionAnulacionDocumentoAjuste(
            SolicitudServicioReversionAnulacionDocumentoAjuste=solicitud
        ))
    )

    nota_credito_debito.mensaje_sin = str(resp.get("mensajesList") or "")

    # Mismo codigoEstado=907 que confirma una reversion de anulacion de
    # factura normal (reversionAnulacionFactura).
    if resp.get("transaccion") and resp.get("codigoEstado") == 907:
        nota_credito_debito.estado_sin = nota_credito_debito.SIN_REVERTIDA
        nota_credito_debito.fecha_reversion_sin = timezone.now()

        # Simetrico a anular_nota_credito_debito_sin: revertir la
        # anulacion revive la devolucion -- el stock vuelve a entrar
        # (misma cantidad, misma logica que la emision original) y, si
        # la factura original era a credito, saldo_pendiente vuelve a
        # 0 (la correccion que habia saldado la deuda vuelve a regir).
        from fac.models import FacturaDet
        from inv.models import ajustar_stock_sucursal
        factura_original = nota_credito_debito.factura_original
        detalles_originales = FacturaDet.objects.filter(factura=factura_original).select_related('producto')
        for det in detalles_originales:
            # Atomico + sucursal (Fase 2) -- ver comentario en emitir_nota_credito_debito_sin.
            ajustar_stock_sucursal(det.producto_id, factura_original.sucursal, det.cantidad)
        if factura_original.forma_pago == factura_original.FORMA_PAGO_CREDITO:
            factura_original.saldo_pendiente = 0
            factura_original.save()

        nota_credito_debito.save()
        return nota_credito_debito

    nota_credito_debito.save()
    raise EmisionSinError(f"El SIN rechazo la reversion de la anulacion de la NCD: {resp.get('mensajesList')}")


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

    # Fase 2 (20/09/2026): sucursal real de esta factura, ver comentario en emitir_factura_sin.
    codigo_sucursal = factura_enc.sucursal.codigo_sucursal if factura_enc.sucursal else 0
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
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

    # Fase 2 (20/09/2026): sucursal real de esta factura, ver comentario en emitir_factura_sin.
    codigo_sucursal = factura_enc.sucursal.codigo_sucursal if factura_enc.sucursal else 0
    empresa, sucursal = _obtener_empresa_y_sucursal(codigo_sucursal)
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

def solicitar_cuis_sucursal_sin(sucursal, forzar=False):
    """
    Pide al SIN el CUIS de una Sucursal (servicio cuis, WSDL
    FacturacionCodigos, punto de venta 0) y lo guarda en la Sucursal.
    Agregado 24/09/2026 (pedido de Carlos: boton por sucursal, listo
    para cuando haga falta facturar desde una sucursal nueva).

    Requisitos: que el SIN ya tenga registrada esa sucursal para el NIT
    (con ese mismo codigo_sucursal) -- si no, el SIN rechaza la solicitud
    y se muestra su mensaje tal cual. Para no pedir CUIS de mas (el
    prototipo ya advertia de riesgo al pedirlo de nuevo), si la
    sucursal ya tiene un CUIS que todavia no esta por vencer, NO se
    vuelve a pedir salvo que se fuerce; el SIN permite renovarlo desde
    5 dias antes de su vencimiento.
    """
    empresa = Empresa.objects.first()
    if not empresa:
        raise EmisionSinError("No hay configuracion de Empresa cargada (completar en /fe/).")
    if not empresa.nit:
        raise EmisionSinError("La Empresa no tiene NIT cargado.")
    if not empresa.codigo_sistema:
        raise EmisionSinError("La Empresa no tiene codigo_sistema cargado "
                               "(Autorizacion de Sistemas pendiente ante el SIN).")

    ahora = timezone.now()
    if (not forzar and sucursal.codigo_cuis and sucursal.fecha_vigencia_cuis
            and sucursal.fecha_vigencia_cuis - timedelta(days=5) > ahora):
        raise EmisionSinError(
            f"La sucursal ya tiene un CUIS vigente hasta "
            f"{timezone.localtime(sucursal.fecha_vigencia_cuis):%d/%m/%Y %H:%M}. "
            "Recien se puede renovar desde 5 dias antes de esa fecha."
        )

    codigo_ambiente = (
        CODIGO_AMBIENTE_PRODUCCION if empresa.ambiente == Empresa.PRODUCCION
        else CODIGO_AMBIENTE_PILOTO
    )
    client = _cliente_soap(WSDL_CODIGOS, _obtener_token())
    solicitud = {
        "codigoAmbiente": codigo_ambiente,
        "codigoModalidad": CODIGO_MODALIDAD,
        "codigoSistema": empresa.codigo_sistema,
        "codigoSucursal": sucursal.codigo_sucursal,
        "nit": empresa.nit,
        "codigoPuntoVenta": 0,
    }
    resp = _llamar(
        "solicitud de CUIS",
        lambda: serialize_object(client.service.cuis(SolicitudCuis=solicitud))
    )

    if not resp.get("transaccion") or not resp.get("codigo"):
        mensajes = resp.get("mensajesList") or []
        detalle = "; ".join(
            str(m.get("descripcion", m)) if isinstance(m, dict) else str(m) for m in mensajes
        ) or "sin detalle"
        raise EmisionSinError(f"El SIN rechazo la solicitud de CUIS: {detalle}")

    vigencia = resp.get("fechaVigencia")
    if vigencia is not None and timezone.is_naive(vigencia):
        vigencia = timezone.make_aware(vigencia)

    sucursal.codigo_cuis = resp["codigo"]
    sucursal.fecha_autorizacion_cuis = ahora
    sucursal.fecha_vigencia_cuis = vigencia
    sucursal.save(update_fields=["codigo_cuis", "fecha_autorizacion_cuis", "fecha_vigencia_cuis"])
    return sucursal.codigo_cuis
