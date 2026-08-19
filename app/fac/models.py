import datetime
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

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

    PLAZO_7 = 7
    PLAZO_15 = 15
    PLAZO_30 = 30
    PLAZO_CREDITO_CHOICES = [
        (PLAZO_7, '7 días'),
        (PLAZO_15, '15 días'),
        (PLAZO_30, '30 días'),
    ]

    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    celular = models.CharField(max_length=20, null=True, blank=False)
    tipo=models.CharField(max_length=10, choices=TIPO_CLIENTE, default=NAT)
    ci = models.CharField(max_length=20, null=True, unique=True)
    nit = models.CharField(max_length=30, null=True, blank=True, unique=True)
    razon = models.CharField(max_length=100, null=True, unique=True)
    email = models.CharField(max_length=250, null=True, blank=True)
    descuento_autorizado_pct = models.FloatField(
        default=0,
        help_text="Porcentaje de descuento pre-aprobado para este cliente "
                   "(ej. 10 = 10%). Se aplica automaticamente en cada venta."
    )

    # --- Venta a credito ---
    autorizado_credito = models.BooleanField(
        default=False,
        help_text="Si esta marcado, este cliente puede elegir 'Crédito' "
                   "como forma de pago al facturar."
    )
    plazo_credito_dias = models.PositiveSmallIntegerField(
        choices=PLAZO_CREDITO_CHOICES, null=True, blank=True,
        help_text="Plazo de pago para este cliente. Se aplica automaticamente "
                   "a todas sus ventas a credito (no se elige por venta)."
    )
    limite_credito = models.FloatField(
        default=0,
        help_text="Monto maximo de saldo pendiente permitido para este "
                   "cliente (suma de todas sus facturas a credito sin pagar "
                   "por completo). 0 = sin limite definido (bloquea cualquier "
                   "venta a credito hasta que se cargue un limite real)."
    )

    def __str__(self):
        return '{} {}'.format(self.apellidos,self.nombres)

    def save(self, *args, **kwargs):
        self.nombres = self.nombres.upper()
        self.apellidos = self.apellidos.upper()
        self.razon = self.razon.upper()
        self.nit = self.nit.strip() if self.nit else None
        super(Cliente, self).save( *args, **kwargs)

    @property
    def saldo_credito_pendiente(self):
        """Suma de saldo_pendiente de todas sus facturas a credito activas."""
        facturas = FacturaEnc.objects.filter(
            cliente=self, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO, anulado=False
        )
        return round(sum(f.saldo_pendiente for f in facturas), 2)

    @property
    def tiene_creditos_vencidos(self):
        """
        True si este cliente tiene AL MENOS una factura a credito vencida
        con saldo pendiente > 0. Se usa para bloquear CUALQUIER venta
        nueva a este cliente (ni siquiera al contado), hasta que regularice.
        """
        hoy = timezone.localdate()
        return FacturaEnc.objects.filter(
            cliente=self, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO,
            anulado=False, fecha_vencimiento__lt=hoy, saldo_pendiente__gt=0
        ).exists()

    class Meta:
        verbose_name_plural = "Clientes"

