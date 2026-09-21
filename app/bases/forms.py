from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User, Group, Permission

from fe.models import Sucursal


class CSGPasswordChangeForm(PasswordChangeForm):
    """Envuelve el PasswordChangeForm de Django solo para aplicarle las
    clases CSS del tema (Django no las trae por defecto)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({
            'class': 'form-control', 'placeholder': 'Contraseña actual'})
        self.fields['new_password1'].widget.attrs.update({
            'class': 'form-control', 'placeholder': 'Nueva contraseña'})
        self.fields['new_password2'].widget.attrs.update({
            'class': 'form-control', 'placeholder': 'Repetir nueva contraseña'})


class UsuarioForm(forms.ModelForm):
    """Formulario para crear/editar usuarios del sistema.

    El manejo de contraseña queda fuera de este formulario a proposito:
    al crear un usuario se genera una contraseña temporal aleatoria, y
    luego se puede restablecer desde la pantalla dedicada
    "Restablecer Contraseña" (bases:usuario_reset_password).
    """
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Roles",
    )
    # sucursal (20/09/2026, Fase 2): NO es un campo de User -- vive en
    # PerfilUsuario (OneToOne aparte). Se agrega aca como campo suelto
    # del formulario (no ModelForm-mapeado) y se guarda a mano en
    # UsuarioNew/UsuarioEdit (bases/views.py), para no tener que
    # exponer una pantalla separada solo para esto.
    sucursal = forms.ModelChoiceField(
        queryset=Sucursal.objects.all().order_by('codigo_sucursal'),
        required=False,
        label="Sucursal",
        help_text="Sucursal donde opera este usuario. Vacío = se resuelve solo "
                   "si la empresa tiene una única sucursal.",
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'groups', 'is_active', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control no-uppercase', 'placeholder': 'usuario.login'}),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Nombres'}),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Apellidos'}),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'correo@dominio.com'}),
        }
        labels = {
            'username': 'Usuario (login)',
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
            'email': 'Correo electrónico',
            'is_active': 'Activo',
            'is_superuser': 'Administrador (acceso total, sin restricciones)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sucursal'].widget.attrs.update({'class': 'form-control'})
        # Precargar la sucursal actual al EDITAR un usuario que ya
        # tiene PerfilUsuario -- self.instance existe pero puede no
        # tener pk todavia (formulario de creacion, User(id=None)).
        if self.instance and self.instance.pk:
            perfil = getattr(self.instance, 'perfilusuario', None)
            if perfil:
                self.fields['sucursal'].initial = perfil.sucursal_id


class PerfilForm(forms.ModelForm):
    """Formulario para que el propio usuario edite sus datos basicos.
    A proposito NO incluye username, groups, is_active ni is_superuser:
    esos campos siguen siendo exclusivos de la pantalla de administracion
    de Usuarios (superusuarios), para que nadie pueda auto-otorgarse
    permisos desde aca."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Nombres'}),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Apellidos'}),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'correo@dominio.com'}),
        }
        labels = {
            'first_name': 'Nombres',
            'last_name': 'Apellidos',
            'email': 'Correo electrónico',
        }
# Apps cuyos permisos se muestran en el editor de roles. Se deja fuera
# el resto de apps internas de Django (admin, contenttypes, sessions)
# porque no se usan en el dia a dia del sistema.
APPS_GESTIONADAS = ['inv', 'cmp', 'fac', 'auth', 'bases']


class GrupoForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(
            content_type__app_label__in=APPS_GESTIONADAS
        ).select_related('content_type').order_by(
            'content_type__app_label', 'content_type__model', 'codename'
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Permisos",
    )

    class Meta:
        model = Group
        fields = ['name', 'permissions']
        widgets = {
            # 'no-uppercase' agregado 02/09/2026: el nombre del rol debe
            # aceptar mayusculas y minusculas normales, como el campo
            # Usuario del login -- mismo mecanismo de excepcion que ya
            # usa ese campo (ver el JS global en base.html), sin tocar
            # nada de JS.
            'name': forms.TextInput(attrs={
                'class': 'form-control no-uppercase', 'placeholder': 'Nombre del rol'}),
        }
        labels = {
            'name': 'Nombre del Rol',
        }