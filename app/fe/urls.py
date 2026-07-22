from django.urls import path

from fe.views import EmpresaConfigView, SucursalNew, SucursalEdit, SucursalDel, \
    PuntoVentaNew, PuntoVentaEdit, PuntoVentaDel

urlpatterns = [
    path('', EmpresaConfigView.as_view(), name='empresa_config'),

    path('sucursales/nueva/', SucursalNew.as_view(), name='sucursal_new'),
    path('sucursales/<int:pk>/editar/', SucursalEdit.as_view(), name='sucursal_edit'),
    path('sucursales/<int:pk>/eliminar/', SucursalDel.as_view(), name='sucursal_del'),

    path('sucursales/<int:sucursal_id>/puntos-venta/nuevo/', PuntoVentaNew.as_view(), name='puntoventa_new'),
    path('puntos-venta/<int:pk>/editar/', PuntoVentaEdit.as_view(), name='puntoventa_edit'),
    path('puntos-venta/<int:pk>/eliminar/', PuntoVentaDel.as_view(), name='puntoventa_del'),
]
