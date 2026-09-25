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
from fe.models import Empresa, Sucursal

User = get_user_model()


class ComprasBaseTestCase(TestCase):
    """CORREGIDO 23/09/2026 (Etapa D): ver docstring de
    FacturacionBaseTestCase en fac/tests.py -- mismo motivo (falta
    Sucursal en la base de tests), mismo fix."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_cmp_test", "admin_cmp@test.com", "AdminTest123!"
        )

        self.empresa = Empresa.objects.create(razon_social="EMPRESA DE PRUEBA CMP")
        self.sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=0, nombre="Central Test"
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


class CompraDetDeleteTests(ComprasBaseTestCase):
    """
    NUEVO 23/09/2026 (Etapa D): CompraDetDelete ("quitar linea de una
    compra") ya habia sido corregido el 10/09/2026 por el mismo bug de
    Django 5.2 que se encontro de nuevo en FacturaDetDelete (delete()
    es codigo muerto, la logica real tiene que vivir en post()) -- pero
    nunca habia quedado una prueba de regresion para sus dos controles
    reales (dia cerrado, stock negativo). Sin esta prueba, un futuro
    cambio podria reintroducir el mismo bug en silencio, igual que paso
    con FacturaDetDelete.
    """

    def test_no_se_puede_quitar_linea_de_compra_de_dia_cerrado(self):
        from django.contrib.auth.models import Permission
        from fac.models import CierreDia

        self._post_nueva_compra(cantidad=20)
        compra = ComprasEnc.objects.order_by('-id').first()
        det = ComprasDet.objects.filter(compra=compra).first()
        CierreDia.objects.create(fecha=compra.fecha_compra)

        # Usuario NO superusuario -- self.admin (superuser) tiene todos
        # los permisos automaticamente via has_perm(), incluido el
        # bypass de dia cerrado, y no serviria para probar el bloqueo.
        cajero = User.objects.create_user("cajero_cmp_test", "cajero@test.com", "CajeroTest123!")
        cajero.user_permissions.add(Permission.objects.get(codename="delete_comprasdet", content_type__app_label="cmp"))
        client_cajero = self.client_class()
        client_cajero.login(username="cajero_cmp_test", password="CajeroTest123!")

        client_cajero.post(f"/cmp/compras/{compra.id}/delete/{det.id}")

        # "Quitar linea" crea una CONTRA-linea nueva con cantidad
        # negativa (no modifica ni borra la original) -- si el bloqueo
        # funciona, esa contra-linea nunca se crea.
        self.assertEqual(ComprasDet.objects.filter(compra=compra).count(), 1)

    def test_no_se_puede_quitar_linea_si_deja_stock_negativo(self):
        from fac.models import Cliente, FacturaEnc, FacturaDet

        self._post_nueva_compra(cantidad=20)
        compra = ComprasEnc.objects.order_by('-id').first()
        det = ComprasDet.objects.filter(compra=compra).first()

        # Se vende parte de ese stock -- revertir la compra completa
        # dejaria el producto en existencia negativa.
        cliente = Cliente.objects.create(
            ci="5555555", nombres="Cliente", apellidos="Negativo", nit="5555555",
            razon="Cliente Negativo", tipo="Natural", uc=self.admin,
        )
        enc_venta = FacturaEnc.objects.create(cliente=cliente, sub_total=0, descuento=0, total=0)
        FacturaDet.objects.create(
            factura=enc_venta, producto=self.producto, cantidad=15,
            precio=self.producto.precio, sub_total=15 * self.producto.precio,
            descuento=0, total=15 * self.producto.precio, uc=self.admin,
        )

        self.client.post(f"/cmp/compras/{compra.id}/delete/{det.id}")

        self.assertEqual(ComprasDet.objects.filter(compra=compra).count(), 1)


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


class ProveedoresPorSucursalTests(ComprasBaseTestCase):
    """25/09/2026: cada sucursal tiene sus proveedores locales; los de
    sucursal vacia son compartidos."""

    def setUp(self):
        super().setUp()
        from bases.models import PerfilUsuario
        self.cbba = Sucursal.objects.create(empresa=self.empresa, codigo_sucursal=1, nombre="Cochabamba")
        self.prov_local_central = Proveedor.objects.create(
            descripcion="Local Central", nit="111", contacto="x", telefono="1", email="a@a.com",
            sucursal=self.sucursal, uc=self.admin)
        self.prov_local_cbba = Proveedor.objects.create(
            descripcion="Local Cbba", nit="222", contacto="x", telefono="1", email="b@b.com",
            sucursal=self.cbba, uc=self.admin)
        # self.proveedor (base) es compartido (sucursal vacia)
        PerfilUsuario.objects.create(user=self.admin, sucursal=self.cbba)

    def test_listado_limitado_muestra_compartidos_y_los_de_su_sucursal(self):
        from bases.models import PerfilUsuario
        from django.contrib.auth.models import Permission
        u = User.objects.create_user("lim_prov", "l@t.com", "Test12345!")
        u.user_permissions.add(Permission.objects.get(codename="view_proveedor", content_type__app_label="cmp"))
        PerfilUsuario.objects.create(user=u, sucursal=self.cbba, alcance="SUCURSAL")
        self.client.login(username="lim_prov", password="Test12345!")
        resp = self.client.get("/cmp/proveedores/")
        nombres = {p.descripcion for p in resp.context["obj"]}
        self.assertEqual(nombres, {"PROVEEDOR DE PRUEBA", "LOCAL CBBA"})

    def test_compra_solo_ofrece_proveedores_de_la_sucursal_actual(self):
        resp = self.client.get("/cmp/compras/new")
        nombres = {p.descripcion for p in resp.context["form_enc"].fields["proveedor"].queryset}
        self.assertEqual(nombres, {"PROVEEDOR DE PRUEBA", "LOCAL CBBA"})

    def test_no_se_puede_comprar_a_un_proveedor_de_otra_sucursal(self):
        self.client.post("/cmp/compras/new", {
            "fecha_compra": "2026-07-18", "observacion": "x", "no_factura": "F-1",
            "fecha_factura": "2026-07-18", "proveedor": self.prov_local_central.id,
            "id_id_producto": self.producto.id, "id_cantidad_detalle": 5,
            "id_precio_detalle": 8, "id_sub_total_detalle": 40,
            "id_descuento_detalle": 0, "id_total_detalle": 40,
        })
        self.assertFalse(ComprasEnc.objects.exists())

    def test_mismo_nombre_permitido_en_sucursales_distintas_pero_no_en_la_misma(self):
        from cmp.forms import ProveedorForm
        datos = {"descripcion": "Local Central", "nit": "999", "contacto": "x",
                 "telefono": "1", "email": "z@z.com", "estado": True}
        otra = ProveedorForm(data={**datos, "sucursal": self.cbba.id})
        self.assertTrue(otra.is_valid(), otra.errors)
        misma = ProveedorForm(data={**datos, "sucursal": self.sucursal.id})
        self.assertFalse(misma.is_valid())
