import datetime
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum, F
from django.db.models.functions import TruncDate

from bases.models import ClaseModelo,ClaseModelo2
from inv.models import Producto, ajustar_stock_sucursal

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
    # CI/NIT/razon (Fase 2, 20/09/2026): dejan de ser unique=True GLOBAL
    # -- decision de negocio confirmada por Carlos el 16/09/2026 ("cada
    # sucursal tenga su propio cliente... lo que va a diferenciar es la
    # sucursal, aunque se repita el nombre y el NIT"). La unicidad real
    # pasa a Meta.constraints, por (sucursal, campo) -- ver mas abajo.
    ci = models.CharField(max_length=20, null=True)
    nit = models.CharField(max_length=30, null=True, blank=True)
    razon = models.CharField(max_length=100, null=True)
    email = models.CharField(max_length=250, null=True, blank=True)
    # sucursal (Fase 2, 20/09/2026): CONFIRMADO por Carlos -- cada
    # sucursal tiene sus propios clientes, no compartidos. Null en
    # datos viejos (migrados a la sucursal por defecto) y en
    # instalaciones todavia sin sucursales.
    sucursal = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, null=True, blank=True
    )
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

    @property
    def whatsapp_numero(self):
        """
        Normaliza 'celular' al formato que exige el link wa.me (solo
        digitos, con codigo de pais). Agregado 16/09/2026 (Fase 1 --
        envio de factura por correo/WhatsApp). Bolivia = 591; los
        celulares locales tienen 8 digitos y casi siempre se cargan sin
        el codigo de pais, asi que se antepone salvo que ya venga
        incluido. None si no hay celular cargado.
        """
        if not self.celular:
            return None
        digitos = ''.join(c for c in self.celular if c.isdigit())
        if not digitos:
            return None
        if not digitos.startswith('591'):
            digitos = '591' + digitos
        return digitos

    def save(self, *args, **kwargs):
        self.nombres = self.nombres.upper()
        self.apellidos = self.apellidos.upper()
        # Corregido 20/09/2026 (hallazgo de paso, al tocar este mismo
        # metodo por Fase 2): 'razon' es null=True en el modelo, pero
        # esta linea asumia que siempre venia cargado -- un cliente
        # Natural (sin razon social) tiraba AttributeError al guardar
        # si razon quedaba en None.
        self.razon = self.razon.upper() if self.razon else None
        self.nit = self.nit.strip() if self.nit else None
        super(Cliente, self).save( *args, **kwargs)

    @property
    def saldo_credito_pendiente(self):
        """Suma de saldo_pendiente de todas sus facturas a credito activas."""
        # estado=True excluye facturas eliminadas (soft-delete) -- una
        # factura eliminada no debe seguir contando contra el limite
        # de credito del cliente.
        facturas = FacturaEnc.objects.filter(
            cliente=self, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO, anulado=False, estado=True
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
        # estado=True excluye facturas eliminadas -- no deben poder
        # seguir bloqueando al cliente.
        return FacturaEnc.objects.filter(
            cliente=self, forma_pago=FacturaEnc.FORMA_PAGO_CREDITO,
            anulado=False, estado=True, fecha_vencimiento__lt=hoy, saldo_pendiente__gt=0
        ).exists()

    class Meta:
        verbose_name_plural = "Clientes"
        # Fase 2, 20/09/2026: unicidad por sucursal, no global (ver
        # comentario en los campos ci/nit/razon mas arriba).
        constraints = [
            models.UniqueConstraint(fields=['sucursal', 'ci'], name='cliente_unico_ci_por_sucursal'),
            models.UniqueConstraint(fields=['sucursal', 'nit'], name='cliente_unico_nit_por_sucursal'),
            models.UniqueConstraint(fields=['sucursal', 'razon'], name='cliente_unico_razon_por_sucursal'),
        ]

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
    # sucursal (Fase 2, 20/09/2026): que sucursal vendio. Null en datos
    # viejos (migrados a la sucursal por defecto) y en instalaciones
    # todavia sin sucursales -- ver ajustar_stock_sucursal (inv/models.py)
    # y _obtener_empresa_y_sucursal (fe/services.py) para como se usa.
    # La NUMERACION de factura NO cambia por esto: todas las sucursales
    # de una empresa comparten la misma tabla FacturaEnc (Silo Model =
    # un NIT = una base, no una sucursal = una base), asi que el id
    # autoincremental ya sale secuencial entre sucursales tal cual.
    sucursal = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, null=True, blank=True
    )
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
    # leyenda (21/09/2026, checklist SIN Fase II punto 4): elegida al azar
    # del catalogo CatalogoSIN (LEYENDAS) en el momento de emitir, y
    # guardada aca -- asi el mismo texto que se mando al SIN en el XML es
    # el que se imprime en la representacion grafica (y el que se sigue
    # mostrando si se reimprime/reenvia despues), en vez de recalcularse
    # distinto cada vez. Null en facturas emitidas antes de este cambio.
    leyenda = models.CharField(max_length=200, null=True, blank=True)
    # codigo_control (agregado 17/09/2026): ya se calculaba y se usaba
    # para derivar el CUF en emitir_factura_sin, pero nunca se
    # guardaba -- es uno de los datos que el propio portal de
    # verificacion del SIN (Oficina Virtual, ov.impuestos.gob.bo)
    # exige junto al NIT/Numero de Factura/CUF/fecha/total para que
    # alguien pueda verificar la factura a mano, asi que tiene que
    # quedar impreso en el documento igual que el CUF.
    codigo_control = models.CharField(max_length=20, null=True, blank=True)
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
            # El saldo pendiente arranca igual al total en dos casos:
            # (1) factura recien creada (sin pk todavia), o (2) la
            # factura YA existia pero recien esta pasando A credito
            # desde otra forma de pago (donde saldo_pendiente estaba
            # forzado en 0 por el "else" de abajo). Se detecta
            # comparando contra la forma_pago que tenia ANTES en la
            # base -- "not self.pk" solo no alcanzaba (bug real
            # detectado en la factura 557: se cargo como Efectivo, se
            # corrigio a Credito via "Actualizar Cliente/Forma de
            # Pago", y saldo_pendiente se quedo en 0 porque la factura
            # ya tenia pk, entonces nunca se inicializaba).
            #
            # En cualquier OTRO guardado (factura que YA era credito y
            # sigue siendolo -- agregar producto, un pago, etc.) no se
            # toca: se respeta el valor que el llamador (la señal de
            # FacturaDet, o pago_registrado) ya haya dejado en
            # saldo_pendiente. Asi se sigue evitando el bug anterior
            # (0 tras un pago completo no se pisaba con el total).
            forma_pago_previa = (
                FacturaEnc.objects.filter(pk=self.pk)
                .values_list('forma_pago', flat=True).first()
                if self.pk else None
            )
            if not self.pk or forma_pago_previa != self.FORMA_PAGO_CREDITO:
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
        # 'estado' cubre el soft-delete de eliminar_factura -- una
        # factura eliminada queda bloqueada aca centralmente, sin tener
        # que repetir el chequeo en cada vista que hoy usa esta misma
        # propiedad (agregar producto, reversion, borrado de linea,
        # actualizar cliente/forma de pago).
        return self.estado and not self.anulado and not self.reportada_ante_sin

    # Umbral para considerar una factura a credito "proxima a vencer"
    # (siempre que todavia tenga saldo pendiente). Centralizado aca para
    # que estado_credito y cualquier reporte que necesite el mismo
    # criterio (ej. el Kardex de Cliente) usen un solo numero -- antes
    # el Kardex tenia su propia constante local duplicada.
    UMBRAL_PROXIMO_VENCIMIENTO_DIAS = 7

    @property
    def estado_credito(self):
        """Solo tiene sentido si forma_pago == CREDITO."""
        if self.forma_pago != self.FORMA_PAGO_CREDITO:
            return None
        # Anulado/eliminado se chequean ANTES que saldo_pendiente <= 0
        # -- una factura anulada o eliminada sin abonos previos (la
        # unica situacion permitida, ver anular_factura/eliminar_factura)
        # tambien queda con saldo_pendiente en 0, pero el motivo real no
        # es que "se pago", es que el documento ya no es valido. Sin
        # este orden, se mostraria enganosamente como 'pagado'.
        if self.anulado:
            return 'anulado'
        if not self.estado:
            return 'eliminado'
        if self.saldo_pendiente <= 0:
            return 'pagado'
        if self.fecha_vencimiento:
            dias = (self.fecha_vencimiento - timezone.localdate()).days
            if dias < 0:
                return 'vencido'
            if dias <= self.UMBRAL_PROXIMO_VENCIMIENTO_DIAS:
                return 'por_vencer'
        return 'vigente'

    @property
    def dias_mora(self):
        """Dias de atraso respecto al vencimiento (0 si no esta vencido)."""
        if self.estado_credito != 'vencido':
            return 0
        return (timezone.localdate() - self.fecha_vencimiento).days

    @property
    def dias_para_vencer(self):
        """
        Dias con signo hasta el vencimiento: positivo = dias que faltan,
        negativo = dias de mora (vencida hace N dias). None si la
        factura no tiene fecha_vencimiento cargada (no es a credito, o
        nunca se calculo). Pensado para una sola columna numerica que
        sirva tanto para 'vigente'/'por_vencer' como para 'vencido',
        en vez de tener que combinar dos campos distintos.
        """
        if not self.fecha_vencimiento:
            return None
        return (self.fecha_vencimiento - timezone.localdate()).days

    class Meta:
        verbose_name_plural = "Encabezado Facturas"
        verbose_name="Encabezado Factura"
        permissions = [
            ('sup_caja_facturaenc','Permisos de Supervisor de Caja Encabezado'),
            ('anular_facturaenc','Permiso para Anular Facturas'),
            ('gestionar_creditos', 'Permiso para gestionar ventas a credito y cobranza'),
            # Agregados 27/08/2026 al definir los roles del sistema:
            ('eliminar_facturaenc', 'Permiso para eliminar una factura completa'),
            # Separado de gestionar_creditos a proposito -- antes, ver la
            # Cartera de Creditos o el Kardex de Cliente exigia el MISMO
            # permiso que registrar un pago, asi que no habia forma de
            # darle a alguien (ej. un contador) acceso de solo lectura
            # sin darle tambien la capacidad de cobrar. gestionar_creditos
            # sigue existiendo para la ACCION de registrar el pago;
            # ver_creditos es solo para mirar (Cartera, Kardex, recibos).
            ('ver_creditos', 'Permiso para ver Cartera de Creditos y Kardex de Cliente (solo lectura)'),
            # Reportes financieros agregados (Cierre de Ventas, Cierre de
            # Caja) -- antes no exigian ningun permiso, solo estar
            # logueado. Separado de view_facturaenc (que cubre listar/
            # imprimir facturas individuales, tarea normal de un cajero)
            # porque estos reportes son una vista financiera agregada del
            # negocio, pensada para administracion/contabilidad, no para
            # el dia a dia de caja.
            ('ver_reportes_financieros', 'Permiso para ver Cierre de Ventas y Cierre de Caja'),
        ]
    

