import os


def datos_logo_header(empresa, max_ancho_pt=90, max_alto_pt=32):
    """
    Tamaño de logo listo para el encabezado de un reporte PDF
    (xhtml2pdf) -- mismo calculo que ya usaba fac/reportes.py solo
    para facturas/NCD (agregado 18/09/2026, ver ese archivo para el
    detalle completo del bug real que motivo esto): xhtml2pdf/
    reportlab NO respeta max-height/max-width en <img> -- sin un
    width/height EXPLICITO en puntos, renderiza el logo a su tamaño
    nativo en pixeles. Centralizado aca (20/09/2026, pedido de Carlos)
    para que TODOS los reportes del sistema (no solo factura/NCD)
    puedan mostrar el logo de la empresa sin repetir este calculo.
    """
    logo_valido = bool(empresa and empresa.logo and os.path.exists(empresa.logo.path))
    resultado = {'logo_valido': logo_valido, 'logo_ancho_pt': None, 'logo_alto_pt': None}
    if logo_valido:
        try:
            from PIL import Image
            with Image.open(empresa.logo.path) as img:
                ancho_px, alto_px = img.size
            escala = min(max_ancho_pt / ancho_px, max_alto_pt / alto_px, 1)
            resultado['logo_ancho_pt'] = round(ancho_px * escala, 1)
            resultado['logo_alto_pt'] = round(alto_px * escala, 1)
        except Exception:
            pass
    return resultado
