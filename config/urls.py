from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from core import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # --- DJANGO ADMIN (Panel Oscuro) ---
    path('admin/', admin.site.urls),

    # ============================================
    # 1. ACCESO Y SEGURIDAD (Login, Registro, Usuarios)
    # ============================================
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    # Registro Público
    path('registro/', views.registro_publico, name='registro_publico'),
    
    # GESTIÓN DE USUARIOS (Vistas del Organizador)
    path('crear-usuario/', views.crear_usuario, name='crear_usuario'),
    path('gestion/usuarios/', views.admin_gestion_usuarios, name='admin_gestion_usuarios'), 
    path('usuarios/', views.gestionar_usuarios, name='gestionar_usuarios'),

    # ============================================
    # 2. VISTAS PRINCIPALES Y TORNEOS (ORGANIZADOR)
    # ============================================
    path('', views.dashboard, name='dashboard'),
    path('torneos/', views.gestionar_torneos, name='gestionar_torneos'),
    path('torneos/editar/<int:torneo_id>/', views.editar_torneo, name='editar_torneo'),
    path('torneos/eliminar/<int:torneo_id>/', views.eliminar_torneo, name='eliminar_torneo'),
    
    # ============================================
    # 3. GESTIÓN DE EQUIPOS Y JUGADORES
    # ============================================
    path('equipos/', views.gestionar_equipos, name='gestionar_equipos'),
    path('equipos/editar/<int:equipo_id>/', views.editar_equipo, name='editar_equipo'),
    path('equipos/eliminar/<int:equipo_id>/', views.eliminar_equipo, name='eliminar_equipo'),

    path('equipos/<int:equipo_id>/carnets/', views.imprimir_carnets, name='imprimir_carnets'),
    
    # Sanciones (Lista Negra) y Asignación de Cupos Pagados
    path('equipos/sancionar/<int:equipo_id>/', views.sancionar_equipo, name='sancionar_equipo'),
    path('equipos/cupos/<int:equipo_id>/', views.asignar_cupos, name='asignar_cupos'),
    
    # Gestión de Jugadores
    path('jugadores/', views.gestionar_jugadores, name='gestionar_jugadores'), # Vista para Dirigentes
    path('gestion/jugadores/', views.admin_gestion_jugadores, name='admin_gestion_jugadores'), # Vista para Admin
    
    path('jugadores/editar/<int:jugador_id>/', views.editar_jugador, name='editar_jugador'),
    path('jugadores/eliminar/<int:jugador_id>/', views.eliminar_jugador, name='eliminar_jugador'),
    
    # Traspaso en el Mercado de Fichajes
    path('jugadores/traspasar/<int:jugador_id>/', views.traspasar_jugador, name='traspasar_jugador'),
    
    # API para Cédulas
    path('api/consultar-cedula/', views.api_consultar_cedula, name='api_consultar_cedula'),

    # ============================================
    # 4. GESTIÓN DE PARTIDOS (Calendario y Fixture)
    # ============================================
    path('programar/', views.programar_partidos, name='programar_partidos'),
    path('partido/editar/<int:partido_id>/', views.editar_partido, name='editar_partido'),
    path('partido/eliminar/<int:partido_id>/', views.eliminar_partido, name='eliminar_partido'),
    path('partido/reiniciar/<int:partido_id>/', views.reiniciar_partido, name='reiniciar_partido'),
    
    path('torneo/<int:torneo_id>/generar-fixture/', views.generar_fixture, name='generar_fixture'),
    path('torneo/<int:torneo_id>/proxima-fecha/', views.proxima_jornada, name='proxima_jornada'),

    # Generadores de Play-Offs (Transiciones de Torneo)
    path('generar-fase2/<int:torneo_id>/', views.generar_fase2, name='generar_fase2'), # Desde Grupos
    path('torneo/<int:torneo_id>/generar-cuartos/', views.generar_cuartos_final, name='generar_cuartos_final'), # Desde Grupos
    
    # Saltos Directos desde Fase 1
    path('torneo/<int:torneo_id>/generar-cuartos-directos/', views.generar_cuartos_directos, name='generar_cuartos_directos'), 
    path('torneo/<int:torneo_id>/generar-semis-directas/', views.generar_semis_directas, name='generar_semis_directas'), 

    path('torneo/<int:torneo_id>/generar-semis/', views.generar_semifinales, name='generar_semifinales'),
    path('torneo/<int:torneo_id>/generar-final/', views.generar_finales, name='generar_finales'),
    path('torneo/<int:torneo_id>/llaves-finales/', views.llaves_eliminatorias, name='llaves_eliminatorias'),

    # ============================================
    # 5. JUEGO Y VOCALÍA (El corazón del sistema)
    # ============================================
    path('partido/<int:partido_id>/resultado/', views.registrar_resultado, name='registrar_resultado'),
    path('partido/<int:partido_id>/vocalia/', views.gestionar_vocalia, name='gestionar_vocalia'),
    path('partido/<int:partido_id>/incidencia/', views.registrar_incidencia, name='registrar_incidencia'),
    
    # Acciones dentro de la Vocalía
    path('evento/eliminar/<int:evento_id>/', views.eliminar_evento, name='eliminar_evento'),
    path('partido/<int:partido_id>/eliminar-evento-ultimo/<int:jugador_id>/<str:tipo>/', views.eliminar_evento_ultimo, name='eliminar_evento_ultimo'),
    path('multa/eliminar/<int:multa_id>/', views.eliminar_multa, name='eliminar_multa'),
    path('vocalia/asistencia/<int:partido_id>/<int:jugador_id>/', views.toggle_asistencia, name='toggle_asistencia'),
    
    # Acta Digital
    path('partido/acta-pdf/<int:partido_id>/', views.generar_acta_pdf, name='generar_acta_pdf'),

    # ============================================
    # 6. TABLAS DE POSICIONES Y ESTADÍSTICAS
    # ============================================
    path('tabla/<int:torneo_id>/', views.tabla_posiciones, name='tabla_posiciones'),
    path('tabla/fase2/<int:torneo_id>/', views.tabla_posiciones_f2, name='tabla_posiciones_f2'),

    path('goleadores/<int:torneo_id>/', views.tabla_goleadores, name='tabla_goleadores'),
    path('reportes/', views.seleccionar_reporte, name='seleccionar_reporte'),
    path('reportes/<int:torneo_id>/', views.reporte_estadisticas, name='reporte_estadisticas'),

    # ============================================
    # 7. FINANZAS (Cobros, Pagos y Sanciones)
    # ============================================
    path('finanzas/', views.gestionar_finanzas, name='gestionar_finanzas'),
    path('finanzas/pagar/', views.registrar_pago, name='registrar_pago'),
    path('finanzas/historial/<int:equipo_id>/', views.historial_pagos_equipo, name='historial_pagos_equipo'),
    path('finanzas/recibo/<int:pago_id>/', views.generar_recibo_pago_pdf, name='generar_recibo_pago_pdf'),
    path('sancion/cobrar/<int:sancion_id>/', views.cobrar_sancion, name='cobrar_sancion'),
    path('sancion/revertir/<int:sancion_id>/', views.revertir_cobro_sancion, name='revertir_cobro_sancion'), 

    # ============================================
    # 8. SISTEMA DE RESERVAS (Turnos)
    # ============================================
    path('reservar/', views.reservar_cancha, name='reservar_cancha'),
    path('mis-reservas/', views.mis_reservas, name='mis_reservas'),

    # Flujo de Inscripción
    path('torneos-disponibles/', views.ver_torneos_activos, name='ver_torneos_activos'),
    path('inscribirse/<int:torneo_id>/', views.solicitar_inscripcion, name='solicitar_inscripcion'),
    path('inscribirse/<int:torneo_nuevo_id>/importar/', views.importar_equipo_existente, name='importar_equipo_existente'), # Importar histórico
    
    # Aprobaciones y Solicitudes
    path('solicitudes/', views.gestionar_solicitudes, name='gestionar_solicitudes'),
    path('aprobar-reserva/<int:reserva_id>/', views.aprobar_reserva_admin, name='aprobar_reserva_admin'),

    # Carrito y Cancelaciones
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('checkout/', views.checkout_pago, name='checkout_pago'),
    path('cancelar/reserva/<int:reserva_id>/', views.cancelar_reserva, name='cancelar_reserva'),
    path('cancelar/equipo/<int:equipo_id>/', views.cancelar_inscripcion_equipo, name='cancelar_inscripcion_equipo'),

    # ============================================
    # 9. CONFIGURACIÓN DEL SISTEMA, CATEGORÍAS Y MEDIOS
    # ============================================
    
    # 🔥 AQUÍ ESTÁ LA NUEVA RUTA DE CATEGORÍAS 🔥
    path('categorias/', views.gestionar_categorias, name='gestionar_categorias'),
    path('categorias/editar/<int:categoria_id>/', views.editar_categoria, name='editar_categoria'),
    path('categorias/eliminar/<int:categoria_id>/', views.eliminar_categoria, name='eliminar_categoria'),

    
    path('horarios/', views.gestionar_horarios, name='gestionar_horarios'),
    path('horarios/eliminar/<int:horario_id>/', views.eliminar_horario, name='eliminar_horario'),

    path('marketing/', views.gestionar_medios, name='gestionar_medios'),
    path('marketing/foto/eliminar/<int:foto_id>/', views.eliminar_foto, name='eliminar_foto'),
    path('marketing/publicidad/eliminar/<int:pub_id>/', views.eliminar_publicidad, name='eliminar_publicidad'),
    
    # ============================================
    # 10. RECUPERACIÓN DE CONTRASEÑAS (Auth Views)
    # ============================================
    path('recuperar/', auth_views.PasswordResetView.as_view(template_name='registration/password_reset_form.html'), name='password_reset'),
    path('recuperar/enviado/', auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('recuperar/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('recuperar/completo/', auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    
    # Herramientas del Fixture
    path('torneo/<int:torneo_id>/revertir-transicion/', views.revertir_transicion, name='revertir_transicion'),
    path('torneo/<int:torneo_id>/activar-vuelta/', views.activar_vuelta_f1, name='activar_vuelta_f1'),
    path('torneo/<int:torneo_id>/cambiar-formato/', views.cambiar_formato_fase1, name='cambiar_formato_fase1'),
    
    path('api/buscar-jugador/<str:cedula>/', views.buscar_jugador_api, name='buscar_jugador_api'),
    path('ajustes/sistema/', views.gestionar_configuracion, name='gestionar_configuracion'),
    path('rechazar-reserva/<int:reserva_id>/', views.rechazar_reserva_admin, name='rechazar_reserva_admin'),

]
# Permite servir archivos Media (imágenes) en el entorno de desarrollo local
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)