"""
Suite de pruebas del API interna (api/v1/productos, api/v1/clientes).

Como correrla:
    python manage.py test api

Cubre:
- Autenticacion obligatoria en los 3 endpoints (Etapa C, 23/09/2026 --
  antes estaban completamente abiertos, ver commit de esa etapa).
- Busqueda de producto por codigo interno Y por codigo de barra
  (usado por el lector de codigo de barra en Facturas/Compras/alta de
  Productos).
- Producto/Cliente inexistente devuelve 404, no un error de servidor.
"""
from django.test import TestCase
from django.contrib.auth import get_user_model

from inv.models import Categoria, SubCategoria, Marca, UnidadMedida, Producto
from fac.models import Cliente

User = get_user_model()


class ApiBaseTestCase(TestCase):

    def setUp(self):
        self.usuario = User.objects.create_user(
            "api_test_user", "api_test@test.com", "ApiTest123!"
        )

        self.categoria = Categoria.objects.create(descripcion="CATEGORIA API TEST", uc=self.usuario)
        self.subcategoria = SubCategoria.objects.create(
            categoria=self.categoria, descripcion="SUBCATEGORIA API TEST", uc=self.usuario
        )
        self.marca = Marca.objects.create(descripcion="MARCA API TEST", uc=self.usuario)
        self.um = UnidadMedida.objects.create(descripcion="UNIDAD API TEST", uc=self.usuario)

        self.producto = Producto.objects.create(
            codigo="APITEST001",
            codigo_barra="1234567890123",
            descripcion="Producto de Prueba API",
            precio=15,
            existencia=0,
            marca=self.marca,
            unidad_medida=self.um,
            subcategoria=self.subcategoria,
            uc=self.usuario,
        )

        self.cliente = Cliente.objects.create(
            ci="6666666", nombres="Cliente", apellidos="API Test", nit="6666666",
            razon="Cliente API Test", tipo="Natural", uc=self.usuario,
        )


class AutenticacionApiTests(ApiBaseTestCase):
    """CORREGIDO 23/09/2026 (Etapa C): los 3 endpoints estaban
    completamente abiertos -- sin login, un anonimo podia bajar todo
    el catalogo de productos (con costo_actual) y todos los clientes
    (CI/NIT/telefono). Estas pruebas fijan esa proteccion."""

    def test_producto_list_rechaza_anonimo(self):
        resp = self.client.get("/api/v1/productos/")
        self.assertEqual(resp.status_code, 403)

    def test_producto_detalle_rechaza_anonimo(self):
        resp = self.client.get(f"/api/v1/productos/{self.producto.codigo}")
        self.assertEqual(resp.status_code, 403)

    def test_cliente_list_rechaza_anonimo(self):
        resp = self.client.get("/api/v1/clientes/")
        self.assertEqual(resp.status_code, 403)

    def test_producto_list_permite_usuario_logueado(self):
        self.client.login(username="api_test_user", password="ApiTest123!")
        resp = self.client.get("/api/v1/productos/")
        self.assertEqual(resp.status_code, 200)

    def test_cliente_list_permite_usuario_logueado(self):
        self.client.login(username="api_test_user", password="ApiTest123!")
        resp = self.client.get("/api/v1/clientes/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)


class ProductoDetalleTests(ApiBaseTestCase):
    """Busqueda usada por el lector de codigo de barra (Facturas,
    Compras, alta de Productos) -- ver api/views.py, ProductoDetalle
    busca por Q(codigo=x) | Q(codigo_barra=x)."""

    def setUp(self):
        super().setUp()
        self.client.login(username="api_test_user", password="ApiTest123!")

    def test_encuentra_producto_por_codigo_interno(self):
        resp = self.client.get(f"/api/v1/productos/{self.producto.codigo}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["codigo"], self.producto.codigo)
        self.assertEqual(data["descripcion"], self.producto.descripcion)

    def test_encuentra_producto_por_codigo_de_barra(self):
        resp = self.client.get(f"/api/v1/productos/{self.producto.codigo_barra}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # El lector escanea el codigo de barra, pero el JSON devuelto
        # trae el codigo INTERNO -- asi es como Facturas/Compras
        # rellenan sus campos tras un escaneo (ver buscarProducto() en
        # facturas.html y buscarProductoPorCodigoBarra() en compras.html).
        self.assertEqual(data["codigo"], self.producto.codigo)
        self.assertEqual(data["codigo_barra"], self.producto.codigo_barra)

    def test_codigo_inexistente_devuelve_404_no_error_de_servidor(self):
        resp = self.client.get("/api/v1/productos/CODIGO-QUE-NO-EXISTE")
        self.assertEqual(resp.status_code, 404)




class ExistenciaPorSucursalApiTests(ApiBaseTestCase):
    """25/09/2026: 'existencia' del API es la de la sucursal actual del
    usuario (la pantalla de Facturas la usa para avisar 'sin
    existencia'); el total queda en 'existencia_total'."""

    def test_existencia_es_la_de_la_sucursal_actual(self):
        from fe.models import Empresa, Sucursal
        from inv.models import ajustar_stock_sucursal
        empresa = Empresa.objects.create(razon_social="EMPRESA API")
        central = Sucursal.objects.create(empresa=empresa, codigo_sucursal=0, nombre="Central")
        cbba = Sucursal.objects.create(empresa=empresa, codigo_sucursal=1, nombre="Cochabamba")
        ajustar_stock_sucursal(self.producto.id, central, 40)
        ajustar_stock_sucursal(self.producto.id, cbba, 3)
        from bases.models import PerfilUsuario
        PerfilUsuario.objects.create(user=self.usuario, sucursal=cbba)
        self.client.login(username="api_test_user", password="ApiTest123!")
        data = self.client.get(f"/api/v1/productos/{self.producto.codigo}").json()
        self.assertEqual(data["existencia"], 3)
        self.assertEqual(data["existencia_total"], 43)

