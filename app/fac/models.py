from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

#Para los signals
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum
from django.db.models.functions import TruncDate

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
    # --- Estados posibles ante el SIN (no confundir con "anulado", que
    # es una intencion/estado LOCAL; estado_sin refleja lo que el SIN
    # realmente confirmo) ---
    SIN_NO_ENVIADA = 'no_enviada'
    SIN_PENDIENTE = 'pendiente'
    SIN_VALIDADA = 'validada'
    SIN_OBSERVADA = 'observada'
    SIN_ANULADA = 'anulada'
    SIN_REVERTIDA = 'revertida'
    ESTADO_SIN_CHOICES = [
        (SIN_NO_ENVIADA, 'No enviada al SIN'),
        (SIN_PENDIENTE, 'Pendiente (paquete en revision)'),
        (SIN_VALIDADA, 'Validada por el SIN'),
        (SIN_OBSERVADA, 'Observada por el SIN'),
        (SIN_ANULADA, 'Anulada ante el SIN'),
        (SIN_REVERTIDA, 'Anulacion revertida ante el SIN'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    # Campos para anulacion LOCAL (no se borra el registro, solo se marca)
    anulado = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # --- Integracion SIN (Fase 3) ---
    # Mientras cuf sea null, la factura no ha sido reportada al SIN y
    # puede eliminarse fisicamente.
    cuf = models.CharField(max_length=100, null=True, blank=True)
    cufd = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="CUFD vigente usado al momento de la emision. Se guarda para auditoria."
    )
    estado_sin = models.CharField(
        max_length=15, choices=ESTADO_SIN_CHOICES, default=SIN_NO_ENVIADA,
        help_text="Estado real confirmado por el SIN (distinto de 'anulado', que es la intencion local)."
    )
    codigo_recepcion_sin = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="codigoRecepcion devuelto por el SIN al recibir la factura o el paquete."
    )
    fecha_hora_envio_sin = models.DateTimeField(null=True, blank=True)
    mensaje_sin = models.TextField(
        null=True, blank=True,
        help_text="mensajesList devuelto por el SIN (errores/advertencias), si los hubo."
    )

    # --- Anulacion ante el SIN (motivo va por codigo de catalogo, NO texto libre) ---
    codigo_motivo_anulacion_sin = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Codigo del catalogo MOTIVOS_ANULACION (app catalogos) enviado al SIN."
    )
    fecha_anulacion_sin = models.DateTimeField(null=True, blank=True)

    # --- Reversion de la anulacion (Etapa VIII) ---
    fecha_reversion_sin = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return '{}'.format(self.id)

    def save(self, *args, **kwargs):
        self.total = self.sub_total - self.descuento
        super(FacturaEnc, self).save(*args, **kwargs)

    @property
    def reportada_ante_sin(self):
        """
        True si el SIN ALGUNA VEZ acepto formalmente esta factura -- ya
        sea que siga vigente (validada/pendiente) o que haya sido
        anulada/revertida despues. En CUALQUIERA de estos casos el
        registro tiene existencia formal ante el SIN y no se puede
        editar ni eliminar fisicamente nunca mas -- solo Anular o
        Revertir una anulacion, segun corresponda.
        """
        return self.estado_sin in (
            self.SIN_VALIDADA, self.SIN_PENDIENTE,
            self.SIN_ANULADA, self.SIN_REVERTIDA,
        )

    @property
    def puede_editarse(self):
        """
        True si todavia se pueden agregar/quitar productos del detalle:
        no esta anulada, y el SIN todavia no la acepto formalmente en
        ningun momento de su historia (nunca se envio, o se envio y
        fue observada -- en ese caso se corrige y reintenta).
        """
        return not self.anulado and not self.reportada_ante_sin

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


class CierreDia(ClaseModelo2):
    """
    Registra el cierre formal de un dia de operaciones. Mientras exista
    un dia ANTERIOR a hoy con facturas y sin un CierreDia asociado, el
    sistema bloquea la creacion de facturas nuevas (ver
    dias_pendientes_de_cierre() mas abajo) -- es la red de seguridad
    para que ninguna factura "no_enviada" u "observada" quede olvidada
    sin que alguien la resuelva.
    """
    ESTADO_CERRADO = 'cerrado'
    ESTADO_CERRADO_CON_PENDIENTES = 'cerrado_con_pendientes'
    ESTADO_CHOICES = [
        (ESTADO_CERRADO, 'Cerrado'),
        (ESTADO_CERRADO_CON_PENDIENTES, 'Cerrado con pendientes (forzado por supervisor)'),
    ]

    fecha = models.DateField(unique=True)
    estado = models.CharField(max_length=25, choices=ESTADO_CHOICES, default=ESTADO_CERRADO)
    fecha_hora_cierre = models.DateTimeField(auto_now_add=True)
    usuario_cierre = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    total_facturado = models.FloatField(default=0)
    cantidad_facturas = models.IntegerField(default=0)
    facturas_pendientes_sin = models.IntegerField(
        default=0,
        help_text="Cantidad de facturas que quedaron sin resolver ante el SIN al momento del cierre "
                   "(solo > 0 si se forzo el cierre con pendientes)."
    )
    observaciones = models.TextField(
        null=True, blank=True,
        help_text="Obligatorio si el cierre se forzo con facturas pendientes."
    )

    def __str__(self):
        return f"Cierre {self.fecha}"

    class Meta:
        verbose_name = "Cierre de Día"
        verbose_name_plural = "Cierres de Día"
        permissions = [
            ('gestionar_cierre_dia', 'Permiso para gestionar el Cierre de Día'),
        ]


def dias_pendientes_de_cierre():
    """
    Devuelve, en orden cronologico, las fechas ANTERIORES a hoy que
    tienen al menos una factura pero todavia no tienen un CierreDia
    registrado. Mientras esta lista no este vacia, el sistema bloquea
    la creacion de facturas nuevas.
    """
    hoy = timezone.localdate()
    fechas_con_facturas = (
        FacturaEnc.objects.filter(fecha__date__lt=hoy)
        .annotate(dia=TruncDate('fecha'))
        .values_list('dia', flat=True)
        .distinct()
    )
    fechas_cerradas = set(CierreDia.objects.values_list('fecha', flat=True))
    return sorted(d for d in fechas_con_facturas if d not in fechas_cerradas)


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