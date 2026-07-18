from django import forms

from .models import Cliente

class ClienteForm(forms.ModelForm):
    email = forms.EmailField(max_length=254)
    class Meta:
        model=Cliente
        fields=['nombres','apellidos','ci','nit','razon',
           'tipo','celular','email','estado']
        labels = {'razon':"Razón Social",
                  "estado":"Estado"}   
        exclude = ['um','fm','uc','fc']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({
                'class': 'form-control'
            })