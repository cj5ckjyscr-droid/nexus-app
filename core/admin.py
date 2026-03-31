from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

# Importamos ÚNICAMENTE los modelos de la nueva arquitectura SaaS
from .models import (
    PlanSuscripcion, ComplejoDeportivo, Perfil, 
    Configuracion, FotoGaleria, Categoria, Cupon, 
    Torneo, Equipo, Pago, Jugador, Partido, 
    DetallePartido, Sancion, AbonoSancion
)

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
        # Evitar errores si el usuario aún no tiene perfil creado
        if hasattr(obj, 'perfil'):
            return obj.perfil.get_rol_display()
        return "Sin Rol"
    get_rol.short_description = 'Rol'

# Re-registramos el usuario
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# =================================================
# 2. GESTIÓN DEL SAAS (SÚPER ADMINISTRADOR)
# =================================================

@admin.register(PlanSuscripcion)
class PlanSuscripcionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio_mensual', 'max_torneos', 'max_categorias_por_torneo')
    search_fields = ('nombre',)

@admin.register(ComplejoDeportivo)
class ComplejoDeportivoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'organizador', 'plan', 'activo', 'fecha_vencimiento')
    list_filter = ('activo', 'plan')
    search_fields = ('nombre', 'organizador__username')
    prepopulated_fields = {'slug': ('nombre',)}
    
    def esta_al_dia(self, obj):
        return obj.esta_al_dia()
    esta_al_dia.boolean = True
    esta_al_dia.short_description = '¿Al Día?'

# =================================================
# 3. GESTIÓN DEPORTIVA (TORNEOS Y EQUIPOS)
# =================================================

@admin.register(Torneo)
class TorneoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'complejo', 'organizador', 'fecha_inicio', 'activo', 'inscripcion_abierta')
    list_filter = ('activo', 'complejo', 'organizador')
    list_editable = ('activo', 'inscripcion_abierta') 

@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'torneo', 'dirigente', 'estado_inscripcion', 'tiene_deudas')
    search_fields = ('nombre', 'dirigente__username')
    list_filter = ('torneo__complejo', 'torneo', 'estado_inscripcion')

    def tiene_deudas(self, obj):
        return obj.tiene_deudas()
    tiene_deudas.boolean = True 

@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = ('nombres', 'equipo', 'dorsal', 'esta_habilitado') 
    search_fields = ('nombres', 'cedula')
    list_filter = ('equipo__torneo__complejo', 'equipo__torneo')
    
    def esta_habilitado(self, obj):
        return obj.esta_habilitado
    esta_habilitado.boolean = True 

@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'torneo', 'fecha_hora', 'estado')
    list_filter = ('torneo__complejo', 'torneo', 'estado')
    date_hierarchy = 'fecha_hora' 

# =================================================
# 4. GESTIÓN FINANCIERA Y DISCIPLINARIA 
# =================================================

@admin.register(Sancion)
class SancionAdmin(admin.ModelAdmin):
    list_display = ('equipo', 'tipo', 'monto', 'pagada', 'torneo')
    list_filter = ('pagada', 'tipo', 'torneo__complejo', 'torneo')
    search_fields = ('equipo__nombre',)
    list_editable = ('pagada',) 

@admin.register(FotoGaleria)
class FotoGaleriaAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'complejo', 'orden', 'activa')
    list_editable = ('orden', 'activa')
    list_filter = ('complejo',)

# =================================================
# 5. REGISTROS SIMPLES
# =================================================
admin.site.register(Configuracion)
admin.site.register(Categoria)
admin.site.register(Cupon)
admin.site.register(Pago)
admin.site.register(DetallePartido)
admin.site.register(AbonoSancion)