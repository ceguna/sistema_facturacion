"""
Servicio de sincronización de catálogos con el SIN (Bolivia).

Estado actual: los NOMBRES EXACTOS de las 16 operaciones SOAP de
sincronización individuales (una por catálogo) todavía no están
confirmados contra el WSDL oficial -- eso requiere el certificado de
pruebas y acceso al ambiente Piloto (ver traspaso, Paso 4). Por eso:

  - MAPEO_CATALOGOS marca cada nombre de operación como
    'PENDIENTE_CONFIRMAR' hasta que se verifique contra el WSDL real.
  - MockSOAPClient permite probar toda la lógica de guardado en base
    de datos (altas, bajas lógicas de vigente=False, logging) SIN
    depender todavía de la conexión real ni del certificado.
  - Cuando se resuelva el certificado (Paso 4), solo hay que:
      1) completar MAPEO_CATALOGOS con los nombres reales de operación
      2) reemplazar MockSOAPClient por un zeep.Client real
    El resto del código (guardado, logging, comando) no cambia.
"""

from django.db import transaction

from .models import CatalogoSIN, SincronizacionLog


# Nombre de la operación SOAP que corresponde a cada catálogo.
# TODO (Paso 4): confirmar cada nombre contra el WSDL oficial del
# ambiente Piloto -- no adivinar, se documentará junto con CUIS/CUFD.
MAPEO_CATALOGOS = {
    CatalogoSIN.TipoCatalogo.ACTIVIDADES: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.ACTIVIDADES_DOC_SECTOR: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.LEYENDAS: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.MENSAJES: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.EVENTOS_SIGNIFICATIVOS: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.PAIS_ORIGEN: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_DOC_IDENTIDAD: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_DOC_SECTOR: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_EMISION: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_HABITACION: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_METODO_PAGO: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_MONEDA: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_PUNTO_VENTA: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_FACTURA: "PENDIENTE_CONFIRMAR",
    CatalogoSIN.TipoCatalogo.TIPO_UNIDAD_MEDIDA: "PENDIENTE_CONFIRMAR",
}


class CatalogoSyncError(Exception):
    """Error al sincronizar un catálogo específico con el SIN."""
    pass


class MockSOAPClient:
    """
    Cliente de PRUEBA que simula la respuesta del servicio de
    sincronización del SIN, para poder probar toda la lógica de
    guardado sin depender todavía del certificado ni de la conexión
    real al ambiente Piloto.

    IMPORTANTE: los códigos/descripciones de abajo son solo de
    ejemplo para validar el flujo -- NO son los códigos oficiales
    reales del SIN. Reemplazar este cliente por uno zeep real
    conectado al WSDL del ambiente Piloto en el Paso 4.
    """

    DATOS_MOCK = {
        CatalogoSIN.TipoCatalogo.TIPO_MONEDA: [
            {"codigo": "1", "descripcion": "BOLIVIANOS"},
            {"codigo": "2", "descripcion": "DOLARES AMERICANOS"},
        ],
        CatalogoSIN.TipoCatalogo.TIPO_UNIDAD_MEDIDA: [
            {"codigo": "58", "descripcion": "SERVICIO"},
            {"codigo": "1", "descripcion": "UNIDAD"},
        ],
        CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION: [
            {"codigo": "1", "descripcion": "ERROR EN LA FACTURA"},
            {"codigo": "2", "descripcion": "FACTURA POR CONTINGENCIA"},
        ],
    }

    def obtener_catalogo(self, tipo_catalogo, nombre_operacion):
        return self.DATOS_MOCK.get(tipo_catalogo, [])


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
        CatalogoSIN.objects.update_or_create(
            tipo_catalogo=tipo_catalogo,
            codigo=str(item["codigo"]),
            defaults={
                "descripcion": item["descripcion"],
                "vigente": True,
            },
        )
        actualizados += 1

    # Baja lógica de los códigos que ya no vienen del SIN (nunca se borran)
    CatalogoSIN.objects.filter(tipo_catalogo=tipo_catalogo, vigente=True).exclude(
        codigo__in=codigos_recibidos
    ).update(vigente=False)

    return actualizados


def sincronizar_todos_los_catalogos(cliente_soap=None):
    """
    Corre la sincronización diaria completa (los 16 catálogos).
    Registra el resultado en SincronizacionLog -- éxito total, parcial
    o falla completa -- para poder auditar más adelante (incluso
    útil de mostrar si el SIN pide evidencia en una certificación).

    cliente_soap=None usa el MockSOAPClient de prueba. Cuando exista
    el cliente zeep real (Paso 4), se pasa como parámetro acá.
    """
    cliente_soap = cliente_soap or MockSOAPClient()

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
        else "Errores: " + " | ".join(errores)
    )

    SincronizacionLog.objects.create(
        exitosa=exitosa,
        catalogos_sincronizados=catalogos_ok,
        total_codigos_actualizados=total_codigos,
        mensaje=mensaje,
    )

    return exitosa, mensaje
