import os
from io import BytesIO

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

from bases.alcance import requiere_alcance
from .models import FacturaEnc,FacturaDet,Cliente,Pago,NotaCreditoDebito
from fe.models import Empresa, Sucursal, PuntoVenta
from fe.utils import datos_logo_header


# Formato de factura -> plantilla (17/09/2026): UNA sola tabla, para
# que Ver en Pantalla, Descargar PDF, correo y WhatsApp usen siempre la
# misma plantilla segun lo que el administrador eligio en Empresa --
# nunca se repite el nombre de plantilla suelto en varios lugares.
_PLANTILLA_POR_FORMATO = {
    Empresa.CARTA: 'fac/factura_pdf.html',
    Empresa.TERMICO: 'fac/factura_pdf_termico.html',
}

# Plantilla de la Nota de Credito-Debito, mismo criterio (19/09/2026):
# UN documento distinto de la factura (no una factura "comprimida" --
# tiene su propia estructura: datos de la factura original + datos de
# la devolucion + monto efectivo debito-credito), pero que respeta el
# mismo formato Carta/Termico que ya eligio el administrador.
_PLANTILLA_NCD_POR_FORMATO = {
    Empresa.CARTA: 'fac/ncd_pdf.html',
    Empresa.TERMICO: 'fac/ncd_pdf_termico.html',
}


def _ncd_vigente(enc):
    """
    Devuelve la Nota de Credito-Debito VIGENTE de esta factura ahora
    mismo (Validada o con una anulacion Revertida -- a estos efectos,
    el mismo estado: la correccion esta en efecto), o None si no tiene
    ninguna o si la unica que tuvo esta Anulada (en ese caso la
    correccion quedo sin efecto, la factura ORIGINAL vuelve a ser el
    documento vigente). Mismo criterio que _tiene_ncd_validada en
    fac/views.py -- ver ese comentario para el detalle completo.
    """
    return enc.notas_credito_debito.filter(
        estado_sin__in=[NotaCreditoDebito.SIN_VALIDADA, NotaCreditoDebito.SIN_REVERTIDA]
    ).order_by('-id').first()


def _contexto_documento(enc):
    """
    Punto de entrada REAL para los 4 caminos de generacion de
    documento de una factura (Ver en Pantalla, Descargar PDF, correo,
    WhatsApp) -- decide si corresponde generar la FACTURA original o
    la NOTA DE CREDITO-DEBITO que la corrige, segun el estado vigente
    (agregado 19/09/2026, pedido de Carlos). Devuelve ademas el
    documento efectivamente representado (la factura o la NCD), para
    que quien llama pueda nombrar el archivo/adjunto de forma
    coherente con lo que en verdad se genero.
    """
    ncd = _ncd_vigente(enc)
    if ncd:
        template_name, context = _contexto_ncd_documento(ncd)
        return template_name, context, ncd
    template_name, context = _contexto_factura_documento(enc)
    return template_name, context, enc


