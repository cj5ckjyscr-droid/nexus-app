from django.db import migrations
from django.db.models import Q


def limpiar(apps, schema_editor):
    """La bitácora solo guarda cambios de organizadores y del soporte técnico:
    se borra lo que hicieron dirigentes, vocales u otros usuarios."""
    RegistroCambio = apps.get_model('core', 'RegistroCambio')
    RolComplejo = apps.get_model('core', 'RolComplejo')
    for r in RegistroCambio.objects.filter(en_soporte=False).select_related('complejo', 'usuario').iterator():
        u, c = r.usuario, r.complejo
        es_org = bool(u and c and not u.is_superuser and (
            c.organizador_id == u.id or RolComplejo.objects.filter(usuario=u, complejo=c, rol='ORG').exists()))
        if not es_org or 'dirigente' in (r.detalle or '').lower():
            r.delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0034_trazabilidad_retencion')]
    operations = [migrations.RunPython(limpiar, migrations.RunPython.noop)]
