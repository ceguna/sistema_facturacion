"""
Servicio de sincronización de catálogos con el SIN (Bolivia).

Cliente real (zeep) reemplazando al MockSOAPClient de pruebas.
Confirmado 02/08/2026: header de autenticación "apikey: TokenApi <token>",
WSDL v2/FacturacionSincronizacion.
"""

from django.db import transaction
from zeep import Client
from zeep.transports import Transport
from zeep.helpers import serialize_object
from requests import Session

from .models import CatalogoSIN, SincronizacionLog

WSDL_SINCRONIZACION = "https://pilotosiatservicios.impuestos.gob.bo/v2/FacturacionSincronizacion?wsdl"

# Nombre de la operación SOAP que corresponde a cada catálogo.
# Confirmado contra el WSDL real: v2/FacturacionSincronizacion
MAPEO_CATALOGOS = {
    CatalogoSIN.TipoCatalogo.ACTIVIDADES: "sincronizarActividades",
    CatalogoSIN.TipoCatalogo.ACTIVIDADES_DOC_SECTOR: "sincronizarListaActividadesDocumentoSector",
    CatalogoSIN.TipoCatalogo.LEYENDAS: "sincronizarListaLeyendasFactura",
    CatalogoSIN.TipoCatalogo.MENSAJES: "sincronizarListaMensajesServicios",
    CatalogoSIN.TipoCatalogo.EVENTOS_SIGNIFICATIVOS: "sincronizarParametricaEventosSignificativos",
    CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION: "sincronizarParametricaMotivoAnulacion",
    CatalogoSIN.TipoCatalogo.PAIS_ORIGEN: "sincronizarParametricaPaisOrigen",
    CatalogoSIN.TipoCatalogo.TIPO_DOC_IDENTIDAD: "sincronizarParametricaTipoDocumentoIdentidad",
    CatalogoSIN.TipoCatalogo.TIPO_DOC_SECTOR: "sincronizarParametricaTipoDocumentoSector",
    CatalogoSIN.TipoCatalogo.TIPO_EMISION: "sincronizarParametricaTipoEmision",
    CatalogoSIN.TipoCatalogo.TIPO_HABITACION: "sincronizarParametricaTipoHabitacion",
    CatalogoSIN.TipoCatalogo.TIPO_METODO_PAGO: "sincronizarParametricaTipoMetodoPago",
    CatalogoSIN.TipoCatalogo.TIPO_MONEDA: "sincronizarParametricaTipoMoneda",
    CatalogoSIN.TipoCatalogo.TIPO_PUNTO_VENTA: "sincronizarParametricaTipoPuntoVenta",
    CatalogoSIN.TipoCatalogo.TIPO_FACTURA: "sincronizarParametricaTiposFactura",
    CatalogoSIN.TipoCatalogo.TIPO_UNIDAD_MEDIDA: "sincronizarParametricaUnidadMedida",
    CatalogoSIN.TipoCatalogo.PRODUCTOS_SERVICIOS: "sincronizarListaProductosServicios",
}

# Catálogos cuya operación comparte el tipo de respuesta XSD
# "respuestaListaParametricas" / mismos nombres de campo
# (codigoClasificador + descripcion, dentro de listaCodigos).
# Confirmado en vivo 02/08/2026: TIPO_PUNTO_VENTA, TIPO_EMISION,
# TIPO_FACTURA, MENSAJES.
CATALOGOS_FAMILIA_PARAMETRICA = {
    CatalogoSIN.TipoCatalogo.EVENTOS_SIGNIFICATIVOS,
    CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION,
    CatalogoSIN.TipoCatalogo.PAIS_ORIGEN,
    CatalogoSIN.TipoCatalogo.TIPO_DOC_IDENTIDAD,
    CatalogoSIN.TipoCatalogo.TIPO_DOC_SECTOR,
    CatalogoSIN.TipoCatalogo.TIPO_EMISION,
    CatalogoSIN.TipoCatalogo.TIPO_HABITACION,
    CatalogoSIN.TipoCatalogo.TIPO_METODO_PAGO,
    CatalogoSIN.TipoCatalogo.TIPO_MONEDA,
    CatalogoSIN.TipoCatalogo.TIPO_PUNTO_VENTA,
    CatalogoSIN.TipoCatalogo.TIPO_FACTURA,
    CatalogoSIN.TipoCatalogo.TIPO_UNIDAD_MEDIDA,
    CatalogoSIN.TipoCatalogo.MENSAJES,
}

