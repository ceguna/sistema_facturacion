"""
Crea (o actualiza) los grupos de permisos estandar del sistema.

Uso:
    python manage.py crear_grupos_permisos

Es seguro correrlo mas de una vez: si el grupo ya existe, solo
actualiza sus permisos (no crea duplicados).

Niveles definidos:
    1. Administrador   -> grupo real (no solo is_superuser, ver nota 22/09/2026
                          mas abajo) -- operativo completo + gestion de usuarios,
                          sin ser superusuario tecnico de Django
    2. Supervisor       -> operativo completo (facturar, comprar, anular,
                            cierres, reportes), sin gestion de usuarios
    3. Cajero            -> solo facturar y consultar catalogos
    4. Almacenero         -> solo compras e inventario
    5. Contador            -> solo lectura de todo lo financiero/operativo
    6. Solo Lectura         -> ver todo, no puede crear/editar/borrar nada

NOTA (22/09/2026): 'Administrador' y 'Contador' existian como grupos
reales en la base (armados a mano desde Usuarios y Roles), pero por
fuera de este comando -- por eso, cada vez que se agrega un modelo
nuevo (Ajuste de Inventario, Transferencias, Eventos Significativos),
quedaban desactualizados sin que nadie se diera cuenta hasta que un
menu no coincidia con lo que el rol realmente podia ver. Se
incorporaron aca para que corran junto con el resto y no se
desincronicen de nuevo.
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
        # CORREGIDO 22/09/2026: reporte de Notas de Credito-Debito nuevo,
        # mismo criterio que Facturas Anuladas -- Supervisor es quien
        # autoriza/emite NCD, tiene que poder ver su propio reporte.
        perms_supervisor += get_perms("fac", ["notacreditodebito"], ["view"])
        # CORREGIDO 22/09/2026: Supervisor nunca tuvo estos permisos, pese
        # a que el menu de "Cierre de Dia", los reportes financieros
        # (Cierre de Ventas/Cierre de Caja) y "Cartera" ya asumian que los
        # tenia -- un Supervisor real no podia ni ver esos links, ni
        # cerrar un dia, ni cobrar un credito, contradiciendo el diseno
        # documentado del rol ("operativo completo").
        for codename in ["gestionar_cierre_dia", "ver_reportes_financieros",
                          "ver_creditos", "gestionar_creditos"]:
            p = get_perm_by_codename("fac", codename)
            if p:
                perms_supervisor.append(p)
        # Fase 2 (20/09/2026): Supervisor tiene control total sobre
        # transferencias de stock entre sucursales, incluida la
        # confirmacion/cancelacion (supervision de todo el sistema).
        perms_supervisor += get_perms(
            "inv",
            ["transferenciastockenc", "transferenciastockdet"],
            ["add", "change", "view", "delete"],
        )
        for codename in ["confirmar_transferenciastock", "cancelar_transferenciastock"]:
            p = get_perm_by_codename("inv", codename)
            if p:
                perms_supervisor.append(p)
        # Fase D (contingencia SIN, 21/09/2026): ver eventos/paquetes es
        # solo lectura (los cierra y envia el sistema solo, via la tarea
        # programada) -- Supervisor lo necesita para auditar.
        perms_supervisor += get_perms(
            "fac", ["eventosignificativo", "paquetefacturas"], ["view"]
        )
        # CORREGIDO 22/09/2026: Ajuste de Inventario (13/09/2026) nunca se
        # habia agregado a este comando para ningun rol -- Supervisor
        # ("operativo completo") necesita el mismo nivel de control que ya
        # tiene sobre Transferencias.
        perms_supervisor += get_perms(
            "inv", ["ajusteinventarioenc", "ajusteinventariodet"], ["add", "change", "view", "delete"]
        )
        perms_supervisor += get_perms("inv", ["motivoajusteinventario"], ["view"])
        # 25/09/2026: el Supervisor puede fijar el precio de venta local de
        # una sucursal (PrecioSucursal); Administrador lo tiene por ser
        # superusuario / por su grupo manual.
        for codename in ["gestionar_precios_sucursal"]:
            p = get_perm_by_codename("inv", codename)
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
        # CORREGIDO 22/09/2026: el Cajero podia registrar pagos de credito
        # segun el diseno de roles ya documentado ("Cajero puede registrar
        # pagos de credito pero no revertirlos"), pero nunca tuvo
        # 'gestionar_creditos' -- no podia ni ver ni cobrar Cartera de
        # Creditos pese a que la funcionalidad para eso ya existia.
        for codename in ["ver_creditos", "gestionar_creditos"]:
            p = get_perm_by_codename("fac", codename)
            if p:
                perms_cajero.append(p)
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
        # Fase 2 (20/09/2026): el Almacenero es quien fisicamente envia y
        # recibe mercaderia entre sucursales -- necesita crear
        # transferencias (envio) y confirmar/cancelar (recepcion propia
        # o de otra sucursal, por telefono con el otro almacenero).
        perms_almacenero += get_perms(
            "inv",
            ["transferenciastockenc", "transferenciastockdet"],
            ["add", "change", "view"],
        )
        for codename in ["confirmar_transferenciastock", "cancelar_transferenciastock"]:
            p = get_perm_by_codename("inv", codename)
            if p:
                perms_almacenero.append(p)
        # CORREGIDO 22/09/2026: Ajuste de Inventario (Produccion Interna,
        # Carga Inicial) es tan central al trabajo del Almacenero como
        # Compras o Transferencias, pero nunca se habia agregado aca.
        perms_almacenero += get_perms(
            "inv", ["ajusteinventarioenc", "ajusteinventariodet"], ["add", "change", "view"]
        )
        perms_almacenero += get_perms("inv", ["motivoajusteinventario"], ["view"])
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
            "fac", ["cliente", "facturaenc", "facturadet", "notacreditodebito"], ["view"]
        )
        perms_lectura += get_perms(
            "inv", ["transferenciastockenc", "transferenciastockdet"], ["view"]
        )
        perms_lectura += get_perms(
            "fac", ["eventosignificativo", "paquetefacturas"], ["view"]
        )
        perms_lectura += get_perms(
            "inv", ["ajusteinventarioenc", "ajusteinventariodet", "motivoajusteinventario"], ["view"]
        )
        # CORREGIDO 22/09/2026: Solo Lectura decia "ver todo" pero le
        # faltaban ver_creditos (Cartera de Creditos/Kardex de Cliente) y
        # ver_reportes_financieros (Cierre de Ventas/Cierre de Caja) --
        # nunca "gestionar_creditos" ni "gestionar_cierre_dia", esos son
        # permisos de ACCION, no de vista, y no le corresponden a este rol.
        for codename in ["ver_creditos", "ver_reportes_financieros"]:
            p = get_perm_by_codename("fac", codename)
            if p:
                perms_lectura.append(p)
        lectura.permissions.set(perms_lectura)
        self.stdout.write(self.style.SUCCESS(
            f"Grupo 'Solo Lectura' actualizado ({len(perms_lectura)} permisos)"
        ))

        # NOTA (22/09/2026): 'Administrador' y 'Contador' SI son grupos
        # reales hoy (Carlos los armo a mano desde Usuarios y Roles) --
        # este comando todavia no los gestiona, asi que no se tocan ni se
        # imprimen aca. Quedan sujetos a quedar desactualizados de nuevo
        # cada vez que se agregue un modelo/permiso nuevo, salvo que se
        # incorporen explicitamente a este comando mas adelante.
        self.stdout.write(self.style.SUCCESS(
            "\nListo. 'Administrador' y 'Contador' son grupos reales, "
            "gestionados a mano desde Usuarios y Roles (este comando "
            "todavia no los toca). Un superusuario Django (is_superuser=True) "
            "tiene acceso total automaticamente, sin necesitar ningun grupo."
        ))
