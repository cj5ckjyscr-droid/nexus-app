from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Perfil, Torneo, Equipo, Jugador, Partido, ReservaCancha, Sancion
from .models import FotoGaleria, Publicidad

# =================================================
# 1. CONFIGURACIÓN DE USUARIOS + PERFIL
# =================================================

class PerfilInline(admin.StackedInline):
    """ Muestra el Rol DENTRO de la pantalla de Usuario """
    model = Perfil
    can_delete = False
    verbose_name_plural = 'Perfil de Usuario (Rol)'

class UserAdmin(BaseUserAdmin):
    """ Admin de usuarios personalizado """
    inlines = (PerfilInline,)
    list_display = ('username', 'first_name', 'last_name', 'email', 'get_rol')
    
    def get_rol(self, obj):
        return obj.perfil.get_rol_display()
    get_rol.short_description = 'Rol'

# Re-registramos el usuario
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# =================================================
# 2. GESTIÓN DEPORTIVA (TORNEOS Y EQUIPOS)
# =================================================

@admin.register(Torneo)
class TorneoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'organizador', 'fecha_inicio', 'activo', 'inscripcion_abierta')
    list_filter = ('activo', 'organizador')
    list_editable = ('activo', 'inscripcion_abierta') # Para activar/desactivar rápido

@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'torneo', 'dirigente', 'estado_inscripcion', 'tiene_deudas')
    search_fields = ('nombre', 'dirigente__username')
    list_filter = ('torneo', 'estado_inscripcion')

    # Función para ver si debe dinero desde la lista
    def tiene_deudas(self, obj):
        return obj.tiene_deudas()
    tiene_deudas.boolean = True # Pone un icono de Check/X

@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    
    list_display = ('nombres', 'equipo', 'dorsal') 
    search_fields = ('nombres',)
    list_filter = ('equipo__torneo',)

@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'torneo', 'fecha_hora', 'estado')
    list_filter = ('torneo', 'estado')
    date_hierarchy = 'fecha_hora' # Navegación por fechas arriba

# =================================================
# 3. GESTIÓN FINANCIERA Y DISCIPLINARIA 
# =================================================

@admin.register(Sancion)
class SancionAdmin(admin.ModelAdmin):
    """ AQUÍ ES DONDE HARÁS LA PRUEBA DE LA DEUDA """
    list_display = ('equipo', 'tipo', 'monto', 'pagada', 'torneo')
    list_filter = ('pagada', 'tipo', 'torneo')
    search_fields = ('equipo__nombre',)
    list_editable = ('pagada',) # Checkbox para pagar rápido

@admin.register(ReservaCancha)
class ReservaCanchaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'hora_inicio', 'hora_fin', 'estado', 'usuario', 'es_torneo')
    list_filter = ('fecha', 'estado', 'es_torneo')
    ordering = ('-fecha', 'hora_inicio')

# Si todavía usas DetallePartido, lo dejamos simple:
# admin.site.register(DetallePartido)

@admin.register(FotoGaleria)
class FotoGaleriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'orden', 'activa')
    list_editable = ('orden', 'activa')

@admin.register(Publicidad)
class PublicidadAdmin(admin.ModelAdmin):
    list_display = ('empresa', 'activa', 'enlace')
    list_editable = ('activa',)