from django.shortcuts import render
from django.utils import timezone
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required, permission_required

from xhtml2pdf import pisa

from .models import Producto
from fe.models import Empresa


def _contexto_lista_precios():
    productos = Producto.objects.filter(estado=True).select_related(
        'unidad_medida', 'marca', 'subcategoria'
    ).order_by('codigo')
    empresa = Empresa.objects.first()
    return {
        'productos': productos,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
    }


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def lista_precios(request):
    context = _contexto_lista_precios()
    context['es_pdf'] = False
    context['url_descargar_pdf'] = '/inv/productos/reportes/lista-precios-pdf/'
    return render(request, 'inv/lista_precios.html', context)


@login_required(login_url='/login/')
@permission_required('inv.view_producto', login_url='bases:sin_privilegios')
def lista_precios_pdf(request):
    context = _contexto_lista_precios()
    context['es_pdf'] = True
    html = render_to_string('inv/lista_precios.html', context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="lista_precios.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response