from django.db import models
from django.contrib.auth.models import User

#Para los signals
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

from bases.models import ClaseModelo
from inv.models import Producto, ajustar_stock_sucursal

class Proveedor(ClaseModelo):
    descripcion=models.CharField(
        max_length=100,
        unique=True
        )
    nit = models.CharField(
        max_length=30,
        unique=True
    )
    direccion=models.CharField(
        max_length=250,
        null=True, blank=True
        )
    contacto=models.CharField(
        max_length=100
    )
    telefono=models.CharField(
        max_length=10,
        null=True, blank=False
    )
    email=models.CharField(
        max_length=250,
        null=True, blank=False
    )

    def __str__(self):
        return '{}'.format(self.descripcion)

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Proveedor, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Proveedores"


class ComprasEnc(ClaseModelo):
    fecha_compra=models.DateField(null=True,blank=True)
    observacion=models.TextField(blank=True,null=True)
    no_factura=models.CharField(max_length=100)
    fecha_factura=models.DateField()
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    proveedor=models.ForeignKey(Proveedor,on_delete=models.CASCADE)
    # sucursal (Fase 2, 20/09/2026): que sucursal recibe este stock --
    # la matriz sigue comprando en general, pero cada sucursal puede
    # registrar sus propias compras locales tambien (pedido explicito
    # de Carlos). Null en datos viejos (migrados a la sucursal por
    # defecto) y en instalaciones todavia sin sucursales.
    sucursal = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, null=True, blank=True
    )
    
    def __str__(self):
        return '{}'.format(self.observacion)

    def save(self, *args, **kwargs):
        self.observacion = self.observacion.upper()
        if self.sub_total == None  or self.descuento == None:
            self.sub_total = 0
            self.descuento = 0
            
        self.total = self.sub_total - self.descuento
        super(ComprasEnc, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Encabezado Compras"
        verbose_name="Encabezado Compra"
        permissions = [
            # Agregado 02/09/2026 al corregir el hallazgo "no existe forma
            # de eliminar una compra completa" -- permiso DEDICADO (no
            # reutiliza change_comprasenc), mismo criterio que se acordo
            # para fac.eliminar_facturaenc: una accion tan sensible
            # (revierte stock de todas las lineas) merece su propio
            # permiso, no quedar agrupada bajo "puede editar".
            ('eliminar_comprasenc', 'Permiso para eliminar una compra completa'),
            # Agregado 07/09/2026: Compras nunca tuvo su propio concepto
            # de "cierre" -- se reusa el mismo CierreDia que ya usa
            # Facturacion (confirmado con Carlos que no existe uno
            # separado). Mismo criterio de permiso dedicado que arriba:
            # editar/crear una compra en un dia ya cerrado es sensible,
            # merece su propio permiso, no colgar de is_superuser ni de
            # gestionar_cierre_dia (que es de Facturacion, otro modulo).
            ('editar_compra_dia_cerrado', 'Permiso para crear o editar una compra en un día ya cerrado'),
            # Agregado 08/09/2026: ventana de tiempo escalonada por rol
            # para eliminar (mismo patron que usan ERP grandes como
            # Sage -- "period locking" con roles escalonados: la
            # mayoria solo puede tocar el dia de hoy, un rol de mas
            # confianza puede retroceder mas, y Administrador
            # (editar_compra_dia_cerrado) no tiene limite). Sin este
            # permiso = solo el mismo dia. Con el = todo el mes en
            # curso.
            ('eliminar_compra_mes_vigente', 'Permiso para eliminar compras de cualquier día del mes en curso (no solo el día de hoy)'),
        ]

class ComprasDet(ClaseModelo):
    compra=models.ForeignKey(ComprasEnc,on_delete=models.CASCADE)
    producto=models.ForeignKey(Producto,on_delete=models.CASCADE)
    cantidad=models.BigIntegerField(default=0)
    precio_prv=models.FloatField(default=0)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)
    costo=models.FloatField(default=0)

    # --- Reversion de linea de compra ("contra compra"), 10/09/2026 ---
    # Quitar un producto de una compra ya NO borra la fila: se crea una
    # linea NUEVA con cantidad negativa (misma mecanica que
    # FacturaDet/borrar_detalle_factura en ventas, para tener un solo
    # criterio en todo el sistema). La linea original queda intacta.
    #
    # 'uc' (heredado de ClaseModelo) guarda al usuario de la sesion;
    # 'usuario_reversion' guarda explicitamente a quien autorizo la
    # reversion -- mismo patron que FacturaDet.usuario_reversion. Queda
    # null en las lineas normales (la inmensa mayoria).
    usuario_reversion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text="Usuario que autorizó esta línea como reversión de otra. "
                   "Vacío si la línea no es una reversión."
    )
    # Foto del costo_actual del producto JUSTO ANTES de que esta linea
    # lo moviera. Permite restaurar el costo exacto al revertir la
    # compra mas reciente, sin recalcular todo el historial. Null en
    # lineas viejas (anteriores a este cambio) y en las reversiones.
    costo_actual_antes = models.FloatField(null=True, blank=True)

    def __str__(self):
        return '{}'.format(self.producto)

    @property
    def descuento_pct(self):
        """
        Porcentaje de descuento de esta linea, derivado de los montos
        guardados (12/09/2026: el campo 'descuento' en la base SIGUE
        siendo un monto en Bs -- no se toco el modelo ni las señales
        que ya dependen de el -- pero el formulario y la tabla de
        detalle ahora trabajan en porcentaje, mas natural para cargar
        una compra). 0 si no hay sub_total (evita division por cero).
        """
        if not self.sub_total:
            return 0
        return round(abs(self.descuento) / abs(self.sub_total) * 100, 2)

    def save(self, *args, **kwargs):
        self.sub_total = float(float(int(self.cantidad)) * float(self.precio_prv))
        self.total = self.sub_total - float(self.descuento)
        super(ComprasDet, self).save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Detalles Compras"
        verbose_name="Detalle Compra"

