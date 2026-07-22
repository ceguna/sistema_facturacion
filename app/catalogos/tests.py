"""
Tests de la lógica de sincronización de catálogos, usando el
MockSOAPClient (no requieren conexión real al SIN).

Para incluir estos tests en la suite del proyecto, copiar el
contenido de este archivo dentro de app/catalogos/tests.py
(o renombrar este archivo a tests.py, reemplazando el que
generó `startapp`).
"""

from django.test import TestCase

from .models import CatalogoSIN, SincronizacionLog
from .services import MockSOAPClient, sincronizar_todos_los_catalogos


class SincronizacionCatalogosTests(TestCase):

    def test_primera_sincronizacion_crea_codigos(self):
        exitosa, mensaje = sincronizar_todos_los_catalogos(cliente_soap=MockSOAPClient())

        self.assertTrue(exitosa)
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
