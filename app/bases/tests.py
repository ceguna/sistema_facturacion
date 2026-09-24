"""
Suite de pruebas del modulo base (reportes financieros, gestion de
usuarios).

Como correrla:
    python manage.py test bases

Cubre:
- Permisos reales de los 4 reportes financieros (Libro de Ventas,
  Libro de Compras, Facturas Anuladas, Notas de Credito-Debito) --
  Etapa C, 23/09/2026: antes solo exigian sesion iniciada, sin ningun
  permiso, aunque el menu ya asumia uno.
- Gestion de usuarios: no se puede desactivar la propia cuenta, y las
  acciones administrativas exigen el permiso real (auth.change_user).
- Mi Perfil: siempre edita al usuario de la sesion, nunca a otro (a
  prueba de manipular el pk en la URL).
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

User = get_user_model()


class ReportesFinancierosPermisosTests(TestCase):
    """CORREGIDO 23/09/2026 (Etapa C): LibroVentasView, LibroComprasView,
    FacturasAnuladasView y NotasCreditoDebitoReporteView solo tenian
    LoginRequiredMixin -- cualquier usuario logueado, sin importar su
    rol, podia entrar por URL directa. Se agrego permission_required
    igual al que el menu ya asumia (ver bases/views.py)."""

    REPORTES = {
        "/reportes/libro-ventas/": "fac.view_facturaenc",
        "/reportes/libro-compras/": "cmp.view_comprasenc",
        "/reportes/facturas-anuladas/": "fac.view_facturaenc",
        "/reportes/notas-credito-debito/": "fac.view_notacreditodebito",
    }

    def setUp(self):
        self.usuario_sin_permiso = User.objects.create_user(
            "sin_permiso_test", "sp@test.com", "Test12345!"
        )

    def _permiso(self, codename_con_app):
        app_label, codename = codename_con_app.split(".")
        return Permission.objects.get(codename=codename, content_type__app_label=app_label)

    def test_anonimo_redirige_a_login_en_los_4_reportes(self):
        for url in self.REPORTES:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login/", resp.url)

    def test_usuario_logueado_sin_permiso_es_rechazado_en_los_4_reportes(self):
        self.client.login(username="sin_permiso_test", password="Test12345!")
        for url in self.REPORTES:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("sin_privilegios", resp.url)

    def test_usuario_con_el_permiso_especifico_accede_a_su_reporte(self):
        for i, (url, codename) in enumerate(self.REPORTES.items()):
            with self.subTest(url=url):
                # Prefijo numerico: dos reportes distintos comparten el
                # mismo permiso (fac.view_facturaenc), asi que basar el
                # username solo en el codename chocaba con un usuario
                # duplicado en la segunda vuelta del loop.
                usuario = User.objects.create_user(
                    f"con_permiso_{i}_{codename.split('.')[-1]}", "cp@test.com", "Test12345!"
                )
                usuario.user_permissions.add(self._permiso(codename))
                client = self.client_class()
                client.login(username=usuario.username, password="Test12345!")
                resp = client.get(url)
                self.assertEqual(resp.status_code, 200)


class UsuarioToggleActivoTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "admin_bases_test", "admin@test.com", "AdminTest123!"
        )
        self.otro_usuario = User.objects.create_user(
            "otro_usuario_test", "otro@test.com", "Test12345!", is_active=True
        )

    def test_superusuario_puede_desactivar_a_otro_usuario(self):
        self.client.login(username="admin_bases_test", password="AdminTest123!")
        self.client.post(f"/usuarios/{self.otro_usuario.pk}/toggle-activo/")
        self.otro_usuario.refresh_from_db()
        self.assertFalse(self.otro_usuario.is_active)

    def test_no_puede_desactivar_su_propio_usuario(self):
        self.client.login(username="admin_bases_test", password="AdminTest123!")
        self.client.post(f"/usuarios/{self.admin.pk}/toggle-activo/")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_usuario_sin_permiso_no_puede_desactivar_a_otro(self):
        usuario_normal = User.objects.create_user(
            "normal_bases_test", "normal@test.com", "Test12345!"
        )
        self.client.login(username="normal_bases_test", password="Test12345!")
        self.client.post(f"/usuarios/{self.otro_usuario.pk}/toggle-activo/")
        self.otro_usuario.refresh_from_db()
        self.assertTrue(self.otro_usuario.is_active)


class MiPerfilTests(TestCase):
    """MiPerfilView.get_object() siempre devuelve self.request.user --
    esta prueba confirma que ni manipulando el pk de otro usuario en el
    formulario se puede editar una cuenta ajena (no hay pk en la URL,
    pero se confirma igual que el campo editado es siempre el propio)."""

    def setUp(self):
        self.usuario = User.objects.create_user(
            "perfil_test", "perfil@test.com", "Test12345!",
            first_name="Nombre Original",
        )
        self.otro_usuario = User.objects.create_user(
            "otro_perfil_test", "otro_perfil@test.com", "Test12345!",
            first_name="Otro Original",
        )
        self.client.login(username="perfil_test", password="Test12345!")

    def test_editar_mi_perfil_solo_afecta_al_usuario_de_la_sesion(self):
        self.client.post("/mi-perfil/", {
            "first_name": "Nombre Nuevo",
            "last_name": "",
            "email": "perfil@test.com",
        })
        self.usuario.refresh_from_db()
        self.otro_usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, "Nombre Nuevo")
        self.assertEqual(self.otro_usuario.first_name, "Otro Original")


# ---------------------------------------------------------------------
# Alcance por sucursal (24/09/2026): que sucursal(es) puede VER cada
# usuario -- ver bases/alcance.py
# ---------------------------------------------------------------------
from django.utils import timezone
from bases.alcance import sucursales_visibles_ids
from bases.models import PerfilUsuario
from fac.models import Cliente, FacturaEnc
from fe.models import Empresa, Sucursal


class AlcanceSucursalTests(TestCase):

    def setUp(self):
        self.empresa = Empresa.objects.create(razon_social="EMPRESA ALCANCE")
        self.central = Sucursal.objects.create(empresa=self.empresa, codigo_sucursal=0, nombre="Central")
        self.cbba = Sucursal.objects.create(empresa=self.empresa, codigo_sucursal=1, nombre="Cochabamba")
        self.admin = User.objects.create_superuser("adm_alc", "a@a.com", "Test12345!")

        def usuario(nombre, sucursal, alcance):
            u = User.objects.create_user(nombre, f"{nombre}@t.com", "Test12345!")
            for cod in ("view_facturaenc", "change_facturaenc", "view_cliente", "view_comprasenc"):
                app = "cmp" if "compras" in cod else "fac"
                u.user_permissions.add(Permission.objects.get(codename=cod, content_type__app_label=app))
            PerfilUsuario.objects.create(user=u, sucursal=sucursal, alcance=alcance)
            return u
        self.u_todas = usuario("u_todas", self.central, "TODAS")
        self.u_central = usuario("u_central", self.central, "SUCURSAL")
        self.u_cbba = usuario("u_cbba", self.cbba, "SUCURSAL")

        self.cli_c = Cliente.objects.create(ci="1", nombres="Ana", apellidos="Central", nit="1", razon="Ana C",
                                            tipo="Natural", sucursal=self.central, uc=self.admin)
        self.cli_b = Cliente.objects.create(ci="2", nombres="Beto", apellidos="Cbba", nit="2", razon="Beto B",
                                            tipo="Natural", sucursal=self.cbba, uc=self.admin)
        self.f_central = FacturaEnc.objects.create(cliente=self.cli_c, sub_total=10, descuento=0, total=10,
                                                   sucursal=self.central)
        self.f_cbba = FacturaEnc.objects.create(cliente=self.cli_b, sub_total=20, descuento=0, total=20,
                                                sucursal=self.cbba)

    def _ids_lista(self, resp):
        return {f.id for f in resp.context["obj"]}

    def test_ids_visibles_segun_alcance(self):
        self.assertIsNone(sucursales_visibles_ids(self.admin))
        self.assertIsNone(sucursales_visibles_ids(self.u_todas))
        self.assertEqual(sucursales_visibles_ids(self.u_cbba), [self.cbba.id])

    def test_sin_perfil_ve_todo(self):
        u = User.objects.create_user("sin_perfil_alc", "sp@t.com", "Test12345!")
        self.assertIsNone(sucursales_visibles_ids(u))

    def test_alcance_sucursal_sin_sucursal_asignada_no_ve_nada(self):
        u = User.objects.create_user("huerfano_alc", "h@t.com", "Test12345!")
        PerfilUsuario.objects.create(user=u, sucursal=None, alcance="SUCURSAL")
        self.assertEqual(sucursales_visibles_ids(u), [])

    def test_listado_facturas_limitado_a_su_sucursal(self):
        self.client.login(username="u_cbba", password="Test12345!")
        resp = self.client.get("/fac/facturas/")
        self.assertEqual(self._ids_lista(resp), {self.f_cbba.id})

    def test_listado_facturas_todas_ve_ambas_y_filtra_por_selector(self):
        self.client.login(username="u_todas", password="Test12345!")
        resp = self.client.get("/fac/facturas/")
        self.assertEqual(self._ids_lista(resp), {self.f_central.id, self.f_cbba.id})
        resp = self.client.get(f"/fac/facturas/?sucursal={self.cbba.id}")
        self.assertEqual(self._ids_lista(resp), {self.f_cbba.id})

    def test_selector_no_permite_salirse_del_alcance(self):
        self.client.login(username="u_cbba", password="Test12345!")
        resp = self.client.get(f"/fac/facturas/?sucursal={self.central.id}")
        self.assertEqual(self._ids_lista(resp), set())

    def test_no_abre_factura_de_otra_sucursal_por_url(self):
        self.client.login(username="u_cbba", password="Test12345!")
        resp = self.client.get(f"/fac/facturas/edit/{self.f_central.id}")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("sin_privilegios", resp.url)
        resp = self.client.get(f"/fac/facturas/edit/{self.f_cbba.id}")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_suma_solo_su_sucursal(self):
        self.client.login(username="u_cbba", password="Test12345!")
        resp = self.client.get("/")
        self.assertEqual(resp.context["ventas_mes"], 20)
        self.client.login(username="u_todas", password="Test12345!")
        resp = self.client.get("/")
        self.assertEqual(resp.context["ventas_mes"], 30)

    def test_libro_de_ventas_limitado(self):
        self.client.login(username="u_central", password="Test12345!")
        resp = self.client.get("/reportes/libro-ventas/")
        self.assertEqual({f["factura"].id for f in resp.context["filas"]}, {self.f_central.id})

    def test_clientes_limitados_a_su_sucursal(self):
        self.client.login(username="u_cbba", password="Test12345!")
        resp = self.client.get("/fac/clientes/")
        self.assertEqual({c.id for c in resp.context["obj"]}, {self.cli_b.id})

    def test_formulario_usuario_exige_sucursal_si_limita(self):
        from bases.forms import UsuarioForm
        form = UsuarioForm(data={"username": "nuevo_alc", "alcance": "SUCURSAL", "is_active": True})
        self.assertFalse(form.is_valid())
        self.assertIn("alcance", form.errors)
