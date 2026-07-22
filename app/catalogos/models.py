from django.db import models


class CatalogoSIN(models.Model):
    """
    Tabla genérica para los catálogos paramétricos que el SIN exige
    sincronizar diariamente (Art. 19 RND 101800000026).

    No incluye 'Fecha y Hora': ese es un servicio de sincronización de
    reloj (Art. 20), no una lista de código/descripción, y se maneja
    aparte en el momento de conectar con el ambiente Piloto (Paso 4).
    """

    class TipoCatalogo(models.TextChoices):
        ACTIVIDADES = 'ACTIVIDADES', 'Códigos de Actividades'
        ACTIVIDADES_DOC_SECTOR = 'ACT_DOC_SECTOR', 'Actividades Documento Sector'
        LEYENDAS = 'LEYENDAS', 'Leyendas Facturas'
        MENSAJES = 'MENSAJES', 'Mensajes Servicios'
        EVENTOS_SIGNIFICATIVOS = 'EVENTOS', 'Eventos Significativos'
        MOTIVOS_ANULACION = 'MOTIVOS_ANULACION', 'Motivos Anulación'
        PAIS_ORIGEN = 'PAIS', 'País Origen'
        TIPO_DOC_IDENTIDAD = 'TIPO_DOC_IDENTIDAD', 'Tipo Documento Identidad'
        TIPO_DOC_SECTOR = 'TIPO_DOC_SECTOR', 'Tipo Documento Sector'
        TIPO_EMISION = 'TIPO_EMISION', 'Tipo Emisión'
        TIPO_HABITACION = 'TIPO_HABITACION', 'Tipo Habitación'  # No aplica al rubro de Carlos (librería); se sincroniza igual porque el SIN lo exige, pero no se usará en los formularios.
        TIPO_METODO_PAGO = 'TIPO_METODO_PAGO', 'Tipo Método Pago'
        TIPO_MONEDA = 'TIPO_MONEDA', 'Tipo Moneda'
        TIPO_PUNTO_VENTA = 'TIPO_PUNTO_VENTA', 'Tipo Punto de Venta'
        TIPO_FACTURA = 'TIPO_FACTURA', 'Tipo Factura'
        TIPO_UNIDAD_MEDIDA = 'TIPO_UNIDAD_MEDIDA', 'Tipo Unidad de Medida'

    tipo_catalogo = models.CharField(
        max_length=30,
        choices=TipoCatalogo.choices,
        db_index=True,
        help_text="A qué catálogo del SIN pertenece este código."
    )
    codigo = models.CharField(
        max_length=20,
        help_text="Código tal como lo entrega el SIN (se guarda como texto aunque sea numérico, por seguridad ante ceros a la izquierda u otros formatos)."
    )
    descripcion = models.CharField(max_length=255)
    vigente = models.BooleanField(
        default=True,
        help_text="Se marca False si una sincronización posterior ya no trae este código (baja lógica, nunca se borra el histórico)."
    )
    fecha_sincronizacion = models.DateTimeField(
        auto_now=True,
        help_text="Última vez que este registro fue confirmado por el SIN."
    )

    class Meta:
        verbose_name = "Catálogo SIN"
        verbose_name_plural = "Catálogos SIN"
        unique_together = ("tipo_catalogo", "codigo")
        ordering = ["tipo_catalogo", "codigo"]

    def __str__(self):
        return f"[{self.get_tipo_catalogo_display()}] {self.codigo} - {self.descripcion}"


class SincronizacionLog(models.Model):
    """
    Registro de cada corrida de sincronización diaria de catálogos.
    Permite auditar si corrió bien, cuándo, y qué falló si hubo error.
    """

    fecha_ejecucion = models.DateTimeField(auto_now_add=True)
    exitosa = models.BooleanField(default=False)
    catalogos_sincronizados = models.PositiveIntegerField(
        default=0,
        help_text="Cuántos de los 16 catálogos se actualizaron correctamente en esta corrida."
    )
    total_codigos_actualizados = models.PositiveIntegerField(
        default=0,
        help_text="Suma de códigos nuevos o modificados across todos los catálogos."
    )
    mensaje = models.TextField(
        blank=True,
        help_text="Detalle del error si exitosa=False, o resumen si exitosa=True."
    )

    class Meta:
        verbose_name = "Log de Sincronización SIN"
        verbose_name_plural = "Logs de Sincronización SIN"
        ordering = ["-fecha_ejecucion"]

    def __str__(self):
        estado = "OK" if self.exitosa else "ERROR"
        return f"{self.fecha_ejecucion:%Y-%m-%d %H:%M} — {estado}"