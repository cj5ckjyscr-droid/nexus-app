"""Contenido del Centro de Ayuda.

Cada guía es una receta paso a paso. `url` es el nombre de una ruta de Django
(sin argumentos) para el botón «Ir a esta pantalla»; `roles` indica para quién
es la guía: ORG (organizador / dueño de la cancha), DIR (dirigente), VOC
(vocal de mesa) y FAN (público).
"""

ROLES = {
    'ORG': {'nombre': 'Organizador', 'icono': 'bi-gear-wide-connected', 'color': '#4F46E5',
            'desc': 'Dueño o staff de la cancha: arma torneos, aprueba equipos y cobra.'},
    'DIR': {'nombre': 'Dirigente', 'icono': 'bi-shield-fill', 'color': '#0369A1',
            'desc': 'Representa a un equipo: lo inscribe, ficha jugadores y paga.'},
    'VOC': {'nombre': 'Vocal de mesa', 'icono': 'bi-clipboard-data', 'color': '#B45309',
            'desc': 'Anota en vivo lo que pasa en cada partido y cierra el acta.'},
    'FAN': {'nombre': 'Público', 'icono': 'bi-people-fill', 'color': '#15803D',
            'desc': 'Jugadores e hinchas: ven tablas, goleadores y fixture.'},
}

# La "ruta" de un campeonato, de principio a fin. Cada paso apunta a una guía.
RUTA_CAMPEONATO = [
    {'n': 1, 'titulo': 'Categoría', 'texto': 'Define la división y el color de carnet.', 'guia': 'crear-categoria', 'icono': 'bi-tags'},
    {'n': 2, 'titulo': 'Torneo', 'texto': 'Precios, multas y si las inscripciones están abiertas.', 'guia': 'crear-torneo', 'icono': 'bi-trophy'},
    {'n': 3, 'titulo': 'Equipos', 'texto': 'Se inscriben solos o los registras tú; los apruebas.', 'guia': 'inscribir-equipos', 'icono': 'bi-shield'},
    {'n': 4, 'titulo': 'Jugadores', 'texto': 'Cada equipo ficha a su plantilla con cédula y foto.', 'guia': 'inscribir-jugadores', 'icono': 'bi-person-plus'},
    {'n': 5, 'titulo': 'Carnets', 'texto': 'La organización los imprime por equipo.', 'guia': 'imprimir-carnets', 'icono': 'bi-person-vcard'},
    {'n': 6, 'titulo': 'Empezar', 'texto': 'Eliges la modalidad y el sistema arma fixture y llaves.', 'guia': 'empezar-campeonato', 'icono': 'bi-play-circle'},
    {'n': 7, 'titulo': 'Fechas', 'texto': 'Pones día, hora y cancha a cada partido.', 'guia': 'programar-partidos', 'icono': 'bi-calendar-event'},
    {'n': 8, 'titulo': 'Vocalía', 'texto': 'El vocal anota goles y tarjetas y cierra el acta.', 'guia': 'vocalia', 'icono': 'bi-clipboard-data'},
    {'n': 9, 'titulo': 'Tablas y llaves', 'texto': 'Posiciones y cruces se actualizan solos.', 'guia': 'fases-y-llaves', 'icono': 'bi-diagram-3'},
    {'n': 10, 'titulo': 'Cobros', 'texto': 'Inscripciones y multas se cargan solas; tú cobras.', 'guia': 'cobros-y-finanzas', 'icono': 'bi-cash-stack'},
]

