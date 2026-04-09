from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date
from django.db.models import Sum, Q
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

# =====================================================
# --- VALIDADORES PERSONALIZADOS ---
# =====================================================
def validar_cedula_db(value):
    if len(value) != 10 or not value.isdigit():
        raise ValidationError("La cédula debe tener exactamente 10 dígitos numéricos.")
    provincia = int(value[0:2])
    if provincia < 1 or provincia > 24:
        raise ValidationError("Código de provincia inválido.")
    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    total = sum([
        (int(value[i]) * coeficientes[i] if int(value[i]) * coeficientes[i] < 10 
         else int(value[i]) * coeficientes[i] - 9) 
        for i in range(9)
    ])
    digito = int(value[9])
    calculado = (total + 9) // 10 * 10 - total
    if calculado == 10: calculado = 0
    if calculado != digito:
        raise ValidationError("La cédula ecuatoriana ingresada no es matemáticamente válida.")

validador_letras = RegexValidator(
    regex=r'^[a-zA-ZñÑáéíóúÁÉÍÓÚ\s]+$', 
    message='El nombre solo puede contener letras y espacios. No se permiten números ni símbolos.'
)

# =====================================================
# --- EL CORAZÓN DEL SAAS (SÚPER ADMINISTRADOR) ---
# =====================================================

class PlanSuscripcion(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    costo_inscripcion = models.DecimalField(max_digits=8, decimal_places=2, default=0.00, verbose_name="Costo de Inscripción (Pago único)")
    precio_mensual = models.DecimalField(max_digits=8, decimal_places=2)
    max_torneos = models.PositiveIntegerField(default=1)
    max_categorias_por_torneo = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.nombre} - ${self.precio_mensual}/mes"

class ComplejoDeportivo(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre de la Cancha / Complejo")
    slug = models.SlugField(unique=True, help_text="URL amigable, ej: cancha-los-pinos")
    organizador = models.OneToOneField(User, on_delete=models.CASCADE, related_name='complejo', help_text="El dueño de este complejo")
    plan = models.ForeignKey(PlanSuscripcion, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Control SaaS
    activo = models.BooleanField(default=True, help_text="Desmarcar para suspender la plataforma por falta de pago")
    fecha_vencimiento = models.DateField(help_text="Fecha máxima de cobertura del pago", null=True, blank=True)
    logo = models.ImageField(upload_to='complejos/logos/', null=True, blank=True)
    telefono_contacto = models.CharField(max_length=15, blank=True, null=True)

    def esta_al_dia(self):
        if not self.activo:
            return False
        if self.fecha_vencimiento and self.fecha_vencimiento < timezone.now().date():
            return False
        return True

    def __str__(self):
        estado = "✅ Activo" if self.esta_al_dia() else "❌ Suspendido"
        return f"{self.nombre} [{estado}]"

# =====================================================
# 1. USUARIOS Y PERFILES (CON SANCIONES)
# =====================================================
# 1. PERFIL GLOBAL (Solo datos personales)
# 1. PERFIL GLOBAL (Solo datos personales)
class Perfil(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    telefono = models.CharField(max_length=15, blank=True, null=True)
    foto = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    sancionado_hasta = models.DateField(null=True, blank=True, verbose_name="Suspendido (Lista Negra) Global hasta:")

    def __str__(self):
        return f"{self.usuario.username}"
    
    @property
    def esta_sancionado(self):
        return self.sancionado_hasta and self.sancionado_hasta >= date.today()

    # 👇 ESTO ES LO NUEVO QUE DEBES AGREGAR 👇
    @property
    def rol_principal(self):
        """ Propiedad mágica para mostrar menús en base.html """
        if self.usuario.is_superuser: return 'ORG'
        if hasattr(self.usuario, 'complejo'): return 'ORG' # Si es dueño absoluto
        rc = self.usuario.roles_cancha.first() # Si le dieron rol en alguna cancha
        if rc: return rc.rol
        if self.usuario.equipo_dirigido.exists(): return 'DIR' # Si es dirigente
        return 'FAN'

# 2. NUEVA TABLA: ROLES POR CANCHA (Multi-tenancy real)
class RolComplejo(models.Model):
    ROLES = [
        ('ORG', 'Organizador / Staff'), # Puede ayudar al dueño
        ('VOC', 'Vocal de Mesa'),       
        ('DIR', 'Dirigente de Equipo'), 
        ('FAN', 'Aficionado / Cliente'),
    ]
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles_cancha')
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='usuarios')
    rol = models.CharField(max_length=3, choices=ROLES, default='FAN')

    class Meta:
        # Esto garantiza que un usuario no tenga dos roles repetidos en la misma cancha
        unique_together = ('usuario', 'complejo') 

    def __str__(self):
        return f"{self.usuario.username} es {self.get_rol_display()} en {self.complejo.nombre}"

# =====================================================
# 2. CONFIGURACIÓN GLOBAL (AHORA POR COMPLEJO)
# =====================================================
class Configuracion(models.Model):
    complejo = models.OneToOneField(ComplejoDeportivo, on_delete=models.CASCADE, related_name='configuracion', null=True, blank=True)
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=15.00)
    
    # ESTO ES LO QUE AGREGAMOS PARA QUE APAREZCA EN EL ADMIN
    logo_sistema = models.ImageField(upload_to='logos_sistema/', null=True, blank=True, verbose_name="Logo Global de Nexus")
    
    def __str__(self):
        return f"Configuración de {self.complejo.nombre if self.complejo else 'Global'}"
# =====================================================
# 3. MULTIMEDIA (AHORA POR COMPLEJO)
# =====================================================
class FotoGaleria(models.Model):
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='galeria', null=True, blank=True)
    imagen = models.ImageField(upload_to='galeria/', verbose_name="Foto de la Cancha")
    titulo = models.CharField(max_length=50, blank=True, verbose_name="Título corto (Opcional)")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden de aparición")
    activa = models.BooleanField(default=True, verbose_name="Mostrar en el inicio")

    class Meta:
        verbose_name = "Foto de Galería"
        verbose_name_plural = "Galería de la Cancha"
        ordering = ['orden', '-id']

    def __str__(self):
        return self.titulo if self.titulo else f"Foto {self.id}"

