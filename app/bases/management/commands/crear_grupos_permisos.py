"""
Crea (o actualiza) los grupos de permisos estandar del sistema.

Uso:
    python manage.py crear_grupos_permisos

Es seguro correrlo mas de una vez: si el grupo ya existe, solo
actualiza sus permisos (no crea duplicados).

Niveles definidos:
    1. Administrador   -> no necesita grupo, se maneja con is_superuser=True
    2. Supervisor       -> operativo completo (facturar, comprar, anular,
                            reportes), sin gestion de usuarios
    3. Cajero            -> solo facturar y consultar catalogos
    4. Almacenero         -> solo compras e inventario
    5. Solo Lectura        -> ver todo, no puede crear/editar/borrar nada
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


def get_perms(app_label, model_names, acciones):
    """Busca permisos existentes por (app, modelo, accion) sin fallar
    si alguno todavia no existe (por ejemplo, en una base recien creada
    antes del primer migrate)."""
    perms = []
    for model in model_names:
        for accion in acciones:
            codename = f"{accion}_{model}"
            perm = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if perm:
                perms.append(perm)
    return perms


def get_perm_by_codename(app_label, codename):
    return Permission.objects.filter(
        content_type__app_label=app_label, codename=codename
    ).first()


class Command(BaseCommand):
    help = "Crea o actualiza los grupos de permisos estandar del sistema"

    def handle(self, *args, **options):

        # ---------------------------------------------------------------
        # SUPERVISOR: operativo completo, sin gestion de usuarios
        # ---------------------------------------------------------------
        supervisor, _ = Group.objects.get_or_create(name="Supervisor")
        perms_supervisor = []
        perms_supervisor += get_perms(
            "inv",
            ["categoria", "subcategoria", "marca", "unidadmedida", "producto"],
            ["add", "change", "view", "delete"],
        )
        perms_supervisor += get_perms(
            "cmp",
            ["proveedor", "comprasenc", "comprasdet"],
            ["add", "change", "view", "delete"],
        )
        perms_supervisor += get_perms(
            "fac",
            ["cliente", "facturaenc", "facturadet"],
            ["add", "change", "view", "delete"],
        )
        for codename in ["anular_facturaenc", "sup_caja_facturaenc", "sup_caja_facturadet"]:
            p = get_perm_by_codename("fac", codename)
            if p:
                perms_supervisor.append(p)
        supervisor.permissions.set(perms_supervisor)
        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'Supervisor' actualizado ({len(perms_supervisor)} permisos)"
        ))

        # ---------------------------------------------------------------
        # CAJERO: solo facturar y consultar catalogos
        # ---------------------------------------------------------------
        cajero, _ = Group.objects.get_or_create(name="Cajero")
        perms_cajero = []
        perms_cajero += get_perms(
            "inv",
            ["categoria", "subcategoria", "marca", "unidadmedida", "producto"],
            ["view"],
        )
        perms_cajero += get_perms(
            "fac", ["cliente"], ["add", "change", "view"]
        )
        perms_cajero += get_perms(
            "fac", ["facturaenc", "facturadet"], ["add", "change", "view"]
        )
        cajero.permissions.set(perms_cajero)
        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'Cajero' actualizado ({len(perms_cajero)} permisos)"
        ))

        # ---------------------------------------------------------------
        # ALMACENERO: solo compras e inventario
        # ---------------------------------------------------------------
        almacenero, _ = Group.objects.get_or_create(name="Almacenero")
        perms_almacenero = []
        perms_almacenero += get_perms(
            "inv",
            ["categoria", "subcategoria", "marca", "unidadmedida", "producto"],
            ["add", "change", "view"],
        )
        perms_almacenero += get_perms(
            "cmp", ["proveedor", "comprasenc", "comprasdet"], ["add", "change", "view"]
        )
        almacenero.permissions.set(perms_almacenero)
        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'Almacenero' actualizado ({len(perms_almacenero)} permisos)"
        ))

        # ---------------------------------------------------------------
        # SOLO LECTURA: ver todo, no puede crear/editar/borrar nada
        # ---------------------------------------------------------------
        lectura, _ = Group.objects.get_or_create(name="Solo Lectura")
        perms_lectura = []
        perms_lectura += get_perms(
            "inv",
            ["categoria", "subcategoria", "marca", "unidadmedida", "producto"],
            ["view"],
        )
        perms_lectura += get_perms(
            "cmp", ["proveedor", "comprasenc", "comprasdet"], ["view"]
        )
        perms_lectura += get_perms(
            "fac", ["cliente", "facturaenc", "facturadet"], ["view"]
        )
        lectura.permissions.set(perms_lectura)
        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'Solo Lectura' actualizado ({len(perms_lectura)} permisos)"
        ))

        self.stdout.write(self.style.SUCCESS(
            "\nListo. Recuerda: 'Administrador' no es un grupo, se asigna "
            "marcando a un usuario como superusuario (is_superuser=True) "
            "desde el panel /admin/."
        ))
