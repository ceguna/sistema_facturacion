from django.contrib import admin
from .models import CatalogoSIN, SincronizacionLog


@admin.register(CatalogoSIN)
class CatalogoSINAdmin(admin.ModelAdmin):
    list_display = ("tipo_catalogo", "codigo", "descripcion", "vigente", "fecha_sincronizacion")
    list_filter = ("tipo_catalogo", "vigente")
    search_fields = ("codigo", "descripcion")
    ordering = ("tipo_catalogo", "codigo")
    list_per_page = 50

    # Estos datos vienen del SIN vía sincronización automática,
    # no tiene sentido crearlos ni editarlos a mano desde el admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SincronizacionLog)
class SincronizacionLogAdmin(admin.ModelAdmin):
    list_display = ("fecha_ejecucion", "exitosa", "catalogos_sincronizados", "total_codigos_actualizados")
    list_filter = ("exitosa",)
    ordering = ("-fecha_ejecucion",)
    readonly_fields = ("fecha_ejecucion", "exitosa", "catalogos_sincronizados", "total_codigos_actualizados", "mensaje")

    # Es un log generado por el sistema — de solo lectura, no se crea a mano.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False