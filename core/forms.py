from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

# Importamos SOLO lo que sobrevivió a la limpieza SaaS
from .models import (
    Perfil, Torneo, Equipo, Jugador, Partido, Pago,
    Cupon, FotoGaleria, Configuracion, Sancion,
    ComplejoDeportivo, PlanSuscripcion, PagoSuscripcionSaaS,
    RolComplejo, ComplejoDeportivo, validar_cedula_db, validar_documento
)

# =====================================================
# 1. CREAR USUARIOS
# =====================================================
class CuentaCanchaForm(forms.Form):
    """El dueño de una cancha crea la cuenta de su vocal (o de su staff).
    La cuenta solo existe dentro de esa cancha."""
    ROLES_CREABLES = [
        ('VOC', 'Vocal de mesa'),
        ('DIR', 'Dirigente de equipo'),
        ('ORG', 'Staff / ayudante del organizador'),
    ]
    first_name = forms.CharField(label="Nombres", max_length=150,
                                 widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Juan Carlos', 'autocomplete': 'off'}))
    last_name = forms.CharField(label="Apellidos", max_length=150, required=False,
                                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Pérez', 'autocomplete': 'off'}))
    username = forms.CharField(
        label="Usuario para iniciar sesión", max_length=150, required=False,
        help_text="Déjalo vacío y se genera uno a partir del nombre.",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: juan.perez', 'autocomplete': 'off',
                                      'autocapitalize': 'none', 'spellcheck': 'false'}))
    password = forms.CharField(
        label="Contraseña", min_length=8, max_length=64, required=False,
        help_text="Déjala vacía y se genera una segura. Mínimo 8 caracteres.",
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'new-password',
                                      'autocapitalize': 'none', 'spellcheck': 'false'}))
    rol = forms.ChoiceField(label="Rol en tu cancha", choices=ROLES_CREABLES, initial='VOC',
                            widget=forms.RadioSelect)
    telefono = forms.CharField(label="WhatsApp (opcional)", max_length=15, required=False,
                               help_text="Para enviarle las credenciales con un toque.",
                               widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09…', 'inputmode': 'tel'}))

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip().lower()
        if not username:
            return ''
        import re
        if not re.fullmatch(r'[a-z0-9._-]{3,150}', username):
            raise forms.ValidationError("Usa solo minúsculas, números, punto, guion o guion bajo (mínimo 3).")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ese usuario ya existe. Prueba con otro.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        if password:
            from django.contrib.auth.password_validation import validate_password
            validate_password(password)
        return password


# =====================================================
# 2. CREAR TORNEOS
# =====================================================
class TorneoForm(forms.ModelForm):
    class Meta:
        model = Torneo
        fields = [
            'nombre', 
            'categoria', 
            'fecha_inicio', 
            'inscripcion_abierta', 
            'activo', 
            'costo_inscripcion', 
            'cobro_por_jugador', 
            'costo_inscripcion_jugador',
            'costo_amarilla', 
            'costo_roja'
        ]
        widgets = {
            'fecha_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'costo_inscripcion': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'costo_inscripcion_jugador': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'costo_amarilla': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'costo_roja': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cobro_por_jugador': forms.CheckboxInput(attrs={'class': 'form-check-input fs-4 shadow-sm border-secondary', 'role': 'switch'}),
        }
        labels = {
            'cobro_por_jugador': '¿Cobrar tarifa individual por Jugador?',
        }

# =====================================================
# 3. CREAR EQUIPOS 
# =====================================================
class EquipoSolicitudForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ['nombre', 'escudo', 'nombre_suplente_1', 'nombre_suplente_2', 'telefono_contacto'] 
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Los Rayados FC'}),
            'escudo': forms.FileInput(attrs={'class': 'form-control'}),
            'nombre_suplente_1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del Suplente 1 (Opcional)'}),
            'nombre_suplente_2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre del Suplente 2 (Opcional)'}),
            'telefono_contacto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 0963395614', 'required': 'True'}),   
        }
        
class EquipoForm(forms.ModelForm):
    # Queryset real se restringe en la vista a los usuarios del complejo
    # actual (nunca "todos los usuarios del sistema" — el sistema es
    # compartido entre varios complejos deportivos).
    dirigente = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Dirigente del Equipo",
        empty_label="-- Selecciona un usuario de esta cancha --",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='¿La persona no aparece? Créala primero en "Usuarios".',
    )

    class Meta:
        model = Equipo
        fields = ['torneo', 'dirigente', 'nombre', 'escudo', 'telefono_contacto', 'nombre_suplente_1', 'nombre_suplente_2', 'estado_inscripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Los Rayados FC'}),
            'escudo': forms.FileInput(attrs={'class': 'form-control'}),
            'nombre_suplente_1': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_suplente_2': forms.TextInput(attrs={'class': 'form-control'}),
            'estado_inscripcion': forms.Select(attrs={'class': 'form-select fw-bold border-secondary'}),
        }
        labels = {
            'estado_inscripcion': 'Estado en el Torneo',
        }

