from django.db import migrations


def marcar_clasicos(apps, schema_editor):
    """Los torneos que ya tenían partidos se crearon con el flujo anterior
    (Fase 1 -> Fase 2 -> Cuartos). Se marcan como CLASICO para que sigan
    funcionando exactamente igual; los nuevos arrancan sin formato y deben
    pasar por "Empezar campeonato"."""
    Torneo = apps.get_model('core', 'Torneo')
    Partido = apps.get_model('core', 'Partido')
    ids = Partido.objects.values_list('torneo_id', flat=True).distinct()
    Torneo.objects.filter(id__in=list(ids), formato='').update(formato='CLASICO')


class Migration(migrations.Migration):
    dependencies = [('core', '0028_campeonato_llaves_trazabilidad_suspensiones')]
    operations = [migrations.RunPython(marcar_clasicos, migrations.RunPython.noop)]
