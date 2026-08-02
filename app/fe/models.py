from django.db import models

from bases.models import ClaseModelo2


class Empresa(ClaseModelo2):
    """
    Configuracion de la empresa emisora ante el SIN. Pensado como fila
    unica (una instalacion = un NIT), coherente con la decision de
    arquitectura de una base de datos separada por cliente.

    Los datos de NIT/razon social recien se completan cuando el
    trabajo de formalizacion del negocio (gestion del NIT) este listo;
    mientras tanto puede quedar vacio o con datos provisionales.
    """
    NATURAL = 'Natural'
    JURIDICA = 'Jurídica'
    TIPO_PERSONA = [
        (NATURAL, 'Natural'),
        (JURIDICA, 'Jurídica'),
    ]

    PILOTO = 'Piloto'
    PRODUCCION = 'Producción'
    AMBIENTE = [
        (PILOTO, 'Piloto (pruebas)'),
        (PRODUCCION, 'Producción'),
    ]

    PROPIETARIO = 'Propietario'
    PROVEEDOR = 'Proveedor'
    TIPO_AUTORIZACION = [
        (PROPIETARIO, 'Propietario (uso exclusivo propio)'),
        (PROVEEDOR, 'Proveedor (ofrece el sistema a terceros)'),
    ]

    razon_social = models.CharField(max_length=150)
    nit = models.CharField(
        max_length=30, null=True, blank=True,
        help_text="Numero de Identificacion Tributaria. Se completa cuando este listo el tramite ante Impuestos Nacionales."
    )
    tipo_persona = models.CharField(
        max_length=10, choices=TIPO_PERSONA, default=NATURAL
    )
    codigo_actividad_economica = models.CharField(
        max_length=20, null=True, blank=True,
        help_text="Codigo CIIU segun el padron del SIN (se completa junto con el NIT)."
    )
    ambiente = models.CharField(
        max_length=10, choices=AMBIENTE, default=PILOTO,
        help_text="Mientras se este probando el sistema, debe quedar en Piloto."
    )

    # --- Datos de contacto / branding, para encabezados de factura ---
    telefono = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    logo = models.ImageField(
        upload_to='empresa/logos/', null=True, blank=True,
        help_text="Se usa en el encabezado de las facturas impresas/PDF."
    )

    # --- Autorizacion de Sistemas ante el SIN (tramite externo, en el
    # portal SIAT en Linea; aca solo se guarda el resultado) ---
    tipo_autorizacion = models.CharField(
        max_length=15, choices=TIPO_AUTORIZACION, default=PROPIETARIO,
        help_text="Propietario: este NIT usa el sistema solo para si mismo. "
                   "Proveedor: se ofrece el sistema a otros contribuyentes "
                   "(estos se vinculan despues via 'Asociacion', un tramite "
                   "mas simple que una autorizacion completa nueva)."
    )
    nombre_sistema = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="Nombre del sistema informatico tal como se declara ante el SIN."
    )
    version_sistema = models.CharField(max_length=20, null=True, blank=True)
    codigo_sistema = models.CharField(
        max_length=50, null=True, blank=True,
        help_text="Codigo que asigna el SIN al aprobar la Autorizacion de "
                   "Sistemas. Vacio hasta completar ese tramite."
    )
    fecha_autorizacion_sistema = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.razon_social or "Empresa (sin configurar)"

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresa (configuración SIN)"


class Sucursal(ClaseModelo2):
    """
    Cada sucursal se autoriza por separado ante el SIN y tiene su
    propio codigo (0 = casa matriz). El CUIS se guarda aca porque la
    autorizacion del sistema queda vinculada a NIT + sucursal.
    """
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="sucursales"
    )
    codigo_sucursal = models.PositiveIntegerField(
        help_text="Codigo de sucursal asignado por el SIN (0 = casa matriz)."
    )
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=250, null=True, blank=True)
    departamento = models.CharField(max_length=50, null=True, blank=True)

    # Se completan cuando se apruebe la Autorizacion de Sistemas (Paso 4-5)
    codigo_cuis = models.CharField(max_length=50, null=True, blank=True)
    fecha_autorizacion_cuis = models.DateTimeField(null=True, blank=True)
    fecha_vigencia_cuis = models.DateTimeField(
        null=True, blank=True,
        help_text="Fecha de vencimiento del CUIS (dato 'fechaVigencia' que devuelve el SIN). "
                   "El CUIS se puede renovar desde 5 dias antes de esta fecha."
    )

    def __str__(self):
        return '{} (Cod. {})'.format(self.nombre, self.codigo_sucursal)

    class Meta:
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"
        unique_together = ('empresa', 'codigo_sucursal')


class PuntoVenta(ClaseModelo2):
    """Punto de venta dentro de una sucursal, tambien asignado por el SIN."""

    COMISIONISTA = 1
    VENTANILLA_COBRANZA = 2
    MOVILES = 3
    YPFB = 4
    CAJEROS = 5
    CONJUNTA = 6
    TIPO_PUNTO_VENTA = [
        (COMISIONISTA, "Punto Venta Comisionista"),
        (VENTANILLA_COBRANZA, "Punto Venta Ventanilla de Cobranza"),
        (MOVILES, "Punto de Venta Móviles"),
        (YPFB, "Punto de Venta YPFB"),
        (CAJEROS, "Punto de Venta Cajeros"),
        (CONJUNTA, "Punto de Venta Conjunta"),
    ]

    sucursal = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, related_name="puntos_venta"
    )
    codigo_punto_venta = models.PositiveIntegerField(
        help_text="Codigo de punto de venta. IMPORTANTE: en la integracion real "
                   "este codigo lo ASIGNA el SIN como respuesta del servicio "
                   "registroPuntoVenta, no se elige a mano. Mientras tanto se "
                   "carga manualmente para poder armar la configuracion local."
    )
    codigo_tipo_punto_venta = models.PositiveSmallIntegerField(
        choices=TIPO_PUNTO_VENTA, default=MOVILES,
        help_text="Tipo de punto de venta exigido por el servicio registroPuntoVenta del SIN."
    )
    nombre = models.CharField(max_length=100)

    def __str__(self):
        return '{} (Cod. {})'.format(self.nombre, self.codigo_punto_venta)

    class Meta:
        verbose_name = "Punto de Venta"
        verbose_name_plural = "Puntos de Venta"
        unique_together = ('sucursal', 'codigo_punto_venta')
