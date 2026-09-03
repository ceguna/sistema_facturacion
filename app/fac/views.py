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

from .models import Cliente, FacturaEnc, FacturaDet, CierreDia, dias_pendientes_de_cierre, Pago, NotaCreditoDebito
from .forms import ClienteForm
import inv.views as inv
from inv.models import Producto

from fe.services import emitir_factura_sin, anular_factura_sin, revertir_anulacion_sin, \
    emitir_nota_credito_debito_sin, EmisionSinError
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

    def get_queryset(self):
        # 'estado=False' es el soft-delete de eliminar_factura -- no
        # debe aparecer en el listado normal. Orden descendente por id
        # (equivale a la mas reciente primero, ya que id es
        # autoincremental y nunca se reutiliza) -- antes no tenia
        # order_by, asi que el orden dependia del orden natural de la
        # base, sin garantia.
        return FacturaEnc.objects.filter(estado=True).order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fechas_cerradas = set(CierreDia.objects.values_list('fecha', flat=True))
        for item in context['obj']:
            item.dia_cerrado = timezone.localtime(item.fecha).date() in fechas_cerradas
            item.tiene_ncd = _tiene_ncd_validada(item)
        # _es_supervisor esta definida mas abajo en este mismo modulo --
        # se resuelve en tiempo de ejecucion, no hay problema de orden.
        context['es_supervisor'] = _es_supervisor(self.request.user)
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
            # 'uc' (automatico) va a guardar al cajero de la sesion
            # activa, no a este supervisor -- se guarda aca explicito
            # quien realmente autorizo la reversion.
            det.usuario_reversion = user
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


def _tiene_ncd_validada(enc):
    """
    True si esta factura ya tiene una Nota de Credito-Debito aceptada
    por el SIN -- a partir de ahi queda fiscalmente cerrada: no se
    puede anular, eliminar, ni registrarle nuevos abonos (decision
    tomada el 26/08/2026 al disenar NotaCreditoDebito).
    """
    return enc.notas_credito_debito.filter(estado_sin=NotaCreditoDebito.SIN_VALIDADA).exists()


def _modal_error(request, mensaje):
    """
    Respuesta chica y autocontenida para cuando una vista pensada para
    abrirse dentro del popup (via abrir_modal/$.load()) rechaza el
    acceso ANTES de llegar a mostrar el formulario real -- permiso,
    regla de negocio, etc.

    ANTES: estos casos hacian messages.error(...) + redirect(...). El
    problema es que abrir_modal() carga el contenido con $.load(), que
    SIGUE los redirects -- eso metia la pagina COMPLETA de destino
    (ej. la factura entera) adentro del popup chico, dando la
    impresion de haber "entrado" a la factura en vez de quedarse en el
    listado. Esta respuesta es un modal minimo, autocontenido, que se
    cierra sin haber navegado a ningun lado -- el usuario nunca deja
    el listado de facturas.
    """
    return render(request, 'fac/_modal_error.html', {'mensaje': mensaje})


