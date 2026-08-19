from django.db import models

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
    costo_referencia_usd = models.FloatField(
        null=True, blank=True,
        help_text="Costo del producto en USD, para productos importados. "
                   "Vacio = producto sin costo en moneda extranjera."
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
        tiene costo de referencia en USD cargado.
        """
        if not self.costo_referencia_usd or not tipo_cambio_actual:
            return None
        costo_bs = self.costo_referencia_usd * tipo_cambio_actual.valor
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

