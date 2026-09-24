"""
Suite de pruebas del modulo de Inventario (stock por sucursal, ajustes
de inventario, transferencias entre sucursales).

Como correrla:
    python manage.py test inv

Cubre:
- ajustar_stock_sucursal: punto unico de ajuste de stock (Fase 2,
  20/09/2026), con y sin sucursal resuelta, y que dos sucursales
  distintas del mismo producto no se pisen entre si.
- Ajuste de Inventario: recalculo de costo_actual (Promedio Ponderado,
  y el caso especial de Produccion Interna + empresa Industrial que
  PISA el costo en vez de promediar) -- incluye el lock atomico
  agregado en Etapa B (23/09/2026).
- Transferencias de Stock: el stock SALE del origen al agregar cada
  linea, queda "en transito" (no aparece en ninguna sucursal) hasta
  que el destino confirma; cancelar devuelve el stock al origen.
- Permiso de producto_homologar_pendientes (gap encontrado y cerrado
  en Etapa B).
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from bases.models import PerfilUsuario
from inv.models import (
    Categoria, SubCategoria, Marca, UnidadMedida, Producto, StockSucursal,
    ajustar_stock_sucursal, MotivoAjusteInventario, AjusteInventarioEnc,
    AjusteInventarioDet, TransferenciaStockEnc, TransferenciaStockDet,
)
from fe.models import Empresa, Sucursal

User = get_user_model()


class InventarioBaseTestCase(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_inv_test", "admin_inv@test.com", "AdminTest123!"
        )
        self.empresa = Empresa.objects.create(razon_social="EMPRESA INV TEST")
        self.sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=0, nombre="Central Inv Test"
        )
        self.categoria = Categoria.objects.create(descripcion="CATEGORIA INV TEST", uc=self.admin)
        self.subcategoria = SubCategoria.objects.create(
            categoria=self.categoria, descripcion="SUBCATEGORIA INV TEST", uc=self.admin
        )
        self.marca = Marca.objects.create(descripcion="MARCA INV TEST", uc=self.admin)
        self.um = UnidadMedida.objects.create(descripcion="UNIDAD INV TEST", uc=self.admin)
        self.producto = Producto.objects.create(
            codigo="INVTEST001", codigo_barra="INVTEST001",
            descripcion="Producto de Prueba Inventario", precio=10, existencia=0,
            costo_actual=0, marca=self.marca, unidad_medida=self.um,
            subcategoria=self.subcategoria, uc=self.admin,
        )
        self.client.login(username="admin_inv_test", password="AdminTest123!")


class AjustarStockSucursalTests(InventarioBaseTestCase):

    def test_con_sucursal_crea_stocksucursal_y_actualiza_agregado(self):
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 20)
        fila = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal)
        self.assertEqual(fila.cantidad, 20)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 20)

    def test_con_sucursal_delta_negativo_resta(self):
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 20)
        ajustar_stock_sucursal(self.producto.id, self.sucursal, -8)
        fila = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal)
        self.assertEqual(fila.cantidad, 12)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 12)

    def test_sin_sucursal_ajusta_solo_el_agregado(self):
        ajustar_stock_sucursal(self.producto.id, None, 15)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 15)
        self.assertFalse(StockSucursal.objects.filter(producto=self.producto).exists())

    def test_dos_sucursales_no_se_pisan_y_el_agregado_es_la_suma(self):
        otra_sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=1, nombre="Sucursal 2 Inv Test"
        )
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 10)
        ajustar_stock_sucursal(self.producto.id, otra_sucursal, 25)

        self.assertEqual(
            StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal).cantidad, 10
        )
        self.assertEqual(
            StockSucursal.objects.get(producto=self.producto, sucursal=otra_sucursal).cantidad, 25
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 35)


class AjusteInventarioSignalTests(InventarioBaseTestCase):
    """CORREGIDO 23/09/2026 (Etapa B): el recalculo de costo_actual
    aca pasa ahora por select_for_update() -- estas pruebas confirman
    que la matematica sigue siendo correcta despues de ese cambio
    (no son pruebas de concurrencia real, eso no se puede simular en
    un TestCase de un solo hilo -- ver commit de Etapa B)."""

    def setUp(self):
        super().setUp()
        self.motivo_promedia = MotivoAjusteInventario.objects.create(
            descripcion="Carga Inicial Test", es_entrada=True, afecta_costo_actual=True,
            es_produccion_interna=False, uc=self.admin,
        )
        self.motivo_produccion = MotivoAjusteInventario.objects.create(
            descripcion="Produccion Interna Test", es_entrada=True, afecta_costo_actual=True,
            es_produccion_interna=True, uc=self.admin,
        )

    def test_promedia_costo_ponderado_con_stock_previo(self):
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 40)
        Producto.objects.filter(pk=self.producto.id).update(costo_actual=10.0)

        enc = AjusteInventarioEnc.objects.create(
            fecha="2026-09-23", motivo=self.motivo_promedia, sucursal=self.sucursal, uc=self.admin,
        )
        AjusteInventarioDet.objects.create(
            ajuste=enc, producto=self.producto, cantidad=10, costo_unitario=16.0, uc=self.admin,
        )

        self.producto.refresh_from_db()
        # (40*10 + 10*16) / 50 = 560/50 = 11.2
        self.assertAlmostEqual(self.producto.costo_actual, 11.2, places=4)
        self.assertEqual(self.producto.existencia, 50)

    def test_produccion_interna_en_empresa_industrial_pisa_el_costo(self):
        self.empresa.tipo_empresa = Empresa.INDUSTRIAL
        self.empresa.save(update_fields=["tipo_empresa"])

        ajustar_stock_sucursal(self.producto.id, self.sucursal, 40)
        Producto.objects.filter(pk=self.producto.id).update(costo_actual=10.0)

        enc = AjusteInventarioEnc.objects.create(
            fecha="2026-09-23", motivo=self.motivo_produccion, sucursal=self.sucursal, uc=self.admin,
        )
        AjusteInventarioDet.objects.create(
            ajuste=enc, producto=self.producto, cantidad=5, costo_unitario=99.0, uc=self.admin,
        )

        self.producto.refresh_from_db()
        # Industrial + Produccion Interna: PISA, no promedia.
        self.assertEqual(self.producto.costo_actual, 99.0)

    def test_produccion_interna_en_empresa_comercial_si_promedia(self):
        # Empresa.COMERCIAL es el default -- Produccion Interna en una
        # empresa Comercial sigue promediando como cualquier otro motivo.
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 40)
        Producto.objects.filter(pk=self.producto.id).update(costo_actual=10.0)

        enc = AjusteInventarioEnc.objects.create(
            fecha="2026-09-23", motivo=self.motivo_produccion, sucursal=self.sucursal, uc=self.admin,
        )
        AjusteInventarioDet.objects.create(
            ajuste=enc, producto=self.producto, cantidad=10, costo_unitario=16.0, uc=self.admin,
        )

        self.producto.refresh_from_db()
        self.assertAlmostEqual(self.producto.costo_actual, 11.2, places=4)


class AjusteInventarioViewTests(InventarioBaseTestCase):

    def setUp(self):
        super().setUp()
        self.motivo_produccion = MotivoAjusteInventario.objects.create(
            descripcion="Produccion Interna Vista Test", es_entrada=True,
            afecta_costo_actual=True, es_produccion_interna=True, uc=self.admin,
        )

    def _post_nuevo_ajuste(self, cantidad=10, costo=5):
        return self.client.post("/inv/ajustes/new", {
            "fecha": "2026-09-23",
            "motivo": self.motivo_produccion.id,
            "observacion": "Ajuste de prueba automatizada",
            "id_id_producto": self.producto.id,
            "id_cantidad_detalle": cantidad,
            "id_costo_detalle": costo,
        })

    def test_crear_ajuste_suma_stock_en_casa_matriz(self):
        resp = self._post_nuevo_ajuste(cantidad=12, costo=7)
        self.assertEqual(resp.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 12)
        self.assertEqual(AjusteInventarioEnc.objects.count(), 1)

    def test_rechaza_produccion_interna_fuera_de_casa_matriz(self):
        otra_sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=1, nombre="Sucursal No Matriz"
        )
        PerfilUsuario.objects.create(user=self.admin, sucursal=otra_sucursal)

        self._post_nuevo_ajuste(cantidad=10, costo=5)

        self.assertEqual(AjusteInventarioEnc.objects.count(), 0)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, 0)

    def test_rechaza_motivo_que_no_es_produccion_interna(self):
        motivo_no_valido = MotivoAjusteInventario.objects.create(
            descripcion="Motivo Invalido Test", es_entrada=True,
            afecta_costo_actual=True, es_produccion_interna=False, uc=self.admin,
        )
        resp = self.client.post("/inv/ajustes/new", {
            "fecha": "2026-09-23",
            "motivo": motivo_no_valido.id,
            "observacion": "",
            "id_id_producto": self.producto.id,
            "id_cantidad_detalle": 10,
            "id_costo_detalle": 5,
        })
        self.assertEqual(AjusteInventarioEnc.objects.count(), 0)

    def test_usuario_sin_permiso_no_puede_crear_ajuste(self):
        usuario_normal = User.objects.create_user(
            "usuario_normal_inv_test", "un@test.com", "Test12345!"
        )
        client_normal = self.client_class()
        client_normal.login(username="usuario_normal_inv_test", password="Test12345!")
        client_normal.post("/inv/ajustes/new", {
            "fecha": "2026-09-23", "motivo": self.motivo_produccion.id,
            "id_id_producto": self.producto.id, "id_cantidad_detalle": 10, "id_costo_detalle": 5,
        })
        self.assertEqual(AjusteInventarioEnc.objects.count(), 0)


class TransferenciaStockTests(InventarioBaseTestCase):

    def setUp(self):
        super().setUp()
        self.sucursal_destino = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=1, nombre="Sucursal Destino Test"
        )
        # Con 2 sucursales cargadas, obtener_sucursal_actual ya no puede
        # resolver sola (el fallback de "unica sucursal" deja de aplicar)
        # -- se fija el origen explicito via PerfilUsuario.
        PerfilUsuario.objects.create(user=self.admin, sucursal=self.sucursal)
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 50)

    def _crear_transferencia_con_linea(self, cantidad=20):
        self.client.post("/inv/transferencias/new", {
            "sucursal_destino": self.sucursal_destino.id,
            "id_id_producto": self.producto.id,
            "id_cantidad_detalle": cantidad,
        })
        return TransferenciaStockEnc.objects.order_by("-id").first()

    def test_agregar_linea_saca_stock_del_origen_de_inmediato(self):
        self._crear_transferencia_con_linea(cantidad=20)

        origen = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal)
        self.assertEqual(origen.cantidad, 30)
        # Todavia no llego a ninguna sucursal destino -- esta "en transito".
        self.assertFalse(
            StockSucursal.objects.filter(producto=self.producto, sucursal=self.sucursal_destino).exists()
        )

    def test_no_permite_transferir_mas_stock_del_disponible(self):
        self._crear_transferencia_con_linea(cantidad=999)
        self.assertFalse(TransferenciaStockDet.objects.exists())
        origen = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal)
        self.assertEqual(origen.cantidad, 50)

    def test_confirmar_recepcion_suma_stock_en_destino(self):
        enc = self._crear_transferencia_con_linea(cantidad=20)
        self.client.post(f"/inv/transferencias/{enc.id}/confirmar")

        enc.refresh_from_db()
        self.assertEqual(enc.estado, TransferenciaStockEnc.CONFIRMADA)
        destino = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal_destino)
        self.assertEqual(destino.cantidad, 20)

    def test_cancelar_devuelve_stock_al_origen(self):
        enc = self._crear_transferencia_con_linea(cantidad=20)
        self.client.post(f"/inv/transferencias/{enc.id}/cancelar")

        enc.refresh_from_db()
        self.assertEqual(enc.estado, TransferenciaStockEnc.CANCELADA)
        origen = StockSucursal.objects.get(producto=self.producto, sucursal=self.sucursal)
        self.assertEqual(origen.cantidad, 50)
        self.assertFalse(
            StockSucursal.objects.filter(producto=self.producto, sucursal=self.sucursal_destino).exists()
        )


class ProductoHomologarPendientesPermisosTests(InventarioBaseTestCase):
    """CORREGIDO 23/09/2026 (Etapa B): esta vista tenia login_required
    pero no permission_required -- cualquier usuario logueado, sin
    ningun permiso sobre Productos, podia verla."""

    def test_usuario_sin_permiso_es_rechazado(self):
        usuario_normal = User.objects.create_user(
            "sin_permiso_homolog_test", "sp@test.com", "Test12345!"
        )
        client_normal = self.client_class()
        client_normal.login(username="sin_permiso_homolog_test", password="Test12345!")
        resp = client_normal.get("/inv/productos/homologar-pendientes/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("sin_privilegios", resp.url)

    def test_usuario_con_view_producto_accede(self):
        resp = self.client.get("/inv/productos/homologar-pendientes/")
        self.assertEqual(resp.status_code, 200)