# =====================================================
# 4. CATEGORÍAS (AHORA POR COMPLEJO)
# =====================================================
class Categoria(models.Model):
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='categorias', null=True, blank=True)
    nombre = models.CharField(max_length=100, verbose_name="Nombre de Categoría (Ej: Serie A, Femenino)")
    color_carnet = models.CharField(max_length=7, default="#1D4ED8", help_text="Color en HEX para los carnets")
    activa = models.BooleanField(default=True)

    class Meta:
        # Ya no es 'unique=True' globalmente, sino único POR CANCHA
        constraints = [
            models.UniqueConstraint(fields=['complejo', 'nombre'], name='unica_categoria_por_complejo')
        ]

    def __str__(self):
        return f"{self.nombre} ({self.complejo.nombre if self.complejo else 'Global'})"

# =====================================================
# 5. CUPONES DE DESCUENTO (AHORA POR COMPLEJO)
# =====================================================
class Cupon(models.Model):
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='cupones', null=True, blank=True)
    codigo = models.CharField(max_length=20, help_text="Ej: GOLAZO2026")
    descuento = models.DecimalField(max_digits=5, decimal_places=2, help_text="Monto en $ a descontar")
    activo = models.BooleanField(default=True)
    usos_actuales = models.PositiveIntegerField(default=0)
    limite_usos = models.PositiveIntegerField(null=True, blank=True, help_text="Dejar vacío para ilimitado")
    fecha_expiracion = models.DateField(null=True, blank=True)

    class Meta:
        # El código es único solo dentro de cada complejo
        constraints = [
            models.UniqueConstraint(fields=['complejo', 'codigo'], name='unico_cupon_por_complejo')
        ]

    def es_valido(self):
        ahora = timezone.now().date()
        if not self.activo: return False
        if self.fecha_expiracion and ahora > self.fecha_expiracion: return False
        if self.limite_usos and self.usos_actuales >= self.limite_usos: return False
        return True

    def __str__(self):
        return f"CUPÓN: {self.codigo} (-${self.descuento})"