class FacturaEnc(ClaseModelo2):
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

    FORMA_PAGO_EFECTIVO = 'EFECTIVO'
    FORMA_PAGO_TARJETA_DEBITO = 'TARJETA_DEBITO'
    FORMA_PAGO_TARJETA_CREDITO = 'TARJETA_CREDITO'
    FORMA_PAGO_QR = 'QR'
    FORMA_PAGO_CHEQUE = 'CHEQUE'
    FORMA_PAGO_VALES = 'VALES'
    FORMA_PAGO_TRANSFERENCIA = 'TRANSFERENCIA'
    FORMA_PAGO_DEPOSITO = 'DEPOSITO'
    FORMA_PAGO_SWIFT = 'SWIFT'
    FORMA_PAGO_GIFT_CARD = 'GIFT_CARD'
    FORMA_PAGO_BILLETERA_MOVIL = 'BILLETERA_MOVIL'
    FORMA_PAGO_PAGO_ONLINE = 'PAGO_ONLINE'
    FORMA_PAGO_DEBITO_AUTOMATICO = 'DEBITO_AUTOMATICO'
    FORMA_PAGO_CREDITO = 'CREDITO'

    FORMA_PAGO_CHOICES = [
        (FORMA_PAGO_EFECTIVO, 'Efectivo'),
        (FORMA_PAGO_TARJETA_DEBITO, 'Tarjeta de Débito'),
        (FORMA_PAGO_TARJETA_CREDITO, 'Tarjeta de Crédito'),
        (FORMA_PAGO_QR, 'QR'),
        (FORMA_PAGO_CHEQUE, 'Cheque'),
        (FORMA_PAGO_VALES, 'Vales'),
        (FORMA_PAGO_TRANSFERENCIA, 'Transferencia Bancaria'),
        (FORMA_PAGO_DEPOSITO, 'Depósito en Cuenta'),
        (FORMA_PAGO_SWIFT, 'Transferencia Swift'),
        (FORMA_PAGO_GIFT_CARD, 'Gift Card'),
        (FORMA_PAGO_BILLETERA_MOVIL, 'Billetera Móvil'),
        (FORMA_PAGO_PAGO_ONLINE, 'Pago Online'),
        (FORMA_PAGO_DEBITO_AUTOMATICO, 'Débito Automático'),
        (FORMA_PAGO_CREDITO, 'Crédito (venta a plazo)'),
    ]

    # Credito -> codigo 6 "PAGO POSTERIOR" del catalogo SIN: es
    # exactamente el codigo pensado para una venta donde no se cobra
    # nada al momento de emitir la factura.
    FORMA_PAGO_A_CODIGO_SIN = {
        FORMA_PAGO_EFECTIVO: '1',
        FORMA_PAGO_TARJETA_DEBITO: '2',
        FORMA_PAGO_TARJETA_CREDITO: '2',
        FORMA_PAGO_QR: '7',
        FORMA_PAGO_CHEQUE: '3',
        FORMA_PAGO_VALES: '4',
        FORMA_PAGO_TRANSFERENCIA: '7',
        FORMA_PAGO_DEPOSITO: '8',
        FORMA_PAGO_SWIFT: '9',
        FORMA_PAGO_GIFT_CARD: '27',
        FORMA_PAGO_BILLETERA_MOVIL: '32',
        FORMA_PAGO_PAGO_ONLINE: '33',
        FORMA_PAGO_DEBITO_AUTOMATICO: '295',
        FORMA_PAGO_CREDITO: '6',
    }

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    anulado = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    cuf = models.CharField(max_length=100, null=True, blank=True)
    cufd = models.CharField(max_length=100, null=True, blank=True)
    estado_sin = models.CharField(
        max_length=15, choices=ESTADO_SIN_CHOICES, default=SIN_NO_ENVIADA
    )
    codigo_recepcion_sin = models.CharField(max_length=100, null=True, blank=True)
    fecha_hora_envio_sin = models.DateTimeField(null=True, blank=True)
    mensaje_sin = models.TextField(null=True, blank=True)

    codigo_motivo_anulacion_sin = models.PositiveSmallIntegerField(null=True, blank=True)
    fecha_anulacion_sin = models.DateTimeField(null=True, blank=True)
    fecha_reversion_sin = models.DateTimeField(null=True, blank=True)

    xml_firmado = models.TextField(null=True, blank=True)

    forma_pago = models.CharField(
        max_length=20, choices=FORMA_PAGO_CHOICES, default=FORMA_PAGO_EFECTIVO
    )
    codigo_metodo_pago = models.CharField(max_length=10, default="1")

    # El SIN exige el nodo numeroTarjeta poblado (no null) cuando el
    # metodo de pago es con tarjeta (confirmado con el error real 1012
    # del SIN sobre la factura 549: "EL NUMERO DE TARJETA SOLO PUEDE SER
    # ENVIADO CUANDO EL METODO DE PAGO SEA CON TARJETA"). Se guardan solo
    # los ULTIMOS 4 DIGITOS -- nunca la tarjeta completa, por seguridad
    # (evitar cualquier alcance de PCI-DSS). Se limpia solo en save() si
    # la forma de pago no es Debito/Credito (ver mas abajo).
    numero_tarjeta = models.CharField(
        max_length=4, null=True, blank=True,
        help_text="Últimos 4 dígitos de la tarjeta. Requerido por el SIN "
                   "cuando la forma de pago es Tarjeta de Débito o Crédito."
    )

    # --- Venta a credito ---
    fecha_vencimiento = models.DateField(
        null=True, blank=True,
        help_text="Se calcula solo (fecha de la venta + plazo del cliente) "
                   "cuando forma_pago='CREDITO'."
    )
    saldo_pendiente = models.FloatField(
        default=0,
        help_text="Se inicializa en 'total' al guardar una venta a credito, "
                   "y se descuenta con cada Pago (abono) registrado."
    )

    def __str__(self):
        return '{}'.format(self.id)

    def save(self, *args, **kwargs):
        self.total = self.sub_total - self.descuento
        self.codigo_metodo_pago = self.FORMA_PAGO_A_CODIGO_SIN.get(self.forma_pago, '1')

        # El numero de tarjeta solo tiene sentido si la forma de pago
        # actual es con tarjeta -- si se cambia a otra forma de pago, se
        # limpia para no arrastrar un dato viejo/irrelevante en la BD.
        if self.forma_pago not in (self.FORMA_PAGO_TARJETA_DEBITO, self.FORMA_PAGO_TARJETA_CREDITO):
            self.numero_tarjeta = None

        if self.forma_pago == self.FORMA_PAGO_CREDITO:
            if self.cliente_id and self.cliente.plazo_credito_dias:
                # self.fecha puede llegar como: datetime real (factura ya
                # guardada antes), string "YYYY-MM-DD" (factura nueva,
                # recien creada desde el formulario -- auto_now_add
                # todavia no le asigno un datetime real), o vacio (nunca
                # se lleno, se usa la fecha de hoy). Se normaliza a un
                # objeto date real en los tres casos antes de sumarle
                # el plazo -- sumar timedelta a un string tira TypeError.
                if isinstance(self.fecha, str):
                    fecha_base = datetime.date.fromisoformat(self.fecha)
                elif self.fecha and hasattr(self.fecha, 'date'):
                    fecha_base = self.fecha.date()
                elif self.fecha:
                    fecha_base = self.fecha
                else:
                    fecha_base = timezone.localdate()
                self.fecha_vencimiento = fecha_base + timezone.timedelta(
                    days=self.cliente.plazo_credito_dias
                )
            # El saldo pendiente arranca igual al total SOLO en el
            # primer guardado (factura recien creada, sin pk todavia).
            # OJO: antes esta condicion tambien miraba
            # "self.saldo_pendiente == 0", pensando que 0 siempre
            # significaba "nunca se inicializo" -- pero 0 tambien es el
            # valor LEGITIMO de una factura ya pagada por completo. Eso
            # causaba que, apenas pago_registrado() ponia el saldo en 0
            # tras un pago exacto, este mismo save() lo pisara de vuelta
            # con el total, como si no se hubiera pagado nada (bug real
            # detectado en facturas 553 y 555: el pago exacto no se
            # reflejaba, y un segundo pago dejaba el saldo negativo).
            # Con "not self.pk" alcanza: en cualquier guardado posterior
            # se respeta el valor que el llamador (esta funcion mas
            # arriba, la señal de FacturaDet, o pago_registrado) ya haya
            # dejado en saldo_pendiente.
            if not self.pk:
                self.saldo_pendiente = self.total
        else:
            self.fecha_vencimiento = None
            self.saldo_pendiente = 0

        super(FacturaEnc, self).save(*args, **kwargs)

    @property
    def reportada_ante_sin(self):
        return self.estado_sin in (
            self.SIN_VALIDADA, self.SIN_PENDIENTE,
            self.SIN_ANULADA, self.SIN_REVERTIDA,
        )

    @property
    def puede_editarse(self):
        return not self.anulado and not self.reportada_ante_sin

    @property
    def estado_credito(self):
        """Solo tiene sentido si forma_pago == CREDITO."""
        if self.forma_pago != self.FORMA_PAGO_CREDITO:
            return None
        if self.saldo_pendiente <= 0:
            return 'pagado'
        if self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate():
            return 'vencido'
        return 'vigente'

    @property
    def dias_mora(self):
        """Dias de atraso respecto al vencimiento (0 si no esta vencido)."""
        if self.estado_credito != 'vencido':
            return 0
        return (timezone.localdate() - self.fecha_vencimiento).days

    class Meta:
        verbose_name_plural = "Encabezado Facturas"
        verbose_name="Encabezado Factura"
        permissions = [
            ('sup_caja_facturaenc','Permisos de Supervisor de Caja Encabezado'),
            ('anular_facturaenc','Permiso para Anular Facturas'),
            ('gestionar_creditos', 'Permiso para gestionar ventas a credito y cobranza'),
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


class Pago(ClaseModelo2):
    """Abono a una venta a credito. Puede haber varios por factura."""
    FORMA_PAGO_ABONO_CHOICES = [
        ('EFECTIVO', 'Efectivo'),
        ('TARJETA', 'Tarjeta'),
        ('QR', 'QR'),
        ('TRANSFERENCIA', 'Transferencia Bancaria'),
    ]

    factura = models.ForeignKey(FacturaEnc, on_delete=models.CASCADE, related_name='pagos')
    fecha = models.DateTimeField(auto_now_add=True)
    monto = models.FloatField()
    forma_pago = models.CharField(max_length=20, choices=FORMA_PAGO_ABONO_CHOICES, default='EFECTIVO')
    observacion = models.CharField(max_length=250, null=True, blank=True)

    def __str__(self):
        return f"Pago Bs {self.monto} - Factura {self.factura_id}"

    class Meta:
        verbose_name = "Pago (Abono)"
        verbose_name_plural = "Pagos (Abonos)"
        ordering = ["-fecha"]


class CierreDia(ClaseModelo2):
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
    facturas_pendientes_sin = models.IntegerField(default=0)
    observaciones = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Cierre {self.fecha}"

    class Meta:
        verbose_name = "Cierre de Día"
        verbose_name_plural = "Cierres de Día"
        permissions = [
            ('gestionar_cierre_dia', 'Permiso para gestionar el Cierre de Día'),
        ]


def dias_pendientes_de_cierre():
    hoy = timezone.localdate()
    fechas_con_facturas = (
        FacturaEnc.objects.filter(fecha__date__lt=hoy)
        .annotate(dia=TruncDate('fecha'))
        .values_list('dia', flat=True)
        .distinct()
    )
    fechas_cerradas = set(CierreDia.objects.values_list('fecha', flat=True))
    return sorted(d for d in fechas_con_facturas if d not in fechas_cerradas)


@receiver(post_save, sender=FacturaDet)
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
        # Si es venta a credito, el saldo pendiente debe seguir al total
        # mientras no se haya registrado ningun abono todavia.
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            total_abonado = enc.pagos.aggregate(t=Sum('monto')).get('t') or 0
            if total_abonado == 0:
                enc.saldo_pendiente = enc.sub_total - enc.descuento
        enc.save()

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

    if not ya_estaba_anulada:
        prod=Producto.objects.filter(pk=id_producto).first()
        if prod:
            cantidad = int(prod.existencia) + int(instance.cantidad)
            prod.existencia = cantidad
            prod.save()


@receiver(post_save, sender=Pago)
def pago_registrado(sender, instance, created, **kwargs):
    """Al registrar un abono, descuenta el saldo pendiente de la factura."""
    if not created:
        return
    enc = instance.factura
    total_abonado = enc.pagos.aggregate(t=Sum('monto')).get('t') or 0
    enc.saldo_pendiente = round(enc.total - total_abonado, 2)
    enc.save()


@receiver(post_delete, sender=Pago)
def pago_eliminado(sender, instance, **kwargs):
    """
    Simetrico a pago_registrado: si se borra un abono (ej. se cargo por
    error), recalcula saldo_pendiente contra los Pago que quedan. Sin
    esta señal, borrar un Pago dejaba saldo_pendiente desactualizado
    -- nadie lo volvia a tocar.
    """
    enc = FacturaEnc.objects.filter(pk=instance.factura_id).first()
    if not enc:
        return
    total_abonado = enc.pagos.aggregate(t=Sum('monto')).get('t') or 0
    enc.saldo_pendiente = round(enc.total - total_abonado, 2)
    enc.save()