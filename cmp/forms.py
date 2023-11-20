from django import forms

from .models import Proveedor, ComprasEnc

class ProveedorForm(forms.ModelForm):
    email = forms.EmailField(max_length=254)
    class Meta:
        model=Proveedor 
        #Al no especificar los campos que va tomar, automaticamente toma todos
        exclude = ['um','fm','uc','fc'] #Excluye del formulario esos campos para que no se tomen en cuenta
        widget={'descripcion': forms.TextInput}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class':'form-control'
            })

    def clean(self): #Clean abarca a todos los campos del formulario
        try:
            #Luego se toma de la instancia el campo unique con el metodo GET del modelo proveedor.
            sc = Proveedor.objects.get(
                descripcion=self.cleaned_data["descripcion"].upper()
            )

            if not self.instance.pk:
                print("Registro ya existe")
                raise forms.ValidationError("Registro Ya Existe")
            elif self.instance.pk!=sc.pk:
                print("Cambio no permitido")
                raise forms.ValidationError("Cambio No Permitido, coincide con otro registro")
        #Si no encuentra el objeto, entonces manda un error para que se continue sin problema
        except Proveedor.DoesNotExist: 
            pass
        return self.cleaned_data #Se retorna toda la data que se valido

class ComprasEncForm(forms.ModelForm):
    fecha_compra = forms.DateInput()
    fecha_factura = forms.DateInput()

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
        self.fields['sub_total'].widget.attrs['readonly'] = True 
        self.fields['descuento'].widget.attrs['readonly'] = True
        self.fields['total'].widget.attrs['readonly'] = True 
       