# =====================================================
# 6. TORNEOS (AHORA POR COMPLEJO)
# =====================================================
class Torneo(models.Model):
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='torneos', null=True, blank=True)
    nombre = models.CharField(max_length=100)
    organizador = models.ForeignKey(User, on_delete=models.CASCADE)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoría")
    fecha_inicio = models.DateField(default=timezone.now)
    activo = models.BooleanField(default=True)
    
    # Costos
    cobro_por_jugador = models.BooleanField(default=False, verbose_name="¿Cobrar inscripción POR JUGADOR en vez de equipo?")
    costo_inscripcion = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Costo x Equipo")
    costo_inscripcion_jugador = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Costo x Jugador")
    
    costo_amarilla = models.DecimalField(max_digits=5, decimal_places=2, default=0.50, verbose_name="Multa Amarilla ($)")
    costo_roja = models.DecimalField(max_digits=5, decimal_places=2, default=5.00, verbose_name="Multa Roja ($)")
    
    inscripcion_abierta = models.BooleanField(default=True, verbose_name="¿Inscripción Habilitada?")
    fecha_limite_inscripcion = models.DateField(null=True, blank=True)

    # ✨ FORMATOS DE TORNEO AVANZADOS
    fase1_ida_vuelta = models.BooleanField(default=False, verbose_name="Fase 1 (Todos contra Todos) - Ida o Vuelta")
    fase2_ida_vuelta = models.BooleanField(default=False, verbose_name="Fase 2 (Grupos) - Ida y Vuelta Acumulativa")
    fase3_ida_vuelta = models.BooleanField(default=False, verbose_name="Fase 3 (Eliminatorias/Cuartos) - Ida y Vuelta")

    def __str__(self):
        return f"{self.nombre} ({self.complejo.nombre if self.complejo else ''})"

    @property
    def periodo_valido(self):
        if self.fecha_limite_inscripcion:
            return date.today() <= self.fecha_limite_inscripcion
        return True

# =====================================================
# 7. EQUIPOS
# =====================================================
class Equipo(models.Model):
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE, related_name='equipos')
    dirigente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='equipo_dirigido')
    nombre = models.CharField(max_length=100)
    escudo = models.ImageField(upload_to='escudos/', null=True, blank=True)
    telefono_contacto = models.CharField(max_length=15, blank=True, null=True, verbose_name="Celular de Contacto")
    nombre_suplente_1 = models.CharField(max_length=100, blank=True)
    nombre_suplente_2 = models.CharField(max_length=100, blank=True)
    
    # Control de pagos
    pagado = models.BooleanField(default=False, verbose_name="Inscripción Pagada")
    monto_reembolso = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    cupos_pagados = models.PositiveIntegerField(default=0, verbose_name="Nº de Jugadores Pagados/Habilitados")
    puntos_bonificacion = models.IntegerField(default=0)
    GRUPO_FASE2_CHOICES = [('A', 'Grupo A'), ('B', 'Grupo B'), ('N', 'Ninguno')]
    grupo_fase2 = models.CharField(max_length=1, null=True, blank=True)
    
    ESTADOS_INSCRIPCION = [
        ('PENDIENTE', '⏳ Pendiente de Aprobación'),
        ('APROBADO', '✅ Aprobado'),
        ('RECHAZADO', '❌ Rechazado'),
    ]
    estado_inscripcion = models.CharField(max_length=10, choices=ESTADOS_INSCRIPCION, default='PENDIENTE')
    sancionado_hasta = models.DateField(null=True, blank=True, verbose_name="Equipo en Lista Negra hasta:")

    def __str__(self):
        return self.nombre
    
    @property
    def esta_sancionado(self):
        return self.sancionado_hasta and self.sancionado_hasta >= date.today()

    @property
    def cupos_disponibles(self):
        inscritos = self.jugadores.count()
        return max(0, self.cupos_pagados - inscritos)

    @property
    def puede_fichar(self):
        if self.esta_sancionado: return False
        if self.torneo.cobro_por_jugador:
            return self.cupos_disponibles > 0
        return self.torneo.inscripcion_abierta

    def total_pagado(self):
        resultado = self.pagos.aggregate(total=Sum('monto'))['total']
        return resultado or 0

    def total_multas(self):
        resultado = self.sanciones.aggregate(total=Sum('monto'))['total']
        return resultado or 0

    def deuda_pendiente(self):
        if self.torneo.cobro_por_jugador:
            valor_inscripcion = self.cupos_pagados * self.torneo.costo_inscripcion_jugador
        else:
            valor_inscripcion = self.torneo.costo_inscripcion
            
        multas = self.total_multas()
        pagado = self.total_pagado()
        return (valor_inscripcion + multas) - pagado
    
    def total_deuda(self):
        sanciones_pendientes = Sancion.objects.filter(equipo=self, pagada=False)
        total = sum((sancion.monto - sancion.monto_pagado) for sancion in sanciones_pendientes)
        return total

    def tiene_deudas(self):
        return self.total_deuda() > 0