GUIAS = [
    # ------------------------------------------------------------------ ORGANIZADOR
    {
        'slug': 'crear-categoria', 'roles': ['ORG'], 'icono': 'bi-tags', 'minutos': 1,
        'titulo': 'Crear una categoría',
        'resumen': 'Las categorías separan a los equipos (Libre, Máster, Femenino…) y definen el color de sus carnets.',
        'pasos': [
            {'titulo': 'Abre Categorías', 'texto': 'En el menú superior entra a <b>Competencia → Categorías</b>.', 'url': 'gestionar_categorias'},
            {'titulo': 'Escribe el nombre y elige un color', 'texto': 'En <b>Nueva Categoría</b> pon el nombre (ej. «Máster») y el <b>Color de Carnet</b>: ese color se usa en el panel del escudo de cada carnet.'},
            {'titulo': 'Guarda', 'texto': 'Toca <b>Guardar Categoría</b>. Ya puedes usarla al crear un torneo.'},
        ],
        'consejos': ['Usa colores bien distintos entre categorías: así el vocal reconoce el carnet de un vistazo.'],
        'avisos': ['Tu plan tiene un cupo de categorías. Si aparece «Límite alcanzado», mejora tu plan.'],
    },
    {
        'slug': 'crear-torneo', 'roles': ['ORG'], 'icono': 'bi-trophy', 'minutos': 2,
        'titulo': 'Crear un torneo',
        'resumen': 'El torneo guarda los precios de inscripción, el valor de las multas por tarjeta y si se aceptan equipos.',
        'pasos': [
            {'titulo': 'Abre Torneos', 'texto': 'Entra a <b>Competencia → Torneos</b>.', 'url': 'gestionar_torneos'},
            {'titulo': 'Completa los datos', 'texto': 'Nombre, <b>Categoría</b> y fecha de inicio. Deja marcado <b>¿Inscripción Habilitada?</b> para que los dirigentes puedan inscribirse.'},
            {'titulo': 'Define cuánto se cobra', 'texto': 'Elige si la inscripción es <b>por equipo</b> o <b>por jugador</b> (casilla «¿Cobrar inscripción POR JUGADOR…?») y pon los montos. Abajo van las multas por <b>amarilla</b> y <b>roja</b>: el sistema las cobrará solo al cerrar cada acta.'},
            {'titulo': 'Crea el torneo', 'texto': 'Toca <b>Crear Torneo</b>. Aparecerá en la lista con sus precios.'},
        ],
        'consejos': ['Cuando ya tengas todos los equipos, desmarca «¿Inscripción Habilitada?» para que nadie más se inscriba.'],
        'avisos': ['Tu plan limita cuántos torneos activos puedes tener. Finaliza los torneos viejos para liberar cupo.'],
    },
    {
        'slug': 'inscribir-equipos', 'roles': ['ORG'], 'icono': 'bi-shield', 'minutos': 3,
        'titulo': 'Inscribir y aprobar equipos',
        'resumen': 'Los equipos llegan de dos formas: el dirigente envía una solicitud desde su celular, o tú los registras directamente.',
        'pasos': [
            {'titulo': 'Opción A — el dirigente se inscribe solo', 'texto': 'Comparte el enlace de tu cancha. El dirigente crea su cuenta, entra a <b>Inscribirse</b>, elige el torneo y envía la solicitud. Queda en estado <b>Pendiente</b>.'},
            {'titulo': 'Revisa las solicitudes', 'texto': 'En tu Inicio aparece el aviso de solicitudes; toca <b>Revisar</b>. Por cada equipo puedes <b>Aprobar Equipo</b> o <b>Rechazar</b>. Al aprobar, el dirigente ya puede fichar jugadores y se carga la deuda de inscripción.', 'url': 'gestionar_solicitudes'},
            {'titulo': 'Opción B — lo registras tú', 'texto': 'En <b>Competencia → Equipos</b> llena <b>Registrar Equipo</b>: torneo, nombre, escudo y el <b>Dirigente del Equipo</b>. Si la persona no tiene cuenta, créala primero en <b>Usuarios</b>.', 'url': 'gestionar_equipos'},
            {'titulo': 'Opcional: limita los jugadores', 'texto': 'Con el botón <b>Cupos</b> de cada equipo fijas el máximo de jugadores que puede fichar (útil si cobras por jugador).'},
        ],
        'consejos': ['Solo los equipos <b>aprobados</b> entran al campeonato. Revisa las solicitudes antes de empezar.'],
        'avisos': [],
    },
    {
        'slug': 'inscribir-jugadores', 'roles': ['ORG', 'DIR'], 'icono': 'bi-person-plus', 'minutos': 3,
        'titulo': 'Inscribir (fichar) jugadores',
        'resumen': 'Cada jugador se ficha con su cédula, nombres, dorsal y foto. Lo puede hacer el dirigente de su equipo o el organizador.',
        'pasos': [
            {'titulo': 'Abre la nómina', 'texto': 'Dirigente: en tu Inicio toca <b>Mi Equipo</b>. Organizador: en tu Inicio toca <b>Fichar</b> y elige el equipo.', 'url': 'gestionar_jugadores'},
            {'titulo': 'Escribe la cédula primero', 'texto': 'En <b>Fichar Jugador</b> escribe la <b>Cédula de Identidad</b>. Si el jugador ya jugó antes en el sistema, sus datos y su foto se llenan solos.'},
            {'titulo': 'Completa nombres y dorsal', 'texto': 'Escribe los nombres completos y el <b>Dorsal</b> (del 0 al 99). No se puede repetir un dorsal dentro del mismo equipo.'},
            {'titulo': 'Sube la foto', 'texto': 'Una foto de frente, tipo carnet. El sistema la comprime sola para que cargue rápido.'},
            {'titulo': 'Guarda', 'texto': 'Toca <b>FICHAR JUGADOR</b>. Aparece en la nómina y ya puede jugar.'},
        ],
        'consejos': ['Un jugador no puede estar en dos equipos del mismo torneo. Si cambia de equipo, el organizador usa el <b>Traspaso</b> en <b>Jugadores</b>.',
                     'Los jugadores de Colombia o Venezuela los registra el organizador, que puede cambiar el tipo de documento.'],
        'avisos': ['Si el equipo tiene cupos y ya llegó al máximo, verás «Límite Alcanzado»: pide al organizador que amplíe los cupos.'],
    },
    {
        'slug': 'imprimir-carnets', 'roles': ['ORG'], 'icono': 'bi-person-vcard', 'minutos': 1,
        'titulo': 'Imprimir los carnets',
        'resumen': 'Los carnets salen por equipo, en tamaño tarjeta (8,6 × 5,4 cm), con foto, dorsal, escudo y todos los datos. Solo la organización de la cancha puede imprimirlos.',
        'pasos': [
            {'titulo': 'Busca el equipo', 'texto': 'Entra a <b>Competencia → Equipos</b> y toca <b>Carnets</b> en el equipo. También tienes el botón <b>Imprimir carnets</b> en la nómina de cada equipo.', 'url': 'gestionar_equipos'},
            {'titulo': 'Revisa la vista previa', 'texto': 'Verás todos los carnets del equipo. Si a alguno le falta la foto, edítalo primero en la nómina.'},
            {'titulo': 'Imprime', 'texto': 'Toca <b>Imprimir carnets</b>. Usa hoja A4, escala 100 % y activa «Gráficos de fondo» para que salgan los colores. También puedes «Guardar como PDF».'},
        ],
        'consejos': ['Los nombres largos se ajustan solos para que se lean completos.', 'El color del panel lo define la categoría del torneo.'],
        'avisos': ['Los jugadores expulsados del torneo no aparecen en los carnets.',
                   'Los dirigentes no pueden imprimir carnets: se los entrega la organización.'],
    },
    {
        'slug': 'empezar-campeonato', 'roles': ['ORG'], 'icono': 'bi-play-circle', 'minutos': 4,
        'titulo': 'Empezar el campeonato (fixture y llaves)',
        'resumen': 'Eliges la modalidad y el sistema sortea grupos, arma todas las fechas y fija las llaves. Nada se guarda hasta que confirmes.',
        'pasos': [
            {'titulo': 'Abre el calendario', 'texto': 'Entra a <b>Competencia → Campeonato y fixture</b>, elige el torneo y toca <b>Empezar campeonato</b>.', 'url': 'programar_partidos'},
            {'titulo': 'Elige la modalidad', 'texto': '<b>Liga</b>: todos contra todos. <b>Liga + Llaves</b>: todos contra todos y los mejores pasan a eliminatorias. <b>Grupos + Llaves</b>: grupos sorteados y clasifican los primeros (y mejores terceros). <b>Eliminación directa</b>: llaves desde el inicio.'},
            {'titulo': 'Configura la estructura', 'texto': 'Número de grupos, cuántos clasifican, si hay ida y vuelta, final a ida y vuelta o partido por el 3er lugar. El sistema te muestra las <b>estructuras válidas</b> para tu número de equipos: toca una para usarla.'},
            {'titulo': 'Mira la vista previa', 'texto': 'Toca <b>Ver vista previa</b>. Puedes mover equipos de grupo y <b>Aplicar cambios de grupo</b>, o <b>Volver a sortear</b>. También puedes <b>Descargar PDF</b> para compartir.'},
            {'titulo': 'Confirma', 'texto': 'Toca <b>Confirmar y guardar en el sistema</b>. Se crea el fixture completo y los cruces quedan fijos.'},
        ],
        'consejos': ['El sorteo tiene un número (Sorteo #…): con ese número siempre sale el mismo resultado, así nadie puede decir que fue arreglado.',
                     'Los cruces enfrentan al 1° con el último clasificado: el 1° y el 2° solo pueden verse en la final.'],
        'avisos': ['Después de confirmar <b>no se aceptan equipos nuevos</b>. Los dirigentes sí pueden seguir fichando jugadores.',
                   'Si te equivocaste y aún no se juega ningún partido, puedes usar <b>Reiniciar campeonato</b> en la página del campeonato.'],
    },
    {
        'slug': 'programar-partidos', 'roles': ['ORG'], 'icono': 'bi-calendar-event', 'minutos': 2,
        'titulo': 'Programar día, hora y cancha',
        'resumen': 'Los cruces ya los generó el sistema; tú solo pones cuándo y dónde se juega cada partido.',
        'pasos': [
            {'titulo': 'Abre el calendario del torneo', 'texto': 'En <b>Competencia → Campeonato y fixture</b> elige el torneo. Usa el filtro <b>Sin Fecha</b> para ver lo que falta programar.', 'url': 'programar_partidos'},
            {'titulo': 'Edita cada partido', 'texto': 'Toca el lápiz ✏️ del partido y pon fecha, hora y cancha. Guarda.'},
            {'titulo': 'Comparte la programación', 'texto': 'Descarga el <b>PDF fixture</b> o, desde tu Inicio, la <b>imagen de horarios</b> para mandarla por WhatsApp.'},
        ],
        'consejos': ['En la página del campeonato cada ronda de llaves tiene su propio PDF.'],
        'avisos': [],
    },
    {
        'slug': 'vocalia', 'roles': ['ORG', 'VOC'], 'icono': 'bi-clipboard-data', 'minutos': 5,
        'titulo': 'Llevar la vocalía de un partido',
        'resumen': 'Desde el celular, en la cancha: asistencia, goles, tarjetas, faltas, firmas y cierre del acta.',
        'pasos': [
            {'titulo': 'Abre la mesa de control', 'texto': 'Vocal: en tu Inicio toca <b>Pitar</b> en el partido. Organizador: en el calendario toca <b>A la Mesa</b>.', 'url': 'dashboard'},
            {'titulo': 'Marca quién juega', 'texto': 'Al inicio todos están en la <b>Banca</b>. Toca a cada jugador presente para pasarlo a <b>En Cancha</b>. Solo los que están en cancha pueden recibir goles o tarjetas.'},
            {'titulo': 'Anota durante el partido', 'texto': '⚽ suma un gol, 🟨 amarilla, 🟥 roja directa y ☆ marca al MVP. Si un jugador recibe dos amarillas, el sistema pone la <b>roja por acumulación</b> solo. Las faltas de cada equipo se cuentan arriba.'},
            {'titulo': '¿Te equivocaste?', 'texto': 'Puedes quitar el último evento de un jugador mientras el partido no esté cerrado.'},
            {'titulo': 'Multas, informes y firmas', 'texto': 'Si hubo incidentes aplica <b>Multas Administrativas</b> (barra, invasión…). Escribe el <b>Informe del vocal</b> y del árbitro, y pide la <b>firma</b> de cada capitán en la pantalla.'},
            {'titulo': 'Finaliza', 'texto': 'Toca <b>FINALIZAR PARTIDO</b>. Se actualizan tablas y goleadores, se cargan las multas por tarjeta y se aplican las suspensiones. Si fue eliminatoria y hubo empate, registra los <b>penales</b> antes.'},
            {'titulo': 'Descarga el acta', 'texto': 'El acta oficial en PDF queda disponible en el calendario (botón <b>Acta</b>).'},
        ],
        'consejos': ['Usa <b>Guardar Borrador (Sin Cerrar)</b> si tienes que salir: no se pierde nada.',
                     'Si un equipo no se presentó usa <b>Declarar Walkover (W.O.)</b>: gana 3-0 el que sí llegó.'],
        'avisos': ['Un partido finalizado solo lo puede corregir el administrador de la cancha, y cada corrección queda registrada en el acta.'],
    },
    {
        'slug': 'fases-y-llaves', 'roles': ['ORG', 'FAN'], 'icono': 'bi-diagram-3', 'minutos': 2,
        'titulo': 'Tablas, fases y llaves',
        'resumen': 'Las posiciones se calculan solas con cada acta. Al terminar la primera fase pasas a las llaves con un toque.',
        'pasos': [
            {'titulo': 'Mira las posiciones', 'texto': 'En la página del campeonato, pestaña <b>Posiciones</b>. En verde los que clasifican y en naranja los «mejores» del siguiente puesto.'},
            {'titulo': 'Cierra la primera fase', 'texto': 'Cuando se jugaron todos los partidos aparece <b>Pasar a la siguiente fase</b>. Los clasificados entran a sus llaves, que ya estaban fijadas desde el inicio.'},
            {'titulo': 'Las llaves avanzan solas', 'texto': 'En la pestaña <b>Llaves</b> cada ganador pasa automáticamente a la siguiente ronda al cerrarse el acta.'},
        ],
        'consejos': ['Desempate en la tabla: puntos, diferencia de gol, goles a favor y partidos ganados.'],
        'avisos': [],
    },
    {
        'slug': 'cobros-y-finanzas', 'roles': ['ORG'], 'icono': 'bi-cash-stack', 'minutos': 3,
        'titulo': 'Cobrar inscripciones y multas',
        'resumen': 'Las deudas se crean solas (inscripción al aprobar, tarjetas al cerrar el acta). Tú solo registras lo que te pagan.',
        'pasos': [
            {'titulo': 'Abre Finanzas', 'texto': 'En <b>Administración → Finanzas</b> ves el total en caja y los <b>Saldos de Equipos</b>.', 'url': 'gestionar_finanzas'},
            {'titulo': 'Registra un pago', 'texto': 'Toca <b>Pagar</b> en la deuda. Puedes cobrar el total o un abono parcial: el saldo se actualiza solo.'},
            {'titulo': '¿Cobraste por error?', 'texto': 'Toca <b>Deshacer</b> en el abono. Todo queda guardado en <b>Trazabilidad financiera</b>.'},
            {'titulo': 'Avisa al equipo', 'texto': '<b>Notificar por WhatsApp</b> le envía al dirigente el detalle de lo que debe.'},
            {'titulo': 'Cierra el día', 'texto': 'En <b>Caja diaria</b> ves lo que entró hoy, para cuadrar el efectivo.', 'url': 'cierre_diario_caja'},
        ],
        'consejos': ['Para cobros que no salen de un partido usa <b>Añadir Infracción Manual</b>.'],
        'avisos': ['En vocalía se ven las deudas pendientes de cada equipo antes del partido.'],
    },
    {
        'slug': 'sanciones-y-suspensiones', 'roles': ['ORG', 'DIR', 'VOC'], 'icono': 'bi-slash-circle', 'minutos': 2,
        'titulo': 'Suspensiones y sanciones',
        'resumen': 'El sistema suspende automáticamente según las tarjetas; el organizador puede ajustar a mano.',
        'pasos': [
            {'titulo': 'Reglas automáticas', 'texto': '<b>Roja directa</b>: 2 partidos. <b>Doble amarilla</b> (roja por acumulación): 1 partido. <b>Cada 4 amarillas</b> en la fase: 1 partido. <b>3 rojas directas</b>: expulsión del torneo. Además se carga la multa de cada tarjeta.'},
            {'titulo': 'Ver quién está suspendido', 'texto': 'En <b>Competencia → Jugadores</b> cada ficha muestra «Susp: N» o «Expulsado».', 'url': 'admin_gestion_jugadores'},
            {'titulo': 'Ajustar a mano', 'texto': 'Desde la ficha del jugador el organizador puede sumar o quitar fechas de suspensión, o mandarlo a <b>Lista negra</b>. Un equipo completo se sanciona con el botón <b>Sanción</b> en Equipos.'},
        ],
        'consejos': ['Cada partido que el equipo juega descuenta una fecha de suspensión.'],
        'avisos': [],
    },
    {
        'slug': 'crear-vocal', 'roles': ['ORG'], 'icono': 'bi-person-badge', 'minutos': 2,
        'titulo': 'Crear la cuenta de tu vocal',
        'resumen': 'Solo el dueño de la cancha crea las cuentas de sus vocales. La cuenta solo sirve en tu cancha.',
        'pasos': [
            {'titulo': 'Abre Usuarios', 'texto': 'En <b>Administración → Usuarios y roles</b> toca <b>Crear cuenta de vocal</b>.', 'url': 'crear_usuario'},
            {'titulo': 'Llena los datos', 'texto': 'Elige el rol (vocal, dirigente o staff) y escribe sus nombres. El usuario y la contraseña se generan solos si los dejas vacíos.'},
            {'titulo': 'Comparte las credenciales', 'texto': 'Al guardar verás usuario y contraseña <b>una sola vez</b>. Toca <b>Enviar por WhatsApp</b> o <b>Copiar mensaje completo</b>.'},
            {'titulo': 'Si olvida la contraseña', 'texto': 'En Usuarios toca <b>Nueva contraseña</b> junto a su nombre y compártela otra vez.', 'url': 'gestionar_usuarios'},
        ],
        'consejos': ['Si quitas a la persona de tu cancha, su cuenta se desactiva y ya no puede entrar.'],
        'avisos': ['Ser vocal en tu cancha no le da permisos en ninguna otra.'],
    },
    {
        'slug': 'portal-y-medios', 'roles': ['ORG'], 'icono': 'bi-globe', 'minutos': 2,
        'titulo': 'Tu portal público, logo y galería',
        'resumen': 'Tu cancha tiene una página pública con torneos, tablas y fotos, para compartir con jugadores e hinchas.',
        'pasos': [
            {'titulo': 'Tu logo', 'texto': 'El logo de tu cancha (el que sale en el portal, las actas y los carnets) lo carga el equipo de NEXUS: envíaselo por WhatsApp. En <b>Ajustes</b> puedes cambiar el logo de la barra superior.', 'url': 'gestionar_configuracion'},
            {'titulo': 'Agrega fotos', 'texto': 'En <b>Medios</b> elige varias fotos a la vez, ponles título y márcalas como <b>Visible en App</b>.', 'url': 'gestionar_medios'},
            {'titulo': 'Comparte tu enlace', 'texto': 'Tu portal está en <b>/cancha/&lt;nombre-de-tu-cancha&gt;/</b>. Compártelo en tus grupos.'},
        ],
        'consejos': [],
        'avisos': [],
    },
    # ------------------------------------------------------------------ DIRIGENTE
    {
        'slug': 'inscribir-mi-equipo', 'roles': ['DIR'], 'icono': 'bi-shield-plus', 'minutos': 3,
        'titulo': 'Inscribir mi equipo en un torneo',
        'resumen': 'Creas tu cuenta, eliges el torneo y envías la solicitud. El organizador la aprueba cuando le pagas.',
        'pasos': [
            {'titulo': 'Crea tu cuenta', 'texto': 'Toca <b>Crear Cuenta</b> arriba a la derecha (o entra con Google).', 'url': 'registro_publico'},
            {'titulo': 'Busca el torneo', 'texto': 'En tu Inicio toca <b>Inscribirse</b>. Verás los torneos con inscripciones abiertas y su precio.', 'url': 'ver_torneos_activos'},
            {'titulo': 'Envía la solicitud', 'texto': 'Toca <b>Inscribir Equipo</b>, escribe el nombre, sube el escudo (opcional) y tu celular. Toca <b>ENVIAR SOLICITUD</b>.'},
            {'titulo': 'Coordina el pago', 'texto': 'Escríbele al organizador por WhatsApp. Cuando apruebe tu equipo pasarás a ser <b>Dirigente</b> y podrás fichar jugadores.'},
        ],
        'consejos': ['Si tu equipo jugó la temporada pasada, usa <b>Renovar Equipo</b>: se copia con sus jugadores.'],
        'avisos': [],
    },
    {
        'slug': 'mis-pagos', 'roles': ['DIR'], 'icono': 'bi-wallet2', 'minutos': 1,
        'titulo': 'Ver lo que debe mi equipo',
        'resumen': 'Consulta inscripción, multas por tarjetas y abonos en cualquier momento.',
        'pasos': [
            {'titulo': 'Abre Finanzas', 'texto': 'En tu Inicio toca <b>Finanzas</b>.', 'url': 'mis_finanzas_equipo'},
            {'titulo': 'Revisa el detalle', 'texto': 'Arriba ves <b>Por Pagar</b> y <b>Pagado</b>. Cada deuda indica el jugador y el partido que la generó, y los abonos que ya hiciste.'},
        ],
        'consejos': ['Los pagos se hacen directamente con el organizador; él los registra en el sistema.'],
        'avisos': [],
    },
    # ------------------------------------------------------------------ VOCAL
    {
        'slug': 'primer-ingreso-vocal', 'roles': ['VOC'], 'icono': 'bi-box-arrow-in-right', 'minutos': 1,
        'titulo': 'Mi primer ingreso como vocal',
        'resumen': 'Entras con el usuario y la contraseña que te envió el dueño de la cancha, desde cualquier celular.',
        'pasos': [
            {'titulo': 'Abre el enlace de ingreso', 'texto': 'Entra a la dirección que te enviaron y escribe tu <b>usuario</b> y <b>contraseña</b>.', 'url': 'login'},
            {'titulo': 'Mira tus partidos', 'texto': 'En tu Inicio aparecen los partidos programados de tu cancha y las actas pendientes.', 'url': 'dashboard'},
            {'titulo': 'Empieza a pitar', 'texto': 'Toca <b>Pitar</b> en el partido. Sigue la guía «Llevar la vocalía de un partido».'},
        ],
        'consejos': ['Guarda la página en la pantalla de inicio del celular para entrar más rápido.'],
        'avisos': ['Si olvidas tu contraseña, pídele al dueño de la cancha que te genere una nueva.'],
    },
    # ------------------------------------------------------------------ PÚBLICO
    {
        'slug': 'ver-tablas', 'roles': ['FAN', 'DIR'], 'icono': 'bi-bar-chart', 'minutos': 1,
        'titulo': 'Ver tablas, goleadores y fixture',
        'resumen': 'Sin crear cuenta puedes seguir los torneos de cualquier cancha.',
        'pasos': [
            {'titulo': 'Busca la cancha', 'texto': 'En la página principal toca <b>Explorar Canchas</b> y entra a la tuya.', 'url': 'landing_principal'},
            {'titulo': 'Elige el torneo', 'texto': 'Verás las posiciones, las llaves, el fixture con horarios y la tabla de goleadores.'},
        ],
        'consejos': ['Guarda el enlace de tu cancha para entrar directo.'],
        'avisos': [],
    },
]

