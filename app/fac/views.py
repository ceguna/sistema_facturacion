from django.http import JsonResponse
from django.shortcuts import render,redirect, get_object_or_404
from django.views import generic
from django.views.decorators.http import require_POST

from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from datetime import datetime
from django.contrib import messages

from django.contrib.auth import authenticate
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Sum

from bases.views import SinPrivilegios

from .models import Cliente,FacturaEnc,FacturaDet,CierreDia,dias_pendientes_de_cierre
from .forms import ClienteForm
import inv.views as inv
from inv.models import Producto

from fe.services import emitir_factura_sin, anular_factura_sin, revertir_anulacion_sin, EmisionSinError
from catalogos.models import CatalogoSIN

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

    def get_context_data(self, **kwargs):
        """
        Se agrega 'dia_cerrado' a cada factura de la lista -- indica si
        la FECHA de esa factura ya tiene un CierreDia registrado (no
        confundir con el estado_sin de la factura en si, que ya se
        muestra en la columna 'Estado').
        """
        context = super().get_context_data(**kwargs)
        fechas_cerradas = set(CierreDia.objects.values_list('fecha', flat=True))
        for item in context['obj']:
            item.dia_cerrado = timezone.localtime(item.fecha).date() in fechas_cerradas
        return context

@login_required(login_url='/login/')
@permission_required('fac.change_facturaenc', login_url='bases:sin_privilegios')
def facturas(request,id=None):
    template_name='fac/facturas.html'

    detalle = {}
    clientes = Cliente.objects.filter(estado=True)
    
    if request.method == "GET":
        if not id and dias_pendientes_de_cierre():
            messages.warning(
                request,
                'No puede registrar facturas nuevas: hay días anteriores pendientes de Cierre de Día.'
            )
            return redirect('fac:cierre_dia_pendientes')

        enc = FacturaEnc.objects.filter(pk=id).first()
        if id:
            if not enc:
                messages.error(request,'Factura No Existe')
                return redirect("fac:factura_list")

        if not enc:
            # Instancia "vacia" en memoria (no guardada) para una factura
            # nueva -- asi el template tiene acceso a los mismos campos y
            # properties (puede_editarse, estado_sin, etc.) del modelo
            # real, sin duplicar su definicion en un diccionario aparte.
            enc = FacturaEnc(id=0)
            enc.fecha = datetime.today()
            enc.cliente = None
            enc.sub_total = 0.00
            enc.descuento = 0.00
            enc.total = 0.00
            detalle = None
        else:
            detalle = FacturaDet.objects.filter(factura=enc)

        contexto = {"enc": enc, "det": detalle, "clientes": clientes}
        return render(request, template_name, contexto)
    
    if request.method == "POST":
        # Misma proteccion que en el GET, pero del lado del servidor
        # para una factura NUEVA (no aplica al editar una ya existente,
        # que es justo lo que la pantalla de cierre necesita permitir).
        if not id and dias_pendientes_de_cierre():
            messages.warning(
                request,
                'No puede registrar facturas nuevas: hay días anteriores pendientes de Cierre de Día.'
            )
            return redirect('fac:cierre_dia_pendientes')

        cliente = request.POST.get("enc_cliente")
        fecha  = request.POST.get("fecha")
        cli = Cliente.objects.filter(pk=cliente).first()
        if not cli:
            messages.error(request, 'El cliente seleccionado no existe o no es válido')
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_list")

        # Si la factura ya existe, verificar ANTES que nada que todavia
        # se pueda editar -- esto es lo que realmente protege contra
        # agregar productos a una factura ya emitida al SIN o anulada.
        # El frontend puede ocultar botones, pero la unica proteccion
        # real es esta, del lado del servidor.
        if id:
            enc_existente = FacturaEnc.objects.filter(pk=id).first()
            if enc_existente and not enc_existente.puede_editarse:
                messages.error(
                    request,
                    'No se puede modificar: esta factura ya fue reportada al SIN o está anulada.'
                )
                return redirect("fac:factura_edit", id=id)

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

    def _bloqueada(self, obj):
        """
        Chequeo real del lado del servidor: independiente de que el
        template oculte o no el boton, esta es la unica proteccion
        que efectivamente impide borrar un detalle de una factura ya
        reportada al SIN o anulada.
        """
        return not obj.factura.puede_editarse

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self._bloqueada(self.object):
            messages.error(
                request,
                'No se puede eliminar: esta factura ya fue reportada al SIN o está anulada.'
            )
            return redirect('fac:factura_edit', id=self.object.factura.id)
        return super().get(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self._bloqueada(self.object):
            messages.error(
                request,
                'No se puede eliminar: esta factura ya fue reportada al SIN o está anulada.'
            )
            return redirect('fac:factura_edit', id=self.object.factura.id)
        response = super().delete(request, *args, **kwargs)
        messages.success(self.request, 'Producto Eliminado')
        return response

    def get_success_url(self):
          id=self.kwargs['id']
          return reverse_lazy('fac:factura_edit', kwargs={'id': id})

def _dentro_plazo_anulacion(fecha_factura, ahora):
    """
    Regla del SIN (RND 102100000011): las facturas de la modalidad
    Electronica en Linea pueden anularse (o revertir su anulacion)
    hasta el dia 9 del mes siguiente a su emision.
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


def _es_supervisor(user):
    """Mismo criterio de autorizacion para Anular y Revertir Anulacion."""
    return user.is_superuser or user.has_perm('fac.anular_facturaenc')


def _es_supervisor_cierre(user):
    """Autorizacion para cerrar el dia -- mismo patron que _es_supervisor."""
    return user.is_superuser or user.has_perm('fac.gestionar_cierre_dia')


@login_required(login_url='/login/')
def anular_factura(request, id):
    """
    Anula una factura: primero ante el SIN (servicio real
    anulacionFactura, Etapa VII), y solo si el SIN confirma, recien
    ahi se marca localmente y se devuelve el stock. Si el SIN rechaza,
    la factura queda tal cual estaba -- no se toca stock ni el flag
    local 'anulado'.

    Solo se permite dentro del plazo que exige el SIN, a usuarios
    autorizados (superusuario o con el permiso 'fac.anular_facturaenc').
    Solo aplica a facturas que ya fueron aceptadas por el SIN
    (reportada_ante_sin) -- si nunca se envio o fue observada, no hay
    nada que anular formalmente.
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if not _es_supervisor(request.user):
        messages.error(request, 'No tiene permisos para anular facturas')
        return redirect('fac:factura_edit', id=id)

    if enc.anulado:
        messages.error(request, 'Esta factura ya se encuentra anulada')
        return redirect('fac:factura_edit', id=id)

    if not enc.reportada_ante_sin:
        messages.error(
            request,
            'Solo se pueden anular facturas que ya fueron aceptadas por el SIN. '
            'Esta factura no fue reportada — puede editarla o eliminarla en su lugar.'
        )
        return redirect('fac:factura_edit', id=id)

    ahora = timezone.now()
    if not _dentro_plazo_anulacion(enc.fecha, ahora):
        messages.error(
            request,
            'Fuera del plazo permitido para anular esta factura '
            '(hasta el dia 9 del mes siguiente a su emision, segun normativa del SIN)'
        )
        return redirect('fac:factura_edit', id=id)

    motivos = CatalogoSIN.objects.filter(
        tipo_catalogo=CatalogoSIN.TipoCatalogo.MOTIVOS_ANULACION, vigente=True
    ).order_by('codigo')

    if request.method == 'POST':
        codigo_motivo_raw = request.POST.get('codigo_motivo')
        detalle_adicional = request.POST.get('motivo_anulacion', '').strip()

        motivo_catalogo = motivos.filter(codigo=codigo_motivo_raw).first()
        if not motivo_catalogo:
            messages.error(request, 'Debe seleccionar un motivo de anulación válido.')
            return redirect('fac:factura_anular', id=id)

        try:
            anular_factura_sin(enc, int(motivo_catalogo.codigo))
        except EmisionSinError as e:
            messages.error(request, f'El SIN rechazó la anulación: {e}')
            return redirect('fac:factura_edit', id=id)

        # El SIN confirmo (905) -- recien ahora se refleja localmente:
        # devolver stock, marcar anulado, y guardar el texto combinado
        # (descripcion oficial del catalogo + detalle opcional del usuario).
        detalles = FacturaDet.objects.filter(factura=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) + int(det.cantidad)
            prod.save()

        texto_motivo = motivo_catalogo.descripcion
        if detalle_adicional:
            texto_motivo += f" — {detalle_adicional}"

        enc.anulado = True
        enc.fecha_anulacion = ahora
        enc.motivo_anulacion = texto_motivo
        enc.usuario_anulacion = request.user
        enc.save()

        messages.success(
            request,
            'Factura anulada correctamente ante el SIN. El stock fue restituido.'
        )
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_anular.html', {'enc': enc, 'motivos': motivos})


@login_required(login_url='/login/')
def revertir_anulacion(request, id):
    """
    Revierte ante el SIN la anulacion de una factura (Etapa VIII).
    Mismo nivel de autorizacion que anular_factura (superusuario o
    'fac.anular_facturaenc') -- solo un supervisor puede hacerlo.

    Si el SIN confirma, recien ahi se refleja localmente: se vuelve a
    descontar el stock (inverso exacto de lo que hizo la anulacion),
    y se desmarca 'anulado' -- la factura vuelve a estar activa.
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if not _es_supervisor(request.user):
        messages.error(request, 'No tiene permisos para revertir anulaciones')
        return redirect('fac:factura_edit', id=id)

    if not enc.anulado or enc.estado_sin != FacturaEnc.SIN_ANULADA:
        messages.error(request, 'Esta factura no está anulada ante el SIN, no hay nada que revertir.')
        return redirect('fac:factura_edit', id=id)

    ahora = timezone.now()
    if not _dentro_plazo_anulacion(enc.fecha, ahora):
        messages.error(
            request,
            'Fuera del plazo permitido para revertir la anulación de esta factura '
            '(hasta el dia 9 del mes siguiente a su emision, segun normativa del SIN)'
        )
        return redirect('fac:factura_edit', id=id)

    if request.method == 'POST':
        try:
            revertir_anulacion_sin(enc)
        except EmisionSinError as e:
            messages.error(request, f'El SIN rechazó la reversión: {e}')
            return redirect('fac:factura_edit', id=id)

        # El SIN confirmo (907) -- recien ahora se refleja localmente:
        # se vuelve a descontar el stock (se habia devuelto al anular),
        # y se desmarca el flag local 'anulado'.
        detalles = FacturaDet.objects.filter(factura=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) - int(det.cantidad)
            prod.save()

        enc.anulado = False
        enc.save()

        messages.success(
            request,
            'Anulación revertida correctamente ante el SIN. El stock fue descontado nuevamente.'
        )
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_revertir_anulacion.html', {'enc': enc})


@login_required(login_url='/login/')
def eliminar_factura(request, id):
    """
    Elimina fisicamente una factura. Reservado solo para superusuario.
    Bloqueado si la factura ya fue aceptada por el SIN (reportada_ante_sin),
    ya que en ese caso la unica accion valida es Anular.
    """
    if not request.user.is_superuser:
        messages.error(request, 'Solo el superusuario puede eliminar facturas')
        return redirect('fac:factura_edit', id=id)

    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if enc.reportada_ante_sin:
        messages.error(
            request,
            'No se puede eliminar: esta factura ya fue aceptada por el SIN '
            f'(estado: {enc.get_estado_sin_display()}). Use "Anular" en su lugar.'
        )
        return redirect('fac:factura_edit', id=id)

    if request.method == 'POST':
        enc.delete()  # cascada borra FacturaDet; la señal post_delete restituye stock
        messages.success(request, 'Factura eliminada correctamente')
        return redirect('fac:factura_list')

    return render(request, 'fac/factura_eliminar.html', {'enc': enc})


@login_required(login_url='/login/')
@require_POST
def factura_emitir_sin(request, id):
    """
    Emite la factura ante el SIN (Fase C). Devuelve JSON para que el
    modal de confirmacion en facturas.html (o la pantalla de Cierre
    de Dia) muestre el resultado sin recargar a ciegas.
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        return JsonResponse({"ok": False, "error": "Factura no existe"}, status=404)

    if enc.anulado:
        return JsonResponse({"ok": False, "error": "La factura ya esta anulada"})

    if enc.reportada_ante_sin:
        return JsonResponse({"ok": False, "error": "Esta factura ya fue aceptada por el SIN"})

    if not FacturaDet.objects.filter(factura=enc).exists():
        return JsonResponse({"ok": False, "error": "La factura no tiene productos cargados"})

    try:
        emitir_factura_sin(enc)
        return JsonResponse({
            "ok": True,
            "estado_sin": enc.get_estado_sin_display(),
            "codigo_recepcion": enc.codigo_recepcion_sin,
        })
    except EmisionSinError as e:
        return JsonResponse({
            "ok": False,
            "error": str(e),
            "estado_sin": enc.get_estado_sin_display(),
        })


@login_required(login_url='/login/')
def cierre_dia_pendientes(request):
    """
    Lista los dias anteriores a hoy que todavia no tienen Cierre de Dia.
    Mientras exista al menos uno, el sistema no permite registrar
    facturas nuevas. Los cierres se resuelven en orden cronologico --
    solo el mas antiguo pendiente se puede gestionar en cada momento.
    """
    pendientes = dias_pendientes_de_cierre()
    dias = []
    for fecha in pendientes:
        facturas_dia = FacturaEnc.objects.filter(fecha__date=fecha)
        sin_resolver = facturas_dia.filter(
            estado_sin__in=[FacturaEnc.SIN_NO_ENVIADA, FacturaEnc.SIN_OBSERVADA],
            anulado=False,
        )
        dias.append({
            'fecha': fecha,
            'cantidad_facturas': facturas_dia.count(),
            'total_facturado': facturas_dia.aggregate(t=Sum('total'))['t'] or 0,
            'pendientes_sin': sin_resolver.count(),
        })
    return render(request, 'fac/cierre_dia_pendientes.html', {'dias': dias})


@login_required(login_url='/login/')
def cierre_dia_detalle(request, fecha):
    """
    Pantalla de gestion del cierre de un dia puntual: muestra las
    facturas del dia (en especial las que todavia no se resolvieron
    ante el SIN) y permite reintentar su envio (reusa
    factura_emitir_sin via AJAX), antes de poder cerrar el dia
    formalmente. Cerrar requiere ser supervisor; si quedan facturas
    sin resolver, solo un supervisor puede forzar el cierre dejando
    constancia con una observacion obligatoria.
    """
    fecha_parsed = parse_date(fecha)
    pendientes = dias_pendientes_de_cierre()

    if fecha_parsed not in pendientes:
        messages.error(request, 'Esa fecha no está pendiente de cierre.')
        return redirect('fac:cierre_dia_pendientes')

    if pendientes[0] != fecha_parsed:
        messages.error(
            request,
            f'Debe cerrar primero el día {pendientes[0].strftime("%d/%m/%Y")} '
            '(los cierres se hacen en orden cronológico).'
        )
        return redirect('fac:cierre_dia_pendientes')

    facturas_dia = FacturaEnc.objects.filter(fecha__date=fecha_parsed).order_by('id')
    sin_resolver = facturas_dia.filter(
        estado_sin__in=[FacturaEnc.SIN_NO_ENVIADA, FacturaEnc.SIN_OBSERVADA],
        anulado=False,
    )

    if request.method == 'POST':
        if not _es_supervisor_cierre(request.user):
            messages.error(request, 'No tiene permisos para cerrar el día.')
            return redirect('fac:cierre_dia_detalle', fecha=fecha_parsed)

        forzar = request.POST.get('forzar') == '1'
        observaciones = request.POST.get('observaciones', '').strip()
        cantidad_pendientes = sin_resolver.count()

        if cantidad_pendientes > 0 and not forzar:
            messages.error(
                request,
                f'Todavía hay {cantidad_pendientes} factura(s) sin resolver ante el SIN. '
                'Reintente su envío, o marque "Cerrar de todas formas" si corresponde.'
            )
            return redirect('fac:cierre_dia_detalle', fecha=fecha_parsed)

        if cantidad_pendientes > 0 and forzar and not request.user.is_superuser:
            messages.error(request, 'Solo un superusuario puede forzar el cierre con facturas pendientes.')
            return redirect('fac:cierre_dia_detalle', fecha=fecha_parsed)

        if cantidad_pendientes > 0 and forzar and not observaciones:
            messages.error(request, 'Debe indicar una observación al forzar el cierre con pendientes.')
            return redirect('fac:cierre_dia_detalle', fecha=fecha_parsed)

        CierreDia.objects.create(
            fecha=fecha_parsed,
            estado=CierreDia.ESTADO_CERRADO_CON_PENDIENTES if cantidad_pendientes > 0 else CierreDia.ESTADO_CERRADO,
            usuario_cierre=request.user,
            total_facturado=facturas_dia.aggregate(t=Sum('total'))['t'] or 0,
            cantidad_facturas=facturas_dia.count(),
            facturas_pendientes_sin=cantidad_pendientes,
            observaciones=observaciones or None,
            uc=request.user,
        )

        messages.success(request, f'Día {fecha_parsed.strftime("%d/%m/%Y")} cerrado correctamente.')
        return redirect('fac:cierre_dia_pendientes')

    return render(request, 'fac/cierre_dia_detalle.html', {
        'fecha': fecha_parsed,
        'facturas': facturas_dia,
        'sin_resolver': sin_resolver,
        'total_facturado': facturas_dia.aggregate(t=Sum('total'))['t'] or 0,
        'puede_cerrar_limpio': sin_resolver.count() == 0,
        'es_supervisor': _es_supervisor_cierre(request.user),
    })

@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def cierre_ventas_selector(request):
    """
    Pantalla para elegir el rango de fechas del Reporte de Cierre de
    Ventas (uso contable), antes de verlo en pantalla o descargarlo
    en PDF. Mismo patron que el Listado de Facturas.
    """
    return render(request, 'fac/cierre_ventas_selector.html', {})