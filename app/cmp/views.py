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

from .models import Proveedor, ComprasEnc, ComprasDet, recalcular_costo_actual
from cmp.forms import ProveedorForm,ComprasEncForm
from bases.views import SinPrivilegios, obtener_sucursal_actual
from inv.models import Producto, StockSucursal, ajustar_stock_sucursal

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
            det = ComprasDet.objects.filter(compra=enc).order_by('id')
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
        
        # Cantidad NETA del detalle (suma de cantidades, contando las
        # lineas de reversion en negativo). Si es 0, la compra no tiene
        # ningun producto "util" -- se trata igual que "sin detalle"
        # para los botones Guardar/Cancelar (ver compras.html).
        detalle_neto = sum(int(d.cantidad) for d in det) if det else 0

        # Numero de compra a mostrar en la cabecera (12/09/2026): si ya
        # existe, su id real; si es nueva, una PREVIA del id que le
        # tocaria (mismo criterio ya usado en facturas() -- siguiente
        # id de la secuencia). Es una vista previa, no una reserva: si
        # se crea otra compra antes de guardar esta, el numero real
        # puede terminar siendo otro.
        if enc:
            numero_compra = enc.id
        else:
            ultima = ComprasEnc.objects.order_by('-id').first()
            numero_compra = (ultima.id + 1) if ultima else 1

        contexto={
            'productos':prod,'encabezado':enc,'detalle':det,'form_enc':form_compras,
            'compra_sin_detalle_util': bool(enc) and detalle_neto == 0,
            'numero_compra': numero_compra,
        }

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
        # de los datos es valido.
        #
        # ENDURECIDO 10/09/2026: antes esto SOLO miraba la fecha que
        # venia en el POST. El campo Fecha Compra esta 'readonly' pero
        # tiene un datetimepicker enganchado, asi que un almacenero
        # podia cambiarlo a un dia abierto, agregar el detalle igual, y
        # de paso la vista sobreescribia enc.fecha_compra con esa fecha
        # nueva. Ahora, para una compra YA EXISTENTE, se valida tambien
        # la fecha ALMACENADA (la unica que no se puede falsear desde
        # el navegador) -- mismo criterio que ya usa CompraDetDelete
        # para borrar lineas. Se chequean las dos: la guardada (que la
        # linea nueva pertenece a un dia cerrado) y la del POST (que no
        # se este moviendo la compra HACIA un dia cerrado). ---
        from fac.models import CierreDia

        fechas_a_validar = []
        if compra_id:
            enc_actual = ComprasEnc.objects.filter(pk=compra_id).first()
            if enc_actual and enc_actual.fecha_compra:
                fechas_a_validar.append(enc_actual.fecha_compra)
        if fecha_compra:
            try:
                fechas_a_validar.append(datetime.date.fromisoformat(fecha_compra))
            except ValueError:
                pass

        if not _tiene_permiso_dia_cerrado(request.user):
            for f in fechas_a_validar:
                if CierreDia.objects.filter(fecha=f).exists():
                    messages.error(
                        request,
                        f'El día {f.strftime("%d/%m/%Y")} ya fue cerrado -- '
                        'no se pueden crear ni editar compras (ni agregar detalles) en esa fecha.'
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

        # Sucursal (Fase 2, 20/09/2026): se resuelve sola segun quien
        # esta logueado -- se valida ANTES de crear la cabecera, mismo
        # criterio que el resto de las validaciones de este bloque.
        sucursal_actual = obtener_sucursal_actual(request)
        if not compra_id and sucursal_actual is None:
            messages.error(
                request,
                'No se pudo determinar su sucursal. Pida a un Administrador que se la '
                'asigne en Usuarios y Roles antes de registrar una compra.'
            )
            return redirect("cmp:compras_list")

        # --- Recien aca, con todo validado, se crea/actualiza el
        # encabezado. ---
        if not compra_id:
            enc = ComprasEnc(
                fecha_compra=fecha_compra,
                observacion=observacion,
                no_factura=no_factura,
                fecha_factura=fecha_factura,
                proveedor=prov,
                uc = request.user,
                sucursal=sucursal_actual,
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
            # Foto del costo promedio ANTES de que esta compra lo mueva
            # (para auditoria / posible restauracion exacta al revertir).
            costo_actual_antes=prod.costo_actual,
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

        # Stock de la sucursal de ESTA compra (Fase 2, 20/09/2026), no
        # el total agregado de la empresa.
        productos_en_negativo = []
        for producto_id, cantidad_total in cantidad_por_producto.items():
            prod = Producto.objects.get(pk=producto_id)
            stock_en_sucursal = StockSucursal.objects.filter(
                producto=prod, sucursal=enc.sucursal
            ).first()
            cantidad_actual = stock_en_sucursal.cantidad if stock_en_sucursal else int(prod.existencia)
            if cantidad_actual - cantidad_total < 0:
                productos_en_negativo.append(
                    f'{prod.descripcion} (stock actual en {enc.sucursal or "esta sucursal"}: '
                    f'{cantidad_actual}, se revertirían {cantidad_total})'
                )

        if productos_en_negativo:
            messages.error(
                request,
                'No se puede eliminar esta compra: dejaría stock negativo en: ' +
                '; '.join(productos_en_negativo) +
                '. Probablemente ya se vendió parte de esta mercadería -- revise antes de continuar.'
            )
            return redirect('cmp:compras_edit', compra_id=id)

        enc.estado = False
        enc.save()

        # Revertir stock y recalcular el costo promedio de cada
        # producto afectado. El costo se recalcula DESPUES de marcar
        # enc.estado=False, porque recalcular_costo_actual ignora las
        # lineas de compras con estado=False -- asi la compra eliminada
        # deja de pesar en el promedio. Stock: atomico + con dimension
        # de sucursal (Fase 2, 20/09/2026), ver ajustar_stock_sucursal.
        for producto_id, cantidad_total in cantidad_por_producto.items():
            prod = Producto.objects.get(pk=producto_id)
            recalcular_costo_actual(prod)
            prod.save(update_fields=['costo_actual'])
            ajustar_stock_sucursal(producto_id, enc.sucursal, -cantidad_total)

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


class CompraDetDelete(SinPrivilegios, generic.DetailView):
    """
    "Quitar un producto de una compra". A pesar del nombre historico
    (Delete), 10/09/2026 pasa a NO borrar nada: crea una linea NUEVA
    con cantidad negativa ("contra compra"), dejando la original
    intacta -- misma mecanica que borrar_detalle_factura en ventas,
    para tener un solo criterio en todo el sistema. Ver
    ComprasDet.usuario_reversion y recalcular_costo_actual.

    Antes era un DeleteView con toda la logica de control dentro de un
    metodo delete(). En Django 5.2 ese metodo YA NO SE LLAMA
    (BaseDeleteView.post -> form_valid -> object.delete()), asi que
    TODOS los controles (dia cerrado, ventana de tiempo, stock
    negativo) quedaron como codigo muerto: cualquier usuario podia
    quitar una linea de una compra en dia cerrado sin ningun freno.
    Ahora la logica vive en post(), que si se ejecuta.
    """
    permission_required = "cmp.delete_comprasdet"
    model = ComprasDet
    template_name = "cmp/compras_det_del.html"
    context_object_name = 'obj'

    def post(self, request, *args, **kwargs):
        self.object = det = self.get_object()
        compra = det.compra

        if det.cantidad < 0:
            return _rechazar_envio_modal(
                request, 'Esta línea ya es una reversión, no se puede revertir de nuevo.'
            )

        # --- Control 1: dia cerrado (bypass solo con el permiso
        # editar_compra_dia_cerrado -- Administrador). ---
        from fac.models import CierreDia
        if compra.fecha_compra and CierreDia.objects.filter(fecha=compra.fecha_compra).exists() \
                and not request.user.has_perm('cmp.editar_compra_dia_cerrado'):
            return _rechazar_envio_modal(
                request,
                f'El día {compra.fecha_compra.strftime("%d/%m/%Y")} ya fue cerrado -- '
                'no se pueden quitar productos de esa compra.'
            )

        # NOTA (10/09/2026): la "ventana de tiempo escalonada por rol"
        # (_puede_eliminar_por_ventana_tiempo: Almacenero solo hoy,
        # Supervisor mes en curso, ...) NO se aplica al quitar una
        # linea de detalle. Decision de Carlos (puntos 3, 7 y 8): la
        # unica pregunta es "¿el dia esta cerrado?" -- si NO lo esta,
        # cualquier usuario con permiso puede quitar una linea, incluso
        # la ultima. Esa ventana escalonada sigue vigente solo para
        # eliminar la COMPRA COMPLETA (ver eliminar_compra).

        # --- Control 2: stock negativo -- para TODOS los usuarios, sin
        # excepcion (ni Administrador). Revertir esta linea sacaria
        # `cantidad` unidades del stock; si eso deja negativo, es que
        # ya se vendio parte de esa mercaderia. ---
        prod = det.producto
        if int(prod.existencia) - int(det.cantidad) < 0:
            return _rechazar_envio_modal(
                request,
                f'No se puede quitar: "{prod.descripcion}" quedaría con stock negativo '
                f'(actual: {prod.existencia}, se revertirían {det.cantidad}). '
                'Probablemente ya se vendió parte de esta mercadería.'
            )

        # --- Contra compra: fila nueva con cantidad negativa. La señal
        # detalle_compra_guardar recalcula stock, costo promedio y
        # totales de la cabecera. Mismo patron que ventas
        # (borrar_detalle_factura). ---
        det.id = None
        det.cantidad = -1 * det.cantidad
        det.descuento = -1 * det.descuento
        det.costo_actual_antes = None
        det.usuario_reversion = request.user
        det.uc = request.user
        det.save()

        # abrir_modal() (base.html) toma cualquier 2xx como exito y
        # recarga la pantalla.
        return HttpResponse(status=204)