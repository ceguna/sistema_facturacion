from django.contrib import admin
from .models import NotaCreditoDebito


@admin.register(NotaCreditoDebito)
class NotaCreditoDebitoAdmin(admin.ModelAdmin):
    """
    Registrada para diagnostico -- fac nunca tuvo nada en el admin
    porque todo se maneja con pantallas propias, pero para revisar
    rapido el estado_sin/mensaje_sin real de un intento de NCD (sin
    necesitar construir una pantalla dedicada) esto alcanza.
    """
    list_display = ('id', 'factura_original', 'estado_sin', 'fecha', 'cuf', 'codigo_recepcion_sin')
    list_filter = ('estado_sin',)
    search_fields = ('factura_original__id', 'cuf', 'codigo_recepcion_sin')