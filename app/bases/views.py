from django.shortcuts import render
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin,\
    PermissionRequiredMixin
from django.views import generic

import datetime
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.utils import timezone

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
