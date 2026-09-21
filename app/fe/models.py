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
    # direccion (19/09/2026, pedido de Carlos): distinta de
    # Sucursal.direccion -- esa es por-sucursal y todavia no hay forma
    # de saber desde que sucursal salio cada factura (FacturaEnc no
    # tiene ese FK, ver Fase 2 pendiente). Esta es la direccion de la
    # empresa a nivel general, siempre disponible sin depender de esa
    # relacion; el encabezado de la factura la usa como principal y
    # solo recurre a la de la sucursal si esta queda vacia.
    direccion = models.CharField(
        max_length=250, null=True, blank=True,
        help_text="Dirección principal de la empresa. Aparece en el encabezado de las facturas."
    )
    telefono = models.CharField(max_length=30, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    logo = models.ImageField(
        upload_to='empresa/logos/', null=True, blank=True,
        help_text="Se usa en el encabezado de las facturas impresas/PDF."
    )

    # --- Cobro por QR (QR Simple interbancario, ver app/fac README) ---
    qr_cobro = models.ImageField(
        upload_to='empresa/qr_cobro/', null=True, blank=True,
        help_text="Imagen del QR de cobro estatico (QR Simple) solicitado "
                   "al banco. Se muestra en el recibo de venta para que el "
                   "cliente pueda escanearlo y transferir el monto a mano "
                   "(el QR estatico no lleva el monto incrustado)."
    )
    banco_qr = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="Nombre del banco emisor del QR de cobro (solo informativo, "
                   "se muestra junto al QR en el recibo)."
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

    # --- Tipo de empresa (agregado 13/09/2026, instructivo de Ajuste
    # de Inventario) -- decide COMO se calcula Producto.costo_actual,
    # pero SOLO cuando se registra una entrada por motivo "Producción
    # Interna". Compras NUNCA se ve afectado por este campo: la compra
    # de insumos/materia prima es un modulo de costeo aparte, fuera de
    # alcance por ahora. Se define al registrar la empresa; no se
    # espera que cambie despues (no hay forma de inferirlo solo -- se
    # carga a mano por instalacion).
    COMERCIAL = 'COMERCIAL'
    INDUSTRIAL = 'INDUSTRIAL'
    TIPO_EMPRESA_CHOICES = [
        (COMERCIAL, 'Comercial'),
        (INDUSTRIAL, 'Industrial'),
    ]
    tipo_empresa = models.CharField(
        max_length=20, choices=TIPO_EMPRESA_CHOICES, default=COMERCIAL,
        # Texto de ayuda acortado (19/09/2026, pedido de Carlos) -- la
        # explicacion tecnica completa (por que/como se calcula, que
        # NO afecta) queda documentada arriba en el comentario del
        # campo, no en el help_text que ve el usuario del formulario.
        help_text="Afecta solo el costeo de Producción Interna: Comercial "
                   "promedia el costo, Industrial usa el último valor cargado."
    )

    # --- Formato de impresion/envio de facturas (agregado 17/09/2026,
    # pedido de Carlos: dos opciones oficiales de representacion
    # grafica -- tamaño carta (factura_pdf.html) o rollo termico/quimico
    # 58mm (factura_pdf_termico.html, mismo diseño que ya usa la caja
    # en factura_one.html, pero renderizado a PDF). El administrador
    # elige UNA sola por instalacion; se usa para los 4 caminos donde
    # se genera el documento: Ver en Pantalla, Descargar PDF, envio por
    # correo, y lo que se comparte por WhatsApp (mismo PDF que se
    # descarga) -- una sola fuente de verdad (generar_pdf_factura_bytes
    # en fac/reportes.py) para que nunca queden desincronizados.
    CARTA = 'CARTA'
    TERMICO = 'TERMICO'
    FORMATO_FACTURA_CHOICES = [
        (CARTA, 'Tamaño Carta (hoja A4/carta)'),
        (TERMICO, 'Rollo térmico/químico (58mm, impresora de tickets)'),
    ]
    formato_factura = models.CharField(
        max_length=10, choices=FORMATO_FACTURA_CHOICES, default=TERMICO,
        help_text="Formato que se usa para mostrar, descargar, y enviar por "
                   "correo/WhatsApp las facturas. Por defecto Rollo térmico "
                   "(el que ya usaba el sistema en la caja)."
    )

    # --- Correo saliente propio (agregado 16/09/2026, Fase 1) -- cada
    # empresa/cliente registra SU PROPIA cuenta de correo desde aca en
    # vez de depender de que alguien edite el .env del servidor a mano.
    # Queda vacio por defecto: si esta vacio, fac.views.factura_enviar_correo
    # usa el EMAIL_HOST/EMAIL_HOST_USER/etc de settings.py (.env) como
    # respaldo -- asi la libreria puede seguir usando lo que ya se cargo
    # en .env sin tener que volver a escribirlo aca.
    email_host = models.CharField(
        max_length=150, null=True, blank=True,
        help_text="Servidor SMTP saliente (ej. smtp.gmail.com). Vacío = usa la configuración del servidor (.env)."
    )
    email_port = models.PositiveIntegerField(default=587, null=True, blank=True)
    email_host_user = models.CharField(
        max_length=150, null=True, blank=True,
        help_text="Cuenta de correo desde la que se envían las facturas."
    )
    email_host_password = models.CharField(
        max_length=150, null=True, blank=True,
        help_text="Contraseña o 'contraseña de aplicación' de esa cuenta. "
                   "No se muestra en pantalla una vez guardada."
    )
    email_use_tls = models.BooleanField(default=True)

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
    municipio = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="Municipio (distinto del departamento) — obligatorio para el XML "
                   "de factura electrónica. Ej: depto 'Santa Cruz', municipio "
                   "'Santa Cruz de la Sierra'."
    )

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
        help_text="Codigo de punto de venta que ASIGNA el SIN como respuesta "
                   "del servicio registroPuntoVenta -- se completa solo al "
                   "guardar un punto de venta nuevo, no se elige a mano."
    )
    codigo_tipo_punto_venta = models.PositiveSmallIntegerField(
        choices=TIPO_PUNTO_VENTA, default=MOVILES,
        help_text="Tipo de punto de venta exigido por el servicio registroPuntoVenta del SIN."
    )
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(
        max_length=250, null=True, blank=True,
        help_text="Descripcion del punto de venta -- campo 'descripcion' "
                   "exigido por separado del nombre en registroPuntoVenta."
    )

    # Cada combinacion Sucursal+PuntoVenta tiene su PROPIO CUIS -- no se
    # puede reutilizar el de la Sucursal (codigo_punto_venta=0) para
    # ningun otro punto de venta. Confirmado con datos reales: mismo
    # NIT/sistema/sucursal, distinto codigoPuntoVenta, el SIN devolvio
    # dos CUIS distintos (31477C6C para 0, 558F4FB7 para 1).
    codigo_cuis = models.CharField(max_length=50, null=True, blank=True)
    fecha_autorizacion_cuis = models.DateTimeField(null=True, blank=True)
    fecha_vigencia_cuis = models.DateTimeField(
        null=True, blank=True,
        help_text="Fecha de vencimiento del CUIS de este punto de venta (dato 'fechaVigencia' "
                   "que devuelve el SIN). Renovable desde 5 dias antes de esta fecha."
    )

    def __str__(self):
        return '{} (Cod. {})'.format(self.nombre, self.codigo_punto_venta)

    class Meta:
        verbose_name = "Punto de Venta"
        verbose_name_plural = "Puntos de Venta"
        unique_together = ('sucursal', 'codigo_punto_venta')


