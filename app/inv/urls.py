from django.urls import path


from .views import CategoriaView, CategoriaNew, CategoriaEdit, CategoriaDel, \
    SubCategoriaView, SubCategoriaNew, SubCategoriaEdit, SubCategoriaDel, \
    MarcaView, MarcaNew, MarcaEdit, marca_inactivar, \
    UMView, UMNew, UMEdit, um_inactivar, \
    ProductoView, ProductoNew, ProductoEdit, producto_inactivar, \
    producto_homologar, producto_homologar_pendientes, \
    TipoCambioView, TipoCambioNew, TipoCambioEdit, \
    revision_precios, aplicar_precio_sugerido, aplicar_todos_sugeridos, precios_sucursal, \
    AjusteInventarioView, ajuste_inventario, ajuste_inventario_det_eliminar, \
    eliminar_ajuste_inventario, carga_inicial, carga_inicial_exportar_plantilla, \
    carga_inicial_importar, \
    TransferenciaStockListView, transferencia_stock_new, \
    transferencia_confirmar_recepcion, transferencia_cancelar

from .reportes import lista_precios, lista_precios_pdf

urlpatterns = [
    path('categorias/', CategoriaView.as_view(), name='categoria_list'),
    path('categorias/new', CategoriaNew.as_view(), name='categoria_new'),
    path('categorias/edit/<int:pk>', CategoriaEdit.as_view(), name='categoria_edit'),
    path('categorias/delete/<int:pk>', CategoriaDel.as_view(), name='categoria_del'),

    path('subcategorias/', SubCategoriaView.as_view(), name='subcategoria_list'),
    path('subcategorias/new', SubCategoriaNew.as_view(), name='subcategoria_new'),
    path('subcategorias/edit/<int:pk>', SubCategoriaEdit.as_view(), name='subcategoria_edit'),
    path('subcategorias/delete/<int:pk>', SubCategoriaDel.as_view(), name='subcategoria_del'),

    path('marcas/', MarcaView.as_view(), name='marca_list'),
    path('marcas/new', MarcaNew.as_view(), name='marca_new'),
    path('marcas/edit/<int:pk>', MarcaEdit.as_view(), name='marca_edit'),
    path('marcas/inactivar/<int:id>', marca_inactivar, name='marca_inactivar'),

    path('um/', UMView.as_view(), name='um_list'),
    path('um/new', UMNew.as_view(), name='um_new'),
    path('um/edit/<int:pk>', UMEdit.as_view(), name='um_edit'),
    path('um/inactivar/<int:id>', um_inactivar, name='um_inactivar'),

    path('productos/', ProductoView.as_view(), name='producto_list'),
    path('productos/new', ProductoNew.as_view(), name='producto_new'),
    path('productos/edit/<int:pk>', ProductoEdit.as_view(), name='producto_edit'),
    path('productos/inactivar/<int:id>', producto_inactivar, name='producto_inactivar'),

    path('productos/homologar/<int:id>', producto_homologar, name='producto_homologar'),
    path('productos/homologar-pendientes/', producto_homologar_pendientes, name='producto_homologar_pendientes'),

    path('productos/reportes/lista-precios/', lista_precios, name='lista_precios'),
    path('productos/reportes/lista-precios-pdf/', lista_precios_pdf, name='lista_precios_pdf'),

    path('tipo-cambio/', TipoCambioView.as_view(), name='tipo_cambio_list'),
    path('tipo-cambio/new', TipoCambioNew.as_view(), name='tipo_cambio_new'),
    path('tipo-cambio/edit/<int:pk>', TipoCambioEdit.as_view(), name='tipo_cambio_edit'),

    path('productos/revision-precios/', revision_precios, name='revision_precios'),
    path('productos/precios-sucursal/', precios_sucursal, name='precios_sucursal'),
    path('productos/revision-precios/aplicar/<int:id>/', aplicar_precio_sugerido, name='aplicar_precio_sugerido'),
    path('productos/revision-precios/aplicar-todos/', aplicar_todos_sugeridos, name='aplicar_todos_sugeridos'),

    # --- Ajuste de Inventario (13/09/2026) ---
    path('ajustes/', AjusteInventarioView.as_view(), name='ajuste_inventario_list'),
    path('ajustes/new', ajuste_inventario, name='ajuste_inventario_new'),
    path('ajustes/edit/<int:ajuste_id>', ajuste_inventario, name='ajuste_inventario_edit'),
    path('ajustes/<int:ajuste_id>/delete/<int:pk>', ajuste_inventario_det_eliminar, name='ajuste_inventario_det_eliminar'),
    path('ajustes/eliminar/<int:id>', eliminar_ajuste_inventario, name='ajuste_inventario_eliminar'),

    # --- Carga Inicial de Inventario por Excel ---
    path('ajustes/carga-inicial/', carga_inicial, name='carga_inicial'),
    path('ajustes/carga-inicial/plantilla/', carga_inicial_exportar_plantilla, name='carga_inicial_exportar_plantilla'),
    path('ajustes/carga-inicial/importar/', carga_inicial_importar, name='carga_inicial_importar'),

    # --- Transferencias de Stock entre Sucursales (Fase 2, 20/09/2026) ---
    path('transferencias/', TransferenciaStockListView.as_view(), name='transferencia_stock_list'),
    path('transferencias/new', transferencia_stock_new, name='transferencia_stock_new'),
    path('transferencias/edit/<int:transferencia_id>', transferencia_stock_new, name='transferencia_stock_edit'),
    path('transferencias/<int:id>/confirmar', transferencia_confirmar_recepcion, name='transferencia_stock_confirmar'),
    path('transferencias/<int:id>/cancelar', transferencia_cancelar, name='transferencia_stock_cancelar'),
]
