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
from django.utils import timezone

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


def _tiene_permiso_dia_cerrado(user):
    """
    True si este usuario puede crear/editar una compra aunque su fecha
    ya este cerrada (Cierre de Dia de Facturacion -- Compras nunca
    tuvo su propio concepto de cierre). Permiso dedicado, mismo
    criterio que eliminar_comprasenc: is_superuser SIEMPRE puede
    (has_perm ya lo cubre solo), y ademas cualquiera con el permiso
    explicito, sin necesitar ser superusuario tecnico de Django.
    """
    return user.has_perm('cmp.editar_compra_dia_cerrado')


def _puede_eliminar_por_ventana_tiempo(user, fecha_compra):
    """
    Ventana de tiempo permitida para ELIMINAR (compra completa o una
    linea de detalle), escalonada por permiso -- agregado 08/09/2026,
    mismo patron que usan ERP grandes (Sage: "period locking" con
    roles escalonados). INDEPENDIENTE del chequeo de dia cerrado
    (CierreDia): esto aplica siempre, este el dia formalmente cerrado
    o no -- son dos preguntas distintas ("¿es un dia cerrado del
    todo?" vs "¿que tan atras en el tiempo puede llegar este rol?").

    - Con 'cmp.editar_compra_dia_cerrado' (Administrador): sin limite,
      cualquier fecha -- ya tiene el permiso mas amplio de todos.
    - Con 'cmp.eliminar_compra_mes_vigente' (Supervisor): todo el mes
      en curso (año y mes iguales a hoy).
    - Sin ninguno de los dos (Almacenero): solo el dia de hoy.
    """
    if not fecha_compra:
        return True

    if user.has_perm('cmp.editar_compra_dia_cerrado'):
        return True

    hoy = timezone.localdate()
    if user.has_perm('cmp.eliminar_compra_mes_vigente'):
        return fecha_compra.year == hoy.year and fecha_compra.month == hoy.month

    return fecha_compra == hoy


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

        # --- NUEVO 07/09/2026: no se puede crear NI editar una compra
        # en una fecha ya cerrada. Compras nunca tuvo su propio
        # concepto de "cierre" -- se reusa el mismo CierreDia que ya
        # usa Facturacion (confirmado con Carlos que no existe uno
        # separado). Import local para evitar dependencia circular a
        # nivel de modulo entre cmp y fac. Va ANTES que cualquier otra
        # validacion -- si el dia esta cerrado, no importa si el resto
        # de los datos es valido. ---
        if fecha_compra:
            from fac.models import CierreDia
            try:
                fecha_compra_parsed = datetime.date.fromisoformat(fecha_compra)
            except ValueError:
                fecha_compra_parsed = None

            if fecha_compra_parsed and CierreDia.objects.filter(fecha=fecha_compra_parsed).exists() \
                    and not _tiene_permiso_dia_cerrado(request.user):
                messages.error(
                    request,
                    f'El día {fecha_compra_parsed.strftime("%d/%m/%Y")} ya fue cerrado -- '
                    'no se pueden crear ni editar compras en esa fecha.'
                )
                return redirect("cmp:compras_edit", compra_id=compra_id) if compra_id else redirect("cmp:compras_list")

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

    # NUEVO 08/09/2026: ventana de tiempo escalonada por rol (ver
    # _puede_eliminar_por_ventana_tiempo mas arriba) -- Almacenero solo
    # el mismo dia, Supervisor todo el mes en curso, Administrador sin
    # limite. Se chequea ANTES de mostrar la pantalla de confirmacion
    # (esta vista es pagina completa, no modal via abrir_modal, asi que
    # redirect + messages.error es el patron correcto aca).
    if not _puede_eliminar_por_ventana_tiempo(request.user, enc.fecha_compra):
        messages.error(
            request,
            f'No tiene permisos para eliminar esta compra: su fecha ({enc.fecha_compra.strftime("%d/%m/%Y")}) '
            'está fuera de la ventana de tiempo permitida para su rol.'
        )
        return redirect('cmp:compras_edit', compra_id=id)

    if request.method == 'POST':
        detalles = ComprasDet.objects.filter(compra=enc)

        # NUEVO 07/09/2026: si ya se vendio parte de este stock (via
        # Factura), revertir la compra completa podria dejar el
        # producto en existencia NEGATIVA -- fisicamente sin sentido.
        # Mismo criterio que usan los ERP grandes (SAP Business One,
        # Dynamics 365 Business Central: "Block Negative Inventory" /
        # "Prevent Negative Inventory" son funciones de fabrica, no
        # algo exotico). Se valida TODO antes de tocar nada -- todo o
        # nada, agregando por producto por si la misma compra tiene
        # mas de una linea del mismo producto.
        cantidad_por_producto = {}
        for det in detalles:
            cantidad_por_producto[det.producto_id] = cantidad_por_producto.get(det.producto_id, 0) + det.cantidad

        productos_en_negativo = []
        for producto_id, cantidad_total in cantidad_por_producto.items():
            prod = Producto.objects.get(pk=producto_id)
            if prod.existencia - cantidad_total < 0:
                productos_en_negativo.append(
                    f'{prod.descripcion} (stock actual: {prod.existencia}, se revertirían {cantidad_total})'
                )

        if productos_en_negativo:
            messages.error(
                request,
                'No se puede eliminar esta compra: dejaría stock negativo en: ' +
                '; '.join(productos_en_negativo) +
                '. Probablemente ya se vendió parte de esta mercadería -- revise antes de continuar.'
            )
            return redirect('cmp:compras_edit', compra_id=id)

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


