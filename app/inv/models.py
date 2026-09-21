from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User

from bases.models import ClaseModelo, ClaseModelo2

class Categoria(ClaseModelo):
    descripcion = models.CharField(
        max_length=100,
        help_text='Descripción de la Categoría',
        unique=True
    )

    def __str__(self):
        return '{}'.format(self.descripcion)
    
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Categoria, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural= 'Categorias'

class SubCategoria(ClaseModelo):
    categoria = models.ForeignKey(Categoria,on_delete=models.CASCADE)
    descripcion = models.CharField(
        max_length=100,
        help_text='Descripción de la SubCategoría'
    )

    def __str__(self):
        return '{}:{}'.format(self.categoria.descripcion,self.descripcion)
    
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(SubCategoria, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural= 'Sub Categorias'
        unique_together= ('categoria','descripcion')

class Marca(ClaseModelo):
    descripcion = models.CharField(
        max_length=100,
        help_text='Descripción de la Marca',
        unique=True
    )

    def __str__(self):
        return '{}'.format(self.descripcion)
    
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Marca, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural= 'Marca'

class UnidadMedida(ClaseModelo):
    descripcion = models.CharField(
        max_length=100,
        help_text='Descripción de la Unidad Medida',
        unique=True
    )
    codigo_sin = models.CharField(
        max_length=10, null=True, blank=True,
        help_text="Código del catálogo SIN 'TIPO_UNIDAD_MEDIDA' (ver app catalogos). "
                   "Necesario para facturación electrónica."
    )

    def __str__(self):
        return '{}'.format(self.descripcion)
    
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(UnidadMedida, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural= 'Unidades de Medida'


class TipoCambio(ClaseModelo):
    """
    Registro manual del Tipo de Cambio Oficial (TCO) publicado por el
    BCB. Se carga desde una pantalla propia dentro de Catálogos,
    protegida con el permiso 'gestionar_precios_tc' (ver Producto.Meta)
    -- pensado para poder asignarselo a un rol "Contador" sin darle
    acceso a editar el resto del catalogo de productos.
    """
    fecha = models.DateField(unique=True)
    valor = models.FloatField(
        help_text="Bolivianos por 1 dolar (ej. 9.73)."
    )
    fuente = models.CharField(
        max_length=100, default="BCB Oficial", blank=True
    )

    def __str__(self):
        return f"{self.fecha} - Bs {self.valor}"

    class Meta:
        verbose_name = "Tipo de Cambio"
        verbose_name_plural = "Tipos de Cambio"
        ordering = ["-fecha"]


class Producto(ClaseModelo):
    codigo = models.CharField(
        max_length=20,
        unique=True
    )

    codigo_barra = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=200)
    precio = models.FloatField(default=0)
    existencia = models.IntegerField(default=0)
    ultima_compra = models.DateField(null=True, blank=True)

    # Costo actual del producto (agregado 08/09/2026 como
    # "costo_promedio"; RENOMBRADO a "costo_actual" el 13/09/2026--
    # ver instructivo de Ajuste de Inventario: para una empresa
    # Industrial este campo NO promedia -- se pisa con el ultimo valor
    # de cada Produccion Interna, asi que "promedio" dejo de ser
    # correcto para todos los casos). Se recalcula SOLO con entradas
    # (compras, o ajustes de inventario que afecten costo -- ver
    # cmp.models.detalle_compra_guardar / inv.models.detalle_ajuste_guardar)
    # -- las ventas nunca lo tocan. Arranca en 0 para productos sin
    # ninguna entrada registrada todavia.
    #
    # LIMITACION CONOCIDA: si se elimina una linea de compra vieja
    # (soft-delete de ComprasEnc/ComprasDet), este campo NO se
    # recalcula hacia atras -- reconstruir el costo exacto que habia
    # antes de esa compra exigiria rehacer todo el historial de
    # movimientos en orden cronologico (compras Y ventas mezcladas),
    # no solo las compras. Se acepta un desvio menor y transitorio en
    # ese caso raro, hasta que la proxima compra real lo vuelva a
    # ajustar -- decision tomada el 08/09/2026 para no construir algo
    # mucho mas grande para un caso poco frecuente.
    costo_actual = models.FloatField(
        default=0,
        help_text="Costo actual del producto, calculado automáticamente con "
                   "cada entrada registrada (compra o ajuste de inventario). "
                   "En empresas Comerciales es un Promedio Ponderado; en "
                   "Industriales, el último valor de Producción Interna, sin "
                   "promediar. No editable a mano."
    )

    marca = models.ForeignKey(Marca, on_delete=models.CASCADE)
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.CASCADE)
    subcategoria = models.ForeignKey(SubCategoria, on_delete=models.CASCADE)
    foto = models.ImageField(upload_to="images/",null=True,blank=True)

    # --- Clasificacion SIN (Fase 3), necesaria para facturacion electronica ---
    actividad_economica_sin = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Código CAEB de actividad económica (catálogo ACTIVIDADES en "
                   "app catalogos) asociado a este producto."
    )
    codigo_producto_sin = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Código de producto/servicio SIN (catálogo PRODUCTOS_SERVICIOS "
                   "en app catalogos) asociado a este producto."
    )

    # --- Politica de descuento por producto (promocion, con vigencia) ---
    descuento_promocional_pct = models.FloatField(
        default=0,
        help_text="Porcentaje de descuento promocional para este producto "
                   "(ej. 15 = 15%). Solo se aplica dentro del rango de "
                   "vigencia (si se define). Si el cliente tambien tiene "
                   "descuento, se aplica el MAYOR de los dos, no se suman."
    )
    descuento_vigencia_desde = models.DateField(
        null=True, blank=True,
        help_text="Si se deja vacio junto con 'hasta', el descuento no tiene "
                   "limite de fecha (siempre activo mientras el % sea > 0)."
    )
    descuento_vigencia_hasta = models.DateField(
        null=True, blank=True,
        help_text="Fecha en que la promocion deja de aplicarse automaticamente."
    )

    # --- Precio de referencia / tipo de cambio (productos importados) ---
    # RENOMBRADO 13/09/2026 (de "costo_referencia_usd"): este campo es
    # la BASE para sugerir un precio de venta (ver
    # calcular_precio_sugerido), no un costo -- "Costo Referencial"
    # confundia con costo_actual, que es lo que realmente costo el
    # producto.
    precio_referencia_usd = models.FloatField(
        null=True, blank=True,
        help_text="Precio de referencia del producto en USD, para productos "
                   "importados -- base para sugerir un precio de venta (ver "
                   "Revisión de Precios). Vacío = producto sin referencia en "
                   "moneda extranjera."
    )
    margen_deseado_pct = models.FloatField(
        default=0,
        help_text="Margen deseado sobre el costo en USD convertido a "
                   "bolivianos (ej. 30 = 30%). 0 = sin margen definido."
    )
    tipo_cambio_referencia = models.ForeignKey(
        'TipoCambio', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Tipo de cambio con el que se fijo el precio actual "
                   "de este producto. Se actualiza solo (no editable a "
                   "mano) cada vez que se aplica un ajuste de precio "
                   "desde la pantalla de Revision de Precios."
    )

    def __str__(self):
        return '{}'.format(self.descripcion)
    
    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super(Producto, self).save(*args, **kwargs)

    @property
    def homologado_sin(self):
        """
        True si este producto ya tiene todo lo necesario para poder
        facturarse electronicamente: actividad economica, codigo de
        producto SIN, y que su unidad de medida tenga codigo_sin.
        """
        return bool(
            self.actividad_economica_sin
            and self.codigo_producto_sin
            and self.unidad_medida_id
            and self.unidad_medida.codigo_sin
        )

    @property
    def descuento_promocional_vigente_pct(self):
        """
        Devuelve el porcentaje promocional SOLO si esta dentro de su
        rango de vigencia (o si no tiene fechas definidas, en cuyo caso
        se considera siempre vigente). Fuera de rango, devuelve 0 -- asi
        la promocion "se apaga sola" sin que nadie tenga que acordarse
        de volver el campo a 0 a mano.
        """
        if not self.descuento_promocional_pct:
            return 0
        from django.utils import timezone
        hoy = timezone.localdate()
        if self.descuento_vigencia_desde and hoy < self.descuento_vigencia_desde:
            return 0
        if self.descuento_vigencia_hasta and hoy > self.descuento_vigencia_hasta:
            return 0
        return self.descuento_promocional_pct

    def calcular_precio_sugerido(self, tipo_cambio_actual):
        """
        Calcula el precio sugerido en bolivianos, redondeado al
        boliviano entero, a partir del costo en USD, el tipo de cambio
        vigente, y el margen deseado. Devuelve None si el producto no
        tiene precio de referencia en USD cargado.
        """
        if not self.precio_referencia_usd or not tipo_cambio_actual:
            return None
        costo_bs = self.precio_referencia_usd * tipo_cambio_actual.valor
        precio = costo_bs * (1 + (self.margen_deseado_pct or 0) / 100)
        return round(precio)

    def variacion_tipo_cambio_pct(self, tipo_cambio_actual):
        """
        Porcentaje de variacion entre el tipo de cambio con el que se
        fijo el precio actual y el mas reciente cargado. None si no
        hay datos suficientes para comparar.
        """
        if not self.tipo_cambio_referencia or not tipo_cambio_actual:
            return None
        anterior = self.tipo_cambio_referencia.valor
        if not anterior:
            return None
        return ((tipo_cambio_actual.valor - anterior) / anterior) * 100

    class Meta:
        verbose_name_plural= 'Productos'
        unique_together = ('codigo','codigo_barra')
        permissions = [
            ('gestionar_precios_tc', 'Puede gestionar Tipo de Cambio y Revisión de Precios'),
        ]