PREGUNTAS = [
    {'p': '¿Por qué no puedo anotar un gol a un jugador en vocalía?', 'r': 'Porque está en la banca. Primero tócalo para pasarlo a «En Cancha».', 'roles': ['ORG', 'VOC']},
    {'p': '¿Puedo agregar un equipo después de empezar el campeonato?', 'r': 'No: el fixture y las llaves quedan fijos. Si aún no se jugó ningún partido, reinicia el campeonato e inclúyelo.', 'roles': ['ORG']},
    {'p': '¿Cómo cambio a un jugador de equipo?', 'r': 'El organizador entra a Competencia → Jugadores, busca al jugador y usa Traspaso. El dirigente no puede fichar a alguien que ya está en otro equipo del mismo torneo.', 'roles': ['ORG', 'DIR']},
    {'p': '¿Puedo usar el dorsal 0?', 'r': 'Sí, se aceptan dorsales del 0 al 99. Lo único que no se puede es repetir un dorsal dentro del mismo equipo.', 'roles': ['ORG', 'DIR']},
    {'p': 'Me equivoqué en un partido ya finalizado, ¿qué hago?', 'r': 'Solo el administrador de la cancha puede corregirlo desde la mesa de control. Cada cambio queda anotado en el acta y las tablas, multas y llaves se recalculan solas.', 'roles': ['ORG', 'VOC']},
    {'p': 'Los carnets salen sin colores al imprimir', 'r': 'En la ventana de impresión activa «Gráficos de fondo» (o «Imprimir fondos») y usa escala 100 %.', 'roles': ['ORG']},
    {'p': '¿Puedo imprimir los carnets de mi equipo?', 'r': 'No. Los carnets los imprime y entrega la organización de la cancha. Pídeselos al organizador cuando tu nómina esté completa.', 'roles': ['DIR']},
    {'p': '¿Qué pasa si un equipo no se presenta?', 'r': 'En la mesa de control usa «Declarar Walkover (W.O.)»: el que se presentó gana 3-0. Si no llegó ninguno, es doble W.O. (0-0, nadie suma).', 'roles': ['ORG', 'VOC']},
    {'p': 'Mi vocal olvidó su contraseña', 'r': 'En Usuarios y roles toca «Nueva contraseña» junto a su nombre y compártela por WhatsApp.', 'roles': ['ORG']},
    {'p': 'Envié la solicitud de mi equipo, ¿por qué no puedo fichar?', 'r': 'Tu equipo está «Pendiente» hasta que el organizador lo apruebe. Coordina el pago por WhatsApp.', 'roles': ['DIR']},
    {'p': '¿Dónde descargo el acta de un partido?', 'r': 'En el calendario del torneo, botón «Acta» del partido finalizado.', 'roles': ['ORG', 'VOC', 'DIR']},
]

