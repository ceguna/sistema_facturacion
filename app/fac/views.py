import re

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
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
from django.db.models import Sum

from bases.views import SinPrivilegios

from .models import Cliente, FacturaEnc, FacturaDet, CierreDia, dias_pendientes_de_cierre, Pago
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
            cliente.estado = not cliente.estado
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
            enc = FacturaEnc(id=0)
            enc.fecha = datetime.today()
            enc.cliente = None
            enc.sub_total = 0.00
            enc.descuento = 0.00
            enc.total = 0.00
            enc.forma_pago = FacturaEnc.FORMA_PAGO_EFECTIVO
            detalle = None
            ultimo = FacturaEnc.objects.order_by('-id').first()
            siguiente_numero = (ultimo.id + 1) if ultimo else 1
        else:
            detalle = FacturaDet.objects.filter(factura=enc)
            siguiente_numero = enc.id

        contexto = {
            "enc": enc,
            "det": detalle,
            "clientes": clientes,
            "siguiente_numero": siguiente_numero,
            "forma_pago_choices": FacturaEnc.FORMA_PAGO_CHOICES,
        }
        return render(request, template_name, contexto)
    
    if request.method == "POST":
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
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        # Bloqueo total: si el cliente tiene algun credito vencido, no se
        # le permite NINGUNA venta nueva -- ni siquiera al contado --
        # hasta que regularice. Solo se chequea al CREAR una factura
        # nueva (no al seguir editando una ya existente).
        if not id and cli.tiene_creditos_vencidos:
            messages.error(
                request,
                f'No se puede facturar a {cli}: tiene crédito(s) vencido(s) pendiente(s) '
                'de pago. Debe regularizar antes de una nueva venta.'
            )
            return redirect("fac:factura_new")

        if id:
            enc_existente = FacturaEnc.objects.filter(pk=id).first()
            if enc_existente and not enc_existente.puede_editarse:
                messages.error(
                    request,
                    'No se puede modificar: esta factura ya fue reportada al SIN o está anulada.'
                )
                return redirect("fac:factura_edit", id=id)

            # Una vez que la factura ya tiene al menos un producto en el
            # detalle, el cliente queda bloqueado: los descuentos, el
            # limite de credito y demas ya se calcularon contra ese
            # cliente especifico -- cambiarlo a mitad de la carga dejaria
            # lineas de detalle asociadas a un cliente distinto del que
            # termina en la cabecera. Se rechaza el POST entero (no se
            # ignora el cliente en silencio) para que el cajero se de
            # cuenta del error en el momento.
            if enc_existente and FacturaDet.objects.filter(factura=enc_existente).exists():
                if str(enc_existente.cliente_id) != str(cli.id):
                    messages.error(
                        request,
                        'No se puede cambiar el cliente: esta factura ya tiene productos registrados.'
                    )
                    return redirect("fac:factura_edit", id=id)

        forma_pago = request.POST.get("forma_pago", FacturaEnc.FORMA_PAGO_EFECTIVO)
        if forma_pago not in dict(FacturaEnc.FORMA_PAGO_CHOICES):
            forma_pago = FacturaEnc.FORMA_PAGO_EFECTIVO

        if forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            if not cli.autorizado_credito:
                messages.error(request, f'{cli} no está autorizado para ventas a crédito.')
                return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")
            if not cli.plazo_credito_dias:
                messages.error(request, f'{cli} no tiene un plazo de crédito configurado.')
                return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        # --- Tarjeta (Debito/Credito): el SIN exige el nodo numeroTarjeta
        # poblado (no null) cuando el metodo de pago es con tarjeta --
        # confirmado con el error real del SIN (codigo 1012) sobre la
        # factura 549. Se pide solo los ULTIMOS 4 DIGITOS -- nunca la
        # tarjeta completa, por seguridad (PCI). Validado aca, ANTES de
        # tocar la cabecera, por la misma razon que el resto de las
        # validaciones de este bloque (no dejar cabecera huerfana).
        numero_tarjeta = request.POST.get("numero_tarjeta", "").strip()
        if forma_pago in (FacturaEnc.FORMA_PAGO_TARJETA_DEBITO, FacturaEnc.FORMA_PAGO_TARJETA_CREDITO):
            if not re.fullmatch(r"\d{4}", numero_tarjeta):
                messages.error(
                    request,
                    'Debe ingresar los 4 últimos dígitos de la tarjeta para esta forma de pago.'
                )
                return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")
        else:
            numero_tarjeta = ""

        # --- Validaciones del PRODUCTO y del LIMITE de credito, ANTES
        # de crear/guardar la cabecera (FacturaEnc). Si algo de esto
        # falla, no debe quedar ninguna cabecera huerfana sin detalle
        # en la base de datos -- por eso todo lo que puede rechazar el
        # POST se valida primero, con los datos crudos del formulario,
        # sin depender todavia de un objeto FacturaEnc guardado. ---
        codigo = request.POST.get("codigo")
        cantidad = request.POST.get("cantidad")
        precio = request.POST.get("precio")
        s_total = request.POST.get("sub_total_detalle")
        descuento = request.POST.get("descuento_detalle")
        total = request.POST.get("total_detalle")

        prod = Producto.objects.filter(codigo=codigo).first()
        if not prod:
            messages.error(request, 'El producto ingresado no existe')
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        try:
            cantidad_num = float(cantidad)
            precio_num = float(precio)
            descuento_num = float(descuento) if descuento not in (None, '') else 0.0
        except (TypeError, ValueError):
            messages.error(request, 'Datos de cantidad/precio/descuento inválidos.')
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        if int(cantidad_num) > prod.existencia:
            messages.error(request, 'No hay existencia suficiente de este producto')
            return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        if forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            total_linea_nueva = (cantidad_num * precio_num) - descuento_num
            enc_previa = FacturaEnc.objects.filter(pk=id).first() if id else None
            saldo_actual_esta_factura = enc_previa.saldo_pendiente if (
                enc_previa and enc_previa.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO
            ) else 0
            saldo_previo_otras_facturas = cli.saldo_credito_pendiente - saldo_actual_esta_factura
            saldo_proyectado = saldo_previo_otras_facturas + saldo_actual_esta_factura + total_linea_nueva

            if cli.limite_credito <= 0:
                messages.error(
                    request,
                    f'{cli} no tiene un límite de crédito configurado (0). '
                    'No se pueden agregar productos a esta venta a crédito.'
                )
                return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")
            if saldo_proyectado > cli.limite_credito:
                messages.error(
                    request,
                    f'Esta venta superaría el límite de crédito de {cli} '
                    f'(límite: Bs {cli.limite_credito}, saldo proyectado: Bs {round(saldo_proyectado, 2)}).'
                )
                return redirect("fac:factura_edit", id=id) if id else redirect("fac:factura_new")

        # --- Recien aca, con todo ya validado, se crea o actualiza la
        # cabecera. Si algo fallara despues de este punto (no deberia,
        # pero por las dudas), se limpia la cabecera huerfana en vez
        # de dejarla sin detalle. ---
        if not id:
            enc = FacturaEnc(
                cliente = cli,
                fecha = fecha,
                forma_pago = forma_pago,
                numero_tarjeta = numero_tarjeta or None,
            )
            enc.save()
            id = enc.id
        else:
            enc = FacturaEnc.objects.filter(pk=id).first()
            enc.cliente = cli
            enc.forma_pago = forma_pago
            enc.numero_tarjeta = numero_tarjeta or None
            enc.save()

        det = FacturaDet(
            factura = enc,
            producto = prod,
            cantidad = cantidad,
            precio = precio,
            sub_total = s_total,
            descuento = descuento,
            total = total
        )

        try:
            det.save()
        except Exception:
            if not FacturaDet.objects.filter(factura=enc).exists():
                enc.delete()
            raise
        
        return redirect("fac:factura_edit",id=id)

    return render(request,template_name,contexto)