def _rechazar_envio_modal(request, mensaje):
    """
    Para rechazar un POST que llega desde un formulario YA ABIERTO
    dentro de un popup (abrir_modal ya engancho su submit por AJAX
    desde que se mostro) -- a diferencia de _modal_error() (pensado
    para bloquear ANTES de mostrar el formulario, en el GET inicial),
    un 200 aca lo toma como "exito" el JS generico de abrir_modal, que
    NO mira el contenido de la respuesta, solo el codigo HTTP.
    Encontrado 07/09/2026: CompraDetDelete devolvia _modal_error() en
    sus tres chequeos (dia cerrado, minimo 1 detalle, stock negativo)
    -- todos silenciosamente ignorados, mostrando "Guardado
    Satisfactoriamente" con la eliminacion ya rechazada del lado
    servidor.

    Imita el mismo formato que ya usa MixinFormInvalid
    (form.errors.as_json(), un 400 con {"errors": "<json>"}) para que
    el manejador de errores YA EXISTENTE en base.html lo muestre
    correctamente, sin tocar ese archivo.
    """
    errores = {'__all__': [{'message': mensaje, 'code': 'rechazado'}]}
    return JsonResponse({'errors': json.dumps(errores)}, status=400)


def _modal_error(request, mensaje):
    """
    Mismo patron que ya usa fac/views.py: abrir_modal() en base.html
    trata CUALQUIER respuesta 2xx como "exito" (aunque sea un redirect
    seguido, termina en 200) -- un simple redirect() aca mostraria
    "Guardado Satisfactoriamente" aunque en realidad se haya
    rechazado la accion. Se reusa la MISMA plantilla de fac (es
    generica, no tiene nada especifico de Facturacion en su marcado).
    """
    return render(request, 'fac/_modal_error.html', {'mensaje': mensaje})


class CompraDetDelete(SinPrivilegios, generic.DeleteView):
    permission_required = "cmp.delete_comprasdet"
    model = ComprasDet
    template_name = "cmp/compras_det_del.html"
    context_object_name = 'obj'
    
    def get_success_url(self):
          compra_id=self.kwargs['compra_id']
          return reverse_lazy('cmp:compras_edit', kwargs={'compra_id': compra_id})

    def delete(self, request, *args, **kwargs):
        """
        CORREGIDO 07/09/2026 -- dos bloqueos que faltaban, confirmados
        en vivo por Carlos, MAS un bug de fondo en como se rechazaban:
        1. Esta vista no chequeaba dia cerrado en absoluto -- se podia
           eliminar una linea de una compra en un dia ya cerrado
           (mismo CierreDia de Facturacion, mismo criterio que en
           compras()).
        2. Nada impedia dejar una compra con CERO lineas de detalle --
           confirmado en vivo que al borrar la unica linea, la
           cabecera quedaba guardada vacia, un estado invalido que no
           deberia poder existir (una compra necesita al menos un
           producto).
        3. (bug de fondo, encontrado al investigar por que 1 y 2 no
           frenaban nada) Los tres chequeos usaban _modal_error(), que
           devuelve 200 -- pero el formulario de esta vista YA esta
           abierto y YA fue enganchado por abrir_modal() cuando se
           mostro el popup. El JS generico de exito no mira el
           contenido de la respuesta, solo el codigo HTTP: un 200 se
           toma como "Guardado Satisfactoriamente" sin importar que la
           eliminacion se haya rechazado del lado servidor. Se
           reemplazo por _rechazar_envio_modal() (ver mas arriba), que
           imita el formato de error que ya usa MixinFormInvalid.
        """
        self.object = self.get_object()
        compra = self.object.compra

        from fac.models import CierreDia
        if compra.fecha_compra and CierreDia.objects.filter(fecha=compra.fecha_compra).exists() \
                and not request.user.has_perm('cmp.editar_compra_dia_cerrado'):
            return _rechazar_envio_modal(
                request,
                f'El día {compra.fecha_compra.strftime("%d/%m/%Y")} ya fue cerrado -- '
                'no se pueden eliminar líneas de esa compra.'
            )

        # NUEVO 08/09/2026: ventana de tiempo escalonada por rol (ver
        # _puede_eliminar_por_ventana_tiempo) -- independiente del
        # chequeo de dia cerrado de arriba (son dos preguntas
        # distintas: "¿esta cerrado del todo?" vs "¿que tan atras
        # puede llegar este rol?").
        if not _puede_eliminar_por_ventana_tiempo(request.user, compra.fecha_compra):
            return _rechazar_envio_modal(
                request,
                f'No tiene permisos para eliminar líneas de esta compra: su fecha '
                f'({compra.fecha_compra.strftime("%d/%m/%Y")}) está fuera de la ventana '
                'de tiempo permitida para su rol.'
            )

        # CORREGIDO 07/09/2026 -- decision de Carlos: ya NO se bloquea
        # llegar a cero detalle aca. En cambio, se permite eliminar la
        # ultima linea, y es compras.html (boton Cancelar) el que no
        # deja salir de la pantalla de edicion mientras la compra
        # tenga cero detalle -- Guardar ya rechazaba esto de por si
        # (exige producto seleccionado).

        # NUEVO 07/09/2026: mismo criterio que eliminar_compra -- no
        # dejar el producto en existencia negativa si ya se vendio
        # parte de lo comprado. Se chequea ANTES de llamar a
        # super().delete(), que es lo que dispara la señal
        # detalle_compra_borrar (la que de verdad resta el stock).
        prod = self.object.producto
        if prod.existencia - self.object.cantidad < 0:
            return _rechazar_envio_modal(
                request,
                f'No se puede eliminar: "{prod.descripcion}" quedaría con stock negativo '
                f'(actual: {prod.existencia}, se revertirían {self.object.cantidad}). '
                'Probablemente ya se vendió parte de esta mercadería.'
            )

        return super().delete(request, *args, **kwargs)