@login_required(login_url='/login/')
def anular_factura(request, id):
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        return _modal_error(request, 'Factura no existe.')

    if not _es_supervisor(request.user):
        return _modal_error(request, 'No tiene permisos para anular facturas.')

    if enc.anulado:
        return _modal_error(request, 'Esta factura ya se encuentra anulada.')

    if _tiene_ncd_validada(enc):
        return _modal_error(
            request,
            'Esta factura ya tiene una Nota de Crédito-Débito emitida — '
            'queda cerrada fiscalmente, no se puede anular por separado.'
        )

    if not enc.reportada_ante_sin:
        return _modal_error(
            request,
            'Solo se pueden anular facturas que ya fueron aceptadas por el SIN. '
            'Esta factura no fue reportada — puede editarla o eliminarla en su lugar.'
        )

    ahora = timezone.now()
    if not _dentro_plazo_anulacion(enc.fecha, ahora):
        return _modal_error(
            request,
            'Fuera del plazo permitido para anular esta factura '
            '(hasta el dia 9 del mes siguiente a su emision, segun normativa del SIN).'
        )

    # Regla de negocio: no se puede anular una factura a credito que ya
    # tenga algun abono (parcial o total) registrado -- evita la
    # complicacion de que plata ya cobrada quede asociada a un
    # documento anulado sin un flujo explicito para resolverlo. Si no
    # tiene ningun abono, la anulacion tambien "cierra" la cuenta a
    # credito (ver mas abajo, saldo_pendiente se limpia a 0).
    if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO and Pago.objects.filter(factura=enc, revertido=False).exists():
        return _modal_error(
            request,
            'No se puede anular: esta factura a crédito ya tiene abonos registrados. '
            'Contacte al administrador para resolver los abonos antes de anularla.'
        )

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
        # La factura a credito ya paso el chequeo de arriba (sin ningun
        # abono), asi que anularla tambien cierra la cuenta a credito:
        # no debe quedar un saldo pendiente fantasma sobre un documento
        # que ya no es valido.
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            enc.saldo_pendiente = 0
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
        return _modal_error(request, 'Factura no existe.')

    if not _es_supervisor(request.user):
        return _modal_error(request, 'No tiene permisos para revertir anulaciones.')

    if not enc.anulado or enc.estado_sin != FacturaEnc.SIN_ANULADA:
        return _modal_error(request, 'Esta factura no está anulada ante el SIN, no hay nada que revertir.')

    ahora = timezone.now()
    if not _dentro_plazo_anulacion(enc.fecha, ahora):
        return _modal_error(
            request,
            'Fuera del plazo permitido para revertir la anulación de esta factura '
            '(hasta el dia 9 del mes siguiente a su emision, segun normativa del SIN).'
        )

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
        # La anulacion solo fue posible porque en ese momento la
        # factura NO tenia ningun abono (bloqueado en anular_factura),
        # y no pudo haber recibido ninguno despues -- registrar_pago
        # bloquea sobre anulado=True. Osea que el saldo vuelve integro
        # al total, sin necesidad de reconstruir nada mas complejo.
        # ANTES de este fix, la reversion dejaba anulado=False pero
        # saldo_pendiente en 0 -- la factura volvia a estar "activa"
        # pero con el credito del cliente sin reactivar.
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            enc.saldo_pendiente = enc.total
        enc.save()

        messages.success(
            request,
            'Anulación revertida correctamente ante el SIN. El stock fue descontado nuevamente.'
        )
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_revertir_anulacion.html', {'enc': enc})


@login_required(login_url='/login/')
def emitir_ncd(request, id):
    """
    Emite una Nota de Credito-Debito sobre una factura ya validada --
    devolucion TOTAL (unica version soportada, decision del 26/08/2026).
    Mismo nivel de autorizacion que Anular/Revertir (_es_supervisor,
    checkea la sesion actual directo -- no re-autenticacion inline
    como borrar_detalle_factura/revertir_pago). Carlos ya anticipo que
    mas adelante van a definir roles mas especificos para esto, sin
    recargar todo en Supervisor -- pendiente de conversacion aparte.

    Una vez validada por el SIN, la factura_original queda marcada y
    bloqueada para cualquier otra operacion (ver _tiene_ncd_validada,
    ya aplicado en anular_factura y registrar_pago).
    """
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        return _modal_error(request, 'Factura no existe.')

    if not _es_supervisor(request.user):
        return _modal_error(request, 'No tiene permisos para emitir una Nota de Crédito-Débito.')

    if not enc.reportada_ante_sin:
        return _modal_error(
            request,
            'Solo se puede emitir una Nota de Crédito-Débito sobre una factura ya '
            'aceptada por el SIN.'
        )

    if enc.anulado:
        return _modal_error(
            request,
            'Esta factura está anulada -- no corresponde una Nota de Crédito-Débito.'
        )

    if _tiene_ncd_validada(enc):
        return _modal_error(request, 'Esta factura ya tiene una Nota de Crédito-Débito emitida.')

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        if not motivo:
            return _modal_error(request, 'Debe indicar el motivo de la corrección.')

        monto_efectivo = round(enc.total * 0.13, 2)
        ncd = NotaCreditoDebito.objects.create(
            factura_original=enc,
            motivo=motivo,
            monto_total_original=enc.total,
            monto_total_devuelto=enc.total,
            monto_descuento_credito_debito=0,
            monto_efectivo_credito_debito=monto_efectivo,
            usuario_autorizacion=request.user,
            uc=request.user,
        )

        try:
            emitir_nota_credito_debito_sin(ncd)
        except EmisionSinError as e:
            messages.error(request, f'El SIN rechazó la Nota de Crédito-Débito: {e}')
            return redirect('fac:factura_edit', id=id)

        messages.success(
            request,
            f'Nota de Crédito-Débito N° {ncd.id} emitida correctamente ante el SIN '
            f'(estado: {ncd.get_estado_sin_display()}).'
        )
        return redirect('fac:factura_edit', id=id)

    return render(request, 'fac/factura_emitir_ncd.html', {'enc': enc})


