from django import forms

from .models import Empresa, Sucursal, PuntoVenta


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            'razon_social', 'nit', 'tipo_persona', 'codigo_actividad_economica',
            'ambiente', 'telefono', 'email', 'logo',
            'tipo_autorizacion', 'nombre_sistema', 'version_sistema', 'codigo_sistema',
        ]
        widgets = {
            'razon_social': forms.TextInput(attrs={'class': 'form-control'}),
            'nit': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Se completa cuando este listo el tramite del NIT'}),
            'tipo_persona': forms.Select(attrs={'class': 'form-control'}),
            'codigo_actividad_economica': forms.TextInput(attrs={'class': 'form-control'}),
            'ambiente': forms.Select(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control-file'}),
            'tipo_autorizacion': forms.Select(attrs={'class': 'form-control'}),
            'nombre_sistema': forms.TextInput(attrs={'class': 'form-control'}),
            'version_sistema': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo_sistema': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Lo asigna el SIN al aprobar la Autorización de Sistemas'}),
        }
        labels = {
            'razon_social': 'Razón Social',
            'nit': 'NIT',
            'tipo_persona': 'Tipo de Persona',
            'codigo_actividad_economica': 'Código Actividad Económica (CIIU)',
            'ambiente': 'Ambiente',
            'telefono': 'Teléfono',
            'email': 'Correo Electrónico',
            'logo': 'Logo (para facturas impresas/PDF)',
            'tipo_autorizacion': 'Tipo de Autorización SIN',
            'nombre_sistema': 'Nombre del Sistema (declarado ante el SIN)',
            'version_sistema': 'Versión del Sistema',
            'codigo_sistema': 'Código de Sistema (asignado por el SIN)',
        }


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = ['codigo_sucursal', 'nombre', 'direccion', 'departamento']
        widgets = {
            'codigo_sucursal': forms.NumberInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'departamento': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'codigo_sucursal': 'Código de Sucursal (SIN)',
            'nombre': 'Nombre',
            'direccion': 'Dirección',
            'departamento': 'Departamento',
        }


class PuntoVentaForm(forms.ModelForm):
    class Meta:
        model = PuntoVenta
        fields = ['codigo_punto_venta', 'codigo_tipo_punto_venta', 'nombre']
        widgets = {
            'codigo_punto_venta': forms.NumberInput(attrs={'class': 'form-control'}),
            'codigo_tipo_punto_venta': forms.Select(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'codigo_punto_venta': 'Código de Punto de Venta (SIN)',
            'codigo_tipo_punto_venta': 'Tipo de Punto de Venta',
            'nombre': 'Nombre',
        }
