from django.db import models

from bases.models import ClaseModelo

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
        Mismo criterio que valida fe.services._validar_homologacion
        antes de emitir -- se expone aca como property para poder
        mostrarlo en pantalla (listado de productos, pantalla de
        homologacion) sin duplicar la logica.
        """
        return bool(
            self.actividad_economica_sin
            and self.codigo_producto_sin
            and self.unidad_medida_id
            and self.unidad_medida.codigo_sin
        )

    class Meta:
        verbose_name_plural= 'Productos'
        unique_together = ('codigo','codigo_barra')