from django import forms

from .models import Categoria, SubCategoria, Marca, UnidadMedida, Producto

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
                  'marca','subcategoria','unidad_medida']
        exclude = ['um','fm','uc','fc'] #Excluye del formulario esos campos para que no se tomen en cuenta
        labels = {'descripcion':"Descripción del Producto",
                  "estado":"Estado"}   
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })
        self.fields['ultima_compra'].widget.attrs['readonly'] = True #Esto hace que en el formulario aparezca estos campos como solo lectura
        self.fields['existencia'].widget.attrs['readonly'] = True

    def clean(self):
        try:
            sc = Producto.objects.get(
                codigo=self.cleaned_data['codigo'].upper()
            )
            if not self.instance.pk:
                raise forms.ValidationError("Registro ya existe")
            elif self.instance.pk!= sc.pk:
                raise forms.ValidationError("Cambio No permitido, coincide con otro registro")
        except Producto.DoesNotExist:
            pass
        return self.cleaned_data