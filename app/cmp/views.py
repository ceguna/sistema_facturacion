from django.http import JsonResponse
from django.shortcuts import render,redirect
from django.views import generic
from django.urls import reverse_lazy
import datetime
from django.http import HttpResponse

from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
import json
from django.db.models import Sum

from .models import Proveedor, ComprasEnc, ComprasDet
from cmp.forms import ProveedorForm,ComprasEncForm
from bases.views import SinPrivilegios
from inv.models import Producto

class ProveedorView(SinPrivilegios, generic.ListView):
    model = Proveedor
    template_name = "cmp/proveedor_list.html"
    context_object_name = "obj"
    permission_required="cmp.view_proveedor"

class ProveedorNew(SuccessMessageMixin,SinPrivilegios,\
                   generic.CreateView):
    permission_required="cmp.add_proveedor"
    model=Proveedor
    template_name="cmp/proveedor_form.html"
    context_object_name = 'obj'
    form_class=ProveedorForm
    success_url= reverse_lazy("cmp:proveedor_list")
    login_url = "bases:login"
    success_message="Proveedor Creado Satisfactoriamente"

    #def form_valid(self, form):
    #    form.instance.uc = self.request.user
    #    #print(self.request.user.id)
    #    return super().form_valid(form)
    
    def form_valid(self, form):
        form.instance.uc = self.request.user
        self.request.session['success_message'] = self.success_message

        # Obtener la URL de redirección
        redirect_url = reverse_lazy("cmp:proveedor_list")

        # Crear una respuesta JSON con la URL de redirección y el mensaje de éxito
        response = JsonResponse({'redirect_url': redirect_url, 'success_message': self.success_message}, status=200)

        # Establecer el encabezado X-Redirect para indicar al navegador que debe redirigir a la URL especificada
        response['X-Redirect'] = redirect_url

        return super().form_valid(form)
    
class ProveedorEdit(SuccessMessageMixin, SinPrivilegios,\
                   generic.UpdateView):
    model=Proveedor
    template_name="cmp/proveedor_form.html"
    context_object_name = 'obj'
    form_class=ProveedorForm
    success_url= reverse_lazy("cmp:proveedor_list")
    success_message="Proveedor Editado"
    permission_required="cmp.change_proveedor"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        print(self.request.user.id)
        return super().form_valid(form)


@login_required(login_url="/login/")
@permission_required("cmp.change_proveedor",login_url="/login/")
def ProveedorInactivar(request,id):
    """
    Activa/desactiva un proveedor. CORREGIDO 02/09/2026 -- antes
    siempre ponia estado=False sin importar el estado actual, sin
    ninguna forma de reactivar un proveedor ya inactivado desde esta
    pantalla. Ahora invierte el estado actual, mismo patron que ya usa
    clienteInactivar en fac/views.py.
    """
    template_name='cmp/catalogos_inactivo.html'
    contexto={}
    prv = Proveedor.objects.filter(pk=id).first()

    if not prv:
        return HttpResponse('Proveedor no existe ' + str(id))

    if request.method=='GET':
        contexto={'obj':prv}

    if request.method=='POST':
        prv.estado = not prv.estado
        prv.save()
        estado_texto = 'activado' if prv.estado else 'inactivado'
        contexto={'obj':'OK'}
        return HttpResponse(f'Proveedor {estado_texto}')

    return render(request,template_name,contexto)


class ComprasView(SinPrivilegios, generic.ListView):
    model = ComprasEnc
    template_name = "cmp/compras_list.html"
    context_object_name = "obj"
    permission_required="cmp.view_comprasenc"

    def get_queryset(self):
        # Agregado 02/09/2026 junto con eliminar_compra: sin este
        # filtro, una compra eliminada (estado=False) seguia
        # apareciendo en el listado normal -- antes no importaba
        # porque no existia ninguna forma de eliminar una compra.
        return ComprasEnc.objects.filter(estado=True).order_by('-id')