# =====================================================
# 8. PAGOS
# =====================================================
class Pago(models.Model):
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateField(default=date.today)
    comprobante = models.ImageField(upload_to='pagos/', null=True, blank=True)
    validado = models.BooleanField(default=False)
    observacion = models.TextField(max_length=500, blank=True, null=True)
    
    def __str__(self):
        return f"Abono ${self.monto} - {self.equipo.nombre}"

# =====================================================
# 9. JUGADORES
# =====================================================
class Jugador(models.Model):
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='jugadores')
    nombres = models.CharField(max_length=100, validators=[validador_letras])
    dorsal = models.PositiveIntegerField()
    cedula = models.CharField(max_length=15, validators=[validar_cedula_db])
    foto = models.ImageField(upload_to='jugadores/', null=True, blank=True)
    
    rojas_directas_acumuladas = models.PositiveIntegerField(default=0)
    expulsado_torneo = models.BooleanField(default=False)
    partidos_suspension = models.IntegerField(default=0, verbose_name="Partidos de Suspensión")
    sancionado_hasta = models.DateField(null=True, blank=True, verbose_name="Jugador Suspendido hasta:")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['equipo', 'dorsal'], name='unico_dorsal_por_equipo')
        ]

    def __str__(self):
        return f"{self.nombres} ({self.dorsal})"
    
    @property
    def esta_sancionado(self):
        return self.sancionado_hasta and self.sancionado_hasta >= date.today()

    @property
    def esta_habilitado(self):
        return (self.partidos_suspension <= 0 
                and not self.expulsado_torneo 
                and self.rojas_directas_acumuladas < 3 
                and not self.esta_sancionado)

# =====================================================
# 10. PARTIDOS
# =====================================================
class Partido(models.Model):
    ESTADOS = [
        ('PROG', 'Programado'), 
        ('VIVO', 'En Vivo (Arbitrando)'), 
        ('ACTA', 'En Acta (Faltan Firmas)'), 
        ('JUG', 'Finalizado'), 
        ('WO', 'Walkover')
    ]
    ETAPAS = [
        ('F1', 'Fase 1'), ('F2', 'Fase 2'), 
        ('4TOS', 'Cuartos de Final'), ('SEMI', 'Semifinal'), 
        ('TERC', 'Tercer Lugar'), ('FINAL', 'Final')
    ]
    
    informe_vocal = models.TextField(blank=True, null=True)
    informe_arbitro = models.TextField(blank=True, null=True)
    validado_local = models.BooleanField(default=False)
    validado_visita = models.BooleanField(default=False)

    numero_fecha = models.PositiveIntegerField(default=1)
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE)
    etapa = models.CharField(max_length=5, choices=ETAPAS, default='F1')
    cancha = models.CharField(max_length=100, default="Cancha Principal")
    
    equipo_local = models.ForeignKey(Equipo, related_name='local', on_delete=models.CASCADE)
    equipo_visita = models.ForeignKey(Equipo, related_name='visita', on_delete=models.CASCADE)
    
    fecha_hora = models.DateTimeField(null=True, blank=True)
    
    goles_local = models.PositiveIntegerField(default=0)
    goles_visita = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=4, choices=ESTADOS, default='PROG')
    ganador_wo = models.ForeignKey(Equipo, null=True, blank=True, on_delete=models.SET_NULL)
    
    sanciones_aplicadas = models.BooleanField(default=False, verbose_name="¿Sanciones procesadas?")

    hubo_penales = models.BooleanField(default=False, verbose_name="¿Hubo Penales?")
    penales_local = models.PositiveIntegerField(default=0, blank=True, null=True)
    penales_visita = models.PositiveIntegerField(default=0, blank=True, null=True)

    def clean(self):
        if self.equipo_local == self.equipo_visita:
            raise ValidationError("⛔ Un equipo no puede jugar contra sí mismo.")

        choque = Partido.objects.filter(
            torneo=self.torneo,
            etapa=self.etapa,
            numero_fecha=self.numero_fecha
        ).filter(
            Q(equipo_local=self.equipo_local, equipo_visita=self.equipo_visita) |
            Q(equipo_local=self.equipo_visita, equipo_visita=self.equipo_local)
        ).exclude(id=self.id)

        if choque.exists():
            raise ValidationError(f"⛔ El partido {self.equipo_local} vs {self.equipo_visita} YA EXISTE en esta jornada de {self.get_etapa_display()}.")

    def __str__(self):
        return f"{self.equipo_local} vs {self.equipo_visita}"

