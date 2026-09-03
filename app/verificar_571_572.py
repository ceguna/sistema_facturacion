from fac.models import FacturaEnc, FacturaDet, Pago

for fid in (571, 572):
    print(f"\n{'='*70}\nFACTURA {fid}\n{'='*70}")
    enc = FacturaEnc.objects.filter(pk=fid).first()
    if not enc:
        print("NO EXISTE -- revisar el numero")
        continue

    print("anulado:                    ", enc.anulado)
    print("estado (soft-delete, True=activa/False=eliminada):", enc.estado)
    print("estado_sin:                 ", enc.estado_sin)
    print("reportada_ante_sin:         ", enc.reportada_ante_sin)
    print("puede_editarse:             ", enc.puede_editarse)
    print("forma_pago:                 ", enc.forma_pago)
    print("total:                      ", enc.total)
    print("saldo_pendiente:            ", enc.saldo_pendiente, " (deberia ser 0.0)")
    print("estado_credito:             ", enc.estado_credito)
    print("fecha_vencimiento:          ", enc.fecha_vencimiento)

    print("\n--- Datos de anulacion (solo aplica si es la 571) ---")
    print("fecha_anulacion:            ", enc.fecha_anulacion)
    print("motivo_anulacion:           ", enc.motivo_anulacion)
    print("usuario_anulacion:          ", enc.usuario_anulacion)
    print("codigo_motivo_anulacion_sin:", enc.codigo_motivo_anulacion_sin)
    print("fecha_anulacion_sin:        ", enc.fecha_anulacion_sin)
    print("mensaje_sin:                ", enc.mensaje_sin)

    print("\n--- Pagos asociados (debe dar 0 en las dos) ---")
    pagos = Pago.objects.filter(factura=enc)
    print("cantidad de pagos:", pagos.count())

    print("\n--- Detalle y stock devuelto ---")
    detalles = FacturaDet.objects.filter(factura=enc)
    for d in detalles:
        print(f"  {d.producto.codigo} - {d.producto.descripcion} | cantidad facturada: {d.cantidad} | existencia actual: {d.producto.existencia}")

    print("\n--- Visibilidad en listados ---")
    en_listado_facturas = FacturaEnc.objects.filter(pk=fid, estado=True).exists()
    print("aparece en listado de Facturas (estado=True):", en_listado_facturas)
    en_cartera = FacturaEnc.objects.filter(
        pk=fid, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO, anulado=False, estado=True, saldo_pendiente__gt=0
    ).exists()
    print("aparece en Cartera de Creditos:", en_cartera)