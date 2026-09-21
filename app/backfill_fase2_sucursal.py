"""
Script ad-hoc, una sola vez: backfill de datos existentes para la
arquitectura multi-sucursal (Fase 2, 20/09/2026). NO es parte de la
app (mismo criterio que revertir_pendientes.py / verificar_571_572.py).

Que hace:
  1. Crea (si falta) un StockSucursal por cada Producto en la sucursal
     Casa Matriz (codigo_sucursal=0), con cantidad = Producto.existencia
     actual. Esto es critico: ajustar_stock_sucursal() recalcula
     Producto.existencia como el AGREGADO (suma) de StockSucursal en la
     siguiente escritura de stock -- sin este seed, cualquier producto
     sin fila StockSucursal se iria a 0 en la proxima compra/ajuste/venta.
  2. Asigna sucursal=Casa Matriz a todo FacturaEnc, ComprasEnc,
     AjusteInventarioEnc y Cliente que todavia tenga sucursal=None (todo
     lo creado antes de este cambio).

Es idempotente: correrlo dos veces no duplica ni pisa nada (usa
get_or_create para StockSucursal, y solo toca filas con sucursal=None
para los demas modelos).

Uso:
    cd app
    python manage.py shell < backfill_fase2_sucursal.py
"""
from fe.models import Sucursal
from inv.models import Producto, StockSucursal
from fac.models import Cliente, FacturaEnc
from cmp.models import ComprasEnc
from inv.models import AjusteInventarioEnc

casa_matriz = Sucursal.objects.filter(codigo_sucursal=0).first()
if not casa_matriz:
    print("ERROR: no existe ninguna Sucursal con codigo_sucursal=0 (Casa Matriz). Nada que hacer.")
else:
    print(f"Casa Matriz resuelta: {casa_matriz}")

    # --- 1. Seed de StockSucursal desde Producto.existencia ---
    creados, ya_existian = 0, 0
    for prod in Producto.objects.all():
        _, created = StockSucursal.objects.get_or_create(
            producto=prod, sucursal=casa_matriz,
            defaults={'cantidad': prod.existencia, 'uc': prod.uc}
        )
        if created:
            creados += 1
        else:
            ya_existian += 1
    print(f"StockSucursal: {creados} creados, {ya_existian} ya existian.")

    # --- 2. Backfill de sucursal=None -> Casa Matriz ---
    n = FacturaEnc.objects.filter(sucursal__isnull=True).update(sucursal=casa_matriz)
    print(f"FacturaEnc actualizadas: {n}")

    n = ComprasEnc.objects.filter(sucursal__isnull=True).update(sucursal=casa_matriz)
    print(f"ComprasEnc actualizadas: {n}")

    n = AjusteInventarioEnc.objects.filter(sucursal__isnull=True).update(sucursal=casa_matriz)
    print(f"AjusteInventarioEnc actualizadas: {n}")

    n = Cliente.objects.filter(sucursal__isnull=True).update(sucursal=casa_matriz)
    print(f"Cliente actualizados: {n}")

    print("Backfill completo.")