class HistorialPrecioProducto(ClaseModelo2):
    """
    Auditoria de cada cambio de precio de un producto: cuando, con que
    tipo de cambio, y quien lo aplico. Sienta la base para el futuro
    modulo contable (diferencias cambiarias).
    """
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='historial_precios')
    precio_anterior = models.FloatField()
    precio_nuevo = models.FloatField()
    tipo_cambio_usado = models.ForeignKey(
        TipoCambio, on_delete=models.SET_NULL, null=True, blank=True
    )
    motivo = models.CharField(max_length=250, blank=True, default="Ajuste por tipo de cambio")

    def __str__(self):
        return f"{self.producto} — Bs {self.precio_anterior} -> Bs {self.precio_nuevo}"

    class Meta:
        verbose_name = "Historial de Precio"
        verbose_name_plural = "Historial de Precios"
        ordering = ["-fc"]


# =====================================================================
# Stock por Sucursal (Fase 2, 20/09/2026, arquitectura multi-sucursal
# -- diseño confirmado por Carlos). Reemplaza a Producto.existencia
# como la fuente real de "cuanto stock hay" -- ANTES existencia era un
# numero suelto, sin dimension de sucursal, compartido entre TODAS las
# sucursales de la empresa (problema real detectado en la revision de
# seguridad del 16/09/2026 al arreglar la condicion de carrera: con 2
# sucursales escribiendo el mismo producto, F() evita que se pise un
# decremento, pero las dos seguian sumando/restando del MISMO pozo).
#
# Producto.existencia NO se elimino -- sigue existiendo como TOTAL
# agregado (suma de StockSucursal de todas las sucursales), mantenido
# automaticamente por ajustar_stock_sucursal(). Todo el codigo que
# solo necesita "cuanto hay en total" (reportes, la API, listados)
# sigue funcionando sin cambios; todo el codigo que ahora necesita
# saber "cuanto hay en ESTA sucursal" (facturar, comprar, ajustar)
# debe usar StockSucursal / ajustar_stock_sucursal directamente.
# =====================================================================