# ACTIVIDADES_DOC_SECTOR: confirmado en vivo (02/08/2026), pero es una
# tabla de relacion actividad<->tipo de documento (codigoActividad +
# codigoDocumentoSector + tipoDocumentoSector), sin campo de
# descripcion real -- no encaja en el modelo generico codigo/descripcion
# de CatalogoSIN. Se deja fuera de la sincronizacion por ahora; si mas
# adelante hace falta, requiere un modelo propio, no forzarlo aca.
CATALOGOS_SIN_MODELO_GENERICO = {
    CatalogoSIN.TipoCatalogo.ACTIVIDADES_DOC_SECTOR,
}


class CatalogoSyncError(Exception):
    """Error al sincronizar un catálogo específico con el SIN."""
    pass


class SOAPClienteSIN:
    """
    Cliente REAL contra el servicio de sincronización del SIN
    (ambiente Piloto por defecto -- ver codigo_ambiente).

    Requiere las credenciales/identificadores de la empresa que
    sincroniza: token delegado, NIT, código de sistema, y CUIS.
    """

    def __init__(self, token, nit, codigo_sistema, cuis,
                 codigo_sucursal=0, codigo_punto_venta=0, codigo_ambiente=2):
        self.nit = nit
        self.codigo_sistema = codigo_sistema
        self.cuis = cuis
        self.codigo_sucursal = codigo_sucursal
        self.codigo_punto_venta = codigo_punto_venta
        self.codigo_ambiente = codigo_ambiente

        session = Session()
        session.headers.update({"apikey": f"TokenApi {token}"})
        self.client = Client(wsdl=WSDL_SINCRONIZACION, transport=Transport(session=session))

    def _solicitud(self):
        return {
            "codigoAmbiente": self.codigo_ambiente,
            "codigoPuntoVenta": self.codigo_punto_venta,
            "codigoSistema": self.codigo_sistema,
            "codigoSucursal": self.codigo_sucursal,
            "cuis": self.cuis,
            "nit": self.nit,
        }

    def obtener_catalogo(self, tipo_catalogo, nombre_operacion):
        if tipo_catalogo in CATALOGOS_SIN_MODELO_GENERICO:
            raise CatalogoSyncError(
                f"'{tipo_catalogo}' no encaja en el modelo genérico "
                f"código/descripción de CatalogoSIN (es una tabla de "
                f"relación actividad↔documento sector). No se sincroniza "
                f"por acá -- requiere modelo propio si hace falta más adelante."
            )

        operacion = getattr(self.client.service, nombre_operacion)
        respuesta = operacion(SolicitudSincronizacion=self._solicitud())
        respuesta = serialize_object(respuesta)

        if not respuesta.get("transaccion"):
            mensajes = respuesta.get("mensajesList") or []
            raise CatalogoSyncError(f"{nombre_operacion} falló: {mensajes}")

        if tipo_catalogo == CatalogoSIN.TipoCatalogo.PRODUCTOS_SERVICIOS:
            # DTO propio (productosDto), confirmado en vivo 02/08/2026:
            # codigoProducto + descripcionProducto + codigoActividad (+ nandina).
            # codigo_actividad se guarda para poder filtrar el catalogo por
            # actividad economica en la pantalla de Homologacion de Productos.
            items = respuesta.get("listaCodigos", [])
            return [
                {
                    "codigo": str(item["codigoProducto"]),
                    "descripcion": item["descripcionProducto"],
                    "codigo_actividad": str(item["codigoActividad"]),
                }
                for item in items
            ]

        if tipo_catalogo == CatalogoSIN.TipoCatalogo.ACTIVIDADES:
            # DTO propio (actividadesDto), confirmado en vivo 02/08/2026:
            # codigoCaeb + descripcion (+ tipoActividad, no se guarda)
            items = respuesta.get("listaActividades", [])
            return [
                {"codigo": str(item["codigoCaeb"]), "descripcion": item["descripcion"]}
                for item in items
            ]

        if tipo_catalogo == CatalogoSIN.TipoCatalogo.LEYENDAS:
            # DTO propio (parametricaLeyendasDto), confirmado en vivo 02/08/2026:
            # codigoActividad + descripcionLeyenda (el "codigo" es el
            # codigo de actividad -- se repite por cada leyenda de esa
            # actividad, no es un identificador unico de la leyenda en si)
            items = respuesta.get("listaLeyendas", [])
            return [
                {"codigo": str(item["codigoActividad"]), "descripcion": item["descripcionLeyenda"]}
                for item in items
            ]

        if tipo_catalogo in CATALOGOS_FAMILIA_PARAMETRICA:
            items = respuesta.get("listaCodigos", [])
            return [
                {"codigo": str(item["codigoClasificador"]), "descripcion": item["descripcion"]}
                for item in items
            ]

        # No debería llegar acá -- cualquier tipo nuevo agregado a
        # MAPEO_CATALOGOS sin clasificar en una de las categorías de
        # arriba, cae acá como salvaguarda explícita.
        raise CatalogoSyncError(
            f"'{tipo_catalogo}' no está clasificado en ninguna familia conocida "
            f"de respuesta -- agregar su mapeo de campos explícitamente."
        )


