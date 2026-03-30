from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, time, datetime
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
# NUEVO: CATEGORÍAS
# =====================================================
class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre de Categoría (Ej: Serie A, Femenino)")
    color_carnet = models.CharField(max_length=7, default="#1D4ED8", help_text="Color en HEX para los carnets (Ej: #FF0000 para rojo, #00FF00 para verde)")
    activa = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

# =====================================================
# 1. USUARIOS Y PERFILES (CON SANCIONES)
# =====================================================
class Perfil(models.Model):
    ROLES = [
        ('ORG', 'Organizador'),         # Dueño del sistema
        ('VOC', 'Vocal de Mesa'),       # Ayudante
        ('DIR', 'Dirigente de Equipo'), # Cliente Torneo
        ('FAN', 'Aficionado / Cliente'),# Cliente Cancha / Espectador
    ]
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=3, choices=ROLES, default='FAN') 
    telefono = models.CharField(max_length=15, blank=True, null=True)
    foto = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    
    # 🚫 NUEVO: Sanción a Dirigentes (Lista Negra de 1 año)
    sancionado_hasta = models.DateField(null=True, blank=True, verbose_name="Suspendido (Lista Negra) hasta:")

    def __str__(self):
        return f"{self.usuario.username} - {self.get_rol_display()}"
    
    @property
    def esta_sancionado(self):
        """Verifica si el usuario actual cumple una sanción activa"""
        return self.sancionado_hasta and self.sancionado_hasta >= date.today()

# =====================================================
# 2. CUPONES DE DESCUENTO
# =====================================================
class Cupon(models.Model):
    TIPO_CUPON = (
        ('CANCHA', 'Alquiler de Cancha'),
        ('TORNEO', 'Inscripción de Campeonato'),
    )
    codigo = models.CharField(max_length=20, unique=True, help_text="Ej: GOLAZO2026")
    descuento = models.DecimalField(max_digits=5, decimal_places=2, help_text="Monto en $ a descontar")
    tipo = models.CharField(max_length=15, choices=TIPO_CUPON)
    activo = models.BooleanField(default=True)
    
    usos_actuales = models.PositiveIntegerField(default=0)
    limite_usos = models.PositiveIntegerField(null=True, blank=True, help_text="Dejar vacío para ilimitado")
    fecha_expiracion = models.DateField(null=True, blank=True)

    def es_valido(self):
        ahora = timezone.now().date()
        if not self.activo: return False
        if self.fecha_expiracion and ahora > self.fecha_expiracion: return False
        if self.limite_usos and self.usos_actuales >= self.limite_usos: return False
        return True

    def __str__(self):
        return f"CUPÓN: {self.codigo} (-${self.descuento})"

