from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views import generic
from django.urls import reverse_lazy
import datetime
from django.http import HttpResponse

# Se necesita importar el login required
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
import json
from django.db.models import Sum

from .models import Proveedor,ComprasEnc,ComprasDet
from cmp.forms import ProveedorForm,ComprasEncForm
from bases.views import SinPrivilegios
from inv.models import Producto

class ProveedorView(SinPrivilegios, generic.ListView):
    permission_required = "inv.view_proveedor"
    model = Proveedor
    template_name = "cmp/proveedor_list.html"
    context_object_name = "obj"
    login_url = "bases:login"

class ProveedorNew(SuccessMessageMixin,SinPrivilegios, generic.CreateView):
    model = Proveedor
    template_name = "cmp/proveedor_form.html"
    context_object_name = "obj"
    form_class = ProveedorForm
    success_url = reverse_lazy("cmp:proveedor_list")
    success_menssage="Proveedor Nuevo"
    permission_required = "cmp.add_proveedor"
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        #print(self.request.user.id)
        return super().form_valid(form)
    
class ProveedorEdit(SinPrivilegios, generic.UpdateView):
    permission_required = "inv.change_proveedor"
    model = Proveedor
    template_name = "cmp/proveedor_form.html"
    context_object_name = "obj"
    form_class = ProveedorForm
    success_url = reverse_lazy("cmp:proveedor_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        print(self.request.user.id)
        return super().form_valid(form)

@login_required(login_url='/login/')
@permission_required('inv.change_proveedor',login_url='bases:sin_privilegios')    
def ProveedorInactivar(request,id):
    template_name='cmp/catalogos_inactivo.html'
    contexto={}
    prv = Proveedor.objects.filter(pk=id).first()

    if not prv:
        return HttpResponse('Proveedor no existe ' + str(id))
    
    if request.method=='GET':
        contexto={'obj':prv}
    
    if request.method=='POST':
        prv.estado=False
        prv.save()
        contexto={'obj':'OK'}
        return HttpResponse('Proveedor inactivado ' + str(id))

    return render(request,template_name,contexto) 

class ComprasView(SinPrivilegios, generic.ListView):
    model = ComprasEnc
    template_name = "cmp/compras_list.html"
    context_object_name = "obj"
    permission_required = "cmp.view_comprasenc"

@login_required(login_url='/login/')
@permission_required('cmp.view_comprasenc', login_url='bases:sin_privilegios')    
def compras(request,compra_id=None): #None significa que permitira un valor nulo
    template_name="cmp/compras.html"
    prod=Producto.objects.filter(estado=True) #Que filtre para que muestre todos los productos
    form_compras={} #Variables de contexto
    contexto={}

    if request.method=='GET':
       form_compras=ComprasEncForm() #Se inicializa form_compras con el formulario de ComprasEncForm
       enc = ComprasEnc.objects.filter(pk=compra_id).first() #Filtra el registro del encabezado

       if enc: #Si existe el encabezado
           det = ComprasDet.objects.filter(compra=enc)
           fecha_compra = datetime.date.isoformat(enc.fecha_compra)
           fecha_factura = datetime.date.isoformat(enc.fecha_factura)
           e = { #aqui se carga los valores al formulario
               'fecha_compra':fecha_compra,
               'proveedor':enc.proveedor,
               'observacion':enc.observacion,
               'no_factura':enc.no_factura,
               'fecha_factura':fecha_factura,
               'sub_total':enc.sub_total,
               'descuento':enc.descuento,
               'total':enc.total
           }
           form_compras = ComprasEncForm(e) #Aqui se inicializa el formulario
       else:
           det=None #Si no existe encabezado, se inicializa el detalle con vacio

        # El contexto es todo lo que se va enviar a la plantilla
       contexto={'productos':prod,'encabezado':enc,'detalle':det,'form_enc':form_compras}

    if request.method=='POST':
        fecha_compra = request.POST.get("fecha_compra") # Se captura con el request todo lo enviado por el formulario
        observacion = request.POST.get("observacion") 
        no_factura = request.POST.get("no_factura") 
        fecha_factura = request.POST.get("fecha_factura") 
        proveedor = request.POST.get("proveedor") 
        sub_total = 0
        descuento = 0
        total = 0

        if not compra_id: #Si no se envia compra_id es porque el encabezado no existe
           prov=Proveedor.objects.get(pk=proveedor)

           enc = ComprasEnc(
               fecha_compra=fecha_compra,
               observacion=observacion,
               no_factura=no_factura,
               fecha_factura=fecha_factura,
               proveedor=prov,
               uc=request.user
           )
           if enc: #aqui se guarda el encabezado.
               enc.save()
               compra_id=enc.id
        else: #Si el encabezado existe es una actualizacion
           enc=ComprasEnc.objects.filter(pk=compra_id).first()
           if enc:
               enc.fecha_compra = fecha_compra
               enc.observacion = observacion
               enc.no_factura = no_factura
               enc.fecha_factura = fecha_factura
               enc.um=request.user.id
               enc.save()

        if not compra_id:
           return redirect("cmp:compras_list")
        
        # Aqui se va guardar el detalle
        producto = request.POST.get("id_id_producto")
        cantidad = request.POST.get("id_cantidad_detalle") 
        precio = request.POST.get("id_precio_detalle") 
        sub_total_detalle = request.POST.get("id_sub_total_detalle") 
        descuento_detalle = request.POST.get("id_descuento_detalle") 
        total_detalle = request.POST.get("id_total_detalle") 

        prod = Producto.objects.get(pk=producto) 

        det = ComprasDet(
            compra=enc,
            producto=prod,
            cantidad=cantidad,
            precio_prv=precio,
            descuento=descuento_detalle,
            costo=0,
            uc = request.user
        )
       
        if det: #Si se logra crear el objeto det, se lo guarda.
            det.save()

            sub_total = ComprasDet.objects.filter(compra=compra_id).aggregate(Sum('sub_total'))
            descuento = ComprasDet.objects.filter(compra=compra_id).aggregate(Sum('descuento'))
            enc.sub_total = sub_total["sub_total__sum"]
            enc.descuento = descuento["descuento__sum"]
            enc.save()

        return redirect("cmp:compras_edit",compra_id=compra_id)

    return render(request, template_name, contexto)

class CompraDetDelete(SinPrivilegios,generic.DeleteView):
    permission_required = "cmp.delete_comprasdet" #Se requiere permiso para el borrado.
    model = ComprasDet
    template_name = "cmp/compras_det_del.html"
    context_object_name = 'obj'

    def get_success_url(self): #Se reescribe el success_url para que retorne a compras_edit
        compra_id=self.kwargs['compra_id']
        return reverse_lazy('cmp:compras_edit',kwargs={'compra_id':compra_id})