@login_required(login_url='/login/')
def eliminar_factura(request, id):
    # Antes exigia is_superuser directo -- ahora usa un permiso real
    # (fac.eliminar_facturaenc), asignable por rol sin necesitar que la
    # persona sea superusuario tecnico de Django. has_perm() ya
    # devuelve True automaticamente para cualquier superusuario, asi
    # que no hace falta chequear ambas cosas por separado.
    if not request.user.has_perm('fac.eliminar_facturaenc'):
        messages.error(request, 'No tiene permisos para eliminar facturas')
        return redirect('fac:factura_edit', id=id)

    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        messages.error(request, 'Factura No Existe')
        return redirect('fac:factura_list')

    if not enc.estado:
        messages.error(request, 'Esta factura ya fue eliminada.')
        return redirect('fac:factura_list')

    if enc.reportada_ante_sin:
        messages.error(
            request,
            'No se puede eliminar: esta factura ya fue aceptada por el SIN '
            f'(estado: {enc.get_estado_sin_display()}). Use "Anular" en su lugar.'
        )
        return redirect('fac:factura_edit', id=id)

    # No se puede eliminar una factura de un dia YA CERRADO -- cambiar
    # sus totales en silencio invalidaria un Cierre de Dia que ya se
    # dio por definitivo.
    fecha_factura = timezone.localtime(enc.fecha).date()
    if CierreDia.objects.filter(fecha=fecha_factura).exists():
        messages.error(
            request,
            f'No se puede eliminar: el día {fecha_factura.strftime("%d/%m/%Y")} '
            'ya fue cerrado (Cierre de Día). Eliminar esta factura cambiaría '
            'totales ya reportados como definitivos.'
        )
        return redirect('fac:factura_edit', id=id)

    # Si ya tiene algun abono registrado, no se puede eliminar sin mas
    # -- es plata que genuinamente se cobro. Antes, con delete() real,
    # los Pago se borraban en cascada tambien (perdiendo ese registro
    # sin dejar rastro); con soft-delete no se borran, asi que
    # quedarian huerfanos apuntando a una factura "eliminada" si se
    # permitiera seguir.
    if Pago.objects.filter(factura=enc, revertido=False).exists():
        messages.error(
            request,
            'No se puede eliminar: esta factura ya tiene abonos registrados. '
            'Contacte al administrador para resolver los abonos antes de eliminarla.'
        )
        return redirect('fac:factura_edit', id=id)

    if request.method == 'POST':
        # Antes, enc.delete() hacia un CASCADE real que borraba cada
        # FacturaDet, disparando detalle_factura_borrar (que devuelve
        # el stock). Con soft-delete nada se borra de verdad, asi que
        # el stock se devuelve aca a mano -- mismo patron que ya usa
        # anular_factura.
        detalles = FacturaDet.objects.filter(factura=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) + int(det.cantidad)
            prod.save()

        # La factura a credito ya paso el chequeo de arriba (sin ningun
        # abono), asi que eliminarla tambien cierra la cuenta a credito
        # -- mismo tratamiento que anular_factura, para no dejar un
        # saldo pendiente fantasma sobre un documento ya eliminado.
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            enc.saldo_pendiente = 0

        enc.estado = False
        enc.save()

        messages.success(
            request,
            'Factura eliminada correctamente (queda registrada en la base para auditoría, oculta del uso normal).'
        )
        return redirect('fac:factura_list')

    return render(request, 'fac/factura_eliminar.html', {'enc': enc})


