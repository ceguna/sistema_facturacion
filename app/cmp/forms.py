from django import forms

from .models import Proveedor, ComprasEnc

class ProveedorForm(forms.ModelForm):
    email = forms.EmailField(max_length=254)

    class Meta:
        model=Proveedor
        #Al no especificar los campos que va tomar, automaticamente toma todos
        exclude = ['um','fm','uc','fc'] #Excluye del formulario esos campos para que no se tomen en cuenta
        widget={'descripcion': forms.TextInput}
        labels = {'sucursal': 'Sucursal (vacío = compartido con todas)'}

    def __init__(self, *args, user=None, sucursal_actual=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })
        # Alcance (25/09/2026): un usuario limitado a su sucursal solo puede
        # crear proveedores de SU sucursal (no compartidos ni de otra); uno
        # sin restriccion puede elegir cualquiera o dejarlo compartido.
        from bases.alcance import sucursales_visibles_ids
        ids = sucursales_visibles_ids(user) if user is not None else None
        if ids is not None:
            self.fields['sucursal'].queryset = self.fields['sucursal'].queryset.filter(pk__in=ids)
            self.fields['sucursal'].required = True
            self.fields['sucursal'].empty_label = None
        if not self.instance.pk and sucursal_actual is not None and 'sucursal' not in self.initial:
            self.initial['sucursal'] = sucursal_actual.pk

    def clean(self):
        cleaned = super().clean()
        descripcion = (cleaned.get('descripcion') or '').upper()
        sucursal = cleaned.get('sucursal')
        if descripcion:
            repetido = Proveedor.objects.filter(descripcion=descripcion, sucursal=sucursal) \
                .exclude(pk=self.instance.pk).first()
            if repetido:
                raise forms.ValidationError(
                    "Registro Ya Existe" if not self.instance.pk
                    else "Cambio No Permitido, coincide con otro registro"
                )
        return cleaned

class ComprasEncForm(forms.ModelForm):

    class Meta:
        model=ComprasEnc 
        fields = ['proveedor','fecha_compra','observacion','no_factura', 
                  'fecha_factura','sub_total','descuento','total']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })
        self.fields['fecha_compra'].widget.attrs['readonly'] = True 
        self.fields['fecha_factura'].widget.attrs['readonly'] = True
        # Formato explicito (ISO) para que coincida con el datepicker JS
        # (formato 'Y-m-d') y no dependa del formato regional del navegador.
        self.fields['fecha_compra'].widget.format = '%Y-%m-%d'
        self.fields['fecha_compra'].input_formats = ['%Y-%m-%d']
        self.fields['fecha_factura'].widget.format = '%Y-%m-%d'
        self.fields['fecha_factura'].input_formats = ['%Y-%m-%d']
        self.fields['sub_total'].widget.attrs['readonly'] = True 
        self.fields['descuento'].widget.attrs['readonly'] = True
        self.fields['total'].widget.attrs['readonly'] = True 
       
