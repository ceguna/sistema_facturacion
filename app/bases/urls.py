from django.urls import path
from django.contrib.auth import views as auth_views

from bases.views import Home, HomeSinPrivilegios, ChartsView, TablesView, \
    LibroVentasView, LibroComprasView, FacturasAnuladasView

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
]