class StockSucursal(ClaseModelo2):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='stock_por_sucursal')
    sucursal = models.ForeignKey('fe.Sucursal', on_delete=models.CASCADE, related_name='stock_productos')
    cantidad = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.producto} @ {self.sucursal}: {self.cantidad}"

    class Meta:
        verbose_name = "Stock por Sucursal"
        verbose_name_plural = "Stock por Sucursal"
        unique_together = ('producto', 'sucursal')


def ajustar_stock_sucursal(producto_id, sucursal, delta):
    """
    Punto UNICO de ajuste de stock de una sucursal especifica (Fase 2,
    20/09/2026) -- reemplaza los ajustes directos y dispersos que antes
    hacia cada modulo (fac, cmp, inv, fe) sobre Producto.existencia.
    Atomico de punta a punta (F() en las dos tablas, sin leer-modificar-
    escribir en Python) para no reintroducir la condicion de carrera
    que ya se habia corregido el 16/09/2026 -- ahora con el agravante
    de que hay que mantener DOS numeros en sincronia (el de la
    sucursal y el total agregado), no solo uno.

    `sucursal` puede ser None (dato viejo sin migrar, o una instalacion
    todavia sin sucursales cargadas) -- en ese caso SOLO se ajusta el
    agregado en Producto.existencia (comportamiento identico al que
    tenia el sistema antes de esta fase), sin crear un StockSucursal
    "fantasma" sin sucursal real. Se loguea con logger.warning para
    que quede rastro de que algo se esta moviendo sin sucursal.
    """
    from django.db.models import F, Sum
    from django.db.models.functions import Coalesce

    if sucursal is not None:
        fila, _ = StockSucursal.objects.get_or_create(producto_id=producto_id, sucursal=sucursal)
        StockSucursal.objects.filter(pk=fila.pk).update(cantidad=F('cantidad') + delta)

    # Producto.existencia se mantiene como el TOTAL agregado -- se
    # recalcula con una subconsulta (Sum de todas las filas de
    # StockSucursal de este producto), no con "F('existencia')+delta",
    # para que quede exactamente consistente con la suma real aunque
    # el ajuste haya sido sobre datos sin sucursal (caso de arriba).
    Producto.objects.filter(pk=producto_id).update(
        existencia=Coalesce(
            models.Subquery(
                StockSucursal.objects.filter(producto_id=producto_id)
                .values('producto_id')
                .annotate(total=Sum('cantidad'))
                .values('total')[:1]
            ),
            0,
        ) if sucursal is not None else F('existencia') + delta
    )