# =====================================================
# 11. DETALLES Y SANCIONES
# =====================================================
class DetallePartido(models.Model):
    TIPOS = [
        ('GOL', '⚽ Gol'), ('ASIS', '✅ Asistencia'), ('TA', '🟨 Amarilla'),
        ('TR', '🟥 Roja'), ('DA', '🟨🟨 Doble A.'), ('AZUL', '👕 Uniforme'), ('EBRI', '🍺 Ebrio'),
        ('STAR', '⭐ Figura')
    ]
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='detalles')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE)
    equipo_incidencia = models.ForeignKey(Equipo, on_delete=models.CASCADE, null=True, blank=True, help_text="Asegura que los goles no se fuguen si se traspasa al jugador")
    tipo = models.CharField(max_length=5, choices=TIPOS)
    minuto = models.PositiveIntegerField(blank=True, null=True, default=0) 
    observacion = models.TextField(blank=True, null=True)

class Sancion(models.Model):
    TIPOS = [
        ('INSCRIPCION', 'Deuda por Inscripción'),
        ('AMARILLA', 'Tarjeta Amarilla'), 
        ('ROJA', 'Tarjeta Roja'), 
        ('ADMIN', 'Sanción Administrativa')
    ]
    torneo = models.ForeignKey(Torneo, on_delete=models.CASCADE)
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='sanciones')
    jugador = models.ForeignKey(Jugador, on_delete=models.SET_NULL, null=True, blank=True)
    partido = models.ForeignKey(Partido, on_delete=models.SET_NULL, null=True, blank=True)
    
    tipo = models.CharField(max_length=15, choices=TIPOS)
    monto = models.DecimalField(max_digits=5, decimal_places=2)
    descripcion = models.CharField(max_length=200, blank=True)
    
    pagada = models.BooleanField(default=False, verbose_name="¿Pagada?")
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    monto_pagado = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)

    def __str__(self):
        estado = "PAGADO" if self.pagada else "DEUDA"
        return f"{self.equipo.nombre} - {self.get_tipo_display()} (${self.monto}) [{estado}]"
    
    @property
    def saldo(self):
        return self.monto - self.monto_pagado

class AbonoSancion(models.Model):
    sancion = models.ForeignKey(Sancion, on_delete=models.CASCADE, related_name='historial_abonos')
    monto = models.DecimalField(max_digits=8, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)
    partido = models.ForeignKey(Partido, on_delete=models.SET_NULL, null=True, blank=True, related_name='abonos_cobrados')

    def __str__(self):
        return f"Abono ${self.monto} - {self.sancion.equipo.nombre}"
    
# =====================================================
# 12. CONTABILIDAD DEL SOFTWARE (TUS GANANCIAS COMO DUEÑO)
# =====================================================
class PagoSuscripcionSaaS(models.Model):
    complejo = models.ForeignKey(ComplejoDeportivo, on_delete=models.CASCADE, related_name='pagos_saas')
    monto = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Monto Pagado a NEXUS")
    # CAMBIO AQUÍ: default=timezone.now en lugar de auto_now_add=True
    fecha_pago = models.DateField(default=timezone.now, verbose_name="Fecha en que se realizó el pago")
    meses_pagados = models.PositiveIntegerField(default=1, help_text="¿Cuántos meses pagó?")
    observacion = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Pago de {self.complejo.nombre} - ${self.monto}"
    