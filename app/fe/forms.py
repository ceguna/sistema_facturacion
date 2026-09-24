from django import forms

from .models import Empresa, Sucursal, PuntoVenta


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            'razon_social', 'nit', 'tipo_persona', 'codigo_actividad_economica',
            'ambiente', 'direccion', 'telefono', 'email', 'logo',
            'qr_cobro', 'banco_qr',
            'tipo_autorizacion', 'nombre_sistema', 'version_sistema', 'codigo_sistema',
            'tipo_empresa', 'formato_factura',
            'email_host', 'email_port', 'email_host_user', 'email_host_password', 'email_use_tls',
        ]
        widgets = {
            # no-uppercase (17/09/2026, pedido de Carlos): la razon
            # social de la empresa debe poder cargarse tal cual está
            # registrada legalmente, sin que la regla global de
            # mayusculas de base.html la fuerce mientras se escribe.
            'razon_social': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
            'tipo_empresa': forms.Select(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Se completa cuando este listo el tramite del NIT'}),
            'tipo_persona': forms.Select(attrs={'class': 'form-control'}),
            'codigo_actividad_economica': forms.TextInput(attrs={'class': 'form-control'}),
            'ambiente': forms.Select(attrs={'class': 'form-control'}),
            # no-uppercase (19/09/2026, pedido de Carlos): mismo criterio
            # que razon_social -- una direccion se escribe naturalmente
            # con mayusculas/minusculas mezcladas (calles, nombres propios).
            'direccion': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'qr_cobro': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'banco_qr': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Banco Unión, BCP, BNB...'}),
            'tipo_autorizacion': forms.Select(attrs={'class': 'form-control'}),
            'formato_factura': forms.Select(attrs={'class': 'form-control'}),
            'nombre_sistema': forms.TextInput(attrs={'class': 'form-control'}),
            'version_sistema': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo_sistema': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Lo asigna el SIN al aprobar la Autorización de Sistemas'}),
            # no-uppercase (17/09/2026, pedido de Carlos): base.html
            # convierte a mayuscula cualquier <input type="text"> mientras
            # se escribe (regla global del sistema) -- para datos de SMTP
            # eso arruina host/usuario/contraseña, que son sensibles a
            # mayusculas/minusculas. email_host es el unico que en verdad
            # corria ese riesgo (los otros tres ya quedan afuera por su
            # 'type'); se agrega la clase a los cuatro para dejarlo
            # explicito y a prueba de cambios futuros de widget.
            'email_host': forms.TextInput(attrs={
                'class': 'form-control no-uppercase', 'placeholder': 'Ej: smtp.gmail.com'}),
            'email_port': forms.NumberInput(attrs={'class': 'form-control no-uppercase'}),
            'email_host_user': forms.EmailInput(attrs={
                'class': 'form-control no-uppercase', 'placeholder': 'Cuenta desde la que se envían las facturas'}),
            # render_value=False (16/09/2026): sin esto, Django repite la
            # contraseña YA guardada en el HTML de la pagina cada vez que
            # se abre el formulario -- queda expuesta en el codigo fuente
            # de la pantalla sin necesidad. Con esto, el campo se ve
            # vacio al entrar (no significa que no haya nada guardado);
            # solo se pisa si se escribe una nueva.
            'email_host_password': forms.PasswordInput(
                attrs={'class': 'form-control no-uppercase', 'placeholder': 'Dejar en blanco para no cambiarla', 'autocomplete': 'new-password'},
                render_value=False,
            ),
            'email_use_tls': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'razon_social': 'Razón Social',
            'nit': 'NIT',
            'tipo_persona': 'Tipo de Persona',
            'codigo_actividad_economica': 'Código Actividad Económica (CIIU)',
            'ambiente': 'Ambiente',
            'direccion': 'Dirección',
            'telefono': 'Teléfono',
            'email': 'Correo Electrónico',
            'logo': 'Logo (aparece en las facturas y en el menú del sistema)',
            'qr_cobro': 'QR de Cobro (para recibos de venta)',
            'banco_qr': 'Banco emisor del QR',
            'tipo_autorizacion': 'Tipo de Autorización SIN',
            'formato_factura': 'Formato de impresión/envío de facturas',
            'nombre_sistema': 'Nombre del Sistema (declarado ante el SIN)',
            'version_sistema': 'Versión del Sistema',
            'codigo_sistema': 'Código de Sistema (asignado por el SIN)',
            'email_host': 'Servidor SMTP',
            'email_port': 'Puerto SMTP',
            'email_host_user': 'Cuenta de correo',
            'email_host_password': 'Contraseña / contraseña de aplicación',
            'email_use_tls': 'Usar TLS',
        }

    def clean_email_host_password(self):
        # El campo se muestra siempre vacio (render_value=False, ver
        # widget arriba) -- si el usuario lo deja en blanco, NO hay que
        # pisar la contraseña ya guardada con un string vacio, o se
        # rompe el envio de correo la proxima vez sin que nadie lo haya
        # tocado a proposito.
        nueva = self.cleaned_data.get('email_host_password')
        if not nueva and self.instance and self.instance.pk:
            return self.instance.email_host_password
        return nueva


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = ['codigo_sucursal', 'nombre', 'direccion', 'departamento', 'municipio']
        widgets = {
            'codigo_sucursal': forms.NumberInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
            # no-uppercase (21/09/2026, pedido de Carlos): mismo criterio que
            # Empresa.direccion -- una direccion se escribe naturalmente, no
            # tiene sentido forzarla a mayusculas.
            'direccion': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
            'departamento': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
            'municipio': forms.TextInput(attrs={'class': 'form-control no-uppercase'}),
        }
        labels = {
            'codigo_sucursal': 'Código de Sucursal (SIN)',
            'nombre': 'Nombre',
            'direccion': 'Dirección',
            'departamento': 'Departamento',
            'municipio': 'Municipio',
        }


class PuntoVentaForm(forms.ModelForm):
    """
    NO incluye 'codigo_punto_venta' -- ese valor lo asigna el SIN como
    respuesta de registroPuntoVenta (ver PuntoVentaNew.form_valid en
    views.py), nunca se elige a mano desde este formulario. 'descripcion'
    es un campo nuevo, exigido por separado del nombre en ese mismo
    servicio.
    """
    class Meta:
        model = PuntoVenta
        fields = ['nombre', 'descripcion', 'codigo_tipo_punto_venta']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo_tipo_punto_venta': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'nombre': 'Nombre',
            'descripcion': 'Descripción',
            'codigo_tipo_punto_venta': 'Tipo de Punto de Venta',
        }