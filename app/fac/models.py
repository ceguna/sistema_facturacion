from django.db import models
from django.contrib.auth.models import User

#Para los signals
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

from bases.models import ClaseModelo,ClaseModelo2
from inv.models import Producto

class Cliente(ClaseModelo):
    NAT='Natural'
    JUR='Jurídica'
    TIPO_CLIENTE = [
        (NAT,'Natural'),
        (JUR,'Jurídica')
    ]
    nombres = models.CharField(
        max_length=100
    )
    apellidos = models.CharField(
        max_length=100
    )
    celular = models.CharField(
        max_length=20,
        null=True,
        blank=True
    )
    tipo=models.CharField(
        max_length=10,
        choices=TIPO_CLIENTE,
        default=NAT
    )
    ci = models.CharField(
        max_length=20,
        null=True,
        unique=True
    )
    nit = models.CharField(
        max_length=30,
        null=True,
        unique=True
    )
    razon = models.CharField(
        max_length=100,
        null=True,
        unique=True
    )
    email = models.CharField(
        max_length=250,
        null=True, 
        blank=True
    )

    def __str__(self):
        return '{} {}'.format(self.apellidos,self.nombres)

    def save(self, *args, **kwargs):
        self.nombres = self.nombres.upper()
        self.apellidos = self.apellidos.upper()
        self.razon = self.razon.upper()
        super(Cliente, self).save( *args, **kwargs)

    class Meta:
        verbose_name_plural = "Clientes"

class FacturaEnc(ClaseModelo2):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    # Campos para anulacion (no se borra el registro, solo se marca)
    anulado = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Placeholder para Fase 3 (integracion SIN). Mientras sea null, la
    # factura no ha sido reportada al SIN y puede eliminarse fisicamente.
    cuf = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return '{}'.format(self.id)

    def save(self, *args, **kwargs):
        self.total = self.sub_total - self.descuento
        super(FacturaEnc, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Encabezado Facturas"
        verbose_name="Encabezado Factura"
        permissions = [
            ('sup_caja_facturaenc','Permisos de Supervisor de Caja Encabezado'),
            ('anular_facturaenc','Permiso para Anular Facturas')
        ]
    

class FacturaDet(ClaseModelo2):
    factura = models.ForeignKey(FacturaEnc,on_delete=models.CASCADE)
    producto=models.ForeignKey(Producto,on_delete=models.CASCADE)
    cantidad=models.BigIntegerField(default=0)
    precio=models.FloatField(default=0)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    def __str__(self):
        return '{}'.format(self.producto)

    def save(self, *args, **kwargs):
        self.sub_total = float(float(int(self.cantidad)) * float(self.precio))
        self.total = self.sub_total - float(self.descuento)
        super(FacturaDet, self).save(*args, **kwargs)
    
    class Meta:
        verbose_name_plural = "Detalles Facturas"
        verbose_name="Detalle Factura"
        permissions = [
            ('sup_caja_facturadet','Permisos de Supervisor de Caja Detalle')
        ]


@receiver(post_save, sender=FacturaDet) #Este es el modelo que se va estar vigilando.
def detalle_fac_guardar(sender,instance,**kwargs):
    factura_id = instance.factura.id
    producto_id = instance.producto.id

    enc = FacturaEnc.objects.filter(pk=factura_id).first()
    if enc:
        sub_total = FacturaDet.objects.filter(factura=factura_id) \
            .aggregate(sub_total=Sum('sub_total')).get('sub_total',0.00)
        
        descuento = FacturaDet.objects.filter(factura=factura_id) \
            .aggregate(descuento=Sum('descuento')).get('descuento',0.00)

        enc.sub_total = sub_total or 0.00
        enc.descuento = descuento or 0.00
        enc.save()

    #Se dismimuye la cantidad facturada
    prod=Producto.objects.filter(pk=producto_id).first()
    if prod:
        cantidad = int(prod.existencia) - int(instance.cantidad)
        prod.existencia = cantidad
        prod.save()

@receiver(post_delete, sender=FacturaDet)
def detalle_factura_borrar(sender,instance, **kwargs):
    id_producto = instance.producto.id
    id_factura = instance.factura.id

    enc = FacturaEnc.objects.filter(pk=id_factura).first()
    ya_estaba_anulada = enc.anulado if enc else False

    if enc:
        sub_total = FacturaDet.objects.filter(factura=id_factura).aggregate(Sum('sub_total'))
        descuento = FacturaDet.objects.filter(factura=id_factura).aggregate(Sum('descuento'))
        enc.sub_total = sub_total['sub_total__sum'] or 0.00
        enc.descuento = descuento['descuento__sum'] or 0.00
        enc.save()

    # Si la factura ya estaba anulada, el stock de este producto ya se
    # devolvio en ese momento (ver anular_factura). No volver a sumarlo
    # aqui, o quedaria duplicado.
    if not ya_estaba_anulada:
        prod=Producto.objects.filter(pk=id_producto).first()
        if prod:
            cantidad = int(prod.existencia) + int(instance.cantidad)
            prod.existencia = cantidad
            prod.save()