class CUFDVigente(models.Model):
    """
    Ultimo CUFD obtenido con exito del SIN, por Sucursal+punto de venta
    (Fase A, contingencia, 21/09/2026). Se actualiza solo, como efecto
    secundario de cada CUFD pedido con exito (ver _pedir_cufd en
    fe/services.py) -- es la unica forma de poder seguir firmando
    facturas OFFLINE cuando el SIN se vuelve inalcanzable: el CUFD ya
    esta guardado de ANTES del corte, no hace falta pedirlo de nuevo en
    ese momento (lo cual requeriria, contradictoriamente, tener
    conexion). Un solo registro por combinacion -- se pisa, no se
    acumula historial.
    """
    sucursal = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, related_name='cufd_vigentes'
    )
    codigo_punto_venta = models.PositiveIntegerField(default=0)
    cufd = models.CharField(max_length=150)
    codigo_control = models.CharField(max_length=100)
    fecha_obtencion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "CUFD Vigente (caché offline)"
        verbose_name_plural = "CUFD Vigentes (caché offline)"
        unique_together = ('sucursal', 'codigo_punto_venta')

    def __str__(self):
        return f"CUFD de {self.sucursal} / PV {self.codigo_punto_venta} (obtenido {self.fecha_obtencion:%d/%m/%Y %H:%M})"