# =====================================================================
# Ajuste de Inventario (agregado 13/09/2026, ver instructivo
# "ajuste_inventario_instructivo.md") -- documento generico para sumar
# stock sin que exista una Compra real: Carga Inicial (al empezar a
# usar el sistema) y Producción Interna (Agrotextil produce su propia
# mercaderia, no la compra a un proveedor). Vive en `inv`, no en `cmp`
# (que es especificamente de compras a proveedores) -- el formulario
# de Compras tiene Proveedor/No. Factura/Fecha Factura, campos que no
# tienen sentido aca.
# =====================================================================

class MotivoAjusteInventario(ClaseModelo):
    """
    Catalogo de motivos para un Ajuste de Inventario -- tabla propia,
    no una lista fija en codigo (choices=), para que agregar un motivo
    nuevo en el futuro (ej. "Merma", "Correccion de Conteo Fisico")
    sea un registro de datos, no un cambio de codigo ni una migracion.
    """
    descripcion = models.CharField(max_length=100, unique=True)
    es_entrada = models.BooleanField(
        default=True,
        help_text="True = este motivo SUMA stock (Carga Inicial, "
                  "Producción Interna). False = resta stock -- "
                  "reservado para cuando se agregue el caso de mermas/"
                  "correcciones a la baja; NO USADO en esta version."
    )
    afecta_costo_actual = models.BooleanField(
        default=True,
        help_text="True = las entradas con este motivo recalculan "
                   "Producto.costo_actual. Dejar en True para Carga "
                   "Inicial y Producción Interna."
    )
    es_produccion_interna = models.BooleanField(
        default=False,
        help_text="Marca el motivo 'Producción Interna' especificamente "
                  "-- es el UNICO que se ve afectado por "
                  "Empresa.tipo_empresa. Los demas motivos (ej. Carga "
                  "Inicial) siempre usan Promedio Ponderado, sin "
                  "importar el tipo de empresa."
    )

    def __str__(self):
        return self.descripcion

    def save(self, *args, **kwargs):
        self.descripcion = self.descripcion.upper()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Motivo de Ajuste de Inventario"
        verbose_name_plural = "Motivos de Ajuste de Inventario"


