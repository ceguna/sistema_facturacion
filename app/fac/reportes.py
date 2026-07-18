from django.shortcuts import render
from django.utils.dateparse import parse_date
from datetime import timedelta

from .models import FacturaEnc,FacturaDet

def imprimir_factura_recibo(request,id):
    template_name="fac/factura_one.html"

    enc = FacturaEnc.objects.get(id=id)
    det = FacturaDet.objects.filter(factura=id)

    context={
        'request':request,
        'enc':enc,
        'detalle':det
    }

    return render(request,template_name,context)

def imprimir_factura_list(request,f1,f2):
    template_name="fac/facturas_print_all.html"

    f1=parse_date(f1) #Aqui convierte la fecha a formarto de fecha.
    f2=parse_date(f2)
    f2=f2 + timedelta(days=1) #Aqui se aumenta 1 dia a la fecha

    #fecha__gte es mayor o igual a f1 y fecha__lt es menor a f2
    enc = FacturaEnc.objects.filter(fecha__gte=f1,fecha__lt=f2) 
    f2=f2 - timedelta(days=1) #Aqui se disminuye 1 dia a la fecha
    
    context = {
        'request':request,
        'f1':f1,
        'f2':f2,
        'enc':enc
    }

    return render(request,template_name,context)