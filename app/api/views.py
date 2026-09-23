from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .serializers import ProductoSerializer,ClienteSerializer
from inv.models import Producto
from fac.models import Cliente

from django.db.models import Q #El objeto Q permite filtrar en la query set el codigo de producto como el codigo de barra

# CORREGIDO 23/09/2026 (Etapa C): ninguna de las 3 vistas de abajo tenia
# permission_classes -- sin REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES en
# settings.py, DRF cae en su default de fabrica (AllowAny), asi que
# /api/v1/productos/ y /api/v1/clientes/ devolvian TODOS los campos
# (incluido costo_actual de cada producto y CI/NIT/telefono de cada
# cliente) a cualquiera sin sesion iniciada -- confirmado con una
# peticion anonima real antes de este fix. Los tres endpoints los
# consumen exclusivamente llamadas AJAX desde pantallas ya autenticadas
# (Facturas, Compras, alta de Productos), asi que exigir sesion iniciada
# no rompe ningun flujo real.
class ProductoList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        prod = Producto.objects.all() #para traer todos los productos.
        data = ProductoSerializer(prod,many=True).data #Luego se serializa todos los productos
        return Response(data)

class ProductoDetalle(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request, codigo): #para traer un producto.
        #El Q se usa aplicado la condicion entre parentesis y se filtrar en este caso con el operador logico OR
        prod = get_object_or_404(Producto,Q(codigo=codigo)|Q(codigo_barra=codigo))
        data = ProductoSerializer(prod).data
        return Response(data)

class ClienteList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        obj = Cliente.objects.all()
        data = ClienteSerializer(obj,many=True).data
        return Response(data)
