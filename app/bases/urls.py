from django.urls import path
from django.contrib.auth import views as auth_views

from bases.views import Home, HomeSinPrivilegios, ChartsView, TablesView, \
    LibroVentasView, LibroComprasView, FacturasAnuladasView, \
    UsuarioListView, UsuarioNew, UsuarioEdit, UsuarioResetPassword, \
    UsuarioToggleActivo, GrupoListView, GrupoNew, GrupoEdit, GrupoDel, \
    MiPerfilView, MiCambiarPasswordView

urlpatterns = [
    path('',Home.as_view(), name='home'),
    path('login/',auth_views.LoginView.as_view(template_name='bases/login.html'), name='login'),
    path('logout/',auth_views.LoginView.as_view(template_name='bases/login.html'), name='logout'),
    path('sin_privilegios/',HomeSinPrivilegios.as_view(), name='sin_privilegios'),
    path('charts/', ChartsView.as_view(), name='charts'),
    path('tables/', TablesView.as_view(), name='tables'),
    path('reportes/libro-ventas/', LibroVentasView.as_view(), name='libro_ventas'),
    path('reportes/libro-compras/', LibroComprasView.as_view(), name='libro_compras'),
    path('reportes/facturas-anuladas/', FacturasAnuladasView.as_view(), name='facturas_anuladas'),

    # Mi Perfil (cualquier usuario logueado)
    path('mi-perfil/', MiPerfilView.as_view(), name='mi_perfil'),
    path('mi-perfil/cambiar-password/', MiCambiarPasswordView.as_view(), name='cambiar_password'),

    # Gestion de Usuarios y Roles (reemplaza los accesos directos al admin)
    path('usuarios/', UsuarioListView.as_view(), name='usuario_list'),
    path('usuarios/nuevo/', UsuarioNew.as_view(), name='usuario_new'),
    path('usuarios/<int:pk>/editar/', UsuarioEdit.as_view(), name='usuario_edit'),
    path('usuarios/<int:pk>/reset-password/', UsuarioResetPassword.as_view(), name='usuario_reset_password'),
    path('usuarios/<int:pk>/toggle-activo/', UsuarioToggleActivo.as_view(), name='usuario_toggle_activo'),

    path('grupos/', GrupoListView.as_view(), name='grupo_list'),
    path('grupos/nuevo/', GrupoNew.as_view(), name='grupo_new'),
    path('grupos/<int:pk>/editar/', GrupoEdit.as_view(), name='grupo_edit'),
    path('grupos/<int:pk>/eliminar/', GrupoDel.as_view(), name='grupo_del'),
]