from django.contrib import admin
from django.urls import path, include
from core import views
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # 1. LANDING SAAS Y LOGIN
    path('', views.landing_principal, name='landing_principal'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('registro/', views.registro_publico, name='registro_publico'),
    path('nexus-admin/planes/', views.gestionar_planes_saas, name='gestionar_planes_saas'),
    
    # 2. PORTAL MULTI-TENANT (PÚBLICO POR CANCHA)
    # Por ahora lo dejamos simple, luego se puede expandir
    path('cancha/<slug:slug_complejo>/', views.portal_complejo, name='portal_complejo'),

    # 3. RUTAS DEL SISTEMA PRIVADO (DASHBOARD)
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Torneos y Equipos
    path('torneos/', views.gestionar_torneos, name='gestionar_torneos'),
    path('torneos/editar/<int:torneo_id>/', views.editar_torneo, name='editar_torneo'),
    path('torneos/eliminar/<int:torneo_id>/', views.eliminar_torneo, name='eliminar_torneo'),
    
    path('categorias/', views.gestionar_categorias, name='gestionar_categorias'),
    path('categorias/editar/<int:categoria_id>/', views.editar_categoria, name='editar_categoria'),
    path('categorias/eliminar/<int:categoria_id>/', views.eliminar_categoria, name='eliminar_categoria'),

    path('equipos/', views.gestionar_equipos, name='gestionar_equipos'),
    path('equipos/editar/<int:equipo_id>/', views.editar_equipo, name='editar_equipo'),
    path('equipos/eliminar/<int:equipo_id>/', views.eliminar_equipo, name='eliminar_equipo'),
    path('sancionar_equipo/<int:equipo_id>/', views.sancionar_equipo, name='sancionar_equipo'),
    path('asignar_cupos/<int:equipo_id>/', views.asignar_cupos, name='asignar_cupos'),
    
    # Jugadores y Carnets
    path('jugadores/', views.gestionar_jugadores, name='gestionar_jugadores'),
    path('jugadores/editar/<int:jugador_id>/', views.editar_jugador, name='editar_jugador'),
    path('jugadores/eliminar/<int:jugador_id>/', views.eliminar_jugador, name='eliminar_jugador'),
    path('imprimir-carnets/<int:equipo_id>/', views.imprimir_carnets, name='imprimir_carnets'),
    path('api/buscar_cedula/', views.api_consultar_cedula, name='api_consultar_cedula'),
    path('api/buscar_jugador/<str:cedula>/', views.buscar_jugador_api, name='buscar_jugador_api'),
    path('traspasar_jugador/<int:jugador_id>/', views.traspasar_jugador, name='traspasar_jugador'),

    # Calendario y Vocalía
    path('programar/', views.programar_partidos, name='programar_partidos'),
    path('torneo/<int:torneo_id>/cambiar-formato/', views.cambiar_formato_fase1, name='cambiar_formato_fase1'),
    path('partido/editar/<int:partido_id>/', views.editar_partido, name='editar_partido'),
    path('partido/eliminar/<int:partido_id>/', views.eliminar_partido, name='eliminar_partido'),
    path('partido/reiniciar/<int:partido_id>/', views.reiniciar_partido, name='reiniciar_partido'),
    path('partido/resultado/<int:partido_id>/', views.registrar_resultado, name='registrar_resultado'),
    
    path('vocalia/<int:partido_id>/', views.gestionar_vocalia, name='gestionar_vocalia'),
    path('vocalia/incidencia/<int:partido_id>/', views.registrar_incidencia, name='registrar_incidencia'),
    path('vocalia/eliminar-evento/<int:partido_id>/<int:jugador_id>/<str:tipo>/', views.eliminar_evento_ultimo, name='eliminar_evento_ultimo'),
    path('vocalia/eliminar_evento_exacto/<int:evento_id>/', views.eliminar_evento, name='eliminar_evento'),
    path('vocalia/eliminar_multa/<int:multa_id>/', views.eliminar_multa, name='eliminar_multa'),
    path('vocalia/toggle-asistencia/<int:partido_id>/<int:jugador_id>/', views.toggle_asistencia, name='toggle_asistencia'),
    path('acta/pdf/<int:partido_id>/', views.generar_acta_pdf, name='generar_acta_pdf'),

    # Fixtures Automáticos
    path('generar-fixture/<int:torneo_id>/', views.generar_fixture, name='generar_fixture'),
    path('generar_fase2/<int:torneo_id>/', views.generar_fase2, name='generar_fase2'),
    path('generar-semis-directas/<int:torneo_id>/', views.generar_semis_directas, name='generar_semis_directas'),
    path('generar-cuartos-directos/<int:torneo_id>/', views.generar_cuartos_directos, name='generar_cuartos_directos'),
    path('generar_cuartos_final/<int:torneo_id>/', views.generar_cuartos_final, name='generar_cuartos_final'),
    path('generar_semifinales/<int:torneo_id>/', views.generar_semifinales, name='generar_semifinales'),
    path('generar_finales/<int:torneo_id>/', views.generar_finales, name='generar_finales'),
    path('llaves/<int:torneo_id>/', views.llaves_eliminatorias, name='llaves_eliminatorias'),
    path('revertir-transicion/<int:torneo_id>/', views.revertir_transicion, name='revertir_transicion'),
    path('activar-vuelta-f1/<int:torneo_id>/', views.activar_vuelta_f1, name='activar_vuelta_f1'),
    path('cambiar-formato-f1/<int:torneo_id>/', views.cambiar_formato_fase1, name='cambiar_formato_f1'),

    # Tablas y Estadísticas
    path('posiciones/<int:torneo_id>/', views.tabla_posiciones, name='tabla_posiciones'),
    path('posiciones_fase2/<int:torneo_id>/', views.tabla_posiciones_f2, name='tabla_posiciones_f2'),
    path('goleadores/<int:torneo_id>/', views.tabla_goleadores, name='tabla_goleadores'),
    path('seleccionar-reporte/', views.seleccionar_reporte, name='seleccionar_reporte'),
    path('estadisticas/<int:torneo_id>/', views.reporte_estadisticas, name='reporte_estadisticas'),
    path('proxima-jornada/<int:torneo_id>/', views.proxima_jornada, name='proxima_jornada'),

    # Finanzas
    path('finanzas/', views.gestionar_finanzas, name='gestionar_finanzas'),
    path('pago/registrar/', views.registrar_pago, name='registrar_pago'),
    path('pago/historial/<int:equipo_id>/', views.historial_pagos_equipo, name='historial_pagos_equipo'),
    path('pago/pdf/<int:pago_id>/', views.generar_recibo_pago_pdf, name='generar_recibo_pago_pdf'),
    path('sancion/cobrar/<int:sancion_id>/', views.cobrar_sancion, name='cobrar_sancion'),
    path('sancion/reversar/<int:sancion_id>/', views.revertir_cobro_sancion, name='revertir_cobro_sancion'),

    # Solicitudes e Inscripciones Publicas
    path('torneos-activos/', views.ver_torneos_activos, name='ver_torneos_activos'),
    path('solicitar-inscripcion/<int:torneo_id>/', views.solicitar_inscripcion, name='solicitar_inscripcion'),
    path('cancelar-inscripcion/<int:equipo_id>/', views.cancelar_inscripcion_equipo, name='cancelar_inscripcion_equipo'),
    path('solicitudes/', views.gestionar_solicitudes, name='gestionar_solicitudes'),
    path('importar-equipo/<int:torneo_nuevo_id>/', views.importar_equipo_existente, name='importar_equipo_existente'),

    # Configuracion de Admin y Medios
    path('configuracion/', views.gestionar_configuracion, name='gestionar_configuracion'),
    path('medios/', views.gestionar_medios, name='gestionar_medios'),
    path('medios/eliminar-foto/<int:foto_id>/', views.eliminar_foto, name='eliminar_foto'),

    # Gestión Global de Usuarios
    path('usuarios/crear/', views.crear_usuario, name='crear_usuario'),
    path('usuarios/gestionar/', views.gestionar_usuarios, name='gestionar_usuarios'),
    path('admin_jugadores/', views.admin_gestion_jugadores, name='admin_gestion_jugadores'),
    path('admin_usuarios/', views.admin_gestion_usuarios, name='admin_gestion_usuarios'),
    
    # Recuperación de Contraseña
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='core/password_reset_form.html'), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='core/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='core/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='core/password_reset_complete.html'), name='password_reset_complete'),
    path('nexus-admin/', views.dashboard_saas, name='dashboard_saas'),
    path('nexus-admin/', views.dashboard_saas, name='dashboard_saas'),
    path('nexus-admin/canchas/', views.gestionar_canchas_saas, name='gestionar_canchas_saas'),
    path('nexus-admin/canchas/editar/<int:cancha_id>/', views.editar_cancha_saas, name='editar_cancha_saas'),
    path('nexus-admin/pagos/', views.registrar_pago_saas, name='registrar_pago_saas'),

    path('precios/', views.precios_publicos, name='precios_publicos'),

    path('cancha/<slug:slug_complejo>/', views.portal_complejo, name='portal_complejo'),
]

# Servir archivos estáticos/media en entorno local de desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