def recalcular_costo_actual(prod):
    """
    Recalcula `costo_actual` de un producto reproduciendo TODAS sus
    lineas de compra vigentes (ComprasDet de compras con estado=True),
    en orden cronologico (id), aplicando la formula de Promedio
    Ponderado movil linea por linea.

    Se reproduce con una cantidad "solo compras" (no `existencia`, que
    incluye ventas) -- consistente con la regla del negocio: el costo
    solo se mueve con entradas. Las lineas de reversion (cantidad
    negativa, "contra compra") desarman el promedio automaticamente:
    cuando queda stock despues de la reversion, la formula devuelve
    exactamente el promedio previo a la compra revertida.

    Reemplaza (10/09/2026) al calculo incremental anterior, que no
    tenia forma de revertirse al eliminar una compra -- dejaba el
    `costo_actual` "contaminado" con el precio de una compra que ya
    no existia (casos reales: CAL-001, BOR-001, AGE-001).
    """
    lineas = (
        ComprasDet.objects
        .filter(producto=prod, compra__estado=True)
        .order_by('id')
        .values_list('cantidad', 'precio_prv')
    )
    qty = 0
    avg = 0.0
    for cantidad, precio_prv in lineas:
        cantidad = int(cantidad)
        if qty + cantidad > 0:
            avg = (qty * avg + cantidad * float(precio_prv)) / (qty + cantidad)
        qty += cantidad
    prod.costo_actual = round(avg, 4)


def _recalcular_cabecera_compra(id_compra):
    enc = ComprasEnc.objects.filter(pk=id_compra).first()
    if not enc:
        return
    agg = ComprasDet.objects.filter(compra=id_compra).aggregate(
        st=Sum('sub_total'), ds=Sum('descuento')
    )
    enc.sub_total = agg['st'] or 0.00
    enc.descuento = agg['ds'] or 0.00
    enc.save()


@receiver(post_delete, sender=ComprasDet)
def detalle_compra_borrar(sender, instance, **kwargs):
    """
    Solo se dispara ante un DELETE fisico real (admin de Django,
    consola). El flujo normal de "quitar un producto de una compra" ya
    NO borra: crea una linea de reversion con cantidad negativa (ver
    CompraDetDelete en cmp/views.py, mismo criterio que ventas).

    CORREGIDO 20/09/2026 (Fase 2): el ajuste de stock ya no es un
    read-modify-write en Python (`prod.existencia = ...; prod.save()`)
    -- delegado en ajustar_stock_sucursal (atomico, y ahora con
    dimension de sucursal). costo_actual sigue siendo GLOBAL a la
    empresa (no por sucursal, decision de diseño de Fase 2), asi que
    ese calculo sigue igual, leyendo/escribiendo Producto directo.
    """
    _recalcular_cabecera_compra(instance.compra_id)
    prod = Producto.objects.filter(pk=instance.producto_id).first()
    if prod:
        recalcular_costo_actual(prod)
        prod.save(update_fields=['costo_actual'])
        ajustar_stock_sucursal(instance.producto_id, instance.compra.sucursal, -int(instance.cantidad))


@receiver(post_save, sender=ComprasDet)
def detalle_compra_guardar(sender, instance, created, **kwargs):
    # Solo al CREAR la linea. Las lineas de compra no se editan en esta
    # app (la vista solo crea, nunca actualiza) -- correr esto en cada
    # save re-sumaria el stock.
    if not created:
        return

    prod = Producto.objects.filter(pk=instance.producto_id).first()
    if not prod:
        return

    cantidad = int(instance.cantidad)

    if cantidad >= 0:
        # Linea de compra normal: guardar la foto del costo promedio
        # previo (para auditoria) y marcar la fecha de ultima compra.
        if instance.costo_actual_antes is None:
            ComprasDet.objects.filter(pk=instance.pk).update(
                costo_actual_antes=prod.costo_actual
            )
        prod.ultima_compra = instance.compra.fecha_compra
        prod.save(update_fields=['ultima_compra'])

    recalcular_costo_actual(prod)
    prod.save(update_fields=['costo_actual'])
    # CORREGIDO 20/09/2026 (Fase 2): atomico + con dimension de
    # sucursal, ver docstring de detalle_compra_borrar arriba.
    ajustar_stock_sucursal(instance.producto_id, instance.compra.sucursal, cantidad)

    # Mantener los totales de la cabecera en sincronía -- incluye el
    # caso de la "contra compra" (linea negativa), que entra por aca y
    # no por el post_delete.
    _recalcular_cabecera_compra(instance.compra_id)