def _contexto_factura_documento(enc):
    """
    Arma el contexto comun a los 4 caminos donde se genera el
    documento de una factura (Ver en Pantalla, Descargar PDF, correo,
    WhatsApp) -- una sola fuente para no duplicar la consulta de
    detalle ni el chequeo de logo. Devuelve tambien el nombre de
    plantilla a usar, segun Empresa.formato_factura.
    """
    detalle = FacturaDet.objects.filter(factura=enc).select_related('producto')
    empresa = Empresa.objects.first()

    # xhtml2pdf necesita la ruta de archivo real del logo (no la URL)
    # para poder embeberlo -- si el archivo llegara a faltar en disco
    # (borrado a mano, migracion incompleta, etc.), antes esto hacia
    # fallar TODA la generacion del PDF (y por lo tanto el envio de la
    # factura por correo) por un problema puramente cosmetico. Se
    # verifica antes de pasarlo a la plantilla: si no esta, la factura
    # se sigue generando igual, solo que sin logo. (17/09/2026)
    logo_valido = bool(empresa and empresa.logo and os.path.exists(empresa.logo.path))

    formato = empresa.formato_factura if empresa else Empresa.TERMICO
    template_name = _PLANTILLA_POR_FORMATO.get(formato, _PLANTILLA_POR_FORMATO[Empresa.TERMICO])

    context = {'enc': enc, 'detalle': detalle, 'empresa': empresa, 'logo_valido': logo_valido}

    # Datos comunes a AMBOS formatos (20/09/2026 -- antes solo se
    # calculaban para Carta; al agregar el rediseño termico se
    # levantaron aca, una sola vez, para no duplicar la misma consulta/
    # calculo en dos ramas). Todo reutiliza campos que YA existen:
    #
    # Sucursal/Punto de Venta: FacturaEnc todavia no tiene FK a
    # sucursal (eso es Fase 2, multi-sucursal, no construida todavia)
    # -- mientras tanto se muestra la (unica, en la inmensa mayoria de
    # instalaciones de hoy) sucursal/punto de venta registrados de la
    # empresa, no una por-factura real.
    sucursal = Sucursal.objects.filter(empresa=empresa).order_by('id').first() if empresa else None
    punto_venta = PuntoVenta.objects.filter(sucursal=sucursal).order_by('id').first() if sucursal else None
    context['sucursal'] = sucursal
    context['punto_venta'] = punto_venta

    context['importe_en_letras'] = _importe_en_letras(enc.total)

    # Monto Gift Card: no hay un campo separado para "cuanto de esta
    # venta se pago con gift card" -- se deriva de forma_pago (si la
    # venta ENTERA se pago con Gift Card, ese monto es el total; si
    # no, es 0).
    context['monto_gift_card'] = round(enc.total, 2) if enc.forma_pago == FacturaEnc.FORMA_PAGO_GIFT_CARD else 0

    # Importe Base Credito Fiscal: el sistema no maneja impuestos
    # adicionales (ICE/IEHD) que separen esta base del total, asi que
    # coincide con el Total -- formula estandar del SIN para facturas
    # sin esos impuestos especificos.
    context['importe_base_credito_fiscal'] = round(enc.total, 2)

    # QR de verificacion fiscal (19/09/2026): Carlos escaneo el QR de
    # una factura electronica real de otro emisor y confirmo la URL
    # exacta que codifica -- ya no es un formato sin confirmar (antes
    # se habia decidido a proposito NO fabricar un QR por esto mismo,
    # ver notas del 17/09). Requiere NIT del emisor y CUF real (factura
    # ya emitida al SIN); si falta alguno de los dos no se genera nada,
    # no se inventa un QR con datos vacios. Mismo QR para los dos
    # formatos -- misma funcion, mismo algoritmo, solo cambia el
    # tamaño/posicion en cada plantilla.
    if empresa and empresa.nit and enc.cuf:
        url_verificacion = (
            f"https://siat.impuestos.gob.bo/consulta/QR"
            f"?nit={empresa.nit}&cuf={enc.cuf}&numero={enc.id}&t=1"
        )
        context['qr_verificacion_data_uri'] = _generar_qr_data_uri(url_verificacion)

    # CORREGIDO 17/09/2026: xhtml2pdf (motor ReportLab) no corta a
    # mitad de palabra -- word-break/word-wrap en CSS no tienen efecto
    # ahi, es una limitacion conocida del motor. El CUF/CUFD/Codigo de
    # Control (cadenas largas sin espacios) se salen de su columna/caja
    # segun el ancho disponible en cada formato -- se pasa cortado
    # aparte, el valor real (el que se manda al correo/XML) queda
    # intacto. Los cortes son mas chicos en termico (58mm) que en carta.
    if formato == Empresa.TERMICO:
        context['cuf_cortado'] = _cortar_cada_n(enc.cuf, 20)
        context['codigo_control_cortado'] = _cortar_cada_n(enc.codigo_control, 20)

        # Altura dinamica del rollo (20/09/2026, pedido de Carlos):
        # xhtml2pdf/reportlab NO recorta la pagina al contenido solo,
        # necesita un @page size fijo de antemano -- no existe un
        # "height: auto" real para el motor de PDF. Se estima aca en
        # milimetros segun la cantidad de lineas reales (items +
        # descripciones largas que van a envolver a una segunda linea),
        # generoso a proposito para nunca cortar contenido; si sobra
        # espacio en blanco al final es preferible a que se corte algo.
        context['altura_pagina_mm'] = _estimar_altura_termico_mm(enc, detalle)

        # Marca de agua "ANULADA" (20/09/2026, pedido de Carlos), como
        # fondo de pagina (@page background-image) -- ver el docstring
        # de _generar_marca_agua_anulada_data_uri para el porque (un
        # <img> con position:absolute NO se saca del flujo en
        # xhtml2pdf, terminaba empujando el resto del contenido hacia
        # abajo). Se genera del tamaño real de ESTA pagina termica
        # (58mm de ancho, alto dinamico ya calculado arriba) para que
        # quede centrada, a 96dpi.
        if enc.anulado:
            ancho_px = round(58 / 25.4 * 96)
            alto_px = round(context['altura_pagina_mm'] / 25.4 * 96)
            context['marca_agua_anulada_data_uri'] = _generar_marca_agua_anulada_data_uri(
                ancho_px, alto_px, tamano_fuente=60
            )

    if formato == Empresa.CARTA:
        # Tamaño del logo en el encabezado (18/09/2026): xhtml2pdf/
        # reportlab NO respeta max-height/max-width en <img> -- si no
        # se le da un width/height EXPLICITO, cae en el tamaño nativo
        # en pixeles interpretado 1:1 como puntos, lo que en la
        # practica renderizaba el logo real de Carlos a mas de 30cm de
        # alto (bug real, descubierto recien al revisar el PDF
        # generado, no solo el HTML). Se calcula aca el tamaño final en
        # puntos (unidad nativa del motor) que quepa dentro de una caja
        # maxima, preservando la proporcion real del archivo -- no
        # depende de la resolucion/DPI de la imagen que suba cada
        # cliente.
        if logo_valido:
            try:
                from PIL import Image
                with Image.open(empresa.logo.path) as img:
                    ancho_px, alto_px = img.size
                max_ancho_pt, max_alto_pt = 120, 42
                escala = min(max_ancho_pt / ancho_px, max_alto_pt / alto_px, 1)
                context['logo_ancho_pt'] = round(ancho_px * escala, 1)
                context['logo_alto_pt'] = round(alto_px * escala, 1)
            except Exception:
                context['logo_ancho_pt'] = None
                context['logo_alto_pt'] = None

        # Mismo limite real de xhtml2pdf que en el formato termico (no
        # corta a mitad de palabra): el CUF (~60 caracteres) y el CUFD
        # (~55 caracteres, tambien codificado sin espacios) se salian
        # de sus columnas/cajas en carta tambien -- se ve al abrir el
        # PDF real, no en el HTML. Mismo mecanismo (<br> cada N
        # caracteres), valor real intacto.
        context['cuf_cortado'] = _cortar_cada_n(enc.cuf, 30)
        context['cufd_cortado'] = _cortar_cada_n(enc.cufd, 22)

        # Marca de agua "ANULADA" (20/09/2026): tamaño real de la
        # pagina carta (letter) a 96dpi -- ver el docstring de
        # _generar_marca_agua_anulada_data_uri.
        if enc.anulado:
            context['marca_agua_anulada_data_uri'] = _generar_marca_agua_anulada_data_uri()

    return template_name, context


