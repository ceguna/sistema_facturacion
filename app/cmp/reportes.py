import os
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.contrib.staticfiles import finders
from django.utils import timezone

from .models import ComprasEnc, ComprasDet
from fe.models import Empresa
from fe.utils import datos_logo_header

def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those
    resources

    CORREGIDO 20/09/2026: al agregar el logo de la empresa al
    encabezado (base/reporte_logo_header.html), el <img src="..."> pasa
    la ruta de archivo REAL en disco (empresa.logo.path, ej.
    "D:\...\media\empresa\logos\X.jpg"), no una URL de /static/ o
    /media/ -- finders.find() (pensado solo para archivos static)
    reventaba con SuspiciousFileOperation al recibir una ruta absoluta
    de Windows. Si el uri ya es una ruta de archivo existente, se
    devuelve tal cual, sin pasar por la resolucion de static/media.
    """
    if os.path.isfile(uri):
        return uri

    result = finders.find(uri)
    if result:
        if not isinstance(result, (list, tuple)):
            result = [result]
            result = list(os.path.realpath(path) for path in result)
            path=result[0]
        else:
            sUrl = settings.STATIC_URL        # Typically /static/
            sRoot = settings.STATIC_ROOT      # Typically /home/userX/project_static/
            mUrl = settings.MEDIA_URL         # Typically /media/
            mRoot = settings.MEDIA_ROOT       # Typically /home/userX/project_static/media/

            if uri.startswith(mUrl):
                path = os.path.join(mRoot, uri.replace(mUrl, ""))
            elif uri.startswith(sUrl):
                path = os.path.join(sRoot, uri.replace(sUrl, ""))
            else:
                return uri

        # make sure that file exists
        if not os.path.isfile(path):
            raise RuntimeError(
                'media URI must start with %s or %s' % (sUrl, mUrl)
            )
        return path

def reporte_compras(request):
    template_path = 'cmp/compras_print_all.html'
    today = timezone.now()

    compras = ComprasEnc.objects.all()
    empresa = Empresa.objects.first()
    context = {
        'obj': compras,
        'today': today,
        'request': request,
        'empresa': empresa,
        **datos_logo_header(empresa),
    }

    # Create a Django response object, and specify content_type as pdf
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="todas_compras.pdf"' #El inline es para mostrar el reporte en pantalla
    
    # find the template and render it.
    template = get_template(template_path)
    html = template.render(context)

    # create a pdf
    pisa_status = pisa.CreatePDF(
       html, dest=response, link_callback=link_callback)
    # if error then show some funny view
    if pisa_status.err:
       return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response

def imprimir_compra(request, compra_id):
    template_path = 'cmp/compras_print_one.html'
    today = timezone.now()

    enc = ComprasEnc.objects.filter(id=compra_id).first()
    if enc:
        detalle = ComprasDet.objects.filter(compra_id=compra_id)
    else:
        detalle={}

    empresa = Empresa.objects.first()
    context = {
        'detalle': detalle,
        'encabezado': enc,
        'today': today,
        'request': request,
        'empresa': empresa,
        **datos_logo_header(empresa),
    }

    # Create a Django response object, and specify content_type as pdf
    response = HttpResponse(content_type='application/pdf')
    #El inline es para mostrar el reporte en pantalla y attachment permite descargar el archivo
    response['Content-Disposition'] = 'inline; filename="todas_compras.pdf"' 
    
    # find the template and render it.
    template = get_template(template_path)
    html = template.render(context)

    # create a pdf
    pisa_status = pisa.CreatePDF(
       html, dest=response, link_callback=link_callback)
    # if error then show some funny view
    if pisa_status.err:
       return HttpResponse('We had some errors <pre>' + html + '</pre>')
    return response