@login_required(login_url='/login/')
@permission_required('cmp.change_comprasenc', login_url='bases:sin_privilegios')
def compras(request,compra_id=None):
    """
    CORREGIDO 02/09/2026 -- el permiso paso de 'cmp.view_comprasenc' a
    'cmp.change_comprasenc': antes, cualquiera con solo permiso de VER
    compras (ej. un futuro rol de Solo Lectura/contador) podia tambien
    crear y modificar compras desde esta misma vista, porque el
    permiso de ver y el de crear/editar eran el mismo. Mismo criterio
    que ya usa facturas() en fac/views.py (gestiona con 'change_X',
    separado del 'view_X' que usa el ListView del listado).
    """
    template_name="cmp/compras.html"
    prod=Producto.objects.filter(estado=True)
    form_compras={}
    contexto={}

    if request.method=='GET':
        form_compras=ComprasEncForm()
        enc = ComprasEnc.objects.filter(pk=compra_id).first()

        if enc:
            det = ComprasDet.objects.filter(compra=enc)
            fecha_compra = datetime.date.isoformat(enc.fecha_compra)
            fecha_factura = datetime.date.isoformat(enc.fecha_factura)
            e = {
                'fecha_compra':fecha_compra,
                'proveedor': enc.proveedor,
                'observacion': enc.observacion,
                'no_factura': enc.no_factura,
                'fecha_factura': fecha_factura,
                'sub_total': enc.sub_total,
                'descuento': enc.descuento,
                'total':enc.total
            }
            form_compras = ComprasEncForm(e)
        else:
            det=None
            form_compras = ComprasEncForm(initial={
                'fecha_compra': datetime.date.today(),
                'fecha_factura': datetime.date.today(),
            })
        
        contexto={'productos':prod,'encabezado':enc,'detalle':det,'form_enc':form_compras}

    if request.method=='POST':
        fecha_compra = request.POST.get("fecha_compra")
        observacion = request.POST.get("observacion")
        no_factura = request.POST.get("no_factura")
        fecha_factura = request.POST.get("fecha_factura")
        proveedor = request.POST.get("proveedor")

        # --- CORREGIDO 02/09/2026 (hallazgo "encabezado huerfano"):
        # todas las validaciones (proveedor, producto, cantidad,
        # precio) se hacen ANTES de crear/guardar el ComprasEnc.
        # Antes, el encabezado se guardaba primero y RECIEN DESPUES se
        # validaba el producto -- si el producto no existia, quedaba
        # un encabezado vacio (sin ningun detalle) guardado en la
        # base. Mismo criterio que ya usa facturas() en fac/views.py.
        if not compra_id:
            prov = Proveedor.objects.filter(pk=proveedor).first()
            if not prov:
                messages.error(request, 'El proveedor seleccionado no existe o no es válido')
                return redirect("cmp:compras_list")

        producto = request.POST.get("id_id_producto")
        cantidad = request.POST.get("id_cantidad_detalle")
        precio = request.POST.get("id_precio_detalle")
        descuento_detalle = request.POST.get("id_descuento_detalle")

        prod = Producto.objects.filter(pk=producto).first()
        if not prod:
            messages.error(request, 'El producto seleccionado no existe o no es válido')
            return redirect("cmp:compras_edit", compra_id=compra_id) if compra_id else redirect("cmp:compras_list")

        # --- CORREGIDO 02/09/2026 (hallazgo "sin validar cantidad/
        # precio negativos o en cero"): antes nada impedia cargar una
        # cantidad negativa (bajaba el stock en vez de subirlo, ya que
        # la señal detalle_compra_guardar simplemente suma
        # instance.cantidad sin chequear el signo) o un precio en 0/
        # negativo. ---
        try:
            cantidad_num = float(cantidad)
            precio_num = float(precio)
            descuento_num = float(descuento_detalle) if descuento_detalle not in (None, '') else 0.0
        except (TypeError, ValueError):
            messages.error(request, 'Datos de cantidad/precio/descuento inválidos.')
            return redirect("cmp:compras_edit", compra_id=compra_id) if compra_id else redirect("cmp:compras_list")

        if cantidad_num <= 0:
            messages.error(request, 'La cantidad debe ser mayor a 0.')
            return redirect("cmp:compras_edit", compra_id=compra_id) if compra_id else redirect("cmp:compras_list")

        if precio_num <= 0:
            messages.error(request, 'El precio debe ser mayor a 0.')
            return redirect("cmp:compras_edit", compra_id=compra_id) if compra_id else redirect("cmp:compras_list")

        # --- Recien aca, con todo validado, se crea/actualiza el
        # encabezado. ---
        if not compra_id:
            enc = ComprasEnc(
                fecha_compra=fecha_compra,
                observacion=observacion,
                no_factura=no_factura,
                fecha_factura=fecha_factura,
                proveedor=prov,
                uc = request.user 
            )
            enc.save()
            compra_id=enc.id
        else:
            enc=ComprasEnc.objects.filter(pk=compra_id).first()
            if not enc:
                messages.error(request, 'La compra no existe.')
                return redirect("cmp:compras_list")
            enc.fecha_compra = fecha_compra
            enc.observacion = observacion
            enc.no_factura=no_factura
            enc.fecha_factura=fecha_factura
            enc.um=request.user.id
            enc.save()

        det = ComprasDet(
            compra=enc,
            producto=prod,
            cantidad=cantidad_num,
            precio_prv=precio_num,
            descuento=descuento_num,
            costo=0,
            uc = request.user
        )
        det.save()

        sub_total=ComprasDet.objects.filter(compra=compra_id).aggregate(Sum('sub_total'))
        descuento=ComprasDet.objects.filter(compra=compra_id).aggregate(Sum('descuento'))
        enc.sub_total = sub_total["sub_total__sum"] or 0
        enc.descuento = descuento["descuento__sum"] or 0
        enc.save()

        return redirect("cmp:compras_edit",compra_id=compra_id)

    return render(request, template_name, contexto)


