from django.db import models

#Para los signals
from django.db.models.signals import post_save, post_delete, pre_delete
from django.core.exceptions import ValidationError
from django.dispatch import receiver
from django.db.models import Sum

from bases.models import ClaseModelo
from inv.models import Producto

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

    def __str__(self):
        return '{}'.format(self.producto)

    def save(self, *args, **kwargs):
        self.sub_total = float(float(int(self.cantidad)) * float(self.precio_prv))
        self.total = self.sub_total - float(self.descuento)
        super(ComprasDet, self).save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Detalles Compras"
        verbose_name="Detalle Compra"

@receiver(pre_delete, sender=ComprasDet)
def detalle_compra_prevenir_vacio(sender, instance, **kwargs):
    """
    Agregado 07/09/2026: impide dejar una compra con CERO lineas de
    detalle -- sin importar por donde se intente borrar la ultima
    linea (esta app tenia el chequeo solo en la vista CompraDetDelete,
    que resulto insuficiente por si sola: un bug de JS en abrir_modal
    hacia que el rechazo del servidor no se viera reflejado bien en
    pantalla, generando confusion sobre si realmente estaba
    funcionando). Puesto aca, a nivel de senial pre_delete, es
    estructuralmente imposible de saltear -- vista, admin de Django,
    consola, o cualquier codigo futuro quedan cubiertos por igual.

    pre_delete corre ANTES del DELETE real en la base -- si esta
    funcion lanza una excepcion, Django aborta la operacion completa
    (esta dentro de una transaccion atomica propia del framework), la
    fila NUNCA llega a borrarse.
    """
    if ComprasDet.objects.filter(compra=instance.compra).count() <= 1:
        raise ValidationError(
            'No se puede eliminar: la compra debe tener al menos un producto en el detalle.'
        )

@receiver(post_delete, sender=ComprasDet)
def detalle_compra_borrar(sender,instance, **kwargs):
    id_producto = instance.producto.id
    id_compra = instance.compra.id

    enc = ComprasEnc.objects.filter(pk=id_compra).first()
    if enc:
        sub_total = ComprasDet.objects.filter(compra=id_compra).aggregate(Sum('sub_total'))
        descuento = ComprasDet.objects.filter(compra=id_compra).aggregate(Sum('descuento'))
        enc.sub_total = sub_total['sub_total__sum'] or 0.00
        enc.descuento = descuento['descuento__sum'] or 0.00
        enc.save()
    
    prod=Producto.objects.filter(pk=id_producto).first()
    if prod:
        cantidad = int(prod.existencia) - int(instance.cantidad)
        prod.existencia = cantidad
        prod.save()

@receiver(post_save, sender=ComprasDet)
def detalle_compra_guardar(sender,instance,**kwargs):
    id_producto = instance.producto.id
    fecha_compra=instance.compra.fecha_compra

    prod=Producto.objects.filter(pk=id_producto).first()
    if prod:
        # Costo Promedio Ponderado (agregado 08/09/2026) -- se
        # recalcula con el stock ANTES de sumar esta compra, para que
        # el costo solo se mueva con entradas (compras), nunca con
        # salidas (ventas). Ver help_text del campo en inv/models.py
        # para la formula y la limitacion conocida (eliminar una
        # compra vieja no revierte el costo hacia atras).
        stock_anterior = int(prod.existencia)
        cantidad_comprada = int(instance.cantidad)
        if stock_anterior + cantidad_comprada > 0:
            prod.costo_promedio = round(
                (stock_anterior * prod.costo_promedio + cantidad_comprada * instance.precio_prv)
                / (stock_anterior + cantidad_comprada),
                4
            )

        prod.existencia = stock_anterior + cantidad_comprada
        prod.ultima_compra=fecha_compra
        prod.save()