GLOSARIO = [
    ('Acta', 'Hoja oficial del partido: resultado, planilla, tarjetas, informes y firmas.'),
    ('Categoría', 'División de equipos (Libre, Máster…). Define el color del carnet.'),
    ('Cupos', 'Máximo de jugadores que un equipo puede fichar.'),
    ('Dorsal', 'Número de camiseta, del 0 al 99. No se repite dentro del equipo.'),
    ('Fixture', 'Lista de todos los partidos del campeonato, fecha por fecha.'),
    ('Llave', 'Cruce eliminatorio: el ganador avanza y el perdedor queda fuera.'),
    ('Lista negra', 'Jugador bloqueado: no puede ser fichado en la cancha.'),
    ('MVP', 'Figura del partido, marcada por el vocal con ☆.'),
    ('Vocal', 'Persona de mesa que registra lo que pasa en el partido.'),
    ('W.O. (walkover)', 'Partido ganado porque el rival no se presentó (3-0).'),
]

GUIAS_POR_SLUG = {g['slug']: g for g in GUIAS}

# Pantalla del sistema → guía que explica esa pantalla (botón de ayuda flotante)
AYUDA_POR_PANTALLA = {
    'gestionar_categorias': 'crear-categoria',
    'gestionar_torneos': 'crear-torneo',
    'gestionar_solicitudes': 'inscribir-equipos',
    'gestionar_equipos': 'inscribir-equipos',
    'gestionar_jugadores': 'inscribir-jugadores',
    'imprimir_carnets': 'imprimir-carnets',
    'iniciar_campeonato': 'empezar-campeonato',
    'programar_partidos': 'programar-partidos',
    'ver_campeonato': 'fases-y-llaves',
    'gestionar_vocalia': 'vocalia',
    'gestionar_finanzas': 'cobros-y-finanzas',
    'cierre_diario_caja': 'cobros-y-finanzas',
    'trazabilidad_financiera': 'cobros-y-finanzas',
    'admin_gestion_jugadores': 'sanciones-y-suspensiones',
    'gestionar_usuarios': 'crear-vocal',
    'crear_usuario': 'crear-vocal',
    'gestionar_medios': 'portal-y-medios',
    'gestionar_configuracion': 'portal-y-medios',
    'ver_torneos_activos': 'inscribir-mi-equipo',
    'solicitar_inscripcion': 'inscribir-mi-equipo',
    'mis_finanzas_equipo': 'mis-pagos',
}
