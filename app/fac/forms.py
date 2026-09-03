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

    def clean(self):
        # Si el cliente queda autorizado para credito, plazo_credito_dias
        # y limite_credito NO pueden quedar vacios/en 0 -- si no, la
        # inconsistencia recien se descubre al momento de facturar (las
        # validaciones de fac/views.py rechazan la venta ahi), cuando ya
        # es tarde para el cajero. Se corta aca, al guardar el cliente.
        cleaned_data = super().clean()
        autorizado_credito = cleaned_data.get('autorizado_credito')
        plazo_credito_dias = cleaned_data.get('plazo_credito_dias')
        limite_credito = cleaned_data.get('limite_credito')

        if autorizado_credito:
            if not plazo_credito_dias:
                self.add_error(
                    'plazo_credito_dias',
                    'Debe seleccionar un plazo de crédito si el cliente está autorizado.'
                )
            if not limite_credito or limite_credito <= 0:
                self.add_error(
                    'limite_credito',
                    'Debe indicar un límite de crédito mayor a 0 si el cliente está autorizado.'
                )

        return cleaned_data