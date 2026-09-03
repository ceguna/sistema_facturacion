from django.shortcuts import render, get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from django.contrib.auth.decorators import login_required, permission_required
from datetime import timedelta

from xhtml2pdf import pisa
from openpyxl import Workbook
from openpyxl.styles import Font

from .models import FacturaEnc,FacturaDet,Cliente,Pago
from fe.models import Empresa


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_recibo(request,id):
    template_name="fac/factura_one.html"

    enc = get_object_or_404(FacturaEnc, id=id)
    det = FacturaDet.objects.filter(factura=id)
    empresa = Empresa.objects.first()

    context={
        'request':request,
        'enc':enc,
        'detalle':det,
        'empresa':empresa,
    }

    return render(request,template_name,context)


def _contexto_reporte_facturas(f1, f2):
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    # estado=True excluye las facturas eliminadas (soft-delete via
    # eliminar_factura) -- no deben aparecer en ningun reporte.
    enc = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, estado=True
    ).order_by('id')

    empresa = Empresa.objects.first()

    return {
        'f1': f1_parsed,
        'f2': f2_parsed,
        'enc': enc,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_list(request,f1,f2):
    template_name="fac/facturas_print_all.html"

    context = _contexto_reporte_facturas(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/facturas/imprimir-todas-pdf/{f1}/{f2}"

    return render(request,template_name,context)


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_list_pdf(request, f1, f2):
    template_name = "fac/facturas_print_all.html"

    context = _contexto_reporte_facturas(f1, f2)
    context['request'] = request
    context['es_pdf'] = True
    context['url_ver_en_pantalla'] = f"/fac/facturas/imprimir-todas/{f1}/{f2}"

    html = render_to_string(template_name, context)

    response = HttpResponse(content_type='application/pdf')
    nombre_archivo = f"reporte_facturas_{f1}_a_{f2}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'

    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse(
            "Ocurrió un error al generar el PDF. Contacte al administrador.",
            status=500
        )

    return response


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_list_excel(request, f1, f2):
    context = _contexto_reporte_facturas(f1, f2)
    facturas = context['enc']

    wb = Workbook()
    ws = wb.active
    ws.title = "Facturas"

    encabezados = ["No.", "Fecha", "Cliente", "Total", "Estado", "Anulada"]
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True)

    for f in facturas:
        estado = f.get_estado_sin_display() if hasattr(f, 'get_estado_sin_display') else f.estado_sin
        ws.append([
            f.id,
            f.fecha.strftime("%d/%m/%Y") if f.fecha else "",
            str(f.cliente),
            f.total,
            estado,
            "Sí" if f.anulado else "No",
        ])
        ws.cell(row=ws.max_row, column=1).number_format = '@'

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="facturas_{f1}_a_{f2}.xlsx"'
    wb.save(response)
    return response


def _contexto_reporte_cierre_ventas(f1, f2):
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    # estado=True excluye las facturas eliminadas (soft-delete).
    facturas = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, estado=True
    )

    por_dia = (
        facturas.annotate(dia=TruncDate('fecha'))
        .values('dia')
        .annotate(
            cantidad=Count('id'),
            cantidad_anuladas=Count('id', filter=Q(anulado=True)),
            monto_activo=Sum('total', filter=Q(anulado=False)),
            monto_anulado=Sum('total', filter=Q(anulado=True)),
        )
        .order_by('dia')
    )

    from .models import CierreDia
    cierres = {
        c.fecha: c
        for c in CierreDia.objects.filter(fecha__gte=f1_parsed, fecha__lte=f2_parsed)
    }

    dias = []
    total_activo = 0
    total_anulado = 0
    total_facturas = 0
    cierres_con_observacion = []

    for row in por_dia:
        fecha = row['dia']
        cierre = cierres.get(fecha)
        monto_activo = round(row['monto_activo'] or 0, 2)
        monto_anulado = round(row['monto_anulado'] or 0, 2)

        dias.append({
            'fecha': fecha,
            'cantidad': row['cantidad'],
            'cantidad_anuladas': row['cantidad_anuladas'],
            'monto_activo': monto_activo,
            'monto_anulado': monto_anulado,
            'cierre': cierre,
        })

        total_activo += monto_activo
        total_anulado += monto_anulado
        total_facturas += row['cantidad']

        if cierre and cierre.estado == CierreDia.ESTADO_CERRADO_CON_PENDIENTES:
            cierres_con_observacion.append(cierre)

    empresa = Empresa.objects.first()

    return {
        'f1': f1_parsed,
        'f2': f2_parsed,
        'dias': dias,
        'total_activo': round(total_activo, 2),
        'total_anulado': round(total_anulado, 2),
        'total_neto': round(total_activo, 2),
        'total_facturas': total_facturas,
        'cierres_con_observacion': cierres_con_observacion,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }


