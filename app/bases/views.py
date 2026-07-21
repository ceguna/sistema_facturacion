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

        # Ventas de los ultimos 7 dias, para el grafico
        hace_7_dias = hoy - datetime.timedelta(days=6)
        ventas_por_dia = facturas_activas.filter(fecha__date__gte=hace_7_dias) \
            .annotate(dia=TruncDate('fecha')) \
            .values('dia').annotate(total=Sum('total')).order_by('dia')

        ventas_dict = {v['dia']: float(v['total']) for v in ventas_por_dia}
        chart_labels = []
        chart_data = []
        for i in range(7):
            dia = hace_7_dias + datetime.timedelta(days=i)
            chart_labels.append(dia.strftime('%d/%m'))
            chart_data.append(ventas_dict.get(dia, 0))

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


class LibroVentasView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'bases/libro_ventas.html'
    login_url = 'bases:login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from fac.models import FacturaEnc

        hoy = timezone.localtime(timezone.now()).date()
        mes = int(self.request.GET.get('mes', hoy.month))
        anio = int(self.request.GET.get('anio', hoy.year))

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
        mes = int(self.request.GET.get('mes', hoy.month))
        anio = int(self.request.GET.get('anio', hoy.year))

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

        anuladas = FacturaEnc.objects.filter(anulado=True) \
            .select_related('cliente', 'usuario_anulacion') \
            .order_by('-fecha_anulacion')

        for f in anuladas:
            f.total_fmt = "{:,.2f}".format(f.total)

        context.update({
            'anuladas': anuladas,
            'total_anulado': sum(f.total for f in anuladas),
            'total_anulado_fmt': "{:,.2f}".format(sum(f.total for f in anuladas)),
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