# =====================================================
# 3. TORNEOS (CON PAGOS POR JUGADOR Y FORMATOS IDA Y VUELTA)
# =====================================================
class Torneo(models.Model):
    nombre = models.CharField(max_length=100)
    organizador = models.ForeignKey(User, on_delete=models.CASCADE)
    categoria = models.ForeignKey('Categoria', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoría")
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
        return self.nombre

    @property
    def periodo_valido(self):
        if self.fecha_limite_inscripcion:
            return date.today() <= self.fecha_limite_inscripcion
        return True

# =====================================================
# 4. EQUIPOS (CUPOS, SANCIONES Y CATEGORÍAS)
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
    
    # ✨ NUEVO: Control de Cupos de Fichaje (Comprados por el Dirigente)
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
    
    # 🚫 NUEVO: Sanción a Equipos (Lista Negra de 1 año)
    sancionado_hasta = models.DateField(null=True, blank=True, verbose_name="Equipo en Lista Negra hasta:")

    def __str__(self):
        return self.nombre
    
    @property
    def esta_sancionado(self):
        return self.sancionado_hasta and self.sancionado_hasta >= date.today()

    @property
    def cupos_disponibles(self):
        """Calcula cuántos jugadores le faltan por inscribir según lo que pagó"""
        inscritos = self.jugadores.count()
        return max(0, self.cupos_pagados - inscritos)

    @property
    def puede_fichar(self):
        """Bloquea si no le quedan cupos o si el equipo está sancionado"""
        if self.esta_sancionado: return False
        if self.torneo.cobro_por_jugador:
            return self.cupos_disponibles > 0
        return self.torneo.inscripcion_abierta

    # --- MÉTODOS FINANCIEROS (Actualizados para pago por jugador) ---
    def total_pagado(self):
        resultado = self.pagos.aggregate(total=Sum('monto'))['total']
        return resultado or 0

    def total_multas(self):
        resultado = self.sanciones.aggregate(total=Sum('monto'))['total']
        return resultado or 0

    def deuda_pendiente(self):
        if self.torneo.cobro_por_jugador:
            # Si cobra por jugador, la deuda total asume los cupos que le ha dado el administrador
            valor_inscripcion = self.cupos_pagados * self.torneo.costo_inscripcion_jugador
        else:
            valor_inscripcion = self.torneo.costo_inscripcion
            
        multas = self.total_multas()
        pagado = self.total_pagado()
        return (valor_inscripcion + multas) - pagado
    
    def total_deuda(self):
        """Calcula cuánto dinero debe exactamente el equipo consultando el modelo Sancion directamente"""
        # Importamos el modelo aquí adentro para evitar problemas de orden circular en el archivo
        from core.models import Sancion 
        
        # Filtramos directamente en la tabla Sancion
        sanciones_pendientes = Sancion.objects.filter(equipo=self, pagada=False)
        total = sum((sancion.monto - sancion.monto_pagado) for sancion in sanciones_pendientes)
        return total

    def tiene_deudas(self):
        """Devuelve True (Verdadero) si el equipo debe al menos 1 centavo"""
        return self.total_deuda() > 0

# =====================================================
# 5. PAGOS
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
# 6. JUGADORES (SANCIONES Y 3 ROJAS DIRECTAS)
# =====================================================
class Jugador(models.Model):
    equipo = models.ForeignKey(Equipo, on_delete=models.CASCADE, related_name='jugadores')
    
    nombres = models.CharField(max_length=100, validators=[validador_letras])
    dorsal = models.PositiveIntegerField()
    
    cedula = models.CharField(max_length=15, validators=[validar_cedula_db])
    foto = models.ImageField(upload_to='jugadores/', null=True, blank=True)
    
    rojas_directas_acumuladas = models.PositiveIntegerField(default=0) # Al llegar a 3 se suspende del campeonato
    expulsado_torneo = models.BooleanField(default=False)
    partidos_suspension = models.IntegerField(default=0, verbose_name="Partidos de Suspensión")
    
    # 🚫 NUEVO: Sanción a Jugadores (Lista Negra de 1 año)
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
        # Un jugador está habilitado si no tiene partidos de castigo, no fue expulsado, 
        # tiene menos de 3 rojas acumuladas, y no está en lista negra anual.
        return (self.partidos_suspension <= 0 
                and not self.expulsado_torneo 
                and self.rojas_directas_acumuladas < 3 
                and not self.esta_sancionado)

# =====================================================
# 7. PARTIDOS (CRUCES BLINDADOS Y CUARTOS DE FINAL)
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
    
    # Campo para evitar la duplicación de sanciones
    sanciones_aplicadas = models.BooleanField(default=False, verbose_name="¿Sanciones ya procesadas?")

    hubo_penales = models.BooleanField(default=False, verbose_name="¿Hubo Penales?")
    penales_local = models.PositiveIntegerField(default=0, blank=True, null=True)
    penales_visita = models.PositiveIntegerField(default=0, blank=True, null=True)

    def clean(self):
        if self.equipo_local == self.equipo_visita:
            raise ValidationError("⛔ Un equipo no puede jugar contra sí mismo.")

        # Evitar partidos duplicados en Fase 1 y Fase 2 (Excepto Ida y Vuelta si están habilitados en views)
        choque = Partido.objects.filter(
            torneo=self.torneo,
            etapa=self.etapa,
            numero_fecha=self.numero_fecha # Misma fecha
        ).filter(
            Q(equipo_local=self.equipo_local, equipo_visita=self.equipo_visita) |
            Q(equipo_local=self.equipo_visita, equipo_visita=self.equipo_local)
        ).exclude(id=self.id)

        if choque.exists():
            raise ValidationError(f"⛔ El partido {self.equipo_local} vs {self.equipo_visita} YA EXISTE en esta jornada de {self.get_etapa_display()}.")

    def __str__(self):
        return f"{self.equipo_local} vs {self.equipo_visita}"

# =====================================================
# 8. DETALLE DEL PARTIDO (CONSERVACIÓN DE GOLES POR EQUIPO)
# =====================================================
class DetallePartido(models.Model):
    TIPOS = [
        ('GOL', '⚽ Gol'), ('ASIS', '✅ Asistencia'), ('TA', '🟨 Amarilla'),
        ('TR', '🟥 Roja'), ('DA', '🟨🟨 Doble A.'), ('AZUL', '👕 Uniforme'), ('EBRI', '🍺 Ebrio'),
        ('STAR', '⭐ Figura')
    ]
    partido = models.ForeignKey(Partido, on_delete=models.CASCADE, related_name='detalles')
    jugador = models.ForeignKey(Jugador, on_delete=models.CASCADE)
    
    # ✨ NUEVO: Guardamos el equipo exacto con el que hizo el gol.
    # Si traspasan al jugador, este campo garantiza que el gol se quede con el equipo viejo!
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
    equipo = models.ForeignKey('Equipo', on_delete=models.CASCADE, related_name='sanciones')
    jugador = models.ForeignKey('Jugador', on_delete=models.SET_NULL, null=True, blank=True)
    partido = models.ForeignKey('Partido', on_delete=models.SET_NULL, null=True, blank=True)
    
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


# =====================================================
# 9. CONFIGURACIÓN GLOBAL Y HORARIOS CANCHA (Deben ir arriba de Reservas)
# =====================================================
class Configuracion(models.Model):
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=15.00)
    precio_hora_cancha = models.DecimalField(max_digits=6, decimal_places=2, default=15.00)
    logo_sistema = models.ImageField(upload_to='configuracion/', null=True, blank=True, verbose_name="Logo del Sistema")
    
    def __str__(self):
        return f"Configuración del Sistema (IVA: {self.iva_porcentaje}%)"

