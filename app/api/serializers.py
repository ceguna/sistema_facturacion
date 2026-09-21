from rest_framework import serializers

from inv.models import Producto
from fac.models import Cliente

class ProductoSerializer(serializers.ModelSerializer):
    # Campo calculado: reutiliza Producto.descuento_promocional_vigente_pct
    # (la @property del modelo) para no duplicar la logica de fechas de
    # vigencia en JavaScript -- una sola fuente de verdad.
    descuento_vigente_pct = serializers.FloatField(
        source='descuento_promocional_vigente_pct', read_only=True
    )
    # Agregado 16/09/2026: unidad_medida por si solo trae el id (FK) --
    # facturas.html necesita el texto para mostrarlo junto a Cantidad,
    # mismo criterio que ya usa Compras.
    unidad_medida_descripcion = serializers.CharField(
        source='unidad_medida.descripcion', read_only=True, default=''
    )

    class Meta:
        model=Producto
        fields='__all__' #Todos los campos del producto.


class ClienteSerializer(serializers.ModelSerializer):

    class Meta:
        model=Cliente
        fields='__all__' #Todos los campos del cliente.