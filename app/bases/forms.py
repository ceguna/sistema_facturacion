from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User, Group, Permission


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

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'groups', 'is_active', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'usuario.login'}),
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
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Nombre del rol'}),
        }
        labels = {
            'name': 'Nombre del Rol',
        }
