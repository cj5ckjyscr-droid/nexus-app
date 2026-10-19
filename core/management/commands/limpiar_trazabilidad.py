from django.core.management.base import BaseCommand

from core.models import DIAS_RETENCION_TRAZABILIDAD, limpiar_trazabilidad_vieja


class Command(BaseCommand):
    help = f"Borra la trazabilidad (cambios y movimientos) con más de {DIAS_RETENCION_TRAZABILIDAD} días."

    def handle(self, *args, **options):
        cambios, movimientos = limpiar_trazabilidad_vieja(forzar=True)
        self.stdout.write(self.style.SUCCESS(
            f"Trazabilidad depurada: {cambios} cambio(s) y {movimientos} movimiento(s) borrados."))
