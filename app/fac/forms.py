from django import forms

from .models import Cliente

class ClienteForm(forms.ModelForm):
    email = forms.EmailField(max_length=254)
    class Meta:
        model=Cliente
        fields=['nombres','apellidos','ci','nit','razon',
           'tipo','celular','email','estado','descuento_autorizado_pct',
           'autorizado_credito','plazo_credito_dias','limite_credito']
        labels = {'razon':"Razón Social",
                  "estado":"Estado",
                  "descuento_autorizado_pct":"Descuento Autorizado (%)",
                  "autorizado_credito":"Autorizado para Crédito",
                  "plazo_credito_dias":"Plazo de Crédito",
                  "limite_credito":"Límite de Crédito (Bs)"}   
        exclude = ['um','fm','uc','fc']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class': 'form-control'
            })
        self.fields['nit'].required = False

    def clean_nit(self):
        # Convierte "" (texto vacio, lo que manda el navegador si el
        # campo queda en blanco) a None ANTES de que Django valide la
        # unicidad -- si no, la validacion de unique=True del formulario
        # (que corre antes de llegar a save()) rechazaria al segundo
        # cliente sin NIT como si fuera un duplicado real.
        nit = self.cleaned_data.get('nit')
        return nit.strip() if nit else None