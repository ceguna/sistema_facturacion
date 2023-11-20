from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .serializers import ProductoSerializer,ClienteSerializer
from inv.models import Producto
from fac.models import Cliente

from django.db.models import Q #El objeto Q permite filtrar en la query set el codigo de producto como el codigo de barra

class ProductoList(APIView):
    def get(self,request):
        prod = Producto.objects.all() #para traer todos los productos.
        data = ProductoSerializer(prod,many=True).data #Luego se serializa todos los productos
        return Response(data)

class ProductoDetalle(APIView):
    def get(self,request, codigo): #para traer un producto.
        #El Q se usa aplicado la condicion entre parentesis y se filtrar en este caso con el operador logico OR
        prod = get_object_or_404(Producto,Q(codigo=codigo)|Q(codigo_barra=codigo)) 
        data = ProductoSerializer(prod).data
        return Response(data)

class ClienteList(APIView):
    def get(self,request):
        obj = Cliente.objects.all()
        data = ClienteSerializer(obj,many=True).data
        return Response(data)
