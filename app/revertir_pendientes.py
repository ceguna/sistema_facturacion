from fac.models import FacturaEnc, FacturaDet
from fe.services import revertir_anulacion_sin, EmisionSinError
import time

ids_pendientes = [608, 624, 626, 628, 631, 656, 669, 679, 682, 689, 690, 694, 700, 704, 736]

revertidas = 0
fallidas = []

for fid in ids_pendientes:
    enc = FacturaEnc.objects.get(pk=fid)
    try:
        revertir_anulacion_sin(enc, codigo_punto_venta=1)
        detalles = FacturaDet.objects.filter(factura=enc)
        for det in detalles:
            prod = det.producto
            prod.existencia = int(prod.existencia) - int(det.cantidad)
            prod.save()
        enc.anulado = False
        enc.save()
        print(f"OK: factura {fid} revertida")
        revertidas += 1
    except EmisionSinError as e:
        print(f"ERROR factura {fid}: {e}")
        fallidas.append(fid)
    time.sleep(3)

print(f"\nRESUMEN: {revertidas} revertidas de {len(ids_pendientes)} pendientes.")
if fallidas:
    print("Siguen pendientes (probaremos de nuevo despues):", fallidas)