@transaction.atomic
def sincronizar_catalogo(tipo_catalogo, cliente_soap):
    """
    Sincroniza un único catálogo: trae la lista de códigos vigentes
    del SIN, da de alta los nuevos / actualiza descripciones, y marca
    como no vigentes (vigente=False) los que ya no vienen en la
    respuesta -- sin borrarlos nunca, para conservar el histórico
    (por ejemplo, una factura vieja puede referenciar un código de
    moneda que el SIN ya dio de baja, y necesitamos poder mostrarlo).

    Devuelve la cantidad de códigos creados o actualizados.
    """
    nombre_operacion = MAPEO_CATALOGOS.get(tipo_catalogo)
    if not nombre_operacion:
        raise CatalogoSyncError(f"Catálogo sin operación SOAP asignada: {tipo_catalogo}")

    codigos_sin = cliente_soap.obtener_catalogo(tipo_catalogo, nombre_operacion)
    codigos_recibidos = {str(item["codigo"]) for item in codigos_sin}
    actualizados = 0

    for item in codigos_sin:
        defaults = {
            "descripcion": item["descripcion"],
            "vigente": True,
        }
        # codigo_actividad solo viene poblado para PRODUCTOS_SERVICIOS;
        # para el resto de catalogos, item.get(...) devuelve None y el
        # campo queda vacio, tal como corresponde.
        defaults["codigo_actividad"] = item.get("codigo_actividad")

        CatalogoSIN.objects.update_or_create(
            tipo_catalogo=tipo_catalogo,
            codigo=str(item["codigo"]),
            defaults=defaults,
        )
        actualizados += 1

    # Baja lógica de los códigos que ya no vienen del SIN (nunca se borran)
    CatalogoSIN.objects.filter(tipo_catalogo=tipo_catalogo, vigente=True).exclude(
        codigo__in=codigos_recibidos
    ).update(vigente=False)

    return actualizados


def sincronizar_todos_los_catalogos(cliente_soap):
    """
    Corre la sincronización diaria completa. Registra el resultado en
    SincronizacionLog -- éxito total, parcial o falla completa -- para
    poder auditar más adelante (incluso útil de mostrar si el SIN pide
    evidencia en una certificación).

    ACTIVIDADES_DOC_SECTOR se salta intencionalmente (ver
    CATALOGOS_SIN_MODELO_GENERICO) -- queda registrado como error en
    el log, no oculto.

    cliente_soap es OBLIGATORIO -- ya no hay fallback mock en el flujo real.
    """
    catalogos_ok = 0
    total_codigos = 0
    errores = []

    for tipo_catalogo, _ in CatalogoSIN.TipoCatalogo.choices:
        try:
            actualizados = sincronizar_catalogo(tipo_catalogo, cliente_soap)
            catalogos_ok += 1
            total_codigos += actualizados
        except Exception as exc:
            errores.append(f"{tipo_catalogo}: {exc}")

    exitosa = len(errores) == 0
    total_catalogos = len(CatalogoSIN.TipoCatalogo.choices)
    mensaje = (
        f"OK: {catalogos_ok}/{total_catalogos} catálogos, "
        f"{total_codigos} códigos actualizados."
        if exitosa
        else f"OK: {catalogos_ok}/{total_catalogos} catálogos. Errores: " + " | ".join(errores)
    )

    SincronizacionLog.objects.create(
        exitosa=exitosa,
        catalogos_sincronizados=catalogos_ok,
        total_codigos_actualizados=total_codigos,
        mensaje=mensaje,
    )

    return exitosa, mensaje