class JugadorForm(forms.ModelForm):
    """El tipo de documento (Ecuador / Colombia / Venezuela) SOLO lo ve y lo
    puede cambiar el administrador de la cancha. El dirigente siempre ficha
    con cédula ecuatoriana."""
    class Meta:
        model = Jugador
        fields = ['equipo', 'nombres', 'dorsal', 'tipo_documento', 'cedula', 'foto']
        widgets = {
            'equipo': forms.Select(attrs={'class': 'form-select'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Enner Valencia'}),
            'dorsal': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 13', 'min': '0', 'max': '99'}),
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'cedula': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de documento', 'inputmode': 'numeric'}),
            'foto': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, es_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.es_admin = es_admin
        if not es_admin:
            self.fields.pop('tipo_documento')
        else:
            self.fields['tipo_documento'].required = False

    def clean_tipo_documento(self):
        return self.cleaned_data.get('tipo_documento') or 'EC'

    def clean_cedula(self):
        cedula = (self.cleaned_data.get('cedula') or '').strip().upper().replace(' ', '')
        tipo = self.cleaned_data.get('tipo_documento') if self.es_admin else 'EC'
        if not self.es_admin and self.instance.pk:
            tipo = self.instance.tipo_documento
        tipo = tipo or 'EC'
        if tipo == 'VE':
            cedula = cedula.replace('V-', '').replace('E-', '').replace('-', '')
        try:
            validar_documento(tipo, cedula)
        except ValidationError as e:
            raise forms.ValidationError(e.messages)

        equipo_destino = self.cleaned_data.get('equipo')
        if equipo_destino and equipo_destino.torneo:
            # 🔥 BLOQUEO: la cédula ya existe en OTRO equipo del MISMO TORNEO
            jugador_existente = Jugador.objects.filter(
                cedula=cedula, equipo__torneo=equipo_destino.torneo
            ).exclude(equipo=equipo_destino).first()
            if jugador_existente:
                raise forms.ValidationError(f"⛔ Fichaje bloqueado: Este jugador ya pertenece a '{jugador_existente.equipo.nombre}' en este torneo. Solo el organizador puede traspasarlo.")
        return cedula


# =====================================================
# 5. PROGRAMAR PARTIDOS
# =====================================================
class ProgramarPartidoForm(forms.ModelForm):
    class Meta:
        model = Partido
        fields = ['torneo', 'numero_fecha', 'etapa', 'equipo_local', 'equipo_visita', 'fecha_hora', 'cancha']
        widgets = {
            'torneo': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'numero_fecha': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'Ej: 1', 'min': '1'}),
            'etapa': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'equipo_local': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'equipo_visita': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary'}),
            'fecha_hora': forms.DateTimeInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'type': 'datetime-local'}),
            'cancha': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'Ej: Cancha Principal'}),
        }
        labels = {
            'numero_fecha': 'Jornada N°',
            'equipo_local': 'Equipo A (Local)',
            'equipo_visita': 'Equipo B (Visita)',
        }

    def clean(self):
        cleaned_data = super().clean()
        local = cleaned_data.get("equipo_local")
        visita = cleaned_data.get("equipo_visita")

        if local and visita and local == visita:
            self.add_error('equipo_visita', "⛔ ERROR: Un equipo no puede jugar contra sí mismo.")
            self.add_error('equipo_local', "⛔ Selecciona equipos diferentes.")
            raise forms.ValidationError("Error de Lógica: El partido no puede ser entre el mismo equipo.")
        return cleaned_data
    

