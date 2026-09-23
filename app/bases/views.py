from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin,\
    PermissionRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib import messages
from django.views import generic

import datetime
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.contrib.auth.decorators import login_required, permission_required

from django.utils import timezone
from django.db.models import Sum
from inv.models import Producto, Categoria, SubCategoria
from cmp.models import ComprasDet
from fac.models import FacturaDet, NotaCreditoDebito

def obtener_sucursal_actual(request):
    """
    Resuelve la sucursal en la que esta operando el usuario actual
    (Fase 2, 20/09/2026, arquitectura multi-sucursal) -- usada para
    marcar FacturaEnc.sucursal / ComprasEnc.sucursal /
    AjusteInventarioEnc.sucursal al crear, y para filtrar Cliente por
    sucursal. Orden de resolucion:
      1. Superusuario que cambio de sucursal en esta sesion (selector
         en la barra superior, ver CambiarSucursalActual mas abajo) --
         request.session['sucursal_actual_id'].
      2. PerfilUsuario.sucursal -- la sucursal "de base" del usuario.
      3. Si la empresa tiene una UNICA sucursal cargada, esa (caso mas
         comun hoy -- instalaciones de una sola sucursal, ej. la
         libreria -- no tiene sentido pedir que la elijan a mano).
      4. None si no se puede resolver (hay mas de una sucursal y el
         usuario no tiene ninguna asignada) -- quien llame a esta
         funcion debe manejar ese caso mostrando un error claro, nunca
         adivinar cual usar.
    """
    from fe.models import Sucursal

    sucursal_id_sesion = request.session.get('sucursal_actual_id')
    if sucursal_id_sesion and request.user.is_superuser:
        sucursal = Sucursal.objects.filter(pk=sucursal_id_sesion).first()
        if sucursal:
            return sucursal

    perfil = getattr(request.user, 'perfilusuario', None)
    if perfil and perfil.sucursal_id:
        return perfil.sucursal

    sucursales = Sucursal.objects.all()
    if sucursales.count() == 1:
        return sucursales.first()

    return None


class CambiarSucursalActual(LoginRequiredMixin, generic.View):
    """
    Selector de sucursal para superusuarios (20/09/2026, Fase 2) --
    solo ellos pueden operar "como si estuvieran" en cualquier
    sucursal sin que su PerfilUsuario tenga que fijar una fija (un
    cajero/almacenero normal SIEMPRE opera desde la sucursal de su
    PerfilUsuario, no ve este selector). Guarda la eleccion en la
    sesion; obtener_sucursal_actual() la respeta antes que cualquier
    otra fuente.
    """
    def post(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'No tiene permisos para cambiar de sucursal.')
            return redirect(request.META.get('HTTP_REFERER', 'bases:home'))
        from fe.models import Sucursal
        sucursal = Sucursal.objects.filter(pk=request.POST.get('sucursal_id')).first()
        if sucursal:
            request.session['sucursal_actual_id'] = sucursal.id
            messages.success(request, f'Ahora estás operando en la sucursal: {sucursal}.')
        return redirect(request.META.get('HTTP_REFERER', 'bases:home'))


class MixinFormInvalid:
    def form_invalid(self, form):
        is_ajax = self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if is_ajax:
            errors = form.errors.as_json()
            return JsonResponse({'errors': errors}, status=400)
        else:
            return super().form_invalid(form)
        
class SinPrivilegios(LoginRequiredMixin, PermissionRequiredMixin, MixinFormInvalid):
    login_url = 'bases:login'
    raise_exception=False
    redirect_field_name="redirecto_to"

    def handle_no_permission(self):
        from django.contrib.auth.models import AnonymousUser
        if not self.request.user==AnonymousUser():
            self.login_url='bases:sin_privilegios'
        return HttpResponseRedirect(reverse_lazy(self.login_url))

