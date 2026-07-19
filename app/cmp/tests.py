"""
Suite de pruebas automatizadas del modulo de Compras.

Como correrla:
    python manage.py test cmp

Cubre:
- Aumento de stock al registrar una compra
- Recalculo correcto (sin error) al borrar la ultima linea de
  detalle de una compra (regresion del bug NoneType - NoneType)
- Impresion de compra individual y reporte de todas las compras (PDF)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from inv.models import Categoria, SubCategoria, Marca, UnidadMedida, Producto
from cmp.models import Proveedor, ComprasEnc, ComprasDet

User = get_user_model()


class ComprasBaseTestCase(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_cmp_test", "admin_cmp@test.com", "AdminTest123!"
        )

        self.categoria = Categoria(descripcion="CATEGORIA TEST CMP", uc=self.admin)
        self.categoria.save()
        self.subcategoria = SubCategoria(
            categoria=self.categoria, descripcion="SUBCATEGORIA TEST CMP", uc=self.admin
        )
        self.subcategoria.save()
        self.marca = Marca(descripcion="MARCA TEST CMP", uc=self.admin)
        self.marca.save()
        self.um = UnidadMedida(descripcion="UNIDAD TEST CMP", uc=self.admin)
        self.um.save()

        self.producto = Producto(
            codigo="AUTOTESTCMP001",
            codigo_barra="AUTOTESTCMP001",
            descripcion="Producto de Prueba Compras",
            precio=8,
            existencia=0,
            marca=self.marca,
            unidad_medida=self.um,
            subcategoria=self.subcategoria,
            uc=self.admin,
        )
        self.producto.save()

        self.proveedor = Proveedor(
            descripcion="Proveedor De Prueba", nit="6666666", direccion="Direccion Test",
            uc=self.admin,
        )
        self.proveedor.save()

        self.client.login(username="admin_cmp_test", password="AdminTest123!")

    def _post_nueva_compra(self, cantidad, precio=8):
        return self.client.post("/cmp/compras/new", {
            "fecha_compra": "2026-07-18",
            "observacion": "Compra de prueba automatizada",
            "no_factura": "AUTOTEST-001",
            "fecha_factura": "2026-07-18",
            "proveedor": self.proveedor.id,
            "id_id_producto": self.producto.id,
            "id_cantidad_detalle": cantidad,
            "id_precio_detalle": precio,
            "id_sub_total_detalle": cantidad * precio,
            "id_descuento_detalle": 0,
            "id_total_detalle": cantidad * precio,
        })


class StockCompraTests(ComprasBaseTestCase):

    def test_registrar_compra_aumenta_stock(self):
        stock_inicial = self.producto.existencia
        self._post_nueva_compra(cantidad=30)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial + 30)

    def test_borrar_unica_linea_de_compra_no_causa_error(self):
        """Regresion: antes, si no quedaban lineas de detalle, el
        recalculo de sub_total/descuento fallaba con
        TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
        """
        self._post_nueva_compra(cantidad=20)
        compra = ComprasEnc.objects.order_by('-id').first()
        det = ComprasDet.objects.filter(compra=compra).first()

        # Borrar directamente por ORM simula lo que hace la vista de borrado
        det.delete()

        compra.refresh_from_db()
        self.assertEqual(compra.sub_total, 0.0)
        self.assertEqual(compra.descuento, 0.0)
        self.assertEqual(compra.total, 0.0)


class ImpresionComprasTests(ComprasBaseTestCase):

    def test_imprimir_compra_individual_no_arroja_error(self):
        self._post_nueva_compra(cantidad=10)
        compra = ComprasEnc.objects.order_by('-id').first()
        resp = self.client.get(f"/cmp/compras/{compra.id}/imprimir")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get("Content-Type"), "application/pdf")

    def test_reporte_todas_las_compras_no_arroja_error(self):
        self._post_nueva_compra(cantidad=10)
        resp = self.client.get("/cmp/compras/listado")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get("Content-Type"), "application/pdf")