def _contexto_ncd_documento(ncd):
    """
    Arma el contexto para representar graficamente una Nota de
    Credito-Debito (agregado 19/09/2026, a partir de un modelo de
    referencia oficial del SIN que paso Carlos). Estructura DISTINTA a
    la de una factura -- no es "una factura comprimida": muestra los
    datos de la factura ORIGINAL, los datos de la devolucion/rescision,
    y el monto efectivo debito-credito.

    Devolucion TOTAL (unica version soportada, decision del 26/08/2026,
    ver NotaCreditoDebito.__doc__): "detalle_devuelto" hoy es
    exactamente el mismo detalle que "detalle_original" -- se
    consultan por separado (dos variables, misma fuente) a proposito,
    para que si en el futuro se agrega devolucion PARCIAL, solo haya
    que cambiar de donde sale detalle_devuelto sin tocar el resto de
    la plantilla.
    """
    factura_original = ncd.factura_original
    detalle_original = FacturaDet.objects.filter(factura=factura_original).select_related('producto')
    detalle_devuelto = detalle_original

    empresa = Empresa.objects.first()
    logo_valido = bool(empresa and empresa.logo and os.path.exists(empresa.logo.path))

    formato = empresa.formato_factura if empresa else Empresa.TERMICO
    template_name = _PLANTILLA_NCD_POR_FORMATO.get(formato, _PLANTILLA_NCD_POR_FORMATO[Empresa.TERMICO])

    sucursal = Sucursal.objects.filter(empresa=empresa).order_by('id').first() if empresa else None
    punto_venta = PuntoVenta.objects.filter(sucursal=sucursal).order_by('id').first() if sucursal else None

    context = {
        'ncd': ncd,
        'enc': factura_original,
        'detalle_original': detalle_original,
        'detalle_devuelto': detalle_devuelto,
        'empresa': empresa,
        'logo_valido': logo_valido,
        'sucursal': sucursal,
        'punto_venta': punto_venta,
        'importe_en_letras': _importe_en_letras(ncd.monto_total_devuelto),
    }

    # QR de verificacion fiscal -- DESACTIVADO A PROPOSITO (20/09/2026,
    # pedido de Carlos). El parametro "t" para una NCD nunca se
    # confirmo con un ejemplo real escaneado (a diferencia del QR de
    # facturas, que si esta confirmado, ver _contexto_factura_documento)
    # -- se prefiere no mostrar nada antes que mostrar un QR con un
    # dato sin confirmar. La caja de "Verificacion del documento" (mas
    # abajo en la plantilla) ocupa el lugar del QR mientras tanto. Para
    # reactivarlo cuando se tenga la info oficial del SIN, descomentar:
    #
    # if empresa and empresa.nit and ncd.cuf:
    #     url_verificacion = (
    #         f"https://siat.impuestos.gob.bo/consulta/QR"
    #         f"?nit={empresa.nit}&cuf={ncd.cuf}&numero={ncd.id}&t=1"
    #     )
    #     context['qr_verificacion_data_uri'] = _generar_qr_data_uri(url_verificacion)

    if formato == Empresa.TERMICO:
        context['cuf_cortado'] = _cortar_cada_n(ncd.cuf, 20)
        context['codigo_control_cortado'] = _cortar_cada_n(ncd.codigo_control, 20)
        context['cuf_original_cortado'] = _cortar_cada_n(factura_original.cuf, 20)
        context['altura_pagina_mm'] = _estimar_altura_termico_ncd_mm(ncd, detalle_original, detalle_devuelto)

    if formato == Empresa.CARTA:
        if logo_valido:
            try:
                from PIL import Image
                with Image.open(empresa.logo.path) as img:
                    ancho_px, alto_px = img.size
                max_ancho_pt, max_alto_pt = 120, 42
                escala = min(max_ancho_pt / ancho_px, max_alto_pt / alto_px, 1)
                context['logo_ancho_pt'] = round(ancho_px * escala, 1)
                context['logo_alto_pt'] = round(alto_px * escala, 1)
            except Exception:
                context['logo_ancho_pt'] = None
                context['logo_alto_pt'] = None

        context['cuf_cortado'] = _cortar_cada_n(ncd.cuf, 30)
        context['cufd_cortado'] = _cortar_cada_n(ncd.cufd, 22)
        # N° Autorizacion/CUF de la factura ORIGINAL (distinto del CUF
        # de la propia NCD, de arriba) -- va en la columna angosta de
        # datos del cliente (5.9cm), no en el encabezado ancho, asi que
        # necesita un corte mas apretado que el resto.
        context['cuf_original_cortado'] = _cortar_cada_n(factura_original.cuf, 22)

    return template_name, context


