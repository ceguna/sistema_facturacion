from django.http import JsonResponse
from django.shortcuts import render,redirect, get_object_or_404
from django.views import generic

from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from datetime import datetime
from django.contrib import messages

from django.contrib.auth import authenticate
from django.utils import timezone

from bases.views import SinPrivilegios

from .models import Cliente,FacturaEnc,FacturaDet
from .forms import ClienteForm
import inv.views as inv
from inv.models import Producto

class ClienteView(SinPrivilegios, generic.ListView):
    model = Cliente
    template_name = "fac/cliente_list.html"
    context_object_name = "obj"
    permission_required="fac.view_cliente"

class VistaBaseCreate(SuccessMessageMixin,SinPrivilegios, \
    generic.CreateView):
    context_object_name = 'obj'
    success_message="Registro Agregado Satisfactoriamente"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        return super().form_valid(form)

class VistaBaseEdit(SuccessMessageMixin,SinPrivilegios, \
    generic.UpdateView):
    context_object_name = 'obj'
    success_message="Registro Actualizado Satisfactoriamente"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)

class ClienteNew(VistaBaseCreate):
    model=Cliente
    template_name="fac/cliente_form.html"
    form_class=ClienteForm
    success_url= reverse_lazy("fac:cliente_list")
    permission_required="fac.add_cliente"

class ClienteEdit(VistaBaseEdit):
    model=Cliente
    template_name="fac/cliente_form.html"
    form_class=ClienteForm
    success_url= reverse_lazy("fac:cliente_list")
    permission_required="fac.change_cliente"

@login_required(login_url="/login/")
@permission_required("fac.change_cliente",login_url="/login/")
def clienteInactivar(request,id):
    cliente = Cliente.objects.filter(pk=id).first()

    if request.method=="POST":
        if cliente:
            cliente.estado = not cliente.estado #Aqui va cambiar el estado de activo a inactivo y vice versa.
            cliente.save()
            return HttpResponse("OK")
        return HttpResponse("FAIL")   
    return HttpResponse("FAIL")

class FacturaView(SinPrivilegios, generic.ListView):
    model = FacturaEnc
    template_name = "fac/factura_list.html"
    context_object_name = "obj"
    permission_required="fac.view_facturaenc"

@login_required(login_url='/login/')
@permission_required('fac.change_facturaenc', login_url='bases:sin_privilegios')
def facturas(request,id=None):
    template_name='fac/facturas.html'

    detalle = {}
    clientes = Cliente.objects.filter(estado=True)
    
    if request.method == "GET":
        enc = FacturaEnc.objects.filter(pk=id).first()
        if id:
            if not enc:
                messages.error(request,'Factura No Existe')
                return redirect("fac:factura_list")

           # usr = request.user
           # if not usr.is_superuser:
                #if enc.uc != usr:
                #    messages.error(request,'Factura no fue creada por usuario')
                #    return redirect("fac:factura_list")

        if not enc:
            encabezado = {
                'id':0,
                'fecha':datetime.today(),
                'cliente':0,
                'sub_total':0.00,
                'descuento':0.00,
                'total': 0.00,
                'anulado': False,
                'cuf': None
            }
            detalle=None
        else:
            encabezado = {
                'id':enc.id,
                'fecha':enc.fecha,
                'cliente':enc.cliente,
                'sub_total':enc.sub_total,
                'descuento':enc.descuento,
                'total':enc.total,
                'anulado': enc.anulado,
                'cuf': enc.cuf
            }

        detalle=FacturaDet.objects.filter(factura=enc)
        contexto = {"enc":encabezado,"det":detalle,"clientes":clientes}
        return render(request,template_name,contexto)
    
    if request.method == "POST":
        cliente = request.POST.get("enc_cliente")
        fecha  = request.POST.get("fecha")
        cli = Cliente.objects.filter(pk=cliente).first()
        if not cli:
            messages.error(request, 'El cliente seleccionado no existe o no es válido')
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_list")

        if not id:
            enc = FacturaEnc(
                cliente = cli,
                fecha = fecha
            )
            if enc:
                enc.save()
                id = enc.id
        else:
            enc = FacturaEnc.objects.filter(pk=id).first()
            if enc:
                enc.cliente = cli
                enc.save()

        if not id:
            messages.error(request,'No Puedo Continuar No Pude Detectar No. de Factura')
            return redirect("fac:factura_list")
        
        codigo = request.POST.get("codigo")
        cantidad = request.POST.get("cantidad")
        precio = request.POST.get("precio")
        s_total = request.POST.get("sub_total_detalle")
        descuento = request.POST.get("descuento_detalle")
        total = request.POST.get("total_detalle")

        prod = Producto.objects.filter(codigo=codigo).first()
        if not prod:
            messages.error(request, 'El producto ingresado no existe')
            return redirect("fac:factura_edit", id=id)

        # Validacion de stock del lado del servidor (no depender solo de JavaScript)
        if int(cantidad) > prod.existencia:
            messages.error(request, 'No hay existencia suficiente de este producto')
            return redirect("fac:factura_edit", id=id)

        det = FacturaDet(
            factura = enc,
            producto = prod,
            cantidad = cantidad,
            precio = precio,
            sub_total = s_total,
            descuento = descuento,
            total = total
        )
        
        if det:
            det.save()
        
        return redirect("fac:factura_edit",id=id)

    return render(request,template_name,contexto)
 
