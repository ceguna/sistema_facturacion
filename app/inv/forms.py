from django import forms

from .models import Categoria, SubCategoria, Marca, UnidadMedida, Producto, TipoCambio

class CategoriaForm(forms.ModelForm):
    class Meta:
        model=Categoria
        fields = ['descripcion','estado']
        labels = {'descripcion':"Descripción de la Categoría",
                "estado":"Estado"}   
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })

class SubCategoriaForm(forms.ModelForm):
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.filter(estado=True)
        .order_by('descripcion')
    )
    class Meta:
        model=SubCategoria
        fields = ['categoria','descripcion','estado']
        labels = {'descripcion':"Sub Categoría",
                "estado":"Estado"}   
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })
        self.fields['categoria'].empty_label = "Seleccione Categoría"

class MarcaForm(forms.ModelForm):
    class Meta:
        model=Marca
        fields = ['descripcion','estado']
        labels = {'descripcion':"Descripción de la Marca",
                "estado":"Estado"}   
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })

class UnidadMedidaForm(forms.ModelForm):
    class Meta:
        model=UnidadMedida
        fields = ['descripcion','estado']
        labels = {'descripcion':"Descripción de la Unidad de Medida",
                "estado":"Estado"}   
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })

class ProductoForm(forms.ModelForm):
    class Meta:
        model=Producto
        fields = ['codigo','codigo_barra','descripcion','estado', 
                'precio','existencia','ultima_compra',
                'marca','subcategoria','unidad_medida','foto',
                'descuento_promocional_pct','descuento_vigencia_desde',
                'descuento_vigencia_hasta','costo_referencia_usd',
                'margen_deseado_pct']
        exclude = ['um','fm','uc','fc']
        labels = {'descripcion':"Descripción del Producto",
                "estado":"Estado",
                "descuento_promocional_pct":"Descuento Promocional (%)",
                "descuento_vigencia_desde":"Vigente Desde",
                "descuento_vigencia_hasta":"Vigente Hasta",
                "costo_referencia_usd":"Costo Referencia (USD)",
                "margen_deseado_pct":"Margen Deseado (%)"}
        widgets = {
            'descripcion': forms.TextInput,
            'descuento_vigencia_desde': forms.DateInput(
                format='%Y-%m-%d', attrs={'autocomplete': 'off'}
            ),
            'descuento_vigencia_hasta': forms.DateInput(
                format='%Y-%m-%d', attrs={'autocomplete': 'off'}
            ),
        }

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })
        self.fields['ultima_compra'].widget.attrs['readonly'] = True
        self.fields['existencia'].widget.attrs['readonly'] = True
        self.fields['descuento_vigencia_desde'].required = False
        self.fields['descuento_vigencia_hasta'].required = False
        self.fields['descuento_vigencia_desde'].input_formats = ['%Y-%m-%d']
        self.fields['descuento_vigencia_hasta'].input_formats = ['%Y-%m-%d']
        self.fields['costo_referencia_usd'].required = False
        self.fields['margen_deseado_pct'].required = False

    def clean(self):
        cleaned = super().clean()
        pct = cleaned.get('descuento_promocional_pct') or 0
        desde = cleaned.get('descuento_vigencia_desde')
        hasta = cleaned.get('descuento_vigencia_hasta')

        if pct > 0:
            if not desde or not hasta:
                raise forms.ValidationError(
                    "Si ingresa un Descuento Promocional, debe indicar tambien "
                    "la Vigencia Desde y Hasta."
                )
            if hasta <= desde:
                raise forms.ValidationError(
                    "La fecha 'Vigente Hasta' debe ser posterior a 'Vigente Desde' "
                    "(no puede ser la misma fecha ni una anterior)."
                )
        else:
            cleaned['descuento_vigencia_desde'] = None
            cleaned['descuento_vigencia_hasta'] = None

        try:
            sc = Producto.objects.get(
                codigo=cleaned['codigo'].upper()
            )
            if not self.instance.pk:
                raise forms.ValidationError("Registro ya existe")
            elif self.instance.pk!= sc.pk:
                raise forms.ValidationError("Cambio No permitido, coincide con otro registro")
        except Producto.DoesNotExist:
            pass
        return cleaned


class TipoCambioForm(forms.ModelForm):
    class Meta:
        model = TipoCambio
        fields = ['fecha', 'valor', 'fuente', 'estado']
        labels = {
            'fecha': 'Fecha',
            'valor': 'Valor (Bs por 1 USD)',
            'fuente': 'Fuente',
            'estado': 'Estado',
        }
        widgets = {
            'fecha': forms.DateInput(format='%Y-%m-%d', attrs={'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class': 'form-control'
            })
        self.fields['fecha'].input_formats = ['%Y-%m-%d']