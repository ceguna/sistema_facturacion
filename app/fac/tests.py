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
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from inv.models import Categoria, SubCategoria, Marca, UnidadMedida, Producto, ajustar_stock_sucursal
from fac.models import Cliente, FacturaEnc, FacturaDet
from fe.models import Empresa, Sucursal

User = get_user_model()


class FacturacionBaseTestCase(TestCase):
    """Clase base: arma catalogos, cliente y usuarios de prueba.

    CORREGIDO 23/09/2026 (Etapa D): la base de datos de tests se arma
    desde cero solo con migraciones -- a diferencia de la base de
    desarrollo/produccion, no trae ninguna Sucursal (esa la crea a mano
    cada instalacion real). Sin Sucursal, obtener_sucursal_actual()
    (bases/views.py) no puede resolver ninguna y las vistas de
    facturas/compras rechazan el POST con "No se pudo determinar su
    sucursal..." -- estas pruebas fallaban en silencio desde Fase 2
    (20/09/2026) porque nunca se actualizaron para la arquitectura
    multi-sucursal. Se crea una Sucursal unica (mismo caso que la
    libreria real) para que se resuelva sola, igual que en produccion.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_test", "admin_test@test.com", "AdminTest123!"
        )
        self.usuario_normal = User.objects.create_user(
            "user_test", "user_test@test.com", "UserTest123!"
        )

        self.empresa = Empresa.objects.create(razon_social="EMPRESA DE PRUEBA")
        self.sucursal = Sucursal.objects.create(
            empresa=self.empresa, codigo_sucursal=0, nombre="Central Test"
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
            existencia=0,
            marca=self.marca,
            unidad_medida=self.um,
            subcategoria=self.subcategoria,
            uc=self.admin,
        )
        self.producto.save()
        # CORREGIDO 23/09/2026 (Etapa D): asignar existencia=50 directo
        # en el constructor de arriba NO alcanza desde Fase 2 -- la
        # disponibilidad real para facturar se chequea por StockSucursal
        # (ver fac/views.py), no por el agregado Producto.existencia.
        # Se establece el stock inicial por el mismo camino atomico que
        # usa el sistema real.
        ajustar_stock_sucursal(self.producto.id, self.sucursal, 50)
        self.producto.refresh_from_db()

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

        # Motivo de anulacion (Etapa D, 23/09/2026): anular_factura busca
        # el motivo en el catalogo sincronizado del SIN (CatalogoSIN,
        # MOTIVOS_ANULACION) por 'codigo_motivo', no por el texto libre
        # 'motivo_anulacion' del form -- sin esto, la vista rechazaba
        # cualquier anulacion con "Debe seleccionar un motivo... valido".
        from catalogos.models import CatalogoSIN
        self.motivo_anulacion_catalogo = CatalogoSIN.objects.create(
            tipo_catalogo=CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION,
            codigo="1", descripcion="Error en la emisión",
        )

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

    def _crear_factura_directa(self, con_detalle=True, cantidad=5, cuf=None, fecha=None, estado_sin=None):
        """Crea una FacturaEnc directamente por ORM (sin pasar por la vista),
        util para armar escenarios especificos (fecha vieja, con cuf, etc.).

        CORREGIDO 23/09/2026 (Etapa D): nuevo parametro estado_sin -- desde
        que la emision queda automatica al guardar (Fase A.0), tanto
        anular_factura como eliminar_factura exigen mirar
        FacturaEnc.reportada_ante_sin (basado en estado_sin, no en cuf)
        para decidir si la factura ya fue aceptada por el SIN. Por
        defecto queda None ('no_enviada'), el estado real de una factura
        recien creada que todavia no se emitio.
        """
        enc = FacturaEnc(cliente=self.cliente, sub_total=0, descuento=0, total=0, cuf=cuf)
        enc.save()
        if estado_sin:
            FacturaEnc.objects.filter(pk=enc.id).update(estado_sin=estado_sin)
            enc.refresh_from_db()
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

    # CORREGIDO 23/09/2026 (Etapa D): anular_factura llama al servicio
    # SIN real (anular_factura_sin, fe/services.py) para anular ante el
    # SIN antes de tocar stock -- en un entorno de test sin certificado
    # ni Empresa/Sucursal/CUIS reales, eso fallaba rapido con
    # EmisionSinError apenas se llegaba a esa linea. Se mockea para
    # aislar la logica de negocio que SI le corresponde probar a esta
    # suite (restitucion de stock, flags de anulado) de la integracion
    # SIN en si (esa se prueba aparte, contra el Piloto real, no aca).
    @patch('fac.views.anular_factura_sin')
    def test_anular_factura_del_mes_actual_restituye_stock(self, mock_anular_sin):
        stock_inicial = self.producto.existencia
        # anular_factura exige enc.reportada_ante_sin (estado_sin en
        # validada/pendiente/etc) desde que la emision quedo automatica
        # al guardar (Fase A.0) -- sin esto, la vista rechazaba el POST
        # con "Solo se pueden anular facturas que ya fueron aceptadas
        # por el SIN" y esta prueba fallaba en silencio (200 en vez de 302).
        enc = self._crear_factura_directa(cantidad=8, estado_sin=FacturaEnc.SIN_VALIDADA)
        self.producto.existencia = stock_inicial - 8
        self.producto.save()

        resp = self.client.post(
            f"/fac/facturas/anular/{enc.id}",
            {"motivo_anulacion": "Cliente no recogio el pedido", "codigo_motivo": "1"}
        )
        enc.refresh_from_db()
        self.producto.refresh_from_db()

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(enc.anulado)
        # El motivo final combina la descripcion del catalogo SIN con el
        # detalle libre del usuario (ver anular_factura en fac/views.py:
        # texto_motivo = motivo_catalogo.descripcion + " — " + detalle_adicional).
        self.assertIn("Cliente no recogio el pedido", enc.motivo_anulacion)
        self.assertIn(self.motivo_anulacion_catalogo.descripcion, enc.motivo_anulacion)
        self.assertEqual(self.producto.existencia, stock_inicial)

    @patch('fac.views.anular_factura_sin')
    def test_no_se_puede_anular_dos_veces(self, mock_anular_sin):
        enc = self._crear_factura_directa(cantidad=5, estado_sin=FacturaEnc.SIN_VALIDADA)
        resp1 = self.client.post(f"/fac/facturas/anular/{enc.id}", {"codigo_motivo": "1"})
        # La primera anulacion SI debe procesarse -- sin este chequeo,
        # si ambos POST fueran rechazados por el mismo motivo (ej. sin
        # reportar al SIN), la prueba "pasaba" sin probar nada real.
        self.assertEqual(resp1.status_code, 302)
        enc.refresh_from_db()
        self.assertTrue(enc.anulado)
        self.producto.refresh_from_db()
        stock_tras_primera_anulacion = self.producto.existencia

        self.client.post(f"/fac/facturas/anular/{enc.id}", {})
        self.producto.refresh_from_db()
        # El stock no debe cambiar de nuevo
        self.assertEqual(self.producto.existencia, stock_tras_primera_anulacion)

    def test_no_se_puede_anular_factura_fuera_de_plazo(self):
        fecha_vieja = timezone.now() - datetime.timedelta(days=200)
        enc = self._crear_factura_directa(cantidad=5, fecha=fecha_vieja, estado_sin=FacturaEnc.SIN_VALIDADA)

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
        # CORREGIDO 23/09/2026 (Etapa D): "eliminar" es soft-delete en
        # todo el sistema (ClaseModelo.estado=False) -- la fila NUNCA
        # desaparece de la tabla, asi que assertFalse(...exists()) era
        # una asercion imposible de cumplir incluso cuando la eliminacion
        # SI funciona. Se chequea estado=False, el campo real que
        # "eliminar" cambia.
        enc.refresh_from_db()
        self.assertFalse(enc.estado)

    def test_no_se_puede_eliminar_factura_con_cuf(self):
        # CORREGIDO 23/09/2026 (Etapa D): eliminar_factura bloquea por
        # reportada_ante_sin (estado_sin), no por la sola presencia de
        # 'cuf' -- se agrega estado_sin=SIN_VALIDADA para que esta
        # prueba ejercite de verdad el bloqueo que dice probar (antes,
        # con cuf solo, la vista no rechazaba nada y la aserccion
        # "exists()==True" pasaba igual por ser soft-delete, sin probar
        # el bloqueo real).
        enc = self._crear_factura_directa(cantidad=5, cuf="CUF-DE-PRUEBA-123", estado_sin=FacturaEnc.SIN_VALIDADA)
        self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        enc.refresh_from_db()
        self.assertTrue(enc.estado)

    def test_usuario_normal_no_puede_eliminar(self):
        enc = self._crear_factura_directa(cantidad=5)
        client_normal = self.client_class()
        client_normal.login(username="user_test", password="UserTest123!")

        client_normal.post(f"/fac/facturas/eliminar/{enc.id}")
        enc.refresh_from_db()
        self.assertTrue(enc.estado)

    def test_eliminar_no_borra_registros_que_no_existen(self):
        resp = self.client.post("/fac/facturas/eliminar/999999")
        self.assertEqual(resp.status_code, 302)

    @patch('fac.views.anular_factura_sin')
    def test_eliminar_factura_ya_anulada_no_duplica_stock(self, mock_anular_sin):
        """
        CORREGIDO 23/09/2026 (Etapa D): el escenario original de esta
        prueba (eliminar una factura ya anulada, y verificar que no
        duplique la restitucion de stock) ya no puede darse a traves de
        la vista real -- eliminar_factura rechaza CUALQUIER factura con
        reportada_ante_sin=True (incluidas las anuladas, dice
        explicitamente 'Use Anular en su lugar'), asi que ni siquiera
        llega a intentar tocar el stock. Se verifica esa proteccion en
        su lugar: es justamente lo que impide la doble restitucion.
        """
        stock_inicial = self.producto.existencia
        enc = self._crear_factura_directa(cantidad=8, estado_sin=FacturaEnc.SIN_VALIDADA)
        self.producto.existencia = stock_inicial - 8
        self.producto.save()

        # Anular primero (esto restituye el stock)
        self.client.post(f"/fac/facturas/anular/{enc.id}", {"codigo_motivo": "1"})
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.existencia, stock_inicial)

        # Luego eliminar: se rechaza (factura ya reportada al SIN, aunque
        # este anulada) -- el stock no debe volver a moverse.
        self.client.post(f"/fac/facturas/eliminar/{enc.id}")
        enc.refresh_from_db()
        self.assertTrue(enc.estado)
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
        # Soft-delete -- ver nota en test_superusuario_puede_eliminar_factura_sin_cuf.
        enc.refresh_from_db()
        self.assertFalse(enc.estado)


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

    def test_borrar_detalle_bloqueado_si_factura_ya_reportada_al_sin(self):
        """
        NUEVO 23/09/2026 (Etapa D): guarda el bug real encontrado al
        escribir la prueba de arriba -- el mismo problema de Django 5.2
        (delete() no se llama, post() si) tambien dejaba sin efecto el
        chequeo de _bloqueada() en FacturaDetDelete, permitiendo borrar
        una linea de detalle de una factura YA VALIDADA por el SIN sin
        ningun freno. Corregido moviendo la logica a post() (mismo fix
        que ya tenia CompraDetDelete en cmp/views.py).
        """
        enc = self._crear_factura_directa(cantidad=5, estado_sin=FacturaEnc.SIN_VALIDADA)
        det = FacturaDet.objects.filter(factura=enc).first()

        self.client.post(f"/fac/facturas/{enc.id}/delete/{det.id}")

        self.assertTrue(FacturaDet.objects.filter(pk=det.id).exists())


class ImpresionFacturaTests(FacturacionBaseTestCase):

    def test_imprimir_factura_no_arroja_error(self):
        enc = self._crear_factura_directa(cantidad=4)
        resp = self.client.get(f"/fac/facturas/imprimir/{enc.id}")
        self.assertEqual(resp.status_code, 200)




class CierreDiaPorSucursalTests(FacturacionBaseTestCase):
    """25/09/2026: el cierre de dia es POR SUCURSAL -- antes era unico
    por fecha para toda la empresa y, con 2+ sucursales, que una
    cerrara su dia bloqueaba a las demas."""

    def setUp(self):
        super().setUp()
        from fac.models import CierreDia
        self.cbba = Sucursal.objects.create(empresa=self.empresa, codigo_sucursal=1, nombre="Cochabamba")
        self.ayer = timezone.localdate() - datetime.timedelta(days=1)
        for suc in (self.sucursal, self.cbba):
            enc = FacturaEnc.objects.create(cliente=self.cliente, sub_total=10, descuento=0, total=10, sucursal=suc)
            FacturaEnc.objects.filter(pk=enc.pk).update(fecha=timezone.now() - datetime.timedelta(days=1))
        self.CierreDia = CierreDia

    def test_pendientes_se_calculan_por_sucursal(self):
        from fac.models import dias_pendientes_de_cierre
        self.assertEqual(dias_pendientes_de_cierre(self.sucursal), [self.ayer])
        self.CierreDia.objects.create(fecha=self.ayer, sucursal=self.sucursal, uc=self.admin)
        self.assertEqual(dias_pendientes_de_cierre(self.sucursal), [])
        # La otra sucursal sigue pendiente.
        self.assertEqual(dias_pendientes_de_cierre(self.cbba), [self.ayer])

    def test_cierre_global_cuenta_para_todas(self):
        from fac.models import dia_cerrado
        self.CierreDia.objects.create(fecha=self.ayer, sucursal=None, uc=self.admin)
        self.assertTrue(dia_cerrado(self.ayer, self.sucursal))
        self.assertTrue(dia_cerrado(self.ayer, self.cbba))

    def test_cerrar_el_dia_desde_una_sucursal_no_cierra_la_otra(self):
        from bases.models import PerfilUsuario
        PerfilUsuario.objects.create(user=self.admin, sucursal=self.cbba)
        # Las facturas de prueba no se emitieron al SIN, asi que el cierre
        # limpio no aplica: se fuerza con observacion (admin tiene el permiso).
        resp = self.client.post(f"/fac/cierre-dia/{self.ayer.isoformat()}/",
                                {"forzar": "1", "observaciones": "prueba"})
        self.assertEqual(resp.status_code, 302)
        cierre = self.CierreDia.objects.get()
        self.assertEqual(cierre.sucursal, self.cbba)
        from fac.models import dia_cerrado
        self.assertTrue(dia_cerrado(self.ayer, self.cbba))
        self.assertFalse(dia_cerrado(self.ayer, self.sucursal))