def _estimar_altura_termico_ncd_mm(ncd, detalle_original, detalle_devuelto):
    """
    Misma logica que _estimar_altura_termico_mm (factura), pero para
    NCD -- tiene DOS tablas en vez de una, asi que la base fija es
    mayor (dos titulos de seccion + dos resumenes de totales en vez de
    uno).
    """
    ANCHO_DESCRIPCION_CARACTERES = 28
    altura_mm = 110  # encabezado + titulo + datos del documento/cliente/factura original
    for det in detalle_original:
        lineas_descripcion = max(1, -(-len(det.producto.descripcion or '') // ANCHO_DESCRIPCION_CARACTERES))
        altura_mm += 5 * lineas_descripcion + 5
    altura_mm += 15  # "MONTO TOTAL ORIGINAL Bs"
    for det in detalle_devuelto:
        lineas_descripcion = max(1, -(-len(det.producto.descripcion or '') // ANCHO_DESCRIPCION_CARACTERES))
        altura_mm += 5 * lineas_descripcion + 5
    altura_mm += 20  # "MONTO TOTAL DEVUELTO Bs" + "MONTO EFECTIVO DEBITO-CREDITO Bs"
    altura_mm += 15  # "Son: ..."
    altura_mm += 35  # leyendas fiscales + texto de verificacion (sin QR, ver comentario en _contexto_ncd_documento)
    return altura_mm


def _estimar_altura_termico_mm(enc, detalle):
    """
    Estimacion (no exacta) de la altura de pagina necesaria para el
    ticket termico de 58mm, en milimetros -- ver comentario en
    _contexto_factura_documento sobre por que hace falta esto (xhtml2pdf
    no tiene "altura automatica" real). Generosa a proposito.
    """
    ANCHO_DESCRIPCION_CARACTERES = 28  # aprox. lo que entra en una linea a 58mm
    altura_mm = 95  # encabezado + titulo + datos fiscales + datos del cliente
    for det in detalle:
        lineas_descripcion = max(1, -(-len(det.producto.descripcion or '') // ANCHO_DESCRIPCION_CARACTERES))
        altura_mm += 5 * lineas_descripcion  # linea(s) de codigo+descripcion
        altura_mm += 5  # linea de cantidad x precio - descuento ... subtotal
    altura_mm += 45  # totales + "Son: ..."
    altura_mm += 30  # leyendas fiscales + texto de verificacion
    altura_mm += 45  # QR + margen alrededor
    return altura_mm


def _cortar_cada_n(texto, n):
    """<br> cada N caracteres -- ver comentario en _contexto_factura_documento."""
    if not texto:
        return texto
    return '<br>'.join(texto[i:i + n] for i in range(0, len(texto), n))


def _generar_marca_agua_anulada_data_uri(ancho_px=816, alto_px=1056, tamano_fuente=150):
    """
    Imagen PNG del tamaño de la PAGINA (por defecto, proporcion carta
    a 96dpi) con el texto "ANULADA" en diagonal, semi-transparente,
    centrada -- para usar como fondo de pagina (@page background-image,
    ver _contexto_factura_documento) en facturas anuladas (20/09/2026,
    pedido de Carlos).

    CORREGIDO 20/09/2026: la primera version devolvia un <img> normal
    posicionado con CSS position:absolute -- resulto que xhtml2pdf NO
    saca ese elemento del flujo del documento (a diferencia de lo que
    hace un navegador real), asi que en vez de superponerse quedaba
    empujando el resto del contenido hacia abajo (bug real, se veia al
    abrir el PDF, no en el HTML). `@page { background-image: ... }` SI
    funciona como fondo real, sin afectar el flujo, Y se repite solo
    en cada pagina -- resuelve de paso la limitacion ya documentada de
    que la marca solo aparecia en la primera hoja de una factura de
    varias paginas. Se genera la imagen del tamaño de la pagina (no
    cuadrada) para que el texto quede centrado en la hoja real, sea
    cual sea la proporcion con que xhtml2pdf term  ine posicionando el
    fondo.

    Se genera como IMAGEN, no con CSS -- xhtml2pdf no soporta
    transform/rotate en CSS (limitacion real ya confirmada con la
    marca de agua "SIN VALOR LEGAL" del 18-19/09, que por eso se hizo
    horizontal); PIL si puede rotar texto libremente. Usa
    ImageFont.load_default(size=...) (Pillow >=10.1, ya cumplido por
    este proyecto) en vez de una fuente .ttf del sistema operativo --
    una ruta tipo "arialbd.ttf" solo existe en Windows, y el
    despliegue real es en Linux (Hetzner).
    """
    from PIL import Image, ImageDraw, ImageFont
    import base64

    lado = max(ancho_px, alto_px) * 2  # de sobra para que rotar no recorte el texto
    capa_texto = Image.new('RGBA', (lado, lado), (255, 255, 255, 0))
    draw = ImageDraw.Draw(capa_texto)
    texto = "ANULADA"
    fuente = ImageFont.load_default(size=tamano_fuente)
    bbox = draw.textbbox((0, 0), texto, font=fuente)
    ancho_texto, alto_texto = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((lado - ancho_texto) / 2, (lado - alto_texto) / 2),
        texto, font=fuente, fill=(130, 130, 130, 140)
    )
    rotada = capa_texto.rotate(35, expand=False)

    # Recortar del centro de la capa rotada al tamaño final de pagina,
    # para que el texto quede centrado tanto horizontal como
    # verticalmente en la imagen que se usa de fondo.
    izq = (lado - ancho_px) // 2
    arriba = (lado - alto_px) // 2
    pagina = rotada.crop((izq, arriba, izq + ancho_px, arriba + alto_px))

    buffer = BytesIO()
    pagina.save(buffer, format='PNG')
    b64 = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f"data:image/png;base64,{b64}"


def _generar_qr_data_uri(url):
    """
    Genera el QR de verificacion (URL del portal del SIN, ver comentario
    en _contexto_factura_documento) como imagen PNG embebida directo en
    el HTML (data URI) -- asi no hace falta guardar un archivo temporal
    por factura ni exponer una vista/URL publica nueva solo para servir
    la imagen. xhtml2pdf soporta 'data:' en <img src>.
    """
    import base64
    import qrcode

    img = qrcode.make(url, box_size=6, border=1)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    b64 = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f"data:image/png;base64,{b64}"


_UNIDADES = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve',
             'diez', 'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete',
             'dieciocho', 'diecinueve', 'veinte']
_DECENAS = ['', '', 'veinte', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa']
_CENTENAS = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos',
             'seiscientos', 'setecientos', 'ochocientos', 'novecientos']
_VEINTIS = ['veinte', 'veintiuno', 'veintidós', 'veintitrés', 'veinticuatro', 'veinticinco',
            'veintiséis', 'veintisiete', 'veintiocho', 'veintinueve']


def _grupo_en_letras(n):
    """Convierte un numero de 0 a 999 a letras (sin 'mil'/'millones')."""
    if n == 0:
        return ''
    if n == 100:
        return 'cien'
    texto = ''
    if n >= 100:
        texto += _CENTENAS[n // 100]
        n %= 100
        if n:
            texto += ' '
    if 21 <= n <= 29:
        # "veintiuno".."veintinueve" van juntas (no "veinte y uno") --
        # forma moderna preferida en español; el resto de las decenas
        # (30+) si usan "y" separado ("treinta y uno").
        texto += _VEINTIS[n - 20]
        n = 0
    elif n >= 30:
        texto += _DECENAS[n // 10]
        n %= 10
        if n:
            texto += ' y ' + _UNIDADES[n]
    elif n > 0:
        texto += _UNIDADES[n]
    return texto


def _numero_en_letras(n):
    """Convierte un entero (0 a 999.999.999) a letras, en español."""
    n = int(n)
    if n == 0:
        return 'cero'
    partes = []
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    if millones:
        partes.append(('un millón' if millones == 1 else _grupo_en_letras(millones) + ' millones'))
    if miles:
        partes.append(('mil' if miles == 1 else _grupo_en_letras(miles) + ' mil'))
    if unidades:
        partes.append(_grupo_en_letras(unidades))
    return ' '.join(partes)


def _importe_en_letras(monto):
    """
    Convierte un monto (Bs) a su representacion en letras, formato
    exigido por el SIN en la representacion grafica ("Son: Trescientos
    nueve 51/100 Bolivianos") -- agregado 18/09/2026 a partir del
    modelo de referencia oficial que paso Carlos; no existia ningun
    mecanismo de conversion previo en el sistema.
    """
    monto = round(float(monto or 0), 2)
    entero = int(monto)
    centavos = round((monto - entero) * 100)
    texto = _numero_en_letras(entero).capitalize()
    return f"{texto} {centavos:02d}/100 Bolivianos"


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
@requiere_alcance('fac.FacturaEnc', ('sucursal_id',), 'id')
def imprimir_factura_recibo(request, id):
    enc = get_object_or_404(FacturaEnc, id=id)
    template_name, context, documento = _contexto_documento(enc)
    context['request'] = request
    return render(request, template_name, context)


def generar_pdf_factura_bytes(enc):
    """
    Genera el PDF vigente para esta factura -- la FACTURA original, o
    la NOTA DE CREDITO-DEBITO que la corrige si tiene una vigente
    (agregado 19/09/2026, ver _contexto_documento), en el formato que
    la Empresa tenga elegido (Carta o Termico). Devuelve los bytes del
    PDF. Usado tanto por la descarga manual (factura_descargar_pdf)
    como por el envio de correo (Fase 1, 16/09/2026) -- una sola
    fuente para no duplicar el render, y para que ambos caminos queden
    siempre en el mismo formato/documento que "Ver en Pantalla".
    """
    template_name, context, documento = _contexto_documento(enc)
    html = render_to_string(template_name, context)
    buffer = BytesIO()
    resultado = pisa.CreatePDF(html, dest=buffer)
    if resultado.err:
        return None
    return buffer.getvalue()


def nombre_archivo_documento(enc):
    """
    Nombre de archivo coherente con lo que generar_pdf_factura_bytes(enc)
    en verdad produce -- "factura_123.pdf" si no tiene NCD vigente,
    "nota_credito_debito_45.pdf" si la tiene (agregado 19/09/2026).
    Usado por la descarga manual y por el adjunto del correo, para que
    el nombre del archivo nunca contradiga su contenido.
    """
    ncd = _ncd_vigente(enc)
    if ncd:
        return f"nota_credito_debito_{ncd.id}.pdf"
    return f"factura_{enc.id}.pdf"


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
@requiere_alcance('fac.FacturaEnc', ('sucursal_id',), 'id')
def factura_descargar_pdf(request, id):
    enc = get_object_or_404(FacturaEnc, id=id)
    pdf_bytes = generar_pdf_factura_bytes(enc)
    if pdf_bytes is None:
        return HttpResponse(
            "Ocurrió un error al generar el PDF. Contacte al administrador.",
            status=500
        )
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo_documento(enc)}"'
    return response


def _contexto_reporte_facturas(f1, f2, request=None):
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    # estado=True excluye las facturas eliminadas (soft-delete via
    # eliminar_factura) -- no deben aparecer en ningun reporte.
    enc = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, estado=True
    ).order_by('id')
    # Alcance por sucursal (24/09/2026): el del usuario + ?sucursal=N.
    if request is not None:
        from bases.alcance import filtrar_por_sucursal
        enc = filtrar_por_sucursal(enc, request)

    empresa = Empresa.objects.first()

    return {
        'f1': f1_parsed,
        'f2': f2_parsed,
        'enc': enc,
        'empresa': empresa,
        'fecha_emision': timezone.localtime(timezone.now()),
        **datos_logo_header(empresa),
    }


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_list(request,f1,f2):
    template_name="fac/facturas_print_all.html"

    context = _contexto_reporte_facturas(f1, f2, request)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/facturas/imprimir-todas-pdf/{f1}/{f2}" + (f"?sucursal={request.GET['sucursal']}" if request.GET.get('sucursal', '').isdigit() else "")

    return render(request,template_name,context)


@login_required(login_url='/login/')
@permission_required('fac.view_facturaenc', login_url='bases:sin_privilegios')
def imprimir_factura_list_pdf(request, f1, f2):
    template_name = "fac/facturas_print_all.html"

    context = _contexto_reporte_facturas(f1, f2, request)
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
    context = _contexto_reporte_facturas(f1, f2, request)
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


def _contexto_reporte_cierre_ventas(f1, f2, request=None):
    f1_parsed = parse_date(f1)
    f2_parsed = parse_date(f2)
    f2_con_margen = f2_parsed + timedelta(days=1)

    # estado=True excluye las facturas eliminadas (soft-delete).
    facturas = FacturaEnc.objects.filter(
        fecha__gte=f1_parsed, fecha__lt=f2_con_margen, estado=True
    )
    if request is not None:
        from bases.alcance import filtrar_por_sucursal
        facturas = filtrar_por_sucursal(facturas, request)

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
    # Cierre por sucursal (25/09/2026): si el reporte esta acotado a UNA
    # sucursal (alcance del usuario o selector), se muestran los cierres
    # de esa sucursal (mas los globales). Con varias, se muestra el
    # primer cierre que exista para cada fecha (comportamiento anterior).
    cierres_qs = CierreDia.objects.filter(fecha__gte=f1_parsed, fecha__lte=f2_parsed)
    if request is not None:
        from bases.alcance import sucursales_visibles_ids, sucursal_elegida
        _vis = sucursales_visibles_ids(request.user)
        _sel = sucursal_elegida(request)
        _ids = ([_sel] if (_vis is None or _sel in _vis) else []) if _sel else _vis
        if _ids is not None and len(_ids) == 1:
            cierres_qs = cierres_qs.filter(Q(sucursal_id=_ids[0]) | Q(sucursal__isnull=True))
    cierres = {}
    for c in cierres_qs.order_by('-sucursal_id'):
        cierres.setdefault(c.fecha, c)

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
        **datos_logo_header(empresa),
    }


@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def reporte_cierre_ventas(request, f1, f2):
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2, request)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-ventas/pdf/{f1}/{f2}"

    return render(request, template_name, context)


@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def reporte_cierre_ventas_pdf(request, f1, f2):
    template_name = "fac/cierre_ventas_reporte.html"

    context = _contexto_reporte_cierre_ventas(f1, f2, request)
    context['request'] = request
    context['es_pdf'] = True

    html = render_to_string(template_name, context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="cierre_ventas_{f1}_a_{f2}.pdf"'
    resultado = pisa.CreatePDF(html, dest=response)
    if resultado.err:
        return HttpResponse("Ocurrió un error al generar el PDF.", status=500)
    return response

def _contexto_cierre_caja(f1, f2, request=None):
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
    if request is not None:
        from bases.alcance import filtrar_por_sucursal
        facturas_activas = filtrar_por_sucursal(facturas_activas, request)

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
        **datos_logo_header(empresa),
    }

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_resumen(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2, request)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-caja/resumen/pdf/{f1}/{f2}/"
    return render(request, 'fac/cierre_caja_resumen.html', context)

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_resumen_pdf(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2, request)
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
    context = _contexto_cierre_caja(f1, f2, request)
    context['request'] = request
    context['es_pdf'] = False
    context['url_descargar_pdf'] = f"/fac/reportes/cierre-caja/detallado/pdf/{f1}/{f2}/"
    return render(request, 'fac/cierre_caja_detallado.html', context)

@login_required(login_url='/login/')
@permission_required('fac.ver_reportes_financieros', login_url='bases:sin_privilegios')
def cierre_caja_detallado_pdf(request, f1, f2):
    context = _contexto_cierre_caja(f1, f2, request)
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
    from bases.alcance import filtrar_por_sucursal
    clientes = filtrar_por_sucursal(
        Cliente.objects.filter(estado=True), request, usar_filtro_pantalla=False
    ).order_by('apellidos', 'nombres')
    return render(request, 'fac/kardex_cliente_selector.html', {'clientes': clientes})


def _contexto_kardex_cliente(cliente_id, f1=None, f2=None, request=None):
    clientes_qs = Cliente.objects.all()
    if request is not None:
        from bases.alcance import filtrar_por_sucursal
        clientes_qs = filtrar_por_sucursal(clientes_qs, request, usar_filtro_pantalla=False)
    cliente = get_object_or_404(clientes_qs, pk=cliente_id)

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
        **datos_logo_header(empresa),
    }



@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def kardex_cliente(request, cliente_id):
    f1 = parse_date(request.GET.get('f1')) if request.GET.get('f1') else None
    f2 = parse_date(request.GET.get('f2')) if request.GET.get('f2') else None

    context = _contexto_kardex_cliente(cliente_id, f1, f2, request)
    context['request'] = request
    context['es_pdf'] = False
    return render(request, 'fac/kardex_cliente.html', context)


@login_required(login_url='/login/')
@permission_required('fac.ver_creditos', login_url='bases:sin_privilegios')
def kardex_cliente_pdf(request, cliente_id):
    f1 = parse_date(request.GET.get('f1')) if request.GET.get('f1') else None
    f2 = parse_date(request.GET.get('f2')) if request.GET.get('f2') else None

    context = _contexto_kardex_cliente(cliente_id, f1, f2, request)
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