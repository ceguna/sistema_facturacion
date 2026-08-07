from django.urls import path, include

from .views import ClienteView,ClienteNew,ClienteEdit,clienteInactivar, \
    FacturaView, facturas, ProductoView, borrar_detalle_factura, FacturaDetDelete, \
    anular_factura, revertir_anulacion, eliminar_factura, factura_emitir_sin, \
    cierre_dia_pendientes, cierre_dia_detalle, cierre_ventas_selector

from .reportes import imprimir_factura_recibo, imprimir_factura_list, imprimir_factura_list_pdf, \
    reporte_cierre_ventas, reporte_cierre_ventas_pdf

urlpatterns = [
    path('clientes/', ClienteView.as_view(), name='cliente_list'),
    path('clientes/new', ClienteNew.as_view(), name='cliente_new'),
    path('clientes/<int:pk>', ClienteEdit.as_view(), name='cliente_edit'),
    path('clientes/estado/<int:id>',clienteInactivar, name="cliente_inactivar"),

    path('facturas/',FacturaView.as_view(), name="factura_list"),
    path('facturas/new',facturas, name="factura_new"),
    path('facturas/edit/<int:id>',facturas, name="factura_edit"),
    path('facturas/<int:id>/delete/<int:pk>',FacturaDetDelete.as_view(), name="facturas_del"),

    path('facturas/buscar-producto',ProductoView.as_view(), name="factura_producto"),

    path('facturas/borrar-detalle/<int:id>',borrar_detalle_factura, name="factura_borrar_detalle"),

    path('facturas/anular/<int:id>', anular_factura, name="factura_anular"),
    path('facturas/revertir-anulacion/<int:id>', revertir_anulacion, name="factura_revertir_anulacion"),
    path('facturas/eliminar/<int:id>', eliminar_factura, name="factura_eliminar"),
    path('facturas/emitir/<int:id>', factura_emitir_sin, name="factura_emitir_sin"),

    path('facturas/imprimir/<int:id>',imprimir_factura_recibo, name="factura_imprimir_one"),

    path('facturas/imprimir-todas/<str:f1>/<str:f2>',imprimir_factura_list, name="factura_imprimir_all"),
    path('facturas/imprimir-todas-pdf/<str:f1>/<str:f2>',imprimir_factura_list_pdf, name="factura_imprimir_all_pdf"),

    path('cierre-dia/', cierre_dia_pendientes, name='cierre_dia_pendientes'),
    path('cierre-dia/<str:fecha>/', cierre_dia_detalle, name='cierre_dia_detalle'),

    path('reportes/cierre-ventas/', cierre_ventas_selector, name='cierre_ventas_selector'),
    path('reportes/cierre-ventas/ver/<str:f1>/<str:f2>/', reporte_cierre_ventas, name='reporte_cierre_ventas'),
    path('reportes/cierre-ventas/pdf/<str:f1>/<str:f2>/', reporte_cierre_ventas_pdf, name='reporte_cierre_ventas_pdf'),

]