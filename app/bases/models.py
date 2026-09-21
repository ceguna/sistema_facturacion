from django.db import models

from django.contrib.auth.models import User
from django_userforeignkey.models.fields import UserForeignKey

# Create your models here.

class ClaseModelo(models.Model):
    estado = models.BooleanField(default=True)
    fc = models.DateTimeField(auto_now_add=True)
    fm = models.DateTimeField(auto_now=True)
    uc = models.ForeignKey(User, on_delete=models.CASCADE)
    um = models.IntegerField(blank=True,null=True)

# Para no ser tomado en cuenta este modelo para la migración de datos.
    class Meta:
        abstract=True


class PerfilUsuario(models.Model):
    """
    Asocia un usuario del sistema a su sucursal "de base" (Fase 2,
    20/09/2026, arquitectura multi-sucursal, diseño confirmado por
    Carlos). Un cajero/almacenero normal siempre opera desde la misma
    sucursal fisica -- las facturas/compras/ajustes de inventario que
    registre se marcan con esta sucursal automaticamente (ver
    bases.views.obtener_sucursal_actual), sin que tenga que elegirla
    en cada pantalla.

    Sucursal queda en null a proposito para instalaciones de una sola
    sucursal (el caso de la libreria hoy) -- no tiene sentido obligar
    a asignar manualmente lo unico que existe; obtener_sucursal_actual
    resuelve ese caso solo. Solo hace falta cargar este campo de
    verdad cuando una instalacion (ej. Agrotextil) tiene mas de una
    sucursal real.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    sucursal = models.ForeignKey(
        'fe.Sucursal', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Sucursal donde opera este usuario. Vacío = se resuelve "
                   "solo si la empresa tiene una única sucursal; si tiene "
                   "varias, hay que asignarla acá explícitamente."
    )

    def __str__(self):
        return f"Perfil de {self.user.username}"

    class Meta:
        verbose_name = "Perfil de Usuario"
        verbose_name_plural = "Perfiles de Usuario"


class ClaseModelo2(models.Model):
    estado = models.BooleanField(default=True)
    fc = models.DateTimeField(auto_now_add=True)
    fm = models.DateTimeField(auto_now=True)
    #uc = models.ForeignKey(User, on_delete=models.CASCADE)
    #um = models.IntegerField(blank=True,null=True)
    uc = UserForeignKey(auto_user_add=True,related_name='+') #El + anula el mapeo que se hace en reversa cuando se realiza una busquesda. 
    um = UserForeignKey(auto_user=True,related_name='+')

# Para no ser tomado en cuenta este modelo para la migración de datos.
    class Meta:
        abstract=True