class Home(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/home.html'
    login_url='bases:login'

    STOCK_BAJO_UMBRAL = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Import local para evitar dependencias circulares a nivel de modulo
        from fac.models import FacturaEnc, Cliente
        from inv.models import Producto

        hoy = timezone.localtime(timezone.now()).date()
        inicio_mes = hoy.replace(day=1)

        facturas_activas = FacturaEnc.objects.filter(anulado=False)

        ventas_hoy = facturas_activas.filter(fecha__date=hoy) \
            .aggregate(total=Sum('total'))['total'] or 0

        facturas_mes = facturas_activas.filter(fecha__date__gte=inicio_mes)
        ventas_mes = facturas_mes.aggregate(total=Sum('total'))['total'] or 0
        cantidad_facturas_mes = facturas_mes.count()

        productos_stock_bajo = Producto.objects.filter(
            estado=True, existencia__lte=self.STOCK_BAJO_UMBRAL
        ).order_by('existencia')

        clientes_nuevos_mes = Cliente.objects.filter(fc__date__gte=inicio_mes).count()

        ultimas_facturas = FacturaEnc.objects.select_related('cliente') \
            .order_by('-fecha')[:6]

        # Ventas de los ultimos 7 dias, para el grafico (ventas netas
        # activas, como ya estaba) mas el monto anulado por dia -- para
        # detectar de un vistazo si algun dia tuvo demasiadas anulaciones.
        hace_7_dias = hoy - datetime.timedelta(days=6)

        ventas_por_dia = facturas_activas.filter(fecha__date__gte=hace_7_dias) \
            .annotate(dia=TruncDate('fecha')) \
            .values('dia').annotate(total=Sum('total')).order_by('dia')

        anulado_por_dia = FacturaEnc.objects.filter(
            anulado=True, fecha__date__gte=hace_7_dias
        ).annotate(dia=TruncDate('fecha')) \
         .values('dia').annotate(total=Sum('total')).order_by('dia')

        ventas_dict = {v['dia']: float(v['total']) for v in ventas_por_dia}
        anulado_dict = {a['dia']: float(a['total']) for a in anulado_por_dia}

        chart_labels = []
        chart_data = []
        chart_anulado_data = []
        for i in range(7):
            dia = hace_7_dias + datetime.timedelta(days=i)
            chart_labels.append(dia.strftime('%d/%m'))
            chart_data.append(ventas_dict.get(dia, 0))
            chart_anulado_data.append(anulado_dict.get(dia, 0))

        context.update({
            'ventas_hoy': ventas_hoy,
            'ventas_mes': ventas_mes,
            'cantidad_facturas_mes': cantidad_facturas_mes,
            'productos_stock_bajo': productos_stock_bajo[:6],
            'cantidad_stock_bajo': productos_stock_bajo.count(),
            'clientes_nuevos_mes': clientes_nuevos_mes,
            'ultimas_facturas': ultimas_facturas,
            'chart_labels': chart_labels,
            'chart_data': chart_data,
            'chart_anulado_data': chart_anulado_data,
        })
        return context

class HomeSinPrivilegios(LoginRequiredMixin, generic.TemplateView):
    login_url = "bases:login"
    template_name="bases/sin_privilegios.html"

    def get_context_data(self, **kwargs):
        from urllib.parse import urlparse

        context = super().get_context_data(**kwargs)
        # Usamos el Referer (la pantalla desde la que el usuario vino, ej.
        # el listado) en vez del "next" que apunta a la accion bloqueada:
        # redirigir a la accion bloqueada solo la vuelve a rechazar y genera
        # un loop de vuelta a esta misma pantalla.
        next_url = reverse_lazy('bases:home')
        referer = self.request.META.get('HTTP_REFERER')
        if referer:
            partes = urlparse(referer)
            # Solo se acepta si es del mismo sitio (evita open redirect).
            if not partes.netloc or partes.netloc == self.request.get_host():
                if partes.path:
                    next_url = partes.path
                    if partes.query:
                        next_url = f"{next_url}?{partes.query}"
        context['next_url'] = next_url
        return context


class ChartsView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/charts.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        from fac.models import FacturaEnc, FacturaDet

        hoy = timezone.localtime(timezone.now()).date()
        facturas_activas = FacturaEnc.objects.filter(anulado=False)

        # Ventas de los ultimos 6 meses
        meses_labels = []
        meses_data = []
        mes_actual, anio_actual = hoy.month, hoy.year
        for i in range(5, -1, -1):
            m = mes_actual - i
            a = anio_actual
            while m <= 0:
                m += 12
                a -= 1
            total = facturas_activas.filter(fecha__year=a, fecha__month=m) \
                .aggregate(total=Sum('total'))['total'] or 0
            meses_labels.append(f"{['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][m-1]} {a}")
            meses_data.append(float(total))

        # Top 5 productos mas vendidos (por cantidad)
        top_productos = FacturaDet.objects.filter(factura__anulado=False) \
            .values('producto__descripcion') \
            .annotate(total_cantidad=Sum('cantidad')) \
            .order_by('-total_cantidad')[:5]

        # Top 5 clientes por monto comprado
        top_clientes = facturas_activas.values('cliente__nombres', 'cliente__apellidos') \
            .annotate(total_comprado=Sum('total')) \
            .order_by('-total_comprado')[:5]

        context.update({
            'meses_labels': meses_labels,
            'meses_data': meses_data,
            'top_productos_labels': [p['producto__descripcion'] for p in top_productos],
            'top_productos_data': [float(p['total_cantidad']) for p in top_productos],
            'top_clientes_labels': [f"{c['cliente__nombres']} {c['cliente__apellidos']}" for c in top_clientes],
            'top_clientes_data': [float(c['total_comprado']) for c in top_clientes],
        })
        return context


IVA_TASA = 0.13  # Tasa de IVA vigente en Bolivia


def _parse_int_localizado(valor, por_defecto):
    """
    Convierte a int un valor que puede venir con separador de miles
    (ej. '2,026') -- CORREGIDO 12/09/2026: los <select> de mes/año de
    los reportes IVA arman sus <option value="..."> con {{ }}, que con
    USE_THOUSAND_SEPARATOR=True (settings) formatea CUALQUIER entero,
    value incluido -- el año 2026 salia como "2,026" y rompia con
    ValueError: invalid literal for int(). El fix real esta en las
    plantillas (filtro |unlocalize en el value); esto es ademas una
    red de seguridad server-side, por si el parametro llega asi desde
    cualquier otro lado (URL armada a mano, bookmark viejo, etc.).
    """
    if valor is None or valor == '':
        return por_defecto
    try:
        return int(str(valor).replace(',', '').replace('.', ''))
    except (TypeError, ValueError):
        return por_defecto


class LibroVentasView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/libro_ventas.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from fac.models import FacturaEnc

        hoy = timezone.localtime(timezone.now()).date()
        mes = _parse_int_localizado(self.request.GET.get('mes'), hoy.month)
        anio = _parse_int_localizado(self.request.GET.get('anio'), hoy.year)

        facturas = FacturaEnc.objects.filter(
            anulado=False, fecha__year=anio, fecha__month=mes
        ).select_related('cliente').order_by('fecha')

        filas = []
        total_importe = 0.0
        total_base_cf = 0.0
        total_iva = 0.0
        for f in facturas:
            base_cf = f.total / (1 + IVA_TASA)
            iva = f.total - base_cf
            filas.append({
                'factura': f,
                'base_cf': base_cf,
                'iva': iva,
                'base_cf_fmt': "{:,.2f}".format(base_cf),
                'iva_fmt': "{:,.2f}".format(iva),
                'total_fmt': "{:,.2f}".format(f.total),
            })
            total_importe += f.total
            total_base_cf += base_cf
            total_iva += iva

        context.update({
            'filas': filas,
            'mes': mes,
            'anio': anio,
            'total_importe': total_importe,
            'total_base_cf': total_base_cf,
            'total_iva': total_iva,
            'total_base_cf_fmt': "{:,.2f}".format(total_base_cf),
            'total_iva_fmt': "{:,.2f}".format(total_iva),
            'total_importe_fmt': "{:,.2f}".format(total_importe),
            'meses': [
                (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
                (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
                (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
            ],
            'anios': range(hoy.year - 3, hoy.year + 1),
        })
        return context


class LibroComprasView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/libro_compras.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from cmp.models import ComprasEnc

        hoy = timezone.localtime(timezone.now()).date()
        mes = _parse_int_localizado(self.request.GET.get('mes'), hoy.month)
        anio = _parse_int_localizado(self.request.GET.get('anio'), hoy.year)

        compras = ComprasEnc.objects.filter(
            fecha_compra__year=anio, fecha_compra__month=mes
        ).select_related('proveedor').order_by('fecha_compra')

        filas = []
        total_importe = 0.0
        total_base_cf = 0.0
        total_iva = 0.0
        for c in compras:
            base_cf = c.total / (1 + IVA_TASA)
            iva = c.total - base_cf
            filas.append({
                'compra': c,
                'base_cf': base_cf,
                'iva': iva,
                'base_cf_fmt': "{:,.2f}".format(base_cf),
                'iva_fmt': "{:,.2f}".format(iva),
                'total_fmt': "{:,.2f}".format(c.total),
            })
            total_importe += c.total
            total_base_cf += base_cf
            total_iva += iva

        context.update({
            'filas': filas,
            'mes': mes,
            'anio': anio,
            'total_importe': total_importe,
            'total_base_cf': total_base_cf,
            'total_iva': total_iva,
            'total_base_cf_fmt': "{:,.2f}".format(total_base_cf),
            'total_iva_fmt': "{:,.2f}".format(total_iva),
            'total_importe_fmt': "{:,.2f}".format(total_importe),
            'meses': [
                (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
                (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
                (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
            ],
            'anios': range(hoy.year - 3, hoy.year + 1),
        })
        return context


class FacturasAnuladasView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/facturas_anuladas.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from fac.models import FacturaEnc

        # NUEVO 12/09/2026: mismo filtro de periodo (mes/año) que Libro
        # de Ventas -- antes traia TODAS las facturas anuladas de toda
        # la historia sin ningun filtro (mismo tipo de hallazgo de
        # carga lenta que ya se corrigio en el listado de Facturas).
        # Filtra por fecha_anulacion (la fecha relevante de este
        # reporte, no la fecha de emision original).
        hoy = timezone.localtime(timezone.now()).date()
        mes = _parse_int_localizado(self.request.GET.get('mes'), hoy.month)
        anio = _parse_int_localizado(self.request.GET.get('anio'), hoy.year)

        anuladas = FacturaEnc.objects.filter(
            anulado=True, fecha_anulacion__year=anio, fecha_anulacion__month=mes
        ).select_related('cliente', 'usuario_anulacion').order_by('-fecha_anulacion')

        for f in anuladas:
            f.total_fmt = "{:,.2f}".format(f.total)

        context.update({
            'anuladas': anuladas,
            'total_anulado': sum(f.total for f in anuladas),
            'total_anulado_fmt': "{:,.2f}".format(sum(f.total for f in anuladas)),
            'mes': mes,
            'anio': anio,
            'meses': [
                (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
                (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
                (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
            ],
            'anios': range(hoy.year - 3, hoy.year + 1),
        })
        return context


class NotasCreditoDebitoReporteView(LoginRequiredMixin, generic.TemplateView):
    """
    Reporte de Notas de Credito-Debito emitidas (22/09/2026, pedido de
    Carlos, mismo tratamiento que Facturas Anuladas -- filtro de
    periodo, tarjetas de resumen, tabla exportable). Columnas alineadas
    a lo que ya usan sistemas de facturacion/contables de referencia
    (Accoxi, Output Books, Manager.io): numero de NCD, fecha, cliente,
    factura original, motivo, monto devuelto, estado.
    """
    template_name = 'bases/notas_credito_debito_reporte.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from fac.models import NotaCreditoDebito

        hoy = timezone.localtime(timezone.now()).date()
        mes = _parse_int_localizado(self.request.GET.get('mes'), hoy.month)
        anio = _parse_int_localizado(self.request.GET.get('anio'), hoy.year)

        ncds = NotaCreditoDebito.objects.filter(
            fecha__year=anio, fecha__month=mes
        ).select_related(
            'factura_original', 'factura_original__cliente', 'usuario_autorizacion'
        ).order_by('-fecha')

        for n in ncds:
            n.monto_total_devuelto_fmt = "{:,.2f}".format(n.monto_total_devuelto)

        vigentes = [n for n in ncds if not n.anulada]
        total_devuelto = sum(n.monto_total_devuelto for n in vigentes)

        context.update({
            'ncds': ncds,
            'total_devuelto': total_devuelto,
            'total_devuelto_fmt': "{:,.2f}".format(total_devuelto),
            'cantidad_anuladas': sum(1 for n in ncds if n.anulada),
            'mes': mes,
            'anio': anio,
            'meses': [
                (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
                (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
                (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre'),
            ],
            'anios': range(hoy.year - 3, hoy.year + 1),
        })
        return context


class TablesView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/tables.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        from inv.models import Producto
        from fac.models import FacturaDet
        from cmp.models import ComprasDet

        productos = Producto.objects.filter(estado=True).select_related(
            'marca', 'subcategoria', 'subcategoria__categoria', 'unidad_medida'
        )
        for p in productos:
            p.valor_total = p.existencia * p.precio

        valor_total_inventario = sum(p.valor_total for p in productos)

        # ---- Estado de Inventario (Kardex) ----
        hoy = timezone.localtime(timezone.now()).date()
        inicio_mes = hoy.replace(day=1)

        producto_id = self.request.GET.get('producto_id', '').strip()
        producto_seleccionado = None
        kardex_detalle = None
        kardex_resumen = []

        todos_productos_activos = Producto.objects.filter(estado=True).order_by('descripcion')

        if producto_id:
            producto_seleccionado = Producto.objects.filter(pk=producto_id).first()

        productos_a_procesar = [producto_seleccionado] if producto_seleccionado else todos_productos_activos

        for prod in productos_a_procesar:
            if not prod:
                continue

            compras_mes = ComprasDet.objects.filter(
                producto=prod, compra__fecha_compra__gte=inicio_mes, compra__fecha_compra__lte=hoy
            )
            ventas_mes = FacturaDet.objects.filter(
                producto=prod, factura__anulado=False,
                factura__fecha__date__gte=inicio_mes, factura__fecha__date__lte=hoy
            )

            total_compras = compras_mes.aggregate(t=Sum('cantidad'))['t'] or 0
            total_ventas = ventas_mes.aggregate(t=Sum('cantidad'))['t'] or 0
            inventario_inicio = prod.existencia - total_compras + total_ventas

            if producto_seleccionado:
                movimientos = []
                for c in compras_mes.select_related('compra'):
                    movimientos.append({
                        'fecha': c.compra.fecha_compra,
                        'tipo': 'Compra', 'tipo_class': 'success',
                        'documento': f"Compra #{c.compra.id}",
                        'entrada': c.cantidad, 'salida': 0,
                    })
                for v in ventas_mes.select_related('factura'):
                    movimientos.append({
                        'fecha': timezone.localtime(v.factura.fecha).date(),
                        'tipo': 'Venta', 'tipo_class': 'primary',
                        'documento': f"Factura #{v.factura.id}",
                        'entrada': 0, 'salida': v.cantidad,
                    })
                movimientos.sort(key=lambda m: m['fecha'])

                saldo = inventario_inicio
                for m in movimientos:
                    saldo = saldo + m['entrada'] - m['salida']
                    m['saldo'] = saldo

                kardex_detalle = {
                    'producto': prod,
                    'inventario_inicio': inventario_inicio,
                    'movimientos': movimientos,
                    'inventario_actual': prod.existencia,
                }
            else:
                kardex_resumen.append({
                    'producto': prod,
                    'inventario_inicio': inventario_inicio,
                    'compras_mes': total_compras,
                    'ventas_mes': total_ventas,
                    'inventario_actual': prod.existencia,
                })

        context.update({
            'productos': productos,
            'valor_total_inventario': valor_total_inventario,
            'todos_productos_activos': todos_productos_activos,
            'producto_seleccionado': producto_seleccionado,
            'kardex_detalle': kardex_detalle,
            'kardex_resumen': kardex_resumen,
            'inicio_mes': inicio_mes,
            'hoy': hoy,
        })
        return context


# =====================================================================
# Gestion de Usuarios y Roles, integrada al sistema (reemplaza los
# accesos directos al admin de Django). Solo queda accesible a
# superusuarios: ningun grupo estandar creado por
# crear_grupos_permisos.py tiene permisos sobre auth.User / auth.Group,
# y Django ya le concede automaticamente todos los permisos a
# is_superuser=True.
#
# Nota importante: varios modelos del sistema (Categoria, Producto,
# Compras, etc.) tienen FK a User con on_delete=CASCADE. Por eso no se
# ofrece "eliminar usuario": borrar un usuario borraria en cascada todo
# lo que ese usuario creo. En su lugar se ofrece activar/desactivar.
# =====================================================================
from django.contrib.auth.models import User, Group

from .forms import UsuarioForm, GrupoForm, PerfilForm, CSGPasswordChangeForm


class MiPerfilView(LoginRequiredMixin, SuccessMessageMixin, generic.UpdateView):
    """Permite a cualquier usuario logueado editar sus propios datos
    basicos (nombres, apellidos, correo). No toca username, roles,
    ni el estado activo/superusuario: eso sigue siendo exclusivo de
    Usuarios y Roles (superusuarios)."""
    model = User
    form_class = PerfilForm
    template_name = "bases/mi_perfil.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:mi_perfil")
    success_message = "Tus datos se actualizaron satisfactoriamente"

    def get_object(self, queryset=None):
        return self.request.user


class MiCambiarPasswordView(LoginRequiredMixin, SuccessMessageMixin, PasswordChangeView):
    """Cambio de contraseña propia. A diferencia del restablecimiento
    que hace un superusuario sobre otro usuario (que genera una clave
    aleatoria), aca el propio usuario elige su nueva contraseña y debe
    confirmar la actual (PasswordChangeForm de Django ya lo exige)."""
    form_class = CSGPasswordChangeForm
    template_name = "bases/cambiar_password.html"
    success_url = reverse_lazy("bases:mi_perfil")
    success_message = "Tu contraseña se actualizó satisfactoriamente"


class UsuarioListView(SinPrivilegios, generic.ListView):
    permission_required = "auth.view_user"
    model = User
    template_name = "bases/usuario_list.html"
    context_object_name = "obj"
    queryset = User.objects.all().order_by("username").prefetch_related("groups")


class UsuarioNew(SuccessMessageMixin, SinPrivilegios, generic.CreateView):
    permission_required = "auth.add_user"
    model = User
    form_class = UsuarioForm
    template_name = "bases/usuario_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:usuario_list")

    def form_valid(self, form):
        # Se genera una contraseña temporal aleatoria; el usuario no se
        # puede crear sin contraseña. El admin debe comunicarsela o
        # usar "Restablecer Contraseña" para generar una nueva despues.
        clave_temporal = get_random_string(10)
        form.instance.set_password(clave_temporal)
        response = super().form_valid(form)
        # Sucursal (20/09/2026, Fase 2): 'sucursal' no es un campo de
        # User -- se guarda a mano en PerfilUsuario, recien ahora que
        # self.object (el User) ya tiene pk.
        from bases.models import PerfilUsuario
        PerfilUsuario.objects.update_or_create(
            user=self.object, defaults={'sucursal': form.cleaned_data.get('sucursal')}
        )
        messages.success(
            self.request,
            f"Usuario '{self.object.username}' creado. Contraseña temporal: "
            f"{clave_temporal} (anótala ahora, no se volverá a mostrar)."
        )
        return response


class UsuarioEdit(SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
    permission_required = "auth.change_user"
    model = User
    form_class = UsuarioForm
    template_name = "bases/usuario_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:usuario_list")
    success_message = "Usuario actualizado satisfactoriamente"

    def form_valid(self, form):
        response = super().form_valid(form)
        from bases.models import PerfilUsuario
        PerfilUsuario.objects.update_or_create(
            user=self.object, defaults={'sucursal': form.cleaned_data.get('sucursal')}
        )
        return response


class UsuarioResetPassword(SinPrivilegios, generic.DetailView):
    """Pantalla de confirmacion para restablecer la contraseña de un
    usuario. Genera una nueva contraseña aleatoria y la muestra una
    unica vez; no queda guardada en texto plano en ningun lado."""
    permission_required = "auth.change_user"
    model = User
    template_name = "bases/usuario_reset_password.html"
    context_object_name = "obj"

    def post(self, request, *args, **kwargs):
        usuario = self.get_object()
        clave_nueva = get_random_string(10)
        usuario.set_password(clave_nueva)
        usuario.save()
        messages.success(
            request,
            f"Contraseña de '{usuario.username}' restablecida. Nueva "
            f"contraseña temporal: {clave_nueva} (anótala ahora, no se "
            f"volverá a mostrar)."
        )
        return redirect("bases:usuario_list")


class UsuarioToggleActivo(SinPrivilegios, generic.View):
    """Activa/desactiva un usuario. No se ofrece eliminar (ver nota de
    on_delete=CASCADE mas arriba)."""
    permission_required = "auth.change_user"

    def post(self, request, *args, **kwargs):
        usuario = get_object_or_404(User, pk=kwargs["pk"])
        if usuario == request.user:
            messages.error(request, "No puedes desactivar tu propio usuario.")
        else:
            usuario.is_active = not usuario.is_active
            usuario.save()
            estado = "activado" if usuario.is_active else "desactivado"
            messages.success(request, f"Usuario '{usuario.username}' {estado}.")
        return redirect("bases:usuario_list")


class GrupoListView(SinPrivilegios, generic.ListView):
    permission_required = "auth.view_group"
    model = Group
    template_name = "bases/grupo_list.html"
    context_object_name = "obj"
    queryset = Group.objects.all().order_by("name").prefetch_related(
        "permissions", "user_set"
    )


class PermisosAgrupadosMixin:
    """Agrupa los permisos por app.modelo para que el formulario de
    roles se pueda mostrar organizado en secciones, en vez de una
    lista plana de decenas de checkboxes."""

    def get_context_data(self, **kwargs):
        from .forms import APPS_GESTIONADAS
        from django.contrib.auth.models import Permission

        context = super().get_context_data(**kwargs)
        form = context['form']
        seleccionados = set(
            str(v) for v in (form['permissions'].value() or [])
        )
        permisos = Permission.objects.filter(
            content_type__app_label__in=APPS_GESTIONADAS
        ).select_related('content_type').order_by(
            'content_type__app_label', 'content_type__model', 'codename'
        )
        grupos = {}
        for p in permisos:
            clave = f"{p.content_type.app_label}.{p.content_type.model}"
            grupos.setdefault(clave, []).append(p)
        context['permisos_agrupados'] = grupos
        context['permisos_seleccionados'] = seleccionados
        return context


class GrupoNew(PermisosAgrupadosMixin, SuccessMessageMixin, SinPrivilegios, generic.CreateView):
    permission_required = "auth.add_group"
    model = Group
    form_class = GrupoForm
    template_name = "bases/grupo_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:grupo_list")
    success_message = "Rol creado satisfactoriamente"


class GrupoEdit(PermisosAgrupadosMixin, SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
    permission_required = "auth.change_group"
    model = Group
    form_class = GrupoForm
    template_name = "bases/grupo_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:grupo_list")
    success_message = "Rol actualizado satisfactoriamente"


class GrupoDel(SinPrivilegios, generic.DeleteView):
    permission_required = "auth.delete_group"
    model = Group
    template_name = "bases/grupo_del.html"
    context_object_name = "obj"
    success_url = reverse_lazy("bases:grupo_list")

"""
AGREGAR a bases/views.py (no reemplaza nada existente -- son dos
vistas nuevas). Requiere estos imports adicionales al inicio del
archivo, si no los tiene ya:
"""

def _contexto_estado_inventario(request):
    """
    Arma el contexto de Estado de Inventario -- compartido entre la
    pantalla (HTML), el PDF y el Excel (13/09/2026), para que los tres
    formatos muestren siempre los mismos datos con el mismo filtro.
    """
    categoria_id = request.GET.get('categoria_id', '').strip()
    buscar = request.GET.get('buscar', '').strip()

    productos = Producto.objects.filter(estado=True).select_related(
        'subcategoria', 'subcategoria__categoria', 'marca', 'unidad_medida'
    ).order_by('descripcion')

    if categoria_id:
        productos = productos.filter(subcategoria__categoria_id=categoria_id)
    if buscar:
        productos = productos.filter(descripcion__icontains=buscar)

    filas = []
    total_valor_venta = 0
    total_valor_costo = 0
    for prod in productos:
        valor_venta = round(prod.existencia * prod.precio, 2)
        valor_costo = round(prod.existencia * prod.costo_actual, 2)
        total_valor_venta += valor_venta
        total_valor_costo += valor_costo
        filas.append({
            'producto': prod,
            'categoria': prod.subcategoria.categoria.descripcion,
            'valor_venta': valor_venta,
            'valor_costo': valor_costo,
        })

    categoria_obj = Categoria.objects.filter(pk=categoria_id).first() if categoria_id else None

    from fe.models import Empresa
    from fe.utils import datos_logo_header
    empresa = Empresa.objects.first()
    return {
        'filas': filas,
        'categorias': Categoria.objects.filter(estado=True).order_by('descripcion'),
        'categoria_id': categoria_id,
        'categoria_nombre': categoria_obj.descripcion if categoria_obj else 'Todas',
        'buscar': buscar,
        'total_valor_venta': round(total_valor_venta, 2),
        'total_valor_costo': round(total_valor_costo, 2),
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
        **datos_logo_header(empresa),
    }


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def estado_inventario(request):
    """
    Reporte de Estado de Inventario: una "foto" del momento actual,
    no un historico -- existencia, precio de venta, costo actual, y
    valor total a cada uno. Agregado 08/09/2026, junto con Kardex.
    """
    return render(request, 'bases/estado_inventario.html', _contexto_estado_inventario(request))


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def estado_inventario_pdf(request):
    """
    PDF con elementos de reporte real (encabezado con empresa, titulo,
    fecha de emision, filtro aplicado, totales) -- agregado 13/09/2026:
    antes solo se podia "exportar" con el Export Data generico de
    bootstrap-table, que descarga la tabla cruda sin ningun encabezado.
    """
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string
    from django.http import HttpResponse as _HttpResponse

    contexto = _contexto_estado_inventario(request)
    contexto['es_pdf'] = True
    html = render_to_string('bases/estado_inventario_print.html', contexto)

    response = _HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="estado_inventario.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return _HttpResponse("Ocurrió un error al generar el PDF. Contacte al administrador.", status=500)
    return response


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def estado_inventario_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from django.http import HttpResponse as _HttpResponse

    contexto = _contexto_estado_inventario(request)

    wb = Workbook()
    ws = wb.active
    ws.title = "Estado de Inventario"

    ws.append(["Estado de Inventario"])
    ws.append([f"Categoría: {contexto['categoria_nombre']}", "", f"Emitido: {contexto['fecha_emision'].strftime('%d/%m/%Y %H:%M')}"])
    ws.append([])
    encabezados = ["Código", "Descripción", "Categoría", "Existencia", "Precio Venta",
                   "Costo Actual", "Valor (Venta)", "Valor (Costo)"]
    ws.append(encabezados)
    for celda in ws[ws.max_row]:
        celda.font = Font(bold=True)

    for fila in contexto['filas']:
        ws.append([
            fila['producto'].codigo, fila['producto'].descripcion, fila['categoria'],
            fila['producto'].existencia, fila['producto'].precio, fila['producto'].costo_actual,
            fila['valor_venta'], fila['valor_costo'],
        ])
        ws.cell(row=ws.max_row, column=1).number_format = '@'

    ws.append([])
    fila_total = ["", "", "", "", "", "TOTALES", contexto['total_valor_venta'], contexto['total_valor_costo']]
    ws.append(fila_total)
    for celda in ws[ws.max_row]:
        celda.font = Font(bold=True)

    response = _HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="estado_inventario.xlsx"'
    wb.save(response)
    return response


def _movimientos_producto_qs(producto, fecha_desde=None, fecha_hasta=None):
    """
    Devuelve (compras_qs, ventas_qs) para un producto, ya filtrados
    por rango de fecha si se indica. Excluye compras eliminadas
    (ComprasEnc.estado=False) y ventas de facturas anuladas o
    eliminadas -- esos casos revierten el stock por otro camino
    (actualizacion directa de Producto.existencia, sin dejar una linea
    de reversion en el detalle), asi que sumarlos aca duplicaria el
    efecto y desalinearia el Kardex del saldo real.
    """
    compras_qs = ComprasDet.objects.filter(producto=producto, compra__estado=True)
    ventas_qs = FacturaDet.objects.filter(
        producto=producto, factura__anulado=False, factura__estado=True
    )
    if fecha_desde:
        compras_qs = compras_qs.filter(compra__fecha_compra__gte=fecha_desde)
        ventas_qs = ventas_qs.filter(factura__fecha__date__gte=fecha_desde)
    if fecha_hasta:
        compras_qs = compras_qs.filter(compra__fecha_compra__lte=fecha_hasta)
        ventas_qs = ventas_qs.filter(factura__fecha__date__lte=fecha_hasta)
    return compras_qs.select_related('compra'), ventas_qs.select_related('factura')


def _eventos_ncd_producto(producto):
    """
    Movimientos de stock generados por Notas de Credito-Debito sobre
    `producto`, calculados sobre las lineas de la factura original
    (misma fuente que usa fe.services.emitir_nota_credito_debito_sin,
    no hay un detalle propio de la NCD). Agregado 15/09/2026 --
    hallazgo de Carlos probando NCD contra el SIN real (factura 778):
    sin esto, estos movimientos reales (existencia SI cambia) no
    tenian ningun ComprasDet/FacturaDet propio que el Kardex pudiera
    leer, y aparecian enteros como "ajuste no identificado".

    Una NCD Validada devuelve el stock (entrada). Si despues se anula,
    ese stock vuelve a salir (hallazgo #1 de Carlos, mismo dia --
    anular_nota_credito_debito_sin no lo hacia; corregido en
    fe/services.py junto con este fix). Si esa anulacion se revierte,
    vuelve a entrar. Devuelve un evento por cada fase que realmente
    ocurrio (una NCD Anulada aporta 2 eventos; Revertida, 3) -- no solo
    el efecto neto actual, para que el Kardex muestre el historial
    completo.
    """
    ncds = NotaCreditoDebito.objects.filter(
        factura_original__facturadet__producto=producto,
        estado_sin__in=[
            NotaCreditoDebito.SIN_VALIDADA,
            NotaCreditoDebito.SIN_ANULADA,
            NotaCreditoDebito.SIN_REVERTIDA,
        ],
    ).distinct().select_related('factura_original')

    eventos = []
    for ncd in ncds:
        cantidad = FacturaDet.objects.filter(
            factura=ncd.factura_original, producto=producto
        ).aggregate(total=Sum('cantidad'))['total'] or 0
        if not cantidad:
            continue
        eventos.append({
            'fecha': timezone.localtime(ncd.fecha).date(),
            'tipo': 'Devolución por NCD',
            'documento': f'NCD #{ncd.id} (Factura #{ncd.factura_original_id})',
            'cantidad': cantidad,
        })
        if ncd.estado_sin in (NotaCreditoDebito.SIN_ANULADA, NotaCreditoDebito.SIN_REVERTIDA) and ncd.fecha_anulacion:
            eventos.append({
                'fecha': timezone.localtime(ncd.fecha_anulacion).date(),
                'tipo': 'Anulación de NCD',
                'documento': f'NCD #{ncd.id} (Factura #{ncd.factura_original_id})',
                'cantidad': -cantidad,
            })
        if ncd.estado_sin == NotaCreditoDebito.SIN_REVERTIDA and ncd.fecha_reversion_sin:
            eventos.append({
                'fecha': timezone.localtime(ncd.fecha_reversion_sin).date(),
                'tipo': 'Reversión de anulación de NCD',
                'documento': f'NCD #{ncd.id} (Factura #{ncd.factura_original_id})',
                'cantidad': cantidad,
            })
    return eventos


def _calcular_kardex_producto(producto, fecha_desde, fecha_hasta):
    """
    Calcula el Kardex de un producto para el rango [fecha_desde,
    fecha_hasta]: saldo inicial (cantidad y valor), lista de
    movimientos dentro del rango (ordenados por fecha, con saldo
    corriente), y saldo final.

    LIMITACION CONOCIDA (valorizacion): las ENTRADAS se valorizan con
    el precio de compra REAL de esa linea (precio_prv), dato exacto e
    historico. Las SALIDAS (ventas) y el SALDO INICIAL se valorizan
    con el costo_actual del producto -- una aproximacion, ya
    que no se guarda una foto historica del costo promedio en cada
    momento del pasado, solo su valor de hoy. Aceptado como
    aproximacion razonable (decision 08/09/2026, Carlos conforme con
    "sin ser un costeo contable estricto").

    AJUSTE NO IDENTIFICADO (agregado 10/09/2026): el saldo inicial se
    calcula sumando movimientos reales (compras - ventas) anteriores a
    fecha_desde, acumulados desde cero -- NO retrocediendo desde la
    existencia actual. Retroceder desde la existencia escondia
    cualquier descuadre entre Producto.existencia y el historial de
    movimientos dentro del saldo inicial (un producto con la
    existencia inflada por las corridas de volumen de la certificacion
    SIN mostraba un "saldo inicial" fantasma sin origen visible -- ver
    caso AGE-001, +12). Ese descuadre ahora se expone aparte, en
    'ajuste_no_identificado'.
    """
    costo_actual = producto.costo_actual or 0

    # Movimientos de NCD (agregado 15/09/2026, ver _eventos_ncd_producto)
    # -- se calculan una sola vez, y se reparten igual que
    # compras/ventas entre saldo inicial, rango y neto historico.
    eventos_ncd = _eventos_ncd_producto(producto)

    # Saldo inicial = suma de TODOS los movimientos reales anteriores a
    # fecha_desde (entradas - salidas), acumulado desde cero.
    dia_antes = fecha_desde - datetime.timedelta(days=1)
    compras_antes, ventas_antes = _movimientos_producto_qs(producto, fecha_hasta=dia_antes)
    saldo_inicial_cantidad = (
        sum(c.cantidad for c in compras_antes) - sum(v.cantidad for v in ventas_antes)
        + sum(e['cantidad'] for e in eventos_ncd if e['fecha'] <= dia_antes)
    )
    saldo_inicial_valor = round(saldo_inicial_cantidad * costo_actual, 2)

    # Movimientos dentro del rango elegido, para el detalle.
    compras_rango, ventas_rango = _movimientos_producto_qs(
        producto, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )
    eventos_ncd_rango = [e for e in eventos_ncd if fecha_desde <= e['fecha'] <= fecha_hasta]

    movimientos = []
    for c in compras_rango:
        if c.cantidad < 0:
            # Linea de reversion de compra ("contra compra") -- se
            # quito ese producto de la compra. Se muestra como una
            # SALIDA (revierte el ingreso), con entrada en 0, mismo
            # documento (Compra #N), y en Observacion quien la hizo.
            # Explica el saldo negativo que puede aparecer en la linea
            # siguiente hasta la proxima compra.
            cantidad_abs = abs(c.cantidad)
            usuario = c.usuario_reversion
            movimientos.append({
                'fecha': c.compra.fecha_compra,
                'tipo': 'Reversión de compra',
                'documento': f'Compra #{c.compra.id}',
                'entrada': 0,
                'salida': cantidad_abs,
                'valor_entrada': 0,
                'valor_salida': round(cantidad_abs * c.precio_prv, 2),
                'observacion': f'Reversión por {usuario.get_username()}' if usuario else 'Reversión',
            })
        else:
            movimientos.append({
                'fecha': c.compra.fecha_compra,
                'tipo': 'Compra',
                'documento': f'Compra #{c.compra.id}',
                'entrada': c.cantidad,
                'salida': 0,
                'valor_entrada': round(c.cantidad * c.precio_prv, 2),
                'valor_salida': 0,
                'observacion': '',
            })
    for v in ventas_rango:
        es_reversion = v.cantidad < 0
        cantidad_abs = abs(v.cantidad)
        valor_abs = round(cantidad_abs * costo_actual, 2)
        if es_reversion:
            # Una reversion de venta es una ENTRADA (vuelve al stock).
            movimientos.append({
                'fecha': timezone.localtime(v.factura.fecha).date(),
                'tipo': 'Reversión de venta',
                'documento': f'Factura #{v.factura.id}',
                'entrada': cantidad_abs,
                'salida': 0,
                'valor_entrada': valor_abs,
                'valor_salida': 0,
                'observacion': '',
            })
        else:
            movimientos.append({
                'fecha': timezone.localtime(v.factura.fecha).date(),
                'tipo': 'Venta',
                'documento': f'Factura #{v.factura.id}',
                'entrada': 0,
                'salida': cantidad_abs,
                'valor_entrada': 0,
                'valor_salida': valor_abs,
                'observacion': '',
            })
    for e in eventos_ncd_rango:
        cantidad_abs = abs(e['cantidad'])
        valor_abs = round(cantidad_abs * costo_actual, 2)
        es_entrada = e['cantidad'] > 0
        movimientos.append({
            'fecha': e['fecha'],
            'tipo': e['tipo'],
            'documento': e['documento'],
            'entrada': cantidad_abs if es_entrada else 0,
            'salida': 0 if es_entrada else cantidad_abs,
            'valor_entrada': valor_abs if es_entrada else 0,
            'valor_salida': 0 if es_entrada else valor_abs,
            'observacion': '',
        })
    movimientos.sort(key=lambda m: m['fecha'])

    saldo_corriente = saldo_inicial_cantidad
    valor_corriente = saldo_inicial_valor
    for m in movimientos:
        saldo_corriente += m['entrada'] - m['salida']
        valor_corriente += m['valor_entrada'] - m['valor_salida']
        m['saldo_corriente'] = saldo_corriente
        m['valor_saldo_corriente'] = round(valor_corriente, 2)

    total_entradas_rango = sum(m['entrada'] for m in movimientos)
    total_salidas_rango = sum(m['salida'] for m in movimientos)

    # Ajuste no identificado: diferencia entre la existencia que el
    # sistema tiene cargada HOY y la que resultaria de sumar TODOS los
    # movimientos reales (compras - ventas) de toda la historia.
    # Idealmente 0. Cuando no lo es, es arrastre de las corridas de
    # volumen para la certificacion SIN (emisiones/anulaciones/
    # reversiones masivas que movieron existencia por caminos que el
    # Kardex no cuenta) o de los scripts ad-hoc que ajustaron
    # existencia a mano. Es constante -- no depende del rango elegido.
    # Se expone explicito para que el saldo final del Kardex nunca
    # parezca "no cerrar" contra el Estado de Inventario.
    compras_todas, ventas_todas = _movimientos_producto_qs(producto)
    neto_historico = (
        sum(c.cantidad for c in compras_todas) - sum(v.cantidad for v in ventas_todas)
        + sum(e['cantidad'] for e in eventos_ncd)
    )
    ajuste_no_identificado = producto.existencia - neto_historico

    return {
        'producto': producto,
        'saldo_inicial_cantidad': saldo_inicial_cantidad,
        'saldo_inicial_valor': saldo_inicial_valor,
        'movimientos': movimientos,
        'total_entradas': total_entradas_rango,
        'total_salidas': total_salidas_rango,
        'saldo_final_cantidad': saldo_corriente,
        'saldo_final_valor': round(valor_corriente, 2),
        'ajuste_no_identificado': ajuste_no_identificado,
        'ajuste_no_identificado_valor': round(ajuste_no_identificado * costo_actual, 2),
        'existencia_sistema': producto.existencia,
    }


def _contexto_kardex_inventario(request):
    """
    Arma el contexto de Kardex de Inventario (modo resumen o detalle
    segun venga o no producto_id) -- compartido entre la pantalla, el
    PDF y el Excel (13/09/2026). Devuelve (contexto, error): error
    solo se usa en modo detalle cuando el producto_id no existe.
    """
    hoy = timezone.localdate()
    f1_raw = request.GET.get('f1')
    f2_raw = request.GET.get('f2')
    from django.utils.dateparse import parse_date
    fecha_desde = parse_date(f1_raw) if f1_raw else hoy.replace(day=1)
    fecha_hasta = parse_date(f2_raw) if f2_raw else hoy

    producto_id = request.GET.get('producto_id', '').strip()
    categoria_id = request.GET.get('categoria_id', '').strip()

    from fe.models import Empresa
    from fe.utils import datos_logo_header
    empresa = Empresa.objects.first()
    base = {
        'f1': fecha_desde,
        'f2': fecha_hasta,
        'productos': Producto.objects.filter(estado=True).order_by('descripcion'),
        'categorias': Categoria.objects.filter(estado=True).order_by('descripcion'),
        'producto_id': producto_id,
        'categoria_id': categoria_id,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
        **datos_logo_header(empresa),
    }

    if producto_id:
        producto = Producto.objects.filter(pk=producto_id, estado=True).first()
        if not producto:
            return None, 'Producto no encontrado.'
        base.update({'modo': 'detalle', 'kardex': _calcular_kardex_producto(producto, fecha_desde, fecha_hasta)})
        return base, None

    productos = Producto.objects.filter(estado=True).order_by('descripcion')
    if categoria_id:
        productos = productos.filter(subcategoria__categoria_id=categoria_id)

    resumen = []
    for prod in productos:
        k = _calcular_kardex_producto(prod, fecha_desde, fecha_hasta)
        resumen.append({
            'producto': prod,
            'saldo_inicial_cantidad': k['saldo_inicial_cantidad'],
            'saldo_inicial_valor': k['saldo_inicial_valor'],
            'total_entradas': k['total_entradas'],
            'total_salidas': k['total_salidas'],
            'saldo_final_cantidad': k['saldo_final_cantidad'],
            'saldo_final_valor': k['saldo_final_valor'],
            'ajuste_no_identificado': k['ajuste_no_identificado'],
            'existencia_sistema': k['existencia_sistema'],
        })
    base.update({'modo': 'resumen', 'resumen': resumen})
    return base, None


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def kardex_inventario(request):
    """
    Reporte de Movimiento de Inventario (Kardex), con rango de fechas
    elegible y valorizacion aproximada (ver docstring de
    _calcular_kardex_producto). Agregado 08/09/2026 -- generaliza el
    kardex que ya existia (fijo al mes actual, un producto a la vez,
    dentro de la pantalla "Tables") a su propio reporte dedicado, con
    rango de fecha libre.

    Sin producto_id elegido: RESUMEN, un renglon por producto (saldo
    inicial/entradas/salidas/saldo final, sin el detalle linea por
    linea -- mostrar el detalle de TODOS los productos a la vez seria
    ilegible). Con un producto_id elegido: DETALLE completo de ese
    producto.
    """
    contexto, error = _contexto_kardex_inventario(request)
    if error:
        messages.error(request, error)
        return redirect('bases:kardex_inventario')
    return render(request, 'bases/kardex_inventario.html', contexto)


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def kardex_inventario_pdf(request):
    """PDF con elementos de reporte real -- ver estado_inventario_pdf."""
    from xhtml2pdf import pisa
    from django.template.loader import render_to_string
    from django.http import HttpResponse as _HttpResponse

    contexto, error = _contexto_kardex_inventario(request)
    if error:
        return _HttpResponse(error, status=404)

    contexto['es_pdf'] = True
    html = render_to_string('bases/kardex_inventario_print.html', contexto)
    response = _HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="kardex_inventario.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return _HttpResponse("Ocurrió un error al generar el PDF. Contacte al administrador.", status=500)
    return response


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def kardex_inventario_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from django.http import HttpResponse as _HttpResponse

    contexto, error = _contexto_kardex_inventario(request)
    if error:
        return _HttpResponse(error, status=404)

    wb = Workbook()
    ws = wb.active
    ws.title = "Kardex de Inventario"

    ws.append(["Kardex de Inventario"])
    ws.append([f"Período: {contexto['f1'].strftime('%d/%m/%Y')} - {contexto['f2'].strftime('%d/%m/%Y')}",
                "", f"Emitido: {contexto['fecha_emision'].strftime('%d/%m/%Y %H:%M')}"])
    ws.append([])

    if contexto['modo'] == 'detalle':
        k = contexto['kardex']
        ws.append([f"Producto: {k['producto'].codigo} - {k['producto'].descripcion}"])
        ws.append([])
        ws.append(["Fecha", "Tipo", "Documento", "Entrada", "Salida", "Saldo (Cant.)", "Saldo (Valor)", "Observación"])
        for celda in ws[ws.max_row]:
            celda.font = Font(bold=True)
        ws.append(["", "Saldo Inicial", "", "", "", k['saldo_inicial_cantidad'], k['saldo_inicial_valor'], ""])
        for m in k['movimientos']:
            ws.append([
                m['fecha'].strftime('%d/%m/%Y'), m['tipo'], m['documento'],
                m['entrada'] or '', m['salida'] or '', m['saldo_corriente'], m['valor_saldo_corriente'],
                m.get('observacion', ''),
            ])
        ws.append(["", "Saldo Final", "", "", "", k['saldo_final_cantidad'], k['saldo_final_valor'], ""])
        if k['ajuste_no_identificado']:
            ws.append(["", "Ajuste no identificado", "", "", "", k['ajuste_no_identificado'], k['ajuste_no_identificado_valor'], ""])
            ws.append(["", "Existencia actual del sistema", "", "", "", k['existencia_sistema'], "", ""])
    else:
        encabezados = ["Código", "Producto", "Saldo Inicial (Cant.)", "Saldo Inicial (Valor)",
                       "Entradas", "Salidas", "Saldo Final (Cant.)", "Saldo Final (Valor)",
                       "Ajuste no ident.", "Existencia Sistema"]
        ws.append(encabezados)
        for celda in ws[ws.max_row]:
            celda.font = Font(bold=True)
        for fila in contexto['resumen']:
            ws.append([
                fila['producto'].codigo, fila['producto'].descripcion,
                fila['saldo_inicial_cantidad'], fila['saldo_inicial_valor'],
                fila['total_entradas'], fila['total_salidas'],
                fila['saldo_final_cantidad'], fila['saldo_final_valor'],
                fila['ajuste_no_identificado'], fila['existencia_sistema'],
            ])
            ws.cell(row=ws.max_row, column=1).number_format = '@'

    response = _HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="kardex_inventario.xlsx"'
    wb.save(response)
    return response