class FacturaDet(ClaseModelo2):
    factura = models.ForeignKey(FacturaEnc,on_delete=models.CASCADE)
    producto=models.ForeignKey(Producto,on_delete=models.CASCADE)
    cantidad=models.BigIntegerField(default=0)
    precio=models.FloatField(default=0)
    sub_total=models.FloatField(default=0)
    descuento=models.FloatField(default=0)
    total=models.FloatField(default=0)

    # Quien autorizo esta linea como reversion (borrar_detalle_factura).
    # NO se puede usar 'uc' para esto: 'uc' es un UserForeignKey
    # automatico que siempre guarda al usuario de la SESION activa (el
    # cajero navegando), no al usuario que se autentica dentro del
    # dialogo de confirmacion -- ese authenticate() nunca hace login(),
    # asi que 'uc' seguiria mostrando al cajero aunque haya sido un
    # supervisor quien autorizo. Este campo se asigna a mano en la
    # vista con el usuario real devuelto por authenticate(). Queda null
    # para lineas que nunca fueron una reversion (la inmensa mayoria).
    usuario_reversion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text="Supervisor que autorizó esta línea como reversión de otra. "
                   "Vacío si esta línea no es una reversión."
    )

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

    # --- Reversion de abono (Caso 1: error de carga, no una devolucion
    # real -- ver conversacion sobre politica de anulacion con abono).
    # Mismo criterio de auditoria que el resto del sistema: nunca se
    # borra el registro, se marca como revertido y se guarda quien lo
    # autorizo y por que. 'uc' (automatico) queda con el cajero que
    # registro el abono originalmente -- 'usuario_reversion' guarda al
    # supervisor real que autorizo deshacerlo, igual que ya se hace
    # con FacturaDet.usuario_reversion.
    revertido = models.BooleanField(default=False)
    fecha_reversion = models.DateTimeField(null=True, blank=True)
    usuario_reversion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pagos_revertidos'
    )
    motivo_reversion = models.CharField(max_length=250, null=True, blank=True)

    def __str__(self):
        return f"Pago Bs {self.monto} - Factura {self.factura_id}"

    class Meta:
        verbose_name = "Pago (Abono)"
        verbose_name_plural = "Pagos (Abonos)"
        ordering = ["-fecha"]