class HorarioCancha(models.Model):
    hora_inicio = models.TimeField(verbose_name="Hora de Inicio")
    hora_fin = models.TimeField(verbose_name="Hora de Fin")
    precio = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Costo del Turno")
    activo = models.BooleanField(default=True, verbose_name="Disponible para alquilar")

    class Meta:
        ordering = ['hora_inicio']

    def __str__(self):
        return f"{self.hora_inicio.strftime('%H:%M')} a {self.hora_fin.strftime('%H:%M')} - ${self.precio}"

# =====================================================
# 10. RESERVA DE CANCHA (CÁLCULOS CORREGIDOS Y DESCUENTO A DIRIGENTES)
# =====================================================
class ReservaCancha(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reservas', null=True, blank=True)
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    
    precio_total = models.DecimalField(max_digits=6, decimal_places=2, default=0.00)
    pagado = models.BooleanField(default=False)
    
    es_torneo = models.BooleanField(default=False, verbose_name="Bloqueo por Torneo")
    motivo_bloqueo = models.CharField(max_length=100, blank=True, null=True)
    
    cupon = models.ForeignKey(Cupon, on_delete=models.SET_NULL, null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    partido = models.OneToOneField('Partido', on_delete=models.CASCADE, null=True, blank=True, related_name='reserva_bloqueo')

    ESTADOS = [
        ('PENDIENTE', '⏳ Pendiente'),
        ('ACTIVA', '✅ Confirmada'),
        ('CANCELADA', '🚫 Cancelada'),
    ]
    estado = models.CharField(max_length=15, choices=ESTADOS, default='PENDIENTE')

    def clean(self):
        APERTURA = time(15, 0)
        CIERRE = time(21, 0)

        if self.hora_inicio < APERTURA or self.hora_fin > CIERRE:
            raise ValidationError("⚠️ La cancha opera de 03:00 PM a 09:00 PM.")
        if self.hora_inicio >= self.hora_fin:
            raise ValidationError("⚠️ Hora inicio debe ser menor a hora fin.")
        if self.hora_inicio.minute != 0 or self.hora_fin.minute != 0:
             raise ValidationError("⚠️ Solo se permiten reservas en horas exactas (ej: 15:00, 16:00).")

        if not self.es_torneo:
            if self.fecha <= timezone.now().date():
                raise ValidationError("⚠️ Solo se aceptan reservas con al menos 1 día de anticipación.")

        choque = ReservaCancha.objects.filter(
            fecha=self.fecha,
            hora_inicio__lt=self.hora_fin,
            hora_fin__gt=self.hora_inicio
        ).exclude(id=self.id).exclude(estado='CANCELADA')

        if choque.exists():
            c = choque.first()
            msg = "⛔ Reservado para CAMPEONATO" if c.es_torneo else "⛔ Ya reservado por otro cliente"
            raise ValidationError(msg)

    def save(self, *args, **kwargs):
        from decimal import Decimal
        if self.precio_total is None:
            self.precio_total = Decimal('0.00')
            
        if not self.es_torneo:
            # ✨ LA SOLUCIÓN: Si la página web ya calculó el precio (es mayor a 0), 
            # respetamos ese valor y NO lo sobreescribimos.
            if float(self.precio_total) > 0:
                # Solo descontamos el uso del cupón si es que se usó uno
                if self.cupon and self.cupon.es_valido() and not self.pk:
                    self.cupon.usos_actuales += 1
                    self.cupon.save()
            else:
                # Lógica de respaldo: Solo se usa si alguien crea una reserva manual desde el Panel de Admin con precio $0.00
                bloque = HorarioCancha.objects.filter(hora_inicio=self.hora_inicio).first()
                
                if bloque:
                    base = float(bloque.precio)
                else:
                    formato = "%H:%M:%S"
                    ini = datetime.strptime(str(self.hora_inicio), formato)
                    fin = datetime.strptime(str(self.hora_fin), formato)
                    horas = (fin - ini).seconds / 3600
                    base = horas * float(Configuracion.objects.first().precio_hora_cancha if Configuracion.objects.exists() else 15.00)

                if self.usuario and hasattr(self.usuario, 'perfil') and self.usuario.perfil.rol == 'DIR':
                    base = base * 0.60

                if self.cupon and self.cupon.es_valido():
                    total = max(0, base - float(self.cupon.descuento))
                    if not self.pk:
                        self.cupon.usos_actuales += 1
                        self.cupon.save()
                else:
                    total = base
                    
                self.precio_total = Decimal(str(total))
        else:
            self.precio_total = Decimal('0.00')
            
        super().save(*args, **kwargs)


# =====================================================
# 11. MEDIA (GALERÍA Y PUBLICIDAD)
# =====================================================
class FotoGaleria(models.Model):
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

class Publicidad(models.Model):
    imagen = models.ImageField(upload_to='publicidad/', verbose_name="Banner Publicitario")
    empresa = models.CharField(max_length=100, verbose_name="Nombre de la Empresa o Negocio")
    enlace = models.URLField(blank=True, null=True, verbose_name="Link de WhatsApp o Red Social (Opcional)")
    activa = models.BooleanField(default=True, verbose_name="Mostrar anuncio")

    class Meta:
        verbose_name = "Publicidad"
        verbose_name_plural = "Publicidades"

    def __str__(self):
        return f"Publicidad: {self.empresa}"

class AbonoSancion(models.Model):
    sancion = models.ForeignKey(Sancion, on_delete=models.CASCADE, related_name='historial_abonos')
    monto = models.DecimalField(max_digits=8, decimal_places=2)
    fecha = models.DateTimeField(auto_now_add=True)
    partido = models.ForeignKey(Partido, on_delete=models.SET_NULL, null=True, blank=True, related_name='abonos_cobrados')

    def __str__(self):
        return f"Abono ${self.monto} - {self.sancion.equipo.nombre}"