from rest_framework import serializers

from inv.models import Producto
from fac.models import Cliente

class ProductoSerializer(serializers.ModelSerializer):

    class Meta:
        model=Producto
        fields='__all__' #Todos los campos del producto.


class ClienteSerializer(serializers.ModelSerializer):

    class Meta:
        model=Cliente
        fields='__all__' #Todos los campos del cliente.