"""
Tests de la lógica de sincronización de catálogos, usando el
MockSOAPClient (no requieren conexión real al SIN).
"""

from django.test import TestCase

from .models import CatalogoSIN, SincronizacionLog
from .services import sincronizar_todos_los_catalogos


class MockSOAPClient:
    """
    CORREGIDO 23/09/2026 (Etapa D): este archivo importaba
    MockSOAPClient desde catalogos/services.py, pero ese modulo nunca
    tuvo esa clase -- servicios.py trae solo el cliente REAL
    (SOAPClienteSIN) desde que sincronizar_todos_los_catalogos() dejo
    de tener un fallback mock propio ("cliente_soap es OBLIGATORIO --
    ya no hay fallback mock en el flujo real", ver su docstring). Sin
    esta clase, catalogos/tests.py ni siquiera podia importarse
    (ImportError), asi que estas 3 pruebas nunca corrian.

    Reemplaza a SOAPClienteSIN sin tocar la red: implementa la misma
    interfaz que sincronizar_catalogo()/sincronizar_todos_los_catalogos()
    esperan (obtener_catalogo, obtener_actividades_documento_sector),
    devolviendo datos minimos pero validos para cualquier catalogo que
    se le pida.
    """
    DATOS_MOCK = {
        CatalogoSIN.TipoCatalogo.TIPO_MONEDA: [
            {"codigo": "1", "descripcion": "BOLIVIANOS"},
            {"codigo": "2", "descripcion": "DOLARES AMERICANOS"},
        ],
    }

    def obtener_catalogo(self, tipo_catalogo, nombre_operacion):
        return self.DATOS_MOCK.get(tipo_catalogo, [
            {"codigo": "1", "descripcion": f"CODIGO DE PRUEBA ({tipo_catalogo})"},
        ])

    def obtener_actividades_documento_sector(self):
        return [
            {"codigo_actividad": "476000", "codigo_documento_sector": 1, "tipo_documento_sector": "FCV"},
        ]


class SincronizacionCatalogosTests(TestCase):

    def test_primera_sincronizacion_crea_codigos(self):
        # CORREGIDO 23/09/2026 (Etapa D): sincronizar_todos_los_catalogos
        # ya no devuelve (exitosa, mensaje) -- registra el resultado en
        # SincronizacionLog (ver test_registra_log_de_sincronizacion) y
        # no devuelve nada. Se verifica el exito ahi, no desempacando un
        # valor de retorno que ya no existe.
        sincronizar_todos_los_catalogos(cliente_soap=MockSOAPClient())

        log = SincronizacionLog.objects.latest("fecha_ejecucion")
        self.assertTrue(log.exitosa)
        self.assertTrue(
            CatalogoSIN.objects.filter(
                tipo_catalogo=CatalogoSIN.TipoCatalogo.TIPO_MONEDA,
                codigo="1",
                descripcion="BOLIVIANOS",
                vigente=True,
            ).exists()
        )

    def test_registra_log_de_sincronizacion(self):
        sincronizar_todos_los_catalogos(cliente_soap=MockSOAPClient())

        log = SincronizacionLog.objects.latest("fecha_ejecucion")
        self.assertTrue(log.exitosa)
        self.assertGreater(log.total_codigos_actualizados, 0)

    def test_codigo_que_desaparece_se_marca_no_vigente(self):
        # Simula que "BOLIVIANOS" (código 1) ya no viene en una
        # sincronización posterior -- debe quedar vigente=False,
        # nunca borrado (por el histórico de facturas ya emitidas).
        class ClienteConMenosCodigos(MockSOAPClient):
            DATOS_MOCK = {
                CatalogoSIN.TipoCatalogo.TIPO_MONEDA: [
                    {"codigo": "2", "descripcion": "DOLARES AMERICANOS"},
                ],
            }

        sincronizar_todos_los_catalogos(cliente_soap=MockSOAPClient())
        sincronizar_todos_los_catalogos(cliente_soap=ClienteConMenosCodigos())

        boliviano = CatalogoSIN.objects.get(
            tipo_catalogo=CatalogoSIN.TipoCatalogo.TIPO_MONEDA, codigo="1"
        )
        self.assertFalse(boliviano.vigente)
        # Confirma que NO se borró, solo se dio de baja lógica
        self.assertEqual(
            CatalogoSIN.objects.filter(
                tipo_catalogo=CatalogoSIN.TipoCatalogo.TIPO_MONEDA, codigo="1"
            ).count(),
            1,
        )
