from django.core.management.base import BaseCommand

from catalogos.services import sincronizar_todos_los_catalogos


class Command(BaseCommand):
    help = (
        "Sincroniza los catálogos paramétricos del SIN. Debe ejecutarse "
        "diariamente antes de solicitar el CUFD (Art. 19/20 RND "
        "101800000026). Pensado para correr vía Render Cron Jobs, igual "
        "que en el proyecto OJO ALERTA."
    )

    def handle(self, *args, **options):
        exitosa, mensaje = sincronizar_todos_los_catalogos()
        if exitosa:
            self.stdout.write(self.style.SUCCESS(mensaje))
        else:
            self.stdout.write(self.style.ERROR(mensaje))