@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def reporte_cierre_ventas(request, f1, f2):
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-ventas/pdf/{f1}/{f2}"

    return render(request, template_name, context)


@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def reporte_cierre_ventas_pdf(request, f1, f2):
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2)
    context['request'] = request
    context['es_pdf'] = True

    html = render_to_string(template_name, context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cierre_ventas_{f1}_a_{f2}.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response

def _contexto_cierre_caja(f1, f2):
    """
    Cierre de Caja: desglose de ingresos por forma de pago (Resumen) y
    listado factura por factura AGRUPADO por forma de pago, con
    subtotal por grupo (Detallado). Solo se consideran facturas
    ACTIVAS (no anuladas, no eliminadas) -- ni una factura anulada ni
    una eliminada representan un ingreso real de caja.
    """
    from itertools import groupby

    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    facturas_activas = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, anulado=False, estado=True
    )

    resumen_qs = (
        facturas_activas.values('forma_pago')
        .annotate(cantidad=Count('id'), total=Sum('total'))
        .order_by('forma_pago')
    )
    etiquetas = dict(FacturaEnc.FORMA_PAGO_CHOICES)
    resumen = [
        {
            'forma_pago': etiquetas.get(row['forma_pago'], row['forma_pago']),
            'cantidad': row['cantidad'],
            'total': round(row['total'] or 0, 2),
        }
        for row in resumen_qs
    ]
    total_general = round(sum(r['total'] for r in resumen), 2)
    cantidad_general = sum(r['cantidad'] for r in resumen)

    # Detalle agrupado por forma de pago, con subtotal por grupo --
    # requiere ordenar por forma_pago primero para que groupby agrupe
    # correctamente (itertools.groupby solo agrupa elementos
    # consecutivos, no re-ordena por si solo).
    detalle_qs = facturas_activas.select_related('cliente').order_by('forma_pago', 'id')
    detalle_agrupado = []
    for codigo_forma_pago, grupo in groupby(detalle_qs, key=lambda f: f.forma_pago):
        facturas_grupo = list(grupo)
        detalle_agrupado.append({
            'forma_pago': etiquetas.get(codigo_forma_pago, codigo_forma_pago),
            'facturas': facturas_grupo,
            'cantidad': len(facturas_grupo),
            'subtotal': round(sum(f.total for f in facturas_grupo), 2),
        })

    empresa = Empresa.objects.first()

    return {
        'f1': f1_parsed,
        'f2': f2_parsed,
        'resumen': resumen,
        'total_general': total_general,
        'cantidad_general': cantidad_general,
        'detalle_agrupado': detalle_agrupado,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_resumen(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-caja/resumen/pdf/{f1}/{f2}/"
    return render(request, 'fac/cierre_caja_resumen.html', context)

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_resumen_pdf(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2)
    context['request'] = request
    context['es_pdf'] = True
    html = render_to_string('fac/cierre_caja_resumen.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cierre_caja_resumen_{f1}_a_{f2}.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_detallado(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-caja/detallado/pdf/{f1}/{f2}/"
    return render(request, 'fac/cierre_caja_detallado.html', context)

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_detallado_pdf(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2)
    context['request'] = request
    context['es_pdf'] = True
    html = render_to_string('fac/cierre_caja_detallado.html', context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cierre_caja_detallado_{f1}_a_{f2}.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response


# =====================================================================
# Kardex de Cliente: Debe/Haber/Saldo de su cuenta a credito
# =====================================================================

@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def kardex_cliente_selector(request):
    """Selector: elegir un cliente para ver su Kardex de credito."""
    clientes = Cliente.objects.filter(estado=True).order_by('apellidos', 'nombres')
    return render(request, 'fac/kardex_cliente_selector.html', {'clientes': clientes})


def _contexto_kardex_cliente(cliente_id, f1=None, f2=None):
    cliente = get_object_or_404(Cliente, pk=cliente_id)

    # Se arma el historial COMPLETO primero (sin filtro de fechas
    # todavia) -- necesario para poder calcular un saldo de apertura
    # correcto cuando se filtra, y para que un abono de HOY sobre una
    # factura VIEJA se filtre por su propia fecha, no por la fecha de
    # la factura (antes, facturas_credito se filtraba por fecha y
    # pagos se sacaba de "factura__in=facturas_credito" -- un pago de
    # hoy sobre una factura de hace un mes desaparecia si se filtraba
    # "solo hoy", porque su factura quedaba afuera del filtro).
    facturas_credito = FacturaEnc.objects.filter(
        cliente=cliente, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO
    )
    pagos = Pago.objects.filter(factura__in=facturas_credito).select_related('factura')

    todos = []
    for f in facturas_credito:
        # Una factura anulada o eliminada llego a ese estado SOLO si
        # nunca tuvo abonos (regla de negocio de anular_factura /
        # eliminar_factura) -- por eso alcanza con "Debe=0 + nota" sin
        # ninguna otra logica especial: nunca va a tener un Pago
        # asociado que compense algo que nunca conto como deuda real.
        afecta_saldo = f.estado and not f.anulado
        if f.anulado:
            nota = 'Anulada (sin abonos, no afecta el saldo)'
        elif not f.estado:
            nota = 'Eliminada (sin abonos, no afecta el saldo)'
        else:
            nota = ''

        # Color de vencimiento: delega directo en estado_credito (que
        # ya centraliza el umbral de "proximo a vencer" y ya excluye
        # anuladas/eliminadas/pagadas) en vez de reimplementar la
        # comparacion de fechas aca -- mismo criterio exacto que
        # Cartera de Creditos, un solo lugar si el umbral cambia.
        estado_f = f.estado_credito
        color_vencimiento = {'vencido': 'vencido', 'por_vencer': 'proximo'}.get(estado_f, '')

        todos.append({
            'fecha': f.fecha,
            'tipo': 'Nueva venta a crédito',
            'documento': f'Factura N° {f.id}',
            'vencimiento': f.fecha_vencimiento,
            'color_vencimiento': color_vencimiento,
            'debe': round(f.total, 2) if afecta_saldo else 0,
            'haber': 0,
            'nota': nota,
            '_orden': 0,  # la factura aparece antes que sus abonos del mismo dia
        })

    for p in pagos:
        todos.append({
            'fecha': p.fecha,
            'tipo': f'Abono ({p.get_forma_pago_display()})',
            'documento': f'Pago N° {p.id} — Factura N° {p.factura_id}',
            'vencimiento': None,
            'color_vencimiento': '',
            'debe': 0,
            'haber': round(p.monto, 2),
            'nota': p.observacion or '',
            '_orden': 1,
        })

        # Si el abono fue revertido (Caso 1: error de carga, NO una
        # devolucion real -- ver conversacion sobre politica de
        # anulacion con abono), se agrega una linea COMPENSATORIA
        # aparte, en vez de ocultar o modificar la linea original --
        # mismo criterio que el resto del sistema
        # (borrar_detalle_factura usa el mismo patron, con una linea
        # en negativo, para revertir una linea de FacturaDet). El
        # abono original queda visible en el historial completo, y el
        # saldo corriente se recalcula solo con esta linea nueva.
        if p.revertido:
            todos.append({
                'fecha': p.fecha_reversion or p.fecha,
                'tipo': 'Reversión de Abono',
                'documento': f'Pago N° {p.id} — Factura N° {p.factura_id}',
                'vencimiento': None,
                'color_vencimiento': '',
                'debe': round(p.monto, 2),
                'haber': 0,
                'nota': p.motivo_reversion or '',
                '_orden': 2,
            })

    todos.sort(key=lambda m: (m['fecha'], m['_orden']))

    def _fecha_del_movimiento(m):
        f = m['fecha']
        return timezone.localtime(f).date() if hasattr(f, 'date') and callable(getattr(f, 'date', None)) else f

    # Saldo de apertura: todo lo que paso ANTES del filtro "Desde",
    # comparando por la fecha de CADA MOVIMIENTO (no la de su
    # factura). Sin esto, al filtrar, el saldo arrancaba de cero y la
    # ultima fila mostraba un total muy por debajo del real -- dando
    # la falsa impresion de que el cliente debe menos de lo que
    # realmente debe.
    saldo_apertura = 0
    if f1:
        for m in todos:
            if _fecha_del_movimiento(m) < f1:
                saldo_apertura = round(saldo_apertura + m['debe'] - m['haber'], 2)

    movimientos = [
        m for m in todos
        if (not f1 or _fecha_del_movimiento(m) >= f1) and (not f2 or _fecha_del_movimiento(m) <= f2)
    ]

    if f1:
        movimientos.insert(0, {
            'fecha': None,
            'tipo': 'Saldo Anterior',
            'documento': '',
            'vencimiento': None,
            'color_vencimiento': '',
            'debe': None,
            'haber': None,
            'nota': 'Acumulado de movimientos previos a este período.',
            'saldo': saldo_apertura,
        })

    saldo_acumulado = saldo_apertura
    for m in movimientos:
        if m['debe'] is None:  # la fila de "Saldo Anterior" ya trae su saldo puesto
            continue
        saldo_acumulado = round(saldo_acumulado + m['debe'] - m['haber'], 2)
        m['saldo'] = saldo_acumulado

    total_debe = round(sum(m['debe'] for m in movimientos if m['debe'] is not None), 2)
    total_haber = round(sum(m['haber'] for m in movimientos if m['haber'] is not None), 2)

    empresa = Empresa.objects.first()

    return {
        'cliente': cliente,
        'movimientos': movimientos,
        'total_debe': total_debe,
        'total_haber': total_haber,
        'saldo_final': round(saldo_apertura + total_debe - total_haber, 2),
        'f1': f1,
        'f2': f2,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }



@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def kardex_cliente(request, cliente_id):
    f1 = parse_date(request.GET.get('f1')) if request.GET.get('f1') else None
    f2 = parse_date(request.GET.get('f2')) if request.GET.get('f2') else None

    context = _contexto_kardex_cliente(cliente_id, f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    return render(request, 'fac/kardex_cliente.html', context)


@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def kardex_cliente_pdf(request, cliente_id):
    f1 = parse_date(request.GET.get('f1')) if request.GET.get('f1') else None
    f2 = parse_date(request.GET.get('f2')) if request.GET.get('f2') else None

    context = _contexto_kardex_cliente(cliente_id, f1, f2)
    context['request'] = request
    context['es_pdf'] = True

    html = render_to_string('fac/kardex_cliente.html', context)

    response = HttpResponse(content_type='application/pdf')
    nombre_cliente = str(context['cliente']).replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="kardex_{nombre_cliente}_{cliente_id}.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response


# =====================================================================
# Recibo de Abono (impresion termica, mismo patron que factura_one.html)
# =====================================================================

@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def recibo_pago(request, pago_id):
    """
    Recibo imprimible de un abono puntual -- mismo formato/impresora
    termica que factura_one.html (58mm, impresion automatica al abrir).
    Reconstruye saldo antes/despues de ESTE abono sumando los Pago de
    la misma factura hasta este inclusive (por id, ya que se aplican en
    el orden en que se registran) -- no hace falta guardar un snapshot
    en el modelo Pago para esto.
    """
    pago = get_object_or_404(Pago, pk=pago_id)
    factura = pago.factura

    abonos_hasta_este = Pago.objects.filter(
        factura=factura, id__lte=pago.id
    ).aggregate(t=Sum('monto'))['t'] or 0
    saldo_despues = round(factura.total - abonos_hasta_este, 2)
    saldo_antes = round(saldo_despues + pago.monto, 2)

    empresa = Empresa.objects.first()

    return render(request, 'fac/recibo_pago.html', {
        'pago': pago,
        'factura': factura,
        'saldo_antes': saldo_antes,
        'saldo_despues': saldo_despues,
        'empresa': empresa,
    })