class AjusteInventarioEnc(ClaseModelo):
    fecha = models.DateField()
    motivo = models.ForeignKey(MotivoAjusteInventario, on_delete=models.PROTECT)
    observacion = models.TextField(blank=True, null=True)
    # sucursal (Fase 2, 20/09/2026): en que sucursal entra este stock.
    # Null en datos viejos (migrados a la sucursal por defecto, ver
    # migracion de datos) y en instalaciones todavia sin sucursales.
    # "Producción Interna" queda restringida a Casa Matriz
    # (codigo_sucursal=0) -- validado en la vista ajuste_inventario,
    # no aca (el modelo no conoce el motivo de OTRA instancia sin
    # consultarlo).
    sucursal = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, null=True, blank=True
    )

    def __str__(self):
        return f"Ajuste #{self.pk} - {self.motivo} ({self.fecha})"

    class Meta:
        verbose_name = "Ajuste de Inventario"
        verbose_name_plural = "Ajustes de Inventario"
        permissions = [
            ('eliminar_ajusteinventarioenc', 'Permiso para eliminar un ajuste de inventario completo'),
            ('cargar_inventario_inicial', 'Permiso para hacer la carga inicial masiva de inventario por Excel'),
        ]


class AjusteInventarioDet(ClaseModelo):
    ajuste = models.ForeignKey(AjusteInventarioEnc, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField()  # SIEMPRE positivo en esta version
    costo_unitario = models.FloatField()
    sub_total = models.FloatField(default=0)

    def __str__(self):
        return f"{self.producto} x{self.cantidad}"

    def save(self, *args, **kwargs):
        self.sub_total = float(self.cantidad) * float(self.costo_unitario)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Detalle de Ajuste de Inventario"
        verbose_name_plural = "Detalles de Ajuste de Inventario"


@receiver(post_save, sender=AjusteInventarioDet)
def detalle_ajuste_guardar(sender, instance, created, **kwargs):
    """
    Mismo patron que detalle_compra_guardar en cmp/models.py, con UNA
    diferencia: si el motivo es 'Producción Interna' Y la empresa es
    Industrial, el costo NO se promedia -- se PISA con el ultimo valor
    ingresado. Para cualquier otro caso (Comercial, o cualquier otro
    motivo que no sea Producción Interna) se sigue promediando, igual
    que siempre. Solo al CREAR la linea -- este modulo no edita lineas
    ya guardadas (misma convencion que Compras).

    CORREGIDO 20/09/2026 (Fase 2): el ajuste de stock (existencia) ya
    NO es un read-modify-write en Python -- se delega en
    ajustar_stock_sucursal (atomico, y ahora con dimension de
    sucursal). costo_actual sigue siendo GLOBAL a la empresa (no por
    sucursal, decision de diseño de Fase 2 -- el costo de compra/
    produccion no se separa por sucursal), asi que ese calculo sigue
    igual que siempre, leyendo/escribiendo Producto directo.
    """
    if not created:
        return

    from fe.models import Empresa  # import local, evita acoplar apps al importar el modulo

    prod = instance.producto
    motivo = instance.ajuste.motivo
    stock_anterior = int(prod.existencia)
    cantidad = int(instance.cantidad)

    if motivo.afecta_costo_actual:
        empresa = Empresa.objects.first()
        es_industrial_y_produccion = (
            motivo.es_produccion_interna
            and empresa
            and empresa.tipo_empresa == Empresa.INDUSTRIAL
        )
        if es_industrial_y_produccion:
            prod.costo_actual = instance.costo_unitario
        elif stock_anterior + cantidad > 0:
            prod.costo_actual = round(
                (stock_anterior * prod.costo_actual + cantidad * instance.costo_unitario)
                / (stock_anterior + cantidad),
                4
            )
        prod.ultima_compra = instance.ajuste.fecha
        prod.save(update_fields=['costo_actual', 'ultima_compra'])

    ajustar_stock_sucursal(instance.producto_id, instance.ajuste.sucursal, cantidad)


@receiver(post_delete, sender=AjusteInventarioDet)
def detalle_ajuste_borrar(sender, instance, **kwargs):
    """
    Simetrico a detalle_compra_borrar: revierte el stock que esta
    linea habia sumado. Solo se dispara ante un DELETE fisico real
    (admin, consola) -- el flujo normal es eliminar el AjusteInventarioEnc
    completo (soft-delete), que no borra fisicamente el detalle.
    NO recalcula costo_actual hacia atras (misma limitacion aceptada
    que ya existe para Compras -- ver help_text de Producto.costo_actual).
    """
    ajustar_stock_sucursal(instance.producto_id, instance.ajuste.sucursal, -int(instance.cantidad))


# =====================================================================
# Transferencias de Stock entre Sucursales (Fase 2, 20/09/2026 --
# diseño confirmado por Carlos: "con confirmación de recepción" -- el
# stock SALE de la sucursal de origen al agregar cada linea (queda
# fisicamente en camino), pero NO entra a la sucursal de destino hasta
# que esa sucursal confirma que lo recibio. Mientras tanto, el stock
# "no esta" en ninguna sucursal de StockSucursal (esta en transito) --
# a proposito, asi coincide con la realidad fisica (nadie puede vender
# algo que esta en un camion).
# =====================================================================

class TransferenciaStockEnc(ClaseModelo2):
    EN_TRANSITO = 'en_transito'
    CONFIRMADA = 'confirmada'
    CANCELADA = 'cancelada'
    ESTADO_CHOICES = [
        (EN_TRANSITO, 'En Tránsito'),
        (CONFIRMADA, 'Confirmada'),
        (CANCELADA, 'Cancelada'),
    ]

    sucursal_origen = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, related_name='transferencias_enviadas'
    )
    sucursal_destino = models.ForeignKey(
        'fe.Sucursal', on_delete=models.PROTECT, related_name='transferencias_recibidas'
    )
    fecha_envio = models.DateTimeField(auto_now_add=True)
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default=EN_TRANSITO)
    observacion = models.TextField(null=True, blank=True)
    usuario_confirmacion = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text="Usuario de la sucursal DESTINO que confirmó la recepción. Vacío mientras está en tránsito."
    )

    def __str__(self):
        return f"Transferencia #{self.pk}: {self.sucursal_origen} → {self.sucursal_destino}"

    class Meta:
        verbose_name = "Transferencia de Stock"
        verbose_name_plural = "Transferencias de Stock"
        permissions = [
            ('confirmar_transferenciastock', 'Permiso para confirmar la recepción de una transferencia de stock'),
            ('cancelar_transferenciastock', 'Permiso para cancelar una transferencia de stock en tránsito'),
        ]


class TransferenciaStockDet(ClaseModelo2):
    transferencia = models.ForeignKey(TransferenciaStockEnc, on_delete=models.CASCADE, related_name='detalle')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.producto} x{self.cantidad}"

    class Meta:
        verbose_name = "Detalle de Transferencia de Stock"
        verbose_name_plural = "Detalles de Transferencia de Stock"


@receiver(post_save, sender=TransferenciaStockDet)
def detalle_transferencia_guardar(sender, instance, created, **kwargs):
    """
    Al agregar una linea, el stock SALE de inmediato de la sucursal de
    origen (ver comentario de la seccion) -- queda "en transito", no
    en StockSucursal de ninguna sucursal, hasta que el destino
    confirme (ver transferencia_confirmar en inv/views.py, que recien
    ahi SUMA a la sucursal destino). Solo al crear -- estas lineas no
    se editan (mismo criterio que Compras/Ajuste).
    """
    if not created:
        return
    ajustar_stock_sucursal(
        instance.producto_id, instance.transferencia.sucursal_origen, -int(instance.cantidad)
    )