class ProductoView(inv.ProductoView):
    template_name="fac/buscar_producto.html" 

def borrar_detalle_factura(request, id):
    template_name = "fac/factura_borrar_detalle.html"

    det = get_object_or_404(FacturaDet, pk=id)

    if request.method=="GET":
        context={"det":det} #Aqui se carga el detalle en la variable det.

    if request.method == "POST":
        usr = request.POST.get("usuario")
        pas = request.POST.get("pass")

        user =authenticate(username=usr,password=pas)

        if not user:
            return HttpResponse("Usuario o Clave Incorrecta")
        
        if not user.is_active:
            return HttpResponse("Usuario Inactivo")

        if user.is_superuser or user.has_perm("fac.sup_caja_facturadet"):
            det.id = None #Al quitar el ID, genera otro registro 
            # Aqui para que aparezca el nuevo registro pero como valores negativos.
            det.cantidad = (-1 * det.cantidad)
            det.sub_total = (-1 * det.sub_total)
            det.descuento = (-1 * det.descuento)
            det.total = (-1 * det.total)
            det.save()

            return HttpResponse("ok")

        return HttpResponse("Usuario no autorizado")
    
    return render(request,template_name,context)

class FacturaDetDelete(SinPrivilegios, generic.DeleteView):
    permission_required = "fac.delete_facturadet"
    model = FacturaDet
    template_name = "fac/factura_det_del.html"
    context_object_name = 'obj'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Producto Eliminado')
        return response

    def get_success_url(self):
          id=self.kwargs['id']
          return reverse_lazy('fac:factura_edit', kwargs={'id': id})

def _dentro_plazo_anulacion(fecha_factura, ahora):
    """
    Regla del SIN (RND 102100000011): las facturas de la modalidad
    Electronica en Linea pueden anularse hasta el dia 9 del mes
    siguiente a su emision.
    """
    if ahora.year == fecha_factura.year and ahora.month == fecha_factura.month:
        return True

    if fecha_factura.month == 12:
        mes_siguiente, anio_siguiente = 1, fecha_factura.year + 1
    else:
        mes_siguiente, anio_siguiente = fecha_factura.month + 1, fecha_factura.year

    if ahora.year == anio_siguiente and ahora.month == mes_siguiente and ahora.day <= 9:
        return True

    return False


@login_required(login_url='/login/')
def anular_factura(request, id):
    """
    Anula una factura (no la borra). Restituye el stock de los
    productos facturados, y solo se permite dentro del plazo que
    exige el SIN, a usuarios autorizados (superusuario o con el
    permiso 'fac.anular_facturaenc').
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if not (request.user.is_superuser or request.user.has_perm('fac.anular_facturaenc')):
        messages.error(request, 'No tiene permisos para anular facturas')
        return redirect('fac:factura_edit', id=id)

    if enc.anulado:
        messages.error(request, 'Esta factura ya se encuentra anulada')
        return redirect('fac:factura_edit', id=id)

    ahora = timezone.now()
    if not _dentro_plazo_anulacion(enc.fecha, ahora):
        messages.error(
            request,
            'Fuera del plazo permitido para anular esta factura '
            '(hasta el dia 9 del mes siguiente a su emision, segun normativa del SIN)'
        )
        return redirect('fac:factura_edit', id=id)

    if request.method == 'POST':
        motivo = request.POST.get('motivo_anulacion', '')

        # Revertir el stock de cada producto de la factura (como una devolucion)
        detalles = FacturaDet.objects.filter(factura=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) + int(det.cantidad)
            prod.save()

        enc.anulado = True
        enc.fecha_anulacion = ahora
        enc.motivo_anulacion = motivo
        enc.usuario_anulacion = request.user
        enc.save()

        messages.success(request, 'Factura anulada correctamente. El stock fue restituido.')
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_anular.html', {'enc': enc})


@login_required(login_url='/login/')
def eliminar_factura(request, id):
    """
    Elimina fisicamente una factura. Reservado solo para superusuario.
    Bloqueado si la factura ya tiene un CUF asignado (ya reportada al
    SIN), ya que en ese caso la unica accion valida es Anular.
    """
    if not request.user.is_superuser:
        messages.error(request, 'Solo el superusuario puede eliminar facturas')
        return redirect('fac:factura_edit', id=id)

    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if enc.cuf:
        messages.error(
            request,
            'No se puede eliminar: esta factura ya fue reportada al SIN '
            '(tiene CUF asignado). Use "Anular" en su lugar.'
        )
        return redirect('fac:factura_edit', id=id)

    if request.method == 'POST':
        enc.delete()  # cascada borra FacturaDet; la señal post_delete restituye stock
        messages.success(request, 'Factura eliminada correctamente')
        return redirect('fac:factura_list')

    return render(request, 'fac/factura_eliminar.html', {'enc': enc})