# =====================================================
# 6. FINANZAS Y PAGOS 
# =====================================================
class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['equipo', 'monto', 'fecha', 'comprobante', 'observacion']
        widgets = {
            'equipo': forms.Select(attrs={'class': 'form-select bg-white text-dark border-secondary-subtle'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control bg-white text-dark border-secondary-subtle', 'placeholder': '0.00'}),
            'fecha': forms.DateInput(attrs={'class': 'form-control bg-white text-dark border-secondary-subtle', 'type': 'date'}),
            'comprobante': forms.FileInput(attrs={'class': 'form-control bg-white text-dark border-secondary-subtle'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control bg-white text-dark border-secondary-subtle', 'rows': 2, 'placeholder': 'Ej: Abono inscripción / Pago de multa fecha 3'}),
        }
        labels = {
            'equipo': 'Equipo que realiza el pago',
            'monto': 'Valor a pagar ($)',
            'comprobante': 'Imagen del depósito/transferencia',
            'observacion': 'Notas adicionales'
        }

    def clean(self):
        cleaned_data = super().clean()
        monto = cleaned_data.get('monto')
        equipo = cleaned_data.get('equipo')

        if monto is not None:
            if monto <= 0:
                self.add_error('monto', "El monto debe ser mayor a $0. No se permiten negativos.")
            elif equipo:
                deuda_actual = equipo.deuda_pendiente()
                if deuda_actual <= 0:
                    self.add_error('equipo', f"El equipo {equipo.nombre} ya está al día.")
                elif monto > deuda_actual:
                    self.add_error('monto', f"Denegado: Solo adeuda ${deuda_actual}. No puedes cobrar ${monto}.")
        return cleaned_data

class RegistroPublicoForm(UserCreationForm):
    # El "usuario" de registro público ES la cédula (así lo fuerza el JS del
    # formulario: solo dígitos, máx. 10, validada). No se vuelve a pedir la
    # cédula en un campo aparte para no duplicar la misma pregunta.
    first_name = forms.CharField(label="Nombres", required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(label="Apellidos", required=True, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(label="Correo Electrónico", required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    telefono = forms.CharField(label="Teléfono", required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '10 dígitos'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            validar_cedula_db(username)
            if Perfil.objects.filter(cedula=username).exists():
                raise forms.ValidationError("Esa cédula ya está registrada en otra cuenta.")
        return username

    # Le agregamos el parámetro "complejo=None" por si se registran desde la página de una cancha específica
    def save(self, complejo=None, commit=True):
        # Guardamos el usuario base
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']

        if commit:
            user.save()

        # 1. Creamos el Perfil GLOBAL (Solo datos personales)
        perfil, created = Perfil.objects.get_or_create(usuario=user)
        perfil.telefono = self.cleaned_data.get('telefono')
        perfil.cedula = user.username
        # ELIMINADO: perfil.rol = 'FAN' <-- Esto ya no va aquí
        perfil.save()
        
        # 2. Asignamos el Rol CONTEXTUAL (Solo si sabemos en qué cancha se está registrando)
        if complejo:
            RolComplejo.objects.get_or_create(
                usuario=user,
                complejo=complejo,
                defaults={'rol': 'FAN'} # Aficionado por defecto en ESTA cancha
            )
            
        return user
    
class FotoGaleriaForm(forms.ModelForm):
    class Meta:
        model = FotoGaleria
        fields = ['imagen', 'titulo', 'orden', 'activa']
        widgets = {
            'imagen': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Cancha principal iluminada'}),
            'orden': forms.NumberInput(attrs={'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

# =====================================================
# ✨ FORMULARIOS: TRASPASOS, CUPOS Y SANCIONES ✨
# =====================================================

class TraspasoJugadorForm(forms.Form):
    nuevo_equipo = forms.ModelChoiceField(
        queryset=Equipo.objects.none(), 
        label="Seleccionar Nuevo Equipo",
        empty_label="-- Elija el equipo de destino --"
    )
    nuevo_dorsal = forms.IntegerField(
        label="Nuevo Dorsal",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg fw-bold text-center', 'placeholder': 'Ej: 10'})
    )

    def __init__(self, *args, **kwargs):
        torneo_id = kwargs.pop('torneo_id', None)
        equipo_actual_id = kwargs.pop('equipo_actual_id', None)
        super().__init__(*args, **kwargs)
        
        if torneo_id and equipo_actual_id:
            equipos_validos = Equipo.objects.filter(
                torneo_id=torneo_id, 
                estado_inscripcion='APROBADO'
            ).exclude(id=equipo_actual_id)
                
            self.fields['nuevo_equipo'].queryset = equipos_validos
            self.fields['nuevo_equipo'].widget.attrs.update({'class': 'form-select form-select-lg fw-bold'})

    def clean(self):
        cleaned_data = super().clean()
        nuevo_equipo = cleaned_data.get('nuevo_equipo')
        nuevo_dorsal = cleaned_data.get('nuevo_dorsal')

        if nuevo_equipo and nuevo_dorsal is not None:
            from .models import Jugador
            if Jugador.objects.filter(equipo=nuevo_equipo, dorsal=nuevo_dorsal).exists():
                self.add_error('nuevo_dorsal', f'El equipo {nuevo_equipo.nombre} ya tiene un jugador con el dorsal {nuevo_dorsal}.')
        
        return cleaned_data
    
class AsignarCuposForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ['cupos_pagados']
        labels = {
            'cupos_pagados': 'Límite Total de Jugadores'
        }
        widgets = {
            'cupos_pagados': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg fw-black text-center',
                'style': 'font-size: 3rem; height: 100px; border-radius: 20px; border: 3px solid var(--primary-blue);',
                'min': '0'
            })
        }

class SancionListaNegraForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ['sancionado_hasta']
        widgets = {
            'sancionado_hasta': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
        }
        labels = {
            'sancionado_hasta': 'Sancionar (Lista Negra) Hasta:'
        }

class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = ['logo_sistema', 'iva_porcentaje']
        labels = {
            'logo_sistema': 'Logo Global del Sistema',
            'iva_porcentaje': 'Porcentaje de IVA (%)'
        }
        widgets = {
            'logo_sistema': forms.FileInput(attrs={'class': 'form-control'}),
            'iva_porcentaje': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
        }

class SancionManualForm(forms.ModelForm):
    class Meta:
        model = Sancion
        fields = ['torneo', 'equipo', 'monto', 'descripcion']
        widgets = {
            'torneo': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary', 'required': True}),
            'equipo': forms.Select(attrs={'class': 'form-select bg-dark text-white border-secondary', 'required': True}),
            'monto': forms.NumberInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'step': '0.01', 'placeholder': 'Ej: 15.00', 'required': True}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control bg-dark text-white border-secondary', 'placeholder': 'Ej: Multa por daños, Falta a reunión, etc.', 'required': True}),
        }
        labels = {
            'monto': 'Monto de la Deuda ($)',
            'descripcion': 'Motivo / Detalle de la Deuda'
        }

# =====================================================
# ✨ FORMULARIOS DEL DUEÑO DEL SOFTWARE (SaaS) ✨
# =====================================================

class PlanSuscripcionForm(forms.ModelForm):
    class Meta:
        model = PlanSuscripcion
        fields = ['nombre', 'descripcion', 'costo_inscripcion', 'precio_mensual', 'max_torneos',
                  'max_categorias_por_torneo', 'max_jugadores', 'visible_publico', 'destacado']
        labels = {
            'costo_inscripcion': 'Inscripción (pago único)',
            'precio_mensual': 'Precio mensual',
            'max_torneos': 'Torneos',
            'max_categorias_por_torneo': 'Cat. por torneo',
            'max_jugadores': 'Jugadores',
        }
        help_texts = {'max_jugadores': ''}
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Plan Premium'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Ideal para complejos con varias categorías'}),
            'costo_inscripcion': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'precio_mensual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'max_torneos': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'max_categorias_por_torneo': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'max_jugadores': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'visible_publico': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'destacado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }

class ComplejoDeportivoForm(forms.ModelForm):
    class Meta:
        model = ComplejoDeportivo
        fields = ['nombre', 'slug', 'organizador', 'plan', 'activo', 'fecha_vencimiento', 'logo', 'telefono_contacto']
        labels = {
            'nombre': 'Nombre del complejo',
            'slug': 'Dirección web (slug)',
            'organizador': 'Dueño / organizador',
            'plan': 'Plan',
            'activo': 'Servicio activo',
            'fecha_vencimiento': 'Fecha de corte',
            'logo': 'Logo',
            'telefono_contacto': 'Teléfono / WhatsApp',
        }
        help_texts = {
            'slug': 'Su portal queda en /cancha/<slug>/. Solo minúsculas, números y guiones.',
            'activo': 'Si lo apagas, el portal y el acceso del organizador se suspenden al instante.',
            'fecha_vencimiento': 'Hasta qué día cubre el último pago. Se actualiza solo al registrar pagos.',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de la Cancha'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'nombre-sin-espacios'}),
            'organizador': forms.Select(attrs={'class': 'form-select'}),
            'plan': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'fecha_vencimiento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
            'telefono_contacto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09...'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services.pruebas import NOMBRE_PLAN_DEMO
        self.fields['plan'].queryset = PlanSuscripcion.objects.exclude(nombre=NOMBRE_PLAN_DEMO)
        self.fields['plan'].empty_label = '— Sin plan —'
        
class PagoSaaSForm(forms.ModelForm):
    class Meta:
        model = PagoSuscripcionSaaS
        fields = ['complejo', 'monto', 'meses_pagados', 'fecha_pago', 'observacion']
        labels = {
            'complejo': 'Cancha',
            'monto': 'Monto recibido ($)',
            'meses_pagados': 'Meses que cubre',
            'fecha_pago': 'Fecha del pago',
            'observacion': 'Observación',
        }
        help_texts = {'meses_pagados': ''}
        widgets = {
            'complejo': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'meses_pagados': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            # AÑADIMOS EL WIDGET PARA LA FECHA
            'fecha_pago': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'observacion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Transferencia Banco Pichincha'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['complejo'].queryset = ComplejoDeportivo.objects.filter(es_demo=False).select_related('plan').order_by('nombre')
        self.fields['complejo'].empty_label = '— Elige la cancha —'
        if not self.is_bound and not self.instance.pk:
            from django.utils import timezone
            self.initial.setdefault('fecha_pago', timezone.localdate())
