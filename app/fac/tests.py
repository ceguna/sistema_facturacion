"""
Suite de pruebas automatizadas del modulo de Facturacion.

Como correrla:
    python manage.py test fac

Cubre los escenarios validados durante la reactivacion del sistema:
- Descuento de stock al facturar
- Rechazo de facturas con cantidad mayor al stock disponible (backend)
- Anulacion de facturas (restituye stock, respeta el plazo del SIN,
  no se puede anular dos veces)
- Eliminacion de facturas (solo superusuario, bloqueada si ya tiene
  CUF, no duplica la restitucion de stock si la factura ya estaba
  anulada)
- Impresion de factura (no debe arrojar error de servidor)
"""
import datetime

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from inv.models import Categoria, SubCategoria, Marca, UnidadMedida, Producto
from fac.models import Cliente, FacturaEnc, FacturaDet

User = get_user_model()


class FacturacionBaseTestCase(TestCase):
    """Clase base: arma catalogos, cliente y usuarios de prueba."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_test", "admin_test@test.com", "AdminTest123!"
        )
        self.usuario_normal = User.objects.create_user(
            "user_test", "user_test@test.com", "UserTest123!"
        )

        self.categoria = Categoria(descripcion="CATEGORIA TEST", uc=self.admin)
        self.categoria.save()
        self.subcategoria = SubCategoria(
            categoria=self.categoria, descripcion="SUBCATEGORIA TEST", uc=self.admin
        )
        self.subcategoria.save()
        self.marca = Marca(descripcion="MARCA TEST", uc=self.admin)
        self.marca.save()
        self.um = UnidadMedida(descripcion="UNIDAD TEST", uc=self.admin)
        self.um.save()

        self.producto = Producto(
            codigo="AUTOTEST001",
            codigo_barra="AUTOTEST001",
            descripcion="Producto de Prueba Automatizada",
            precio=10,
            existencia=50,
            marca=self.marca,
            unidad_medida=self.um,
            subcategoria=self.subcategoria,
            uc=self.admin,
        )
        self.producto.save()

        self.cliente = Cliente(
            ci="7777777",
            nombres="Cliente",
            apellidos="De Prueba",
            nit="7777777",
            razon="Cliente De Prueba",
            tipo="Natural",
            uc=self.admin,
        )
        self.cliente.save()

        self.client.login(username="admin_test", password="AdminTest123!")

    def _post_nueva_factura(self, cantidad):
        return self.client.post("/fac/facturas/new", {
            "enc_cliente": self.cliente.id,
            "fecha": timezone.now().date().isoformat(),
            "codigo": self.producto.codigo,
            "cantidad": cantidad,
            "precio": self.producto.precio,
            "sub_total_detalle": cantidad * self.producto.precio,
            "descuento_detalle": 0,
            "total_detalle": cantidad * self.producto.precio,
        })

    def _crear_factura_directa(self, con_detalle=True, cantidad=5, cuf=None, fecha=None):
        """Crea una FacturaEnc directamente por ORM (sin pasar por la vista),
        util para armar escenarios especificos (fecha vieja, con cuf, etc.)."""
        enc = FacturaEnc(cliente=self.cliente, sub_total=0, descuento=0, total=0, cuf=cuf)
        enc.save()
        if fecha:
            FacturaEnc.objects.filter(pk=enc.id).update(fecha=fecha)
            enc.refresh_from_db()
        if con_detalle:
            det = FacturaDet(
                factura=enc, producto=self.producto, cantidad=cantidad,
                precio=self.producto.precio, sub_total=cantidad * self.producto.precio,
                descuento=0, total=cantidad * self.producto.precio, uc=self.admin,
            )
            det.save()
        return enc


class StockValidacionTests(FacturacionBaseTestCase):

    def test_facturar_cantidad_valida_descuenta_stock(self):
        stock_inicial = self.producto.existencia
        self._post_nueva_factura(cantidad=10)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial - 10)

    def test_facturar_cantidad_excesiva_es_rechazada_por_el_backend(self):
        stock_inicial = self.producto.existencia
        self._post_nueva_factura(cantidad=stock_inicial + 1000)
        self.producto.refresh_from_db()
        # El stock no debe haber cambiado
        self.assertEqual(self.producto.existencia, stock_inicial)
        # No debe haberse creado ninguna linea de detalle
        factura = FacturaEnc.objects.filter(cliente=self.cliente).order_by('-id').first()
        self.assertEqual(FacturaDet.objects.filter(factura=factura).count(), 0)


class AnularFacturaTests(FacturacionBaseTestCase):

    def test_anular_factura_del_mes_actual_restituye_stock(self):
        stock_inicial = self.producto.existencia
        enc = self._crear_factura_directa(cantidad=8)
        self.producto.existencia = stock_inicial - 8
        self.producto.save()

        resp = self.client.post(
            f"/fac/facturas/anular/{enc.id}", {"motivo_anulacion": "Cliente no recogio el pedido"}
        )
        enc.refresh_from_db()
        self.producto.refresh_from_db()

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(enc.anulado)
        self.assertEqual(enc.motivo_anulacion, "Cliente no recogio el pedido")
        self.assertEqual(self.producto.existencia, stock_inicial)

    def test_no_se_puede_anular_dos_veces(self):
        enc = self._crear_factura_directa(cantidad=5)
        self.client.post(f"/fac/facturas/anular/{enc.id}", {})
        self.producto.refresh_from_db()
        stock_tras_primera_anulacion = self.producto.existencia

        self.client.post(f"/fac/facturas/anular/{enc.id}", {})
        self.producto.refresh_from_db()
        # El stock no debe cambiar de nuevo
        self.assertEqual(self.producto.existencia, stock_tras_primera_anulacion)

    def test_no_se_puede_anular_factura_fuera_de_plazo(self):
        fecha_vieja = timezone.now() - datetime.timedelta(days=200)
        enc = self._crear_factura_directa(cantidad=5, fecha=fecha_vieja)

        resp = self.client.post(f"/fac/facturas/anular/{enc.id}", {})
        enc.refresh_from_db()

        self.assertFalse(enc.anulado)

    def test_usuario_sin_permiso_no_puede_anular(self):
        enc = self._crear_factura_directa(cantidad=5)
        client_normal = self.client_class()
        client_normal.login(username="user_test", password="UserTest123!")

        client_normal.post(f"/fac/facturas/anular/{enc.id}", {})
        enc.refresh_from_db()

        self.assertFalse(enc.anulado)


class EliminarFacturaTests(FacturacionBaseTestCase):

    def test_superusuario_puede_eliminar_factura_sin_cuf(self):
        enc = self._crear_factura_directa(cantidad=5)
        resp = self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(FacturaEnc.objects.filter(pk=enc.id).exists())

    def test_no_se_puede_eliminar_factura_con_cuf(self):
        enc = self._crear_factura_directa(cantidad=5, cuf="CUF-DE-PRUEBA-123")
        self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        self.assertTrue(FacturaEnc.objects.filter(pk=enc.id).exists())

    def test_usuario_normal_no_puede_eliminar(self):
        enc = self._crear_factura_directa(cantidad=5)
        client_normal = self.client_class()
        client_normal.login(username="user_test", password="UserTest123!")

        client_normal.post(f"/fac/facturas/eliminar/{enc.id}")
        self.assertTrue(FacturaEnc.objects.filter(pk=enc.id).exists())

    def test_eliminar_no_borra_registros_que_no_existen(self):
        resp = self.client.post("/fac/facturas/eliminar/999999")
        self.assertEqual(resp.status_code, 302)

    def test_eliminar_factura_ya_anulada_no_duplica_stock(self):
        stock_inicial = self.producto.existencia
        enc = self._crear_factura_directa(cantidad=8)
        self.producto.existencia = stock_inicial - 8
        self.producto.save()

        # Anular primero (esto restituye el stock)
        self.client.post(f"/fac/facturas/anular/{enc.id}", {})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial)

        # Luego eliminar: el stock NO debe volver a subir
        self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial)

    def test_eliminar_factura_sin_anular_si_restituye_stock(self):
        stock_inicial = self.producto.existencia
        enc = self._crear_factura_directa(cantidad=6)
        self.producto.existencia = stock_inicial - 6
        self.producto.save()

        self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial)

    def test_eliminar_ultima_linea_de_detalle_no_causa_error(self):
        """Regresion: antes, si no quedaban lineas de detalle, el
        recalculo de sub_total/descuento fallaba con
        TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
        """
        enc = self._crear_factura_directa(cantidad=3)
        resp = self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(FacturaEnc.objects.filter(pk=enc.id).exists())


class BorrarDetalleFacturaTests(FacturacionBaseTestCase):

    def test_borrar_detalle_muestra_mensaje_y_elimina_la_linea(self):
        """Regresion: en Django 5.2, DeleteView.post() llama a
        form_valid(), no a delete(). Si el mensaje de exito se agrega
        sobreescribiendo delete(), nunca se muestra."""
        enc = self._crear_factura_directa(cantidad=5)
        det = FacturaDet.objects.filter(factura=enc).first()

        resp = self.client.post(f"/fac/facturas/{enc.id}/delete/{det.id}", follow=True)

        self.assertFalse(FacturaDet.objects.filter(pk=det.id).exists())
        mensajes = [str(m) for m in resp.context['messages']]
        self.assertIn('Producto Eliminado', mensajes)


class ImpresionFacturaTests(FacturacionBaseTestCase):

    def test_imprimir_factura_no_arroja_error(self):
        enc = self._crear_factura_directa(cantidad=4)
        resp = self.client.get(f"/fac/facturas/imprimir/{enc.id}")
        self.assertEqual(resp.status_code, 200)
