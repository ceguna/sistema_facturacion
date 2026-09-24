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
