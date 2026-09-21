from django import forms

from .models import (
    Categoria, SubCategoria, Marca, UnidadMedida, Producto, TipoCambio,
    AjusteInventarioEnc, MotivoAjusteInventario,
)

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
        # 'costo_actual' NO forma parte de este formulario a proposito
        # (igual que antes, cuando se llamaba costo_promedio): es un
        # campo puramente calculado por las señales de Compras/Ajuste
        # de Inventario, nunca por el usuario. Se muestra en la
        # plantilla directamente desde 'obj' (solo lectura real, sin
        # pasar por el ciclo de validacion del form) -- ver
        # producto_form.html.
        fields = ['codigo','codigo_barra','descripcion','estado',
                'precio','existencia','ultima_compra',
                'marca','subcategoria','unidad_medida','foto',
                'descuento_promocional_pct','descuento_vigencia_desde',
                'descuento_vigencia_hasta','precio_referencia_usd',
                'margen_deseado_pct']
        exclude = ['um','fm','uc','fc']
        labels = {'descripcion':"Descripción del Producto",
                "estado":"Estado",
                "precio":"Precio de Venta",
                "descuento_promocional_pct":"Descuento Promocional (%)",
                "descuento_vigencia_desde":"Vigente Desde",
                "descuento_vigencia_hasta":"Vigente Hasta",
                "precio_referencia_usd":"Precio Referencial (USD)",
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
        # CORREGIDO 12/09/2026: el select de Categoria/Sub Categoria se
        # arma a mano en la plantilla (no es un campo real del modelo,
        # solo filtra el chained de Sub Categoria), pero la validacion
        # real cae sobre 'subcategoria' -- antes mostraba el mensaje
        # generico de Django ("Este campo es requerido"/"Seleccione
        # una opcion valida...") que no orientaba a donde mirar.
        self.fields['subcategoria'].error_messages.update({
            'required': 'Debe seleccionar categoría.',
            'invalid_choice': 'Debe seleccionar categoría.',
        })
        self.fields['ultima_compra'].widget.attrs['readonly'] = True
        self.fields['existencia'].widget.attrs['readonly'] = True
        # CORREGIDO 07/09/2026: ninguno de los dos tenia el 'required'
        # anulado, asi que Django lo calculaba solo desde el modelo (que
        # no tiene blank=True en ninguno) -- por eso llevaban asterisco
        # sin corresponder. Existencia es de solo lectura (el sistema la
        # calcula, el usuario nunca la tipea) y Descuento Promocional es
        # opcional (un producto puede no tener ninguna promocion).
        self.fields['existencia'].required = False
        self.fields['descuento_promocional_pct'].required = False
        self.fields['descuento_vigencia_desde'].required = False
        self.fields['descuento_vigencia_hasta'].required = False
        self.fields['descuento_vigencia_desde'].input_formats = ['%Y-%m-%d']
        self.fields['descuento_vigencia_hasta'].input_formats = ['%Y-%m-%d']
        # CORREGIDO 06/09/2026: Precio Referencial y Margen Deseado pasan
        # a ser OBLIGATORIOS -- con el dolar fluctuando tanto al alza,
        # sin estos dos datos no se puede calcular un precio de venta
        # sugerido confiable en "Revision de Precios".
        self.fields['precio_referencia_usd'].required = True
        self.fields['margen_deseado_pct'].required = True

        # Asterisco automatico en la etiqueta de cada campo obligatorio
        # de este formulario -- se calcula DESPUES de fijar los
        # required de arriba, para que refleje el estado real (los de
        # vigencia de descuento no lo llevan, costo/margen si). No
        # hace falta tocar la plantilla para los campos ligados al
        # form (usan {{form.CAMPO.label}}) -- Categoria y Sub Categoria
        # son excepciones armadas a mano en el HTML, ver plantilla.
        for field in iter(self.fields):
            if self.fields[field].required:
                self.fields[field].label = f"{self.fields[field].label} *"

    def clean(self):
        cleaned = super().clean()
        pct = cleaned.get('descuento_promocional_pct') or 0
        desde = cleaned.get('descuento_vigencia_desde')
        hasta = cleaned.get('descuento_vigencia_hasta')

        # CORREGIDO 07/09/2026: 'required=True' por si solo no alcanza
        # aca -- si el modelo tiene un valor por defecto (ej. 0) para
        # estos dos campos, el formulario llega precargado con "0", y
        # Django considera que eso YA es un valor presente (no vacio),
        # asi que la validacion de "obligatorio" se cumple aunque el
        # usuario nunca haya escrito nada a proposito. Se valida
        # explicitamente que sean mayores a 0, ligado a cada campo con
        # add_error() (no un error generico) para que se muestre en el
        # lugar correcto.
        costo = cleaned.get('precio_referencia_usd')
        margen = cleaned.get('margen_deseado_pct')
        if not costo or costo <= 0:
            self.add_error('precio_referencia_usd', 'Debe ingresar un Precio Referencial mayor a 0.')
        if not margen or margen <= 0:
            self.add_error('margen_deseado_pct', 'Debe ingresar un Margen Deseado mayor a 0.')

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


class AjusteInventarioEncForm(forms.ModelForm):
    """
    Encabezado de Ajuste de Inventario -- pantalla de Producción
    Interna (mismo patron visual/interaccion que ComprasEncForm, sin
    Proveedor/No. Factura/Fecha Factura, que no tienen sentido aca).
    El motivo se restringe a los que 'es_produccion_interna=True' --
    la Carga Inicial NO se crea desde esta pantalla manual, solo por
    Excel (ver inv/views.py: cargar_inventario_inicial).
    """
    class Meta:
        model = AjusteInventarioEnc
        fields = ['fecha', 'motivo', 'observacion']
        widgets = {
            'fecha': forms.DateInput(format='%Y-%m-%d', attrs={'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in iter(self.fields):
            self.fields[field].widget.attrs.update({'class': 'form-control'})
        self.fields['fecha'].widget.attrs['readonly'] = True
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        self.fields['motivo'].queryset = MotivoAjusteInventario.objects.filter(
            estado=True, es_produccion_interna=True
        )
        self.fields['motivo'].empty_label = "Seleccione motivo"