class NotaCreditoDebito(ClaseModelo2):
    """
    Nota de Credito-Debito: documento fiscal que corrige/ajusta una
    factura ya emitida y aceptada por el SIN, cuando ya no es posible
    (o no corresponde) una simple Anulacion -- tipicamente porque la
    factura ya tiene abonos registrados, o porque paso el plazo de
    anulacion (hasta el dia 9 del mes siguiente).

    CORREGIDO 15/09/2026 (el parrafo de abajo describia una hipotesis
    de fondo que resulto INCORRECTA, ver instructivo NCD Etapas IV/VII/
    VIII/XI para el detalle completo de la investigacion): la NCD NO
    usa el mismo WSDL/servicio que una factura normal. Usa un WSDL
    COMPLETAMENTE DISTINTO --
    ServicioFacturacionDocumentoAjuste (WSDL_DOCUMENTO_AJUSTE en
    fe/services.py), operacion recepcionDocumentoAjuste -- nunca usado
    hasta el 12/09/2026, que es la causa real del error persistente
    995 "SERVICIO NO DISPONIBLE" que bloqueo la certificacion durante
    meses. codigoDocumentoSector=24 (no 47 como se penso originalmente
    -- ese 24 SI es del catalogo real que exige este documento, y
    tipoFacturaDocumento=3, igual que una factura normal). El servicio
    reconstruye TODAS las lineas de la factura original
    (codigoDetalleTransaccion=1) y agrega, aparte, la porcion que se
    esta devolviendo (codigoDetalleTransaccion=2) -- asi el SIN puede
    recalcular el credito fiscal de ambas partes. El detalle en si NO
    se persiste en un modelo aparte: se reconstruye en el momento de
    emitir, a partir de los FacturaDet de factura_original (fuente
    unica de verdad, sin duplicar datos). Ver
    fe.services.emitir_nota_credito_debito_sin.

    Decisiones tomadas el 26/08/2026:
      - Primera version: solo DEVOLUCION TOTAL de la factura (no
        parcial por linea/cantidad) -- se puede ampliar mas adelante.
      - Autorizacion: mismo nivel que Anular/Revertir (_es_supervisor
        en fac/views.py) -- Carlos ya anticipo que mas adelante van a
        definir roles mas especificos para no recargar todo en
        Supervisor, pendiente de una conversacion aparte.
      - Una vez validada por el SIN, la factura_original queda
        marcada y bloqueada para cualquier otra operacion (Anular,
        Eliminar, nuevos abonos, otra NCD) -- ver los chequeos
        agregados en anular_factura, eliminar_factura y
        registrar_pago (fac/views.py).
      - numeroNotaCreditoDebito ante el SIN usa directamente el id
        autoincremental de este modelo (self.id) -- mismo patron ya
        establecido para numeroFactura, que usa FacturaEnc.id
        directamente, sin un campo de numeracion aparte.
    """
    SIN_NO_ENVIADA = 'no_enviada'
    SIN_PENDIENTE = 'pendiente'
    SIN_VALIDADA = 'validada'
    SIN_OBSERVADA = 'observada'
    SIN_ANULADA = 'anulada'
    SIN_REVERTIDA = 'revertida'
    SIN_ESTADO_CHOICES = [
        (SIN_NO_ENVIADA, 'Sin Emitir al SIN'),
        (SIN_PENDIENTE, 'Pendiente SIN'),
        (SIN_VALIDADA, 'Validada SIN'),
        (SIN_OBSERVADA, 'Observada SIN'),
        (SIN_ANULADA, 'Anulada ante el SIN'),
        (SIN_REVERTIDA, 'Anulación revertida ante el SIN'),
    ]

    factura_original = models.ForeignKey(
        FacturaEnc, on_delete=models.PROTECT, related_name='notas_credito_debito',
        help_text="Factura que esta Nota de Credito-Debito corrige/ajusta."
    )
    fecha = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(
        max_length=250,
        help_text="Motivo de la correccion, para auditoria interna -- el XSD de este "
                   "documento no tiene un campo de motivo propio ante el SIN."
    )

    cuf = models.CharField(max_length=100, null=True, blank=True)
    cufd = models.CharField(max_length=100, null=True, blank=True)
    # codigo_control (agregado 19/09/2026, mismo motivo que
    # FacturaEnc.codigo_control del 17/09): se calculaba en
    # emitir_nota_credito_debito_sin para derivar el CUF pero nunca se
    # guardaba -- lo exige el verificador publico del SIN junto al
    # resto de los datos impresos en la representacion grafica de la NCD.
    codigo_control = models.CharField(max_length=20, null=True, blank=True)

    monto_total_original = models.FloatField(
        help_text="Total de la factura original (montoTotalOriginal ante el SIN)."
    )
    monto_total_devuelto = models.FloatField(
        help_text="Monto devuelto -- en esta primera version, siempre igual al total "
                   "de la factura original (devolucion total, no parcial)."
    )
    monto_descuento_credito_debito = models.FloatField(
        default=0,
        help_text="Prorrateo del descuento adicional de la factura original. Nuestro "
                   "sistema nunca usa descuentoAdicional a nivel factura (los descuentos "
                   "ya estan netos en cada linea, ver _armar_cabecera en fe/services.py), "
                   "asi que este campo queda en 0 en la practica."
    )
    monto_efectivo_credito_debito = models.FloatField(
        help_text="13% (IVA) del monto total devuelto -- calculado automaticamente, "
                   "segun exige el XSD oficial de este documento."
    )

    estado_sin = models.CharField(max_length=20, choices=SIN_ESTADO_CHOICES, default=SIN_NO_ENVIADA)
    codigo_recepcion_sin = models.CharField(max_length=100, null=True, blank=True)
    mensaje_sin = models.TextField(null=True, blank=True)
    xml_firmado = models.TextField(null=True, blank=True)

    usuario_autorizacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notas_credito_debito_autorizadas',
        help_text="Supervisor que autorizo la emision de esta NCD."
    )

    # --- Anulacion de la NCD (agregado 15/09/2026, Etapa VII de
    # certificacion) -- mismo patron que FacturaEnc.anulado: un
    # booleano separado de estado_sin (que sigue guardando el ultimo
    # codigoEstado devuelto por el SIN, ahora incluyendo SIN_ANULADA),
    # mas los campos de auditoria de quien/cuando/por que. Ante el SIN
    # se anula via anulacionDocumentoAjuste (WSDL_DOCUMENTO_AJUSTE),
    # NUNCA anulacionFactura -- ver fe.services.anular_nota_credito_debito_sin.
    anulada = models.BooleanField(default=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, null=True, blank=True)
    usuario_anulacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    codigo_motivo_anulacion_sin = models.PositiveSmallIntegerField(null=True, blank=True)
    fecha_anulacion_sin = models.DateTimeField(null=True, blank=True)

    # --- Reversion de la anulacion de la NCD (agregado 15/09/2026,
    # Etapa XI -- confirmada en el dashboard real del SIN: la fila
    # especifica de NCD, codigoDocumentoSector=24/tipoFacturaDocumento=3,
    # SI pide esto, igual que la anulacion). Mismo patron que
    # FacturaEnc.fecha_reversion_sin -- via
    # reversionAnulacionDocumentoAjuste (WSDL_DOCUMENTO_AJUSTE), ver
    # fe.services.revertir_anulacion_nota_credito_debito_sin.
    fecha_reversion_sin = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"NCD N° {self.id} — Factura N° {self.factura_original_id}"

    class Meta:
        verbose_name = "Nota de Crédito-Débito"
        verbose_name_plural = "Notas de Crédito-Débito"
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
            # Agregado 27/08/2026 -- antes, forzar el cierre con facturas
            # pendientes exigia is_superuser directo en el codigo, sin
            # pasar por ningun permiso configurable. Con varios clientes
            # reales en mente (no solo la libreria), cada uno necesita
            # poder tener su propio "Administrador" con esta capacidad
            # sin que eso implique ser superusuario tecnico de Django.
            ('forzar_cierre_dia', 'Permiso para forzar el Cierre de Día con facturas pendientes'),
        ]