@login_required(login_url='/login/')
@require_POST
def factura_emitir_sin(request, id):
    enc = FacturaEnc.objects.filter(pk=id).first()
    if not enc:
        return JsonResponse({"ok": False, "error": "Factura no existe"}, status=404)

    if not enc.estado:
        return JsonResponse({"ok": False, "error": "Esta factura fue eliminada"})

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
        facturas_dia = FacturaEnc.objects.filter(fecha__date=fecha, estado=True)
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

    facturas_dia = FacturaEnc.objects.filter(fecha__date=fecha_parsed, estado=True).order_by('id')
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

        if cantidad_pendientes > 0 and forzar and not request.user.has_perm('fac.forzar_cierre_dia'):
            messages.error(request, 'No tiene permisos para forzar el cierre con facturas pendientes.')
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
        # Distinto de 'es_supervisor' (que habilita el cierre NORMAL) --
        # antes, el template mostraba el checkbox/boton de "Forzar" segun
        # es_supervisor, pero el backend protegia esa accion con
        # is_superuser. Alguien con gestionar_cierre_dia pero sin este
        # permiso nuevo veia la opcion en pantalla y le fallaba al
        # enviarla. Ver 'puede_forzar_cierre' en la plantilla.
        'puede_forzar_cierre': request.user.has_perm('fac.forzar_cierre_dia'),
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
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def cartera_creditos(request):
    """
    Cartera de creditos: lista todas las facturas a credito activas
    (con saldo pendiente > 0), agrupadas en tres estados: vencido,
    por_vencer (dentro de FacturaEnc.UMBRAL_PROXIMO_VENCIMIENTO_DIAS
    dias) y vigente. Sirve como reporte de recordatorio de cobranza --
    el cajero/cobrador usa esta lista para llamar/escribir manualmente
    a cada cliente, priorizando por urgencia.
    """
    facturas = FacturaEnc.objects.filter(
        forma_pago=FacturaEnc.FORMA_PAGO_CREDITO, anulado=False, estado=True, saldo_pendiente__gt=0
    ).select_related('cliente').order_by('fecha_vencimiento')

    filas = []
    for f in facturas:
        filas.append({
            'factura': f,
            'estado_credito': f.estado_credito,
            'dias_mora': f.dias_mora,
            'dias_para_vencer': f.dias_para_vencer,
        })

    vencidas = [f for f in filas if f['estado_credito'] == 'vencido']
    por_vencer = [f for f in filas if f['estado_credito'] == 'por_vencer']
    vigentes = [f for f in filas if f['estado_credito'] == 'vigente']

    return render(request, 'fac/cartera_creditos.html', {
        'vencidas': vencidas,
        'por_vencer': por_vencer,
        'vigentes': vigentes,
        'total_vencido': round(sum(f['factura'].saldo_pendiente for f in vencidas), 2),
        'total_por_vencer': round(sum(f['factura'].saldo_pendiente for f in por_vencer), 2),
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

    # No tiene sentido cobrar un abono sobre una factura que todavia no
    # es un documento fiscal real (no validada por el SIN), ni sobre
    # una que ya dejo de serlo (anulada o eliminada).
    if not enc.estado:
        messages.error(request, 'Esta factura fue eliminada, no se puede registrar un abono.')
        return redirect('fac:cartera_creditos')
    if enc.anulado:
        messages.error(request, 'Esta factura está anulada, no se puede registrar un abono.')
        return redirect('fac:cartera_creditos')
    if _tiene_ncd_validada(enc):
        messages.error(
            request,
            'Esta factura ya tiene una Nota de Crédito-Débito emitida — '
            'queda cerrada fiscalmente, no se pueden registrar más abonos.'
        )
        return redirect('fac:cartera_creditos')
    if enc.estado_sin != FacturaEnc.SIN_VALIDADA:
        messages.error(
            request,
            'Esta factura todavía no fue validada por el SIN '
            f'(estado actual: {enc.get_estado_sin_display()}). No se pueden registrar abonos '
            'hasta que sea un documento fiscal válido.'
        )
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

        pago = Pago.objects.create(
            factura=enc, monto=monto, forma_pago=forma_pago_abono,
            observacion=observacion or None, uc=request.user,
        )

        messages.success(request, f'Abono de Bs {monto} registrado para la factura {enc.id}.')
        return redirect('fac:pago_confirmacion', pago_id=pago.id)

    return render(request, 'fac/registrar_pago.html', {'enc': enc})


@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def pago_confirmacion(request, pago_id):
    """
    Pantalla intermedia tras registrar un abono: confirma el monto y el
    saldo resultante, y ofrece el link para imprimir el recibo (se abre
    en pestaña nueva, mismo patron que el resto de impresiones del
    sistema). No usa AJAX a proposito -- asi el link al recibo puede
    ser un <a target="_blank"> simple, sin depender de JS para abrirlo.
    """
    pago = get_object_or_404(Pago, pk=pago_id)
    return render(request, 'fac/pago_confirmacion.html', {
        'pago': pago,
        'factura': pago.factura,
    })


def revertir_pago(request, id):
    """
    Revierte (soft-delete) un abono cargado por error -- Caso 1 de la
    politica de anulacion con abono: NO es una devolucion real de
    mercaderia (eso es terreno de la Nota de Credito-Debito, pendiente
    de construir), es corregir un dato mal cargado. Mismo patron de
    autenticacion inline que borrar_detalle_factura: cualquier usuario
    logueado puede abrir esta pantalla, pero necesita las credenciales
    de un supervisor real para ejecutarla -- no alcanza con que la
    sesion actual ya sea de supervisor.

    NUNCA se borra el registro del Pago -- se marca revertido=True,
    con quien lo autorizo, cuando, y por que (mismo criterio de
    auditoria que el resto del sistema). El recalculo de
    saldo_pendiente lo hace la señal pago_registrado (dispara en
    cualquier post_save de Pago, no solo al crear).
    """
    template_name = "fac/revertir_pago.html"

    pago = get_object_or_404(Pago, pk=id)

    if pago.revertido:
        return HttpResponse("Este abono ya fue revertido anteriormente.")

    if not pago.factura.estado:
        return HttpResponse("No se puede revertir: la factura fue eliminada.")

    if pago.factura.anulado:
        return HttpResponse("No se puede revertir: la factura ya está anulada.")

    if request.method == "GET":
        context = {"pago": pago}

    if request.method == "POST":
        usr = request.POST.get("usuario")
        pas = request.POST.get("pass")
        motivo = request.POST.get("motivo", "").strip()

        if not motivo:
            return HttpResponse("Debe indicar el motivo de la reversión.")

        user = authenticate(username=usr, password=pas)

        if not user:
            return HttpResponse("Usuario o Clave Incorrecta")

        if not user.is_active:
            return HttpResponse("Usuario Inactivo")

        if user.is_superuser or user.has_perm("fac.anular_facturaenc"):
            pago.revertido = True
            pago.fecha_reversion = timezone.now()
            pago.usuario_reversion = user
            pago.motivo_reversion = motivo
            pago.save()

            return HttpResponse("ok")

        return HttpResponse("Usuario no autorizado")

    return render(request, template_name, context)