@login_required(login_url='/login/')
def eliminar_compra(request, id):
    """
    Elimina (soft-delete) una compra completa. Agregado 02/09/2026 --
    antes NO existia ninguna forma de eliminar/anular una compra
    entera, solo lineas de detalle sueltas (CompraDetDelete, que borra
    fisico). Mismo criterio de auditoria que el resto del sistema: no
    se borra fisicamente, se marca estado=False (ClaseModelo ya trae
    este campo, igual que Cliente/Producto/FacturaEnc).

    Como las lineas de detalle NO se borran fisicamente al eliminar el
    encabezado (siguen existiendo, solo el encabezado queda inactivo),
    hay que revertir a mano el efecto en stock que cada linea ya sumo
    al guardarse -- mismo patron que eliminar_factura en fac/views.py.
    """
    if not request.user.has_perm('cmp.eliminar_comprasenc'):
        messages.error(request, 'No tiene permisos para eliminar compras.')
        return redirect('cmp:compras_edit', compra_id=id)

    enc = ComprasEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Compra no existe.')
        return redirect('cmp:compras_list')

    if not enc.estado:
        messages.error(request, 'Esta compra ya fue eliminada.')
        return redirect('cmp:compras_list')

    if request.method == 'POST':
        detalles = ComprasDet.objects.filter(compra=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) - int(det.cantidad)
            prod.save()

        enc.estado = False
        enc.save()

        messages.success(
            request,
            'Compra eliminada correctamente (queda registrada en la base para auditoría, oculta del uso normal).'
        )
        return redirect('cmp:compras_list')

    return render(request, 'cmp/compras_eliminar.html', {'enc': enc})


class CompraDetDelete(SinPrivilegios, generic.DeleteView):
    permission_required = "cmp.delete_comprasdet"
    model = ComprasDet
    template_name = "cmp/compras_det_del.html"
    context_object_name = 'obj'
    
    def get_success_url(self):
          compra_id=self.kwargs['compra_id']
          return reverse_lazy('cmp:compras_edit', kwargs={'compra_id': compra_id})