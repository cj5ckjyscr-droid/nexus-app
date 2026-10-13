"""Bitácora financiera: TODO movimiento de dinero pasa por aquí para que el
administrador de la cancha vea quién cobró, quién reversó y quién borró qué."""
from decimal import Decimal

from ..models import MovimientoFinanciero


def registrar_movimiento(*, complejo, tipo, monto, usuario=None, equipo=None, torneo=None,
                         partido=None, sancion=None, descripcion='', origen='FINANZAS'):
    if complejo is None:
        return None
    if sancion is not None:
        equipo = equipo or sancion.equipo
        torneo = torneo or sancion.torneo
        partido = partido or sancion.partido
        descripcion = descripcion or sancion.descripcion
    return MovimientoFinanciero.objects.create(
        complejo=complejo, tipo=tipo, monto=Decimal(monto or 0),
        usuario=usuario if (usuario is not None and usuario.is_authenticated) else None,
        equipo=equipo, equipo_nombre=equipo.nombre if equipo else '',
        torneo=torneo, partido=partido,
        sancion_ref=sancion.id if sancion is not None else None,
        descripcion=(descripcion or '')[:200], origen=origen,
    )
