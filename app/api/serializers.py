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

    class Meta:
        model=Producto
        fields='__all__' #Todos los campos del producto.


class ClienteSerializer(serializers.ModelSerializer):

    class Meta:
        model=Cliente
        fields='__all__' #Todos los campos del cliente.