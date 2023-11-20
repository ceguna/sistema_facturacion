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