@login_required(login_url='/login/')
@require_POST
def factura_actualizar_datos(request, id):
    """
    Actualiza SOLO Cliente y Forma de Pago de una factura ya existente,
    sin requerir agregar un producto nuevo -- pensado para corregir un
    error (ej. se cargo como Efectivo por error y en realidad era una
    venta a credito) sin necesidad de agregar otra linea de producto.
    Devuelve JSON, la pantalla se actualiza via AJAX.
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        return JsonResponse({"ok": False, "error": "Factura no existe"}, status=404)

    if not enc.puede_editarse:
        return JsonResponse({"ok": False, "error": "Esta factura ya no se puede editar (reportada al SIN o anulada)."})

    cliente_id = request.POST.get("enc_cliente")
    forma_pago = request.POST.get("forma_pago", FacturaEnc.FORMA_PAGO_EFECTIVO)

    cli = Cliente.objects.filter(pk=cliente_id).first()
    if not cli:
        return JsonResponse({"ok": False, "error": "Cliente no válido."})

    # Mismo bloqueo que en facturas(): con productos ya en el detalle,
    # el cliente no se puede tocar desde este boton tampoco -- solo
    # Forma de Pago (que es para lo que este boton esta pensado).
    if FacturaDet.objects.filter(factura=enc).exists() and str(enc.cliente_id) != str(cli.id):
        return JsonResponse({
            "ok": False,
            "error": "No se puede cambiar el cliente: esta factura ya tiene productos registrados."
        })

    if forma_pago not in dict(FacturaEnc.FORMA_PAGO_CHOICES):
        forma_pago = FacturaEnc.FORMA_PAGO_EFECTIVO

    # Mismo requisito que en facturas(): con tarjeta, el SIN exige el
    # numeroTarjeta poblado -- ver comentario alla para el detalle.
    numero_tarjeta = request.POST.get("numero_tarjeta", "").strip()
    if forma_pago in (FacturaEnc.FORMA_PAGO_TARJETA_DEBITO, FacturaEnc.FORMA_PAGO_TARJETA_CREDITO):
        if not re.fullmatch(r"\d{4}", numero_tarjeta):
            return JsonResponse({
                "ok": False,
                "error": "Debe ingresar los 4 últimos dígitos de la tarjeta para esta forma de pago."
            })
    else:
        numero_tarjeta = ""

    if forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
        if not cli.autorizado_credito:
            return JsonResponse({"ok": False, "error": f"{cli} no está autorizado para ventas a crédito."})
        if not cli.plazo_credito_dias:
            return JsonResponse({"ok": False, "error": f"{cli} no tiene un plazo de crédito configurado."})
        if cli.limite_credito <= 0:
            return JsonResponse({"ok": False, "error": f"{cli} no tiene un límite de crédito configurado (0)."})

        saldo_previo_otras_facturas = cli.saldo_credito_pendiente - (
            enc.saldo_pendiente if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO else 0
        )
        saldo_proyectado = saldo_previo_otras_facturas + enc.total
        if saldo_proyectado > cli.limite_credito:
            return JsonResponse({
                "ok": False,
                "error": f"Esta venta superaría el límite de crédito de {cli} "
                         f"(límite: Bs {cli.limite_credito}, saldo proyectado: Bs {round(saldo_proyectado, 2)})."
            })

    enc.cliente = cli
    enc.forma_pago = forma_pago
    enc.numero_tarjeta = numero_tarjeta or None
    enc.save()

    return JsonResponse({"ok": True, "forma_pago_display": enc.get_forma_pago_display()})

 
class ProductoView(inv.ProductoView):
    template_name="fac/buscar_producto.html" 

def borrar_detalle_factura(request, id):
    template_name = "fac/factura_borrar_detalle.html"

    det = get_object_or_404(FacturaDet, pk=id)

    if not det.factura.puede_editarse:
        return HttpResponse(
            "No se puede revertir: esta factura ya fue reportada al SIN o está anulada."
        )

    if request.method=="GET":
        context={"det":det}

    if request.method == "POST":
        usr = request.POST.get("usuario")
        pas = request.POST.get("pass")

        user =authenticate(username=usr,password=pas)

        if not user:
            return HttpResponse("Usuario o Clave Incorrecta")
        
        if not user.is_active:
            return HttpResponse("Usuario Inactivo")

        if user.is_superuser or user.has_perm("fac.sup_caja_facturadet"):
            det.id = None
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
    return user.is_superuser or user.has_perm('fac.anular_facturaenc')


def _es_supervisor_cierre(user):
    return user.is_superuser or user.has_perm('fac.gestionar_cierre_dia')


@login_required(login_url='/login/')
def anular_factura(request, id):
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
        enc.delete()
        messages.success(request, 'Factura eliminada correctamente')
        return redirect('fac:factura_list')

    return render(request, 'fac/factura_eliminar.html', {'enc': enc})


@login_required(login_url='/login/')
@require_POST
def factura_emitir_sin(request, id):
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
            'total_facturado': round(facturas_dia.aggregate(t=Sum('total'))['t'] or 0, 2),
            'pendientes_sin': sin_resolver.count(),
        })
    return render(request, 'fac/cierre_dia_pendientes.html', {'dias': dias})


@login_required(login_url='/login/')
def cierre_dia_detalle(request, fecha):
    from django.utils.dateparse import parse_date

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
            total_facturado=round(facturas_dia.aggregate(t=Sum('total'))['t'] or 0, 2),
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
        'total_facturado': round(facturas_dia.aggregate(t=Sum('total'))['t'] or 0, 2),
        'puede_cerrar_limpio': sin_resolver.count() == 0,
        'es_supervisor': _es_supervisor_cierre(request.user),
    })


@login_required(login_url='/login/')
def factura_descargar_xml(request, id):
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc or not enc.xml_firmado:
        messages.error(request, 'Esta factura todavía no tiene un XML enviado al SIN para descargar.')
        return redirect('fac:factura_list')

    response = HttpResponse(enc.xml_firmado, content_type='application/xml')
    response['Content-Disposition'] = f'attachment; filename="factura_{enc.id}_{enc.cuf or "sin_cuf"}.xml"'
    return response


@login_required(login_url='/login/')
def facturas_descargar_xml_rango(request, f1, f2):
    import io
    import zipfile
    from django.utils.dateparse import parse_date
    from datetime import timedelta

    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    facturas = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, xml_firmado__isnull=False
    ).exclude(xml_firmado='')

    if not facturas.exists():
        messages.error(request, 'No hay facturas con XML enviado en ese rango de fechas.')
        return redirect('fac:factura_list')

    buffer_zip = io.BytesIO()
    with zipfile.ZipFile(buffer_zip, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for enc in facturas:
            nombre_archivo = f"factura_{enc.id}_{enc.cuf or 'sin_cuf'}.xml"
            zip_file.writestr(nombre_archivo, enc.xml_firmado)

    buffer_zip.seek(0)
    response = HttpResponse(buffer_zip.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="facturas_xml_{f1}_a_{f2}.zip"'
    return response


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def cierre_ventas_selector(request):
    return render(request, 'fac/cierre_ventas_selector.html', {})


@login_required(login_url='/login/')
def factura_mostrar_qr(request, id):
    from fe.models import Empresa

    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura no existe.')
        return redirect('fac:factura_list')

    empresa = Empresa.objects.first()
    if not empresa or not empresa.qr_cobro:
        messages.error(request, 'No hay un QR de cobro cargado. Súbalo desde Configuración SIN → Empresa.')
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_mostrar_qr.html', {'enc': enc, 'empresa': empresa})


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def cierre_caja_selector(request):
    return render(request, 'fac/cierre_caja_selector.html', {})


@login_required(login_url='/login/')
@permission_required('fac.gestionar_creditos', login_url='bases:sin_privilegios')
def cartera_creditos(request):
    """
    Cartera de creditos: lista todas las facturas a credito activas
    (con saldo pendiente > 0), con dias de mora si estan vencidas.
    Sirve como reporte de recordatorio de cobranza -- el cajero/cobrador
    usa esta lista para llamar/escribir manualmente a cada cliente.
    """
    facturas = FacturaEnc.objects.filter(
        forma_pago=FacturaEnc.FORMA_PAGO_CREDITO, anulado=False, saldo_pendiente__gt=0
    ).select_related('cliente').order_by('fecha_vencimiento')

    filas = []
    for f in facturas:
        filas.append({
            'factura': f,
            'estado_credito': f.estado_credito,
            'dias_mora': f.dias_mora,
        })

    vencidas = [f for f in filas if f['estado_credito'] == 'vencido']
    vigentes = [f for f in filas if f['estado_credito'] == 'vigente']

    return render(request, 'fac/cartera_creditos.html', {
        'vencidas': vencidas,
        'vigentes': vigentes,
        'total_vencido': round(sum(f['factura'].saldo_pendiente for f in vencidas), 2),
        'total_vigente': round(sum(f['factura'].saldo_pendiente for f in vigentes), 2),
    })


@login_required(login_url='/login/')
@permission_required('fac.gestionar_creditos', login_url='bases:sin_privilegios')
def registrar_pago(request, id):
    """Registra un abono a una venta a credito."""
    enc = FacturaEnc.objects.filter(pk=id, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO).first()
    if not enc:
        messages.error(request, 'Factura a crédito no encontrada.')
        return redirect('fac:cartera_creditos')

    if request.method == 'POST':
        monto = request.POST.get('monto')
        forma_pago_abono = request.POST.get('forma_pago', 'EFECTIVO')
        observacion = request.POST.get('observacion', '').strip()

        try:
            monto = float(monto)
        except (TypeError, ValueError):
            messages.error(request, 'Monto inválido.')
            return redirect('fac:cartera_creditos')

        if monto <= 0:
            messages.error(request, 'El monto debe ser mayor a 0.')
            return redirect('fac:cartera_creditos')

        if monto > enc.saldo_pendiente:
            messages.error(
                request,
                f'El monto (Bs {monto}) supera el saldo pendiente (Bs {enc.saldo_pendiente}).'
            )
            return redirect('fac:cartera_creditos')

        Pago.objects.create(
            factura=enc, monto=monto, forma_pago=forma_pago_abono,
            observacion=observacion or None, uc=request.user,
        )

        messages.success(request, f'Abono de Bs {monto} registrado para la factura {enc.id}.')
        return redirect('fac:cartera_creditos')

    return render(request, 'fac/registrar_pago.html', {'enc': enc})