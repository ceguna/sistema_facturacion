from django.shortcuts import render, get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from datetime import timedelta

from xhtml2pdf import pisa

from .models import FacturaEnc,FacturaDet,CierreDia
from fe.models import Empresa

def imprimir_factura_recibo(request,id):
    template_name="fac/factura_one.html"

    enc = get_object_or_404(FacturaEnc, id=id)
    det = FacturaDet.objects.filter(factura=id)

    context={
        'request':request,
        'enc':enc,
        'detalle':det
    }

    return render(request,template_name,context)


def _contexto_reporte_facturas(f1, f2):
    """
    Arma el contexto compartido entre la version en pantalla y la
    version PDF del reporte de facturas -- una sola fuente de verdad
    para no repetir la logica de filtrado en dos lugares.
    """
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    #fecha__gte es mayor o igual a f1 y fecha__lt es menor a f2
    enc = FacturaEnc.objects.filter(fecha__gte=f1_parsed, fecha__lt=f2_con_margen)

    empresa = Empresa.objects.first()

    return {
        'f1': f1_parsed,
        'f2': f2_parsed,
        'enc': enc,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }


def imprimir_factura_list(request,f1,f2):
    """Version en pantalla (HTML normal, para ver e imprimir con Ctrl+P)."""
    template_name="fac/facturas_print_all.html"

    context = _contexto_reporte_facturas(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/facturas/imprimir-todas-pdf/{f1}/{f2}"

    return render(request,template_name,context)


def imprimir_factura_list_pdf(request, f1, f2):
    """
    Misma informacion que imprimir_factura_list, pero generada como un
    archivo PDF real para descargar (no HTML para imprimir a mano).
    """
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


def _contexto_reporte_cierre_ventas(f1, f2):
    """
    Arma el contexto compartido entre la version en pantalla y la
    version PDF del Reporte de Cierre de Ventas -- pensado para uso
    contable: por cada dia del rango, muestra si tiene Cierre de Dia
    registrado (y si fue limpio o forzado con pendientes), cantidad de
    facturas, ventas netas (facturas activas, sin anular) y monto
    anulado por separado -- nunca mezclados en un solo total.
    """
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    facturas = FacturaEnc.objects.filter(fecha__gte=f1_parsed, fecha__lt=f2_con_margen)

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
        monto_activo = row['monto_activo'] or 0
        monto_anulado = row['monto_anulado'] or 0

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
        'total_activo': total_activo,
        'total_anulado': total_anulado,
        'total_neto': total_activo,  # ventas netas = activas (las anuladas no cuentan como venta)
        'total_facturas': total_facturas,
        'cierres_con_observacion': cierres_con_observacion,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }


def reporte_cierre_ventas(request, f1, f2):
    """Version en pantalla del Reporte de Cierre de Ventas."""
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-ventas/pdf/{f1}/{f2}"

    return render(request, template_name, context)


def reporte_cierre_ventas_pdf(request, f1, f2):
    """Version PDF descargable del Reporte de Cierre de Ventas."""
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2)
    context['request'] = request
    context['es_pdf'] = True

    html = render_to_string(template_name, context)

    response = HttpResponse(content_type='application/pdf')
    nombre_archivo = f"cierre_ventas_{f1}_a_{f2}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'

    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse(
            "Ocurrió un error al generar el PDF. Contacte al administrador.",
            status=500
        )

    return response