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

    def to_representation(self, instance):
        # 25/09/2026: 'existencia' pasa a ser la de la SUCURSAL ACTUAL del
        # usuario (StockSucursal), no el total de la empresa -- la
        # pantalla de Facturas usa este valor para avisar "sin
        # existencia", y el servidor ya validaba por sucursal, asi que el
        # cajero veia stock disponible que su sucursal no tenia. El total
        # sigue disponible como 'existencia_total'.
        data = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None:
            from bases.views import obtener_sucursal_actual
            from inv.models import StockSucursal
            sucursal = obtener_sucursal_actual(request)
            if sucursal is not None:
                fila = StockSucursal.objects.filter(producto=instance, sucursal=sucursal).first()
                data['existencia_total'] = data['existencia']
                data['existencia'] = fila.cantidad if fila else 0
        return data


class ClienteSerializer(serializers.ModelSerializer):

    class Meta:
        model=Cliente
        fields='__all__' #Todos los campos del cliente.