def dias_pendientes_de_cierre():
    hoy = timezone.localdate()
    fechas_con_facturas = (
        FacturaEnc.objects.filter(fecha__date__lt=hoy, estado=True)
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
        # Si es venta a credito, saldo_pendiente sigue al total menos lo
        # ya abonado -- SIEMPRE, no solo cuando todavia no hay ningun
        # abono. Antes esto solo se recalculaba si total_abonado == 0
        # (pensado para el alta inicial de la factura), y una vez
        # registrado el primer abono, agregar OTRO producto ya no
        # actualizaba saldo_pendiente para nada -- quedaba congelado en
        # el total de ANTES del producto nuevo (bug real confirmado en
        # la factura 558: abono de 150, total termino en 387 con dos
        # productos, pero saldo_pendiente se quedo en 165 -- exactamente
        # 315 [total con un solo producto] menos 150 [abonado]).
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            total_abonado = enc.pagos.aggregate(t=Sum('monto')).get('t') or 0
            enc.saldo_pendiente = round((enc.sub_total - enc.descuento) - total_abonado, 2)
        enc.save()

    # CORREGIDO 16/09/2026 -- revision de seguridad/bugs (Etapa A):
    # leer existencia, restar en Python y guardar es un read-modify-
    # write no atomico -- con dos cajas/sucursales vendiendo el mismo
    # producto casi al mismo tiempo (escenario real con multiples
    # PuntoVenta), el ultimo save() gana y el otro decremento se pierde
    # en silencio, dejando existencia mas alta de lo real. F() empuja
    # la resta a la base de datos, atomica por fila.
    #
    # AMPLIADO 20/09/2026 (Fase 2): ajustar_stock_sucursal reemplaza el
    # F() suelto de arriba -- mismo criterio atomico, pero ahora
    # descuenta de la sucursal REAL de esta factura, no de un pozo
    # global compartido entre todas las sucursales.
    ajustar_stock_sucursal(producto_id, enc.sucursal if enc else None, -instance.cantidad)

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
        # Mismo ajuste que en detalle_fac_guardar: si es venta a
        # credito, saldo_pendiente tiene que seguir al nuevo total menos
        # lo abonado tambien cuando se BORRA un producto (antes no se
        # tocaba nada aca -- mismo tipo de hueco, del lado contrario).
        if enc.forma_pago == FacturaEnc.FORMA_PAGO_CREDITO:
            total_abonado = enc.pagos.aggregate(t=Sum('monto')).get('t') or 0
            enc.saldo_pendiente = round((enc.sub_total - enc.descuento) - total_abonado, 2)
        enc.save()

    if not ya_estaba_anulada:
        # Mismo fix de atomicidad + sucursal que detalle_fac_guardar (ver comentario ahi).
        ajustar_stock_sucursal(id_producto, enc.sucursal if enc else None, instance.cantidad)


@receiver(post_save, sender=Pago)
def pago_registrado(sender, instance, created, **kwargs):
    """
    Recalcula el saldo pendiente de la factura en CUALQUIER guardado de
    un Pago -- no solo al crearlo. Antes decia "if not created: return",
    lo que significaba que actualizar un Pago ya existente (como hace
    revertir_pago() al marcarlo revertido=True) nunca disparaba el
    recalculo. Los pagos revertidos se EXCLUYEN de la suma -- un abono
    revertido ya no debe seguir descontando saldo.
    """
    enc = instance.factura
    total_abonado = enc.pagos.filter(revertido=False).aggregate(t=Sum('monto')).get('t') or 0
    enc.saldo_pendiente = round(enc.total - total_abonado, 2)
    enc.save()


@receiver(post_delete, sender=Pago)
def pago_eliminado(sender, instance, **kwargs):
    """
    Simetrico a pago_registrado: si se borra un abono FISICAMENTE (ej.
    desde el admin de Django -- el flujo normal ahora usa soft-delete
    via revertir_pago, no borrado real), recalcula saldo_pendiente
    contra los Pago que quedan, excluyendo tambien los revertidos.
    """
    enc = FacturaEnc.objects.filter(pk=instance.factura_id).first()
    if not enc:
        return
    total_abonado = enc.pagos.filter(revertido=False).aggregate(t=Sum('monto')).get('t') or 0
    enc.saldo_pendiente = round(enc.total - total_abonado, 2)
    enc.save()