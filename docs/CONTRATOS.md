# CONTRATOS Y FUENTE UNICA DE VERDAD: CLINICA BOUTIQUE LUJO LUMINOSO

Documento maestro y fuente inmutable de verdad para la implementacion de la plataforma omnicanal de agendamiento y operacion clinica de la clinica odontologica boutique "Lujo Luminoso" (1 doctor, 1 sillon odontologico).

Todas las tareas de desarrollo (de la #1 a la #12) se encuentran completadas al 100% y verificadas bajo la suite automatizada tests/test_security_audit.py. Estado del sistema: Version 1.0 Produccion Local Estable.

Regla transversal de diseno y codigo: CERO EMOJIS en codigo fuente, comentarios, logs de sistema, mensajes de error, documentacion, bases de datos e interfaces de usuario. Todo icono visual sera vectorial mediante Lucide Icons.

---

## 1. REGLAS DE NEGOCIO Y HORARIOS CLINICOS

### 1.1. Capacidad Clinica e Infraestructura
- Capacidad instalada: Exactamente 1 doctor y 1 sillon odontologico.
- Exclusividad de atencion: Jamas puede haber mas de un procedimiento activo en el mismo instante temporal.

### 1.2. Dias de Atencion y Zona Horaria
- Zona horaria de referencia: America/Bogota (UTC-5).
- Dias habiles: Lunes a Viernes (indices 0 a 4).
- Fines de semana y festivos: Sabados y Domingos cerrados sin excepcion. Todos los festivos oficiales de Colombia son bloqueados de forma obligatoria mediante el paquete `holidays.country_holidays('CO')` y la tabla `festivos_bloqueos`.

### 1.3. Jornada Diaria y Bloques de Atencion
- Bloque Manana: 07:00 a 12:00.
- Bloque Almuerzo (Receso Obligatorio): 12:00 a 13:00.
  - El intervalo [12:00, 13:00) esta estrictamente cerrado.
  - Ninguna cita puede iniciar, terminar o cruzar este rango.
- Bloque Tarde: 13:00 a 17:00.
  - Ninguna cita puede extenderse mas alla de las 17:00.

### 1.4. Servicios Habilitados y Regla Matematica de Bloques
La hora de finalizacion de una cita se calcula estrictamente como:
`hora_fin = hora_inicio + duracion_min`

Catalogo de procedimientos:
1. Profilaxis / Limpieza (`profilaxis`):
   - Duracion: 30 minutos.
   - Ultimo turno de la manana: 11:30 a 12:00.
   - Ultimo turno de la tarde: 16:30 a 17:00.
2. Control de Ortodoncia (`ortodoncia`):
   - Duracion: 45 minutos.
   - Ultimo turno de la manana: 11:15 a 12:00.
   - Ultimo turno de la tarde: 16:15 a 17:00.
3. Diseno de Sonrisa (`diseno_sonrisa`):
   - Duracion: 60 minutos.
   - Ultimo turno de la manana: 11:00 a 12:00.
   - Ultimo turno de la tarde: 16:00 a 17:00.
4. Cirugia / Implantes (`cirugia_implantes`):
   - Duracion: 120 minutos (2 horas continuas).
   - Ultimo turno de la manana: 10:00 a 12:00.
   - Ultimo turno de la tarde: 15:00 a 17:00.

### 1.5. Politica de Cita Activa Unica por Paciente
- Un paciente (identificado unicamente por su numero de telefono en formato E.164) solo puede tener un maximo de 1 turno activo simultaneo.
- Se consideran turnos activos aquellos en estado: `confirmado`, `en_sala`, `llamando`, `en_atencion`.
- Si un paciente con un turno activo solicita una nueva cita, el sistema rechaza la solicitud con el codigo de error `active_appointment_exists` e informa la fecha/hora de su cita ya agendada.

### 1.6. Ventana de Gracia por Ausentismo (No-Show: 15 Minutos)
- Cuando el doctor presiona el boton "Llamar Paciente", el turno transiciona a `llamando`, se registra `llamado_at = NOW()`, suena una alerta auditiva sutil en la pantalla TV y arranca un cronometro visible de 15 minutos.
- Si el paciente no se presenta trascurridos los 15 minutos:
  - El doctor o el sistema pueden cambiar el estado a `cancelado_ausente`.
  - El bloque horario queda inmediatamente liberado.
  - Se encola una notificacion automatica por WhatsApp al paciente lamentando su inasistencia y ofreciendole un enlace directo para reagendar.

### 1.7. Desplazamiento Masivo por Retrasos Clinicos
- Si un procedimiento quirurgico o clinico se prolonga, el doctor o administrador puede reportar un retraso de 15, 30, 45 o 60 minutos.
- El sistema:
  1. Identifica todos los turnos del dia en estados `confirmado` que inicien despues del turno actual.
  2. Desplaza sus horarios `fecha_inicio` y `fecha_fin` sumando los minutos reportados.
  3. Verifica que ningun turno desplazado invada el almuerzo (12:00-13:00) ni sobrepase el cierre (17:00). Si alguno excede, se marca para gestion asistida.
  4. Encola mensajes de cortesia por WhatsApp a cada paciente afectado informando el nuevo horario estimado.

### 1.8. Protocolo de Triage y Urgencias Clinicas (Cero Consejo Medico por IA)
- Si un paciente describe sintomas de urgencia:
  - Sangrado activo no controlado.
  - Traumatismo dental o facial severo (golpe, fractura osea o avulsion dental).
  - Dolor insoportable acompanado de inflamacion facial evidente o fiebre.
- El agente IA o el sistema automatizado:
  1. No emitira ningun diagnostico, recomendacion farmacologica ni consejo clinico.
  2. Disparara la herramienta `solicitar_atencion_humana(motivo_urgencia)`.
  3. Marcara en la ficha del paciente `requiere_atencion_humana = true` y registrara el `motivo_urgencia`.
  4. Emitira de inmediato una alerta de alta prioridad en el Dashboard de Administracion y en el Modo Enfoque del Doctor.
  5. Entregara al paciente un mensaje de seguridad indicando que su caso ha sido escalado a atencion prioritaria humana y proveyendo la linea de atencion de urgencias o contacto telefonico directo.

### 1.9. Arquitectura de Despliegue Local (PC Clinica + Cloudflare Tunnel + FreeDomain)
- Modalidad autoalojable para operacion clinica de bajo costo (Fase 6 / Tarea #12):
  - El sistema completo se ejecutara localmente en el computador del consultorio (servicio de fondo Windows / lanzador `.bat` o contenedor `docker-compose.yml`).
  - Conexion segura e ininterrumpida a internet mediante Cloudflare Tunnel (`cloudflared`) sin apertura de puertos en el router del consultorio ni exposicion de IP publica estatica.
  - Dominio publico gratuito provisto por DigitalPlat FreeDomain (`.dpdns.org` o `.qzz.io`) con terminacion TLS/HTTPS valida y de alta confianza para recepcion y verificacion de Webhooks de Meta WhatsApp Cloud API.
  - Reloj del servidor y motor logico anclados exclusivamente a `America/Bogota` (ZoneInfo), garantizando total independencia respecto a la zona horaria del cliente o navegador.

---

## 2. CONTRATOS DE BASE DE DATOS (POSTGRESQL EN SUPABASE)

Todas las tablas utilizan identificadores UUID v4 generados en el servidor con `gen_random_uuid()` y cuentan con politicas estrictas de Row Level Security (RLS).

### 2.1. Tabla: `usuarios_staff`
Almacena las credenciales y roles del personal del consultorio.
```sql
CREATE TABLE public.usuarios_staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('admin', 'doctor', 'recepcion')),
    activo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);
```

### 2.2. Tabla: `pacientes`
Directorio unico de pacientes indexado por numero telefonico E.164.
```sql
CREATE TABLE public.pacientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    email TEXT NULL,
    requiere_atencion_humana BOOLEAN NOT NULL DEFAULT false,
    motivo_urgencia TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX idx_pacientes_telefono ON public.pacientes(telefono);
CREATE INDEX idx_pacientes_triage ON public.pacientes(requiere_atencion_humana) WHERE requiere_atencion_humana = true;
```

### 2.3. Tabla: `turnos`
Agenda clinica central con garantia de no-solapamiento fisico en base de datos.
```sql
CREATE TABLE public.turnos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_sala TEXT NOT NULL,
    paciente_id UUID NOT NULL REFERENCES public.pacientes(id) ON DELETE RESTRICT,
    servicio TEXT NOT NULL CHECK (servicio IN ('profilaxis', 'ortodoncia', 'diseno_sonrisa', 'cirugia_implantes')),
    duracion_min INTEGER NOT NULL CHECK (duracion_min IN (30, 45, 60, 120)),
    fecha_inicio TIMESTAMPTZ NOT NULL,
    fecha_fin TIMESTAMPTZ NOT NULL,
    estado TEXT NOT NULL DEFAULT 'confirmado' CHECK (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion', 'completado', 'cancelado_ausente', 'cancelado_paciente')),
    llamado_at TIMESTAMPTZ NULL,
    origen TEXT NOT NULL CHECK (origen IN ('whatsapp_ia', 'web_paciente', 'panel_admin', 'demo')),
    notas_internas TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_turnos_codigo_sala CHECK (char_length(trim(codigo_sala)) >= 2),
    CONSTRAINT chk_turnos_rango_valido CHECK (fecha_fin > fecha_inicio),
    CONSTRAINT chk_turnos_servicio_duracion CHECK (
        (servicio = 'profilaxis' AND duracion_min = 30) OR
        (servicio = 'ortodoncia' AND duracion_min = 45) OR
        (servicio = 'diseno_sonrisa' AND duracion_min = 60) OR
        (servicio = 'cirugia_implantes' AND duracion_min = 120)
    ),
    CONSTRAINT chk_turnos_duracion_exacta CHECK (fecha_fin = fecha_inicio + (duracion_min * INTERVAL '1 minute'))
);

-- Extension btree_gist para soportar exclusion por rangos temporales en PostgreSQL
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Restriccion inmutable de no solapamiento temporal para citas activas (1 solo sillon clinico)
-- Uso del intervalo semiabierto '[)' para permitir turnos contiguos inmediatos
ALTER TABLE public.turnos
ADD CONSTRAINT excl_turnos_sin_solapamiento
EXCLUDE USING gist (
    tstzrange(fecha_inicio, fecha_fin, '[)') WITH &&
)
WHERE (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion'));

-- Indice unico parcial anti-acaparamiento: maximo 1 cita activa por paciente
CREATE UNIQUE INDEX idx_un_turno_activo_por_paciente
ON public.turnos(paciente_id)
WHERE (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion'));

CREATE INDEX idx_turnos_rango ON public.turnos(fecha_inicio, fecha_fin);
CREATE INDEX idx_turnos_estado ON public.turnos(estado);
CREATE INDEX idx_turnos_paciente ON public.turnos(paciente_id);
```

### 2.4. Tabla: `sesiones_chat`
Historial conversacional y contexto de memoria para el agente IA por WhatsApp.
```sql
CREATE TABLE public.sesiones_chat (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL UNIQUE CHECK (telefono ~ '^\+?[1-9]\d{7,14}$'),
    historial JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(historial) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX idx_sesiones_chat_telefono ON public.sesiones_chat(telefono);
```

### 2.5. Tabla: `festivos_bloqueos`
Fechas no laborables especiales o feriados nacionales.
```sql
CREATE TABLE public.festivos_bloqueos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha DATE NOT NULL UNIQUE,
    motivo TEXT NOT NULL CHECK (char_length(trim(motivo)) >= 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX idx_festivos_fecha ON public.festivos_bloqueos(fecha);
```

### 2.6. Politicas de Row Level Security (RLS) y Realtime
- Habilitar y forzar RLS en todas las tablas:
  ```sql
  ALTER TABLE public.usuarios_staff ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.usuarios_staff FORCE ROW LEVEL SECURITY;
  ALTER TABLE public.pacientes ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.pacientes FORCE ROW LEVEL SECURITY;
  ALTER TABLE public.turnos ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.turnos FORCE ROW LEVEL SECURITY;
  ALTER TABLE public.sesiones_chat ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.sesiones_chat FORCE ROW LEVEL SECURITY;
  ALTER TABLE public.festivos_bloqueos ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.festivos_bloqueos FORCE ROW LEVEL SECURITY;
  ```
- Politicas de Acceso Formalizadas:
  - `usuarios_staff`: Politica `p_usuarios_staff_deny_all` para denegacion total a `anon` y `authenticated`. Acceso exclusivo por backend via `service_role`.
  - `sesiones_chat`: Politica `p_sesiones_chat_deny_all` para denegacion total a `anon` y `authenticated`.
  - `pacientes`: Politica `p_pacientes_deny_anon` denegando acceso anonimo. Escritura y lectura sensible restringida a `service_role`.
  - `turnos`:
    - Politica `p_turnos_select_public_tv`: SELECT permitido para `anon` y `authenticated` filtrando unicamente turnos activos (`confirmado`, `en_sala`, `llamando`, `en_atencion`).
    - Politicas `p_turnos_write_deny`, `p_turnos_update_deny`, `p_turnos_delete_deny`: Denegacion explicita de escritura directa para clientes `anon` y `authenticated`.
  - `festivos_bloqueos`:
    - Politica `p_festivos_select_all`: SELECT publico (`USING (true)`).
    - Politicas de denegacion de modificacion para clientes anon/authenticated.
- Supabase Realtime:
  - Tablas publicadas: `turnos` y `pacientes` agregadas a `supabase_realtime`.
  - `REPLICA IDENTITY FULL` configurado en `turnos` y `pacientes` para transmitir el estado completo en eventos UPDATE/INSERT.

### 2.7. Contrato de la Capa de Persistencia (app/database.py) y Esquemas Pydantic (app/schemas.py)
- **Modelos de Entrada Estrictos (`StrictBaseModel`):**
  - Todos los modelos de entrada aplican `extra="forbid"`, `str_strip_whitespace=True` y `from_attributes=True`.
  - Normalizacion E.164 obligatoria para telefonos (`validar_telefono_e164`).
  - Sanitizacion anti-XSS estricta (`validar_texto_seguro`) rechazando `<`, `>` y caracteres de control invisibles en nombres, notas y motivos.
  - Normalizacion obligatoria de correos electronicos a minusculas con `EmailStr`.
  - Identificadores fuertemente tipados con `UUID` de Python (cero enteros secuenciales).
- **Mapeo Transaccional de Errores de Base de Datos:**
  - Codigo PostgreSQL `23P01` o conflicto con `excl_turnos_sin_solapamiento` -> `SlotTakenError` (HTTP 409).
  - Codigo PostgreSQL `23505` y violacion de `idx_un_turno_activo_por_paciente` -> `ActiveAppointmentExistsError` (HTTP 409).
  - Otros errores PostgREST se capturan y registran sin exponer trazas tecnicas, retornando `DomainError`.
- **Firmas del Repositorio Clinico (`ClinicRepository`):**
  - Personal: `get_staff_by_email(email) -> dict | None`, `get_staff_by_id(staff_id) -> StaffUserResponse | None`.
  - Pacientes: `get_paciente_by_telefono(telefono) -> PacienteResponse | None`, `get_paciente_by_id(paciente_id) -> PacienteResponse | None`, `upsert_paciente(data: PacienteCreate) -> PacienteResponse`, `set_triage_emergencia(telefono, motivo, nombre) -> PacienteResponse`, `resolver_triage_emergencia(paciente_id) -> PacienteResponse`, `list_pacientes_con_triage_activo() -> list[PacienteResponse]`.
  - Turnos: `get_turno_activo_by_paciente(paciente_id) -> TurnoResponse | None`, `list_turnos_rango(fecha_inicio, fecha_fin, solo_activos) -> list[TurnoResponse]`, `create_turno(data: TurnoDBInsert) -> TurnoResponse`, `get_turno_by_id(turno_id) -> TurnoResponse | None`, `update_estado_turno(turno_id, nuevo_estado, llamado_at, notas_internas) -> TurnoResponse`, `update_horario_turno(turno_id, nueva_fecha_inicio, nueva_fecha_fin) -> TurnoResponse`, `generar_siguiente_codigo_sala(fecha_inicio_dia, fecha_fin_dia) -> str`.
  - Chat IA: `get_historial_chat(telefono, max_mensajes=10) -> list[dict]` (expiracion automatica tras 12h de inactividad), `save_historial_chat(telefono, historial, max_mensajes=10) -> None`.
  - Festivos: `is_fecha_bloqueada(fecha) -> tuple[bool, str | None]`, `list_festivos_rango(fecha_inicio, fecha_fin) -> list[FestivoBloqueoResponse]`, `create_festivo_bloqueo(data: FestivoBloqueoCreate) -> FestivoBloqueoResponse`.

### 2.8. Contrato del Motor de Logica Clinica (app/logic.py)
- **Utilidades de Zona Horaria:**
  - `now_colombia() -> datetime`: Retorna la fecha y hora consciente en America/Bogota.
  - `combinar_fecha_hora_colombia(fecha: date, hora: time) -> datetime`: Construye un datetime consciente con tzinfo America/Bogota.
- **Validacion de Dias Habiles y Festivos:**
  - `validar_dia_habil(fecha: date, repo: ClinicRepository | None = None) -> None`: Bloquea fines de semana (sabado y domingo), festivos oficiales en Colombia (`holidays`) y bloqueos extraordinarios en `festivos_bloqueos`, levantando `HolidayOrWeekendError`.
- **Validacion Horaria y Duracion:**
  - `validar_horario_servicio(fecha: date, hora_inicio: time, servicio: TipoServicio) -> tuple[datetime, datetime, int]`: Verifica pertenencia integra al bloque manana [07:00, 12:00] o tarde [13:00, 17:00], rechazando solapamientos con el receso de almuerzo [12:00, 13:00) via `LunchBreakConflictError` o fuera de jornada via `OutsideWorkingHoursError`.
- **Disponibilidad y Alternativas:**
  - `calcular_disponibilidad(fecha: date, servicio: TipoServicio, repo: ClinicRepository | None = None) -> DisponibilidadResponse`: Genera bloques candidatos cada 15 min y valida solapamiento semiabierto `[)` contra turnos activos.
  - `obtener_alternativas_cercanas(fecha: date, servicio: TipoServicio, hora_deseada: time, max_alternativas: int = 4, repo: ClinicRepository | None = None) -> list[str]`: Retorna horarios libres ordenados por menor distancia temporal.
- **Ciclo Transaccional:**
  - `procesar_nuevo_turno(datos: TurnoCreateRequest, repo: ClinicRepository | None = None) -> TurnoResponse`: Valida dia, horario, paciente unico con cita activa y captura `SlotTakenError` enriqueciendolo con alternativas reales.
- **Maquina de Estados y Ventana de Gracia:**
  - `cambiar_estado_turno(turno_id: UUID, peticion: TurnoEstadoUpdateRequest, forzar_sin_espera: bool = False, repo: ClinicRepository | None = None) -> TurnoResponse`: Valida transiciones clinicas formales y exige los 15 min de `NO_SHOW_GRACE_MINUTES` antes de permitir `cancelado_ausente` desde `llamando`.
- **Desplazamiento Masivo por Retraso:**
  - `aplicar_retraso_masivo(peticion: RetrasoMasivoRequest, momento_actual: datetime | None = None, repo: ClinicRepository | None = None) -> RetrasoMasivoResponse`: Actualiza los turnos pendientes en orden cronologico inverso (`fecha_inicio` descendente) para neutralizar colisiones GiST 23P01.
- **Operacion en Vivo y Triage:**
  - `obtener_estado_operacion_actual(fecha_referencia: date | None = None, repo: ClinicRepository | None = None) -> EstadoOperacionActualResponse`.
  - `activar_triage_emergencia(telefono: str, motivo_urgencia: str, nombre_paciente: str | None = None, repo: ClinicRepository | None = None) -> PacienteResponse`.
  - `resolver_triage_paciente(paciente_id: UUID, peticion: TriageResolverRequest | None = None, repo: ClinicRepository | None = None) -> PacienteResponse`.
- **Extensiones de Pantalla TV y Gestion Humana de Pacientes (Tarea #6):**
  - `anonimizar_nombre_sala(nombre_completo: str) -> str`: Anonimiza nombres para sala de espera ("Maria Fernanda Lopez" -> "Maria L.", "Valentina" -> "Valentina").
  - `obtener_turnos_pantalla_tv(fecha_referencia: date | None = None, repo: ClinicRepository | None = None) -> list[TurnoPantallaTVResponse]`: Excluye PII exponiendo unicamente iniciales y codigos de turno para Smart TV.
  - `cancelar_turno_activo_por_paciente(telefono: str, motivo: str | None = None, repo: ClinicRepository | None = None) -> TurnoResponse`: Libera el slot de inmediato, actualiza a `cancelado_paciente` con trazabilidad en notas internas y emite Supabase Realtime sin salto automatico al siguiente turno.
  - `registrar_aviso_asistencia_paciente(telefono: str, detalle_aviso: str, minutos_retraso_estimado: int | None = None, repo: ClinicRepository | None = None) -> TurnoResponse`: Registra avisos de demora en notas internas si estan dentro de la tolerancia de 15 min; rechaza si superan dicha tolerancia.

### 2.9. Contrato de Criptografia, Rate Limiting, Cookies HttpOnly y RBAC (app/security.py, app/auth.py, app/main.py)
- **Criptografia y Politica de Contrasenas (app/security.py):**
  - Hashing: Exclusivo con Argon2id mediante `pwdlib.PasswordHash.recommended()`.
  - Mitigacion de Timing Attacks: En inicios de sesion donde el correo no exista en base de datos, se ejecuta `verify_password(password, DUMMY_PASSWORD_HASH)` en tiempo constante.
  - Politica de Robustez (`validate_password_not_leaked`):
    - Minimo 10 caracteres.
    - Al menos una letra mayuscula, una minuscula y un digito o simbolo.
    - Bloqueo de contrasenas comunes o filtradas en brechas (`LEAKED_PASSWORDS`).
    - Bloqueo de inclusion de la parte local del correo del usuario.
- **Gestion de Tokens y Sesion (app/security.py y app/auth.py):**
  - Formato: JWT firmado con HMAC-SHA256 (`HS256`) utilizando `settings.SECRET_KEY`.
  - Expiracion: 480 minutos (8 horas continuas, jornada laboral completa).
  - Claims minimos: `sub` (UUID en string), `email`, `rol` (string del enum RolStaff), `iat`, `exp`.
  - Almacenamiento: Exclusivamente en Cookie HttpOnly con nombre `access_token`. Prohibido el retorno del token en el cuerpo JSON para evitar almacenamiento en `localStorage`.
  - Atributos de Cookie (`set_auth_cookie`): `key="access_token"`, `httponly=True`, `samesite="lax"`, `secure=settings.is_production`, `path="/"`, `max_age=28800`.
  - Cierre de sesion (`clear_auth_cookie`): `delete_cookie` con mismos parametros de path y flags de seguridad.
- **Control de Acceso Basado en Roles (RBAC en Servidor - app/auth.py):**
  - `get_current_staff`: Extrae el token de la cookie HttpOnly (fallback a `Authorization: Bearer`), decodifica el JWT y valida que el usuario exista y tenga `activo=True` en la base de datos.
  - `require_roles(*roles_permitidos: RolStaff)`: Generador de dependencias de FastAPI que intercepta la peticion y levanta `DomainError` (HTTP 403) si el rol del usuario no figura en la tupla permitida.
- **Rate Limiting y Resolucion de IP (slowapi - app/security.py):**
  - Clave de identificacion (`get_real_client_ip`):
    1. Cabecera `CF-Connecting-IP` (Cloudflare Tunnel para PC local).
    2. Primer valor de cabecera `X-Forwarded-For`.
    3. Fallback a direccion remota de la conexion socket (127.0.0.1).
  - Tasa global por defecto: 120 peticiones por minuto por IP.
  - Tasa restrictiva para autenticacion: 5 peticiones por minuto por IP en `POST /api/v1/auth/login`.
- **Cabeceras de Blindaje HTTP (app/main.py):**
  - Middleware inyecta en cada respuesta:
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY`
    - `Referrer-Policy: strict-origin-when-cross-origin`
    - `X-XSS-Protection: 1; mode=block`
    - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (en produccion).
  - Ocultamiento de `/docs`, `/redoc` y `/openapi.json` cuando `settings.is_production == True`.

---

## 3. CONTRATOS DE ENDPOINTS REST Y WEBHOOKS

Todos los endpoints que devuelven error responden con la estructura uniforme:
```json
{
  "status": "error",
  "code": "codigo_formal",
  "message": "Descripcion comprensible para el usuario",
  "details": null
}
```

### 3.1. Modulo de Autenticacion de Personal

#### `POST /api/v1/auth/login`
- Descripcion: Autenticacion de miembros del personal clinico (admin, doctor, recepcion).
- Headers: `Content-Type: application/json`
- Request Body:
  ```json
  {
    "email": "doctor@lujoluminoso.com",
    "password": "PasswordSeguro123"
  }
  ```
- Respuestas:
  - `200 OK`:
    - Headers de respuesta: `Set-Cookie: access_token=...; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800` (con directiva `Secure` en produccion).
    ```json
    {
      "status": "success",
      "data": {
        "usuario": {
          "id": "e305e608-412f-4c54-bcae-213192f1f0a1",
          "email": "doctor@lujoluminoso.com",
          "nombre": "Dr. Mateo Restrepo",
          "rol": "doctor"
        }
      }
    }
    ```
  - `401 Unauthorized`:
    ```json
    {
      "status": "error",
      "code": "unauthorized_access",
      "message": "Credenciales invalidas o cuenta inactiva",
      "details": null
    }
    ```

#### `POST /api/v1/auth/logout`
- Descripcion: Cierre seguro de sesion.
- Respuestas:
  - `200 OK`: Limpia la cookie `access_token` estableciendo `Max-Age=0`.
    ```json
    {
      "status": "success",
      "message": "Sesion cerrada correctamente"
    }
    ```

#### `GET /api/v1/auth/me`
- Descripcion: Obtiene los datos del usuario autenticado actual desde la cookie HttpOnly.
- Respuestas:
  - `200 OK`: Retorna el objeto `usuario`.
  - `401 Unauthorized`: Si la cookie no esta presente o expiro.

#### `POST /api/v1/auth/staff`
- Descripcion: Registra un nuevo miembro del personal clinico (doctor, recepcion o admin).
- Acceso: Restringido estrictamente a colaboradores con rol `admin` (`RolStaff.ADMIN`).
- Rate Limiting: 10 peticiones por minuto.
- Request Body (`StaffCreateRequest`):
  ```json
  {
    "nombre": "Dra. Valentina Morales",
    "email": "valentina@lujoluminoso.co",
    "password": "PasswordFuerte2026#",
    "rol": "doctor"
  }
  ```
- Criptografia: La contrasena se valida contra listas de contrasenas comunes/filtradas y se hashea con Argon2id.
- Respuestas:
  - `201 Created`: Retorna el objeto `usuario` creado sin password_hash.
  - `401 Unauthorized`: Si no hay sesion autenticada.
  - `403 Forbidden`: Si el usuario no tiene rol de Administrador.
  - `409 Conflict`: Si el correo electronico ya se encuentra registrado.

#### `GET /api/v1/auth/staff`
- Descripcion: Obtiene la lista completa de personal clinico registrado en `usuarios_staff`.
- Acceso: Restringido a usuarios con rol `admin`.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "data": {
        "staff": [
          {
            "id": "e305e608-412f-4c54-bcae-213192f1f0a1",
            "email": "doctor@lujoluminoso.com",
            "nombre": "Dr. Armando Casas",
            "rol": "doctor",
            "activo": true,
            "created_at": "2026-11-10T12:00:00Z"
          }
        ]
      }
    }
    ```

---

### 3.2. Modulo de Agenda y Disponibilidad

#### `GET /api/v1/disponibilidad`
- Descripcion: Consulta intervalos de horarios libres para un servicio en una fecha determinada.
- Query Parameters:
  - `fecha` (requerido, formato `YYYY-MM-DD`, e.g. `2026-11-15`)
  - `servicio` (requerido, enum: `profilaxis`, `ortodoncia`, `diseno_sonrisa`, `cirugia_implantes`)
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "data": {
        "fecha": "2026-11-15",
        "servicio": "profilaxis",
        "duracion_min": 30,
        "horarios_disponibles": [
          "07:00", "07:30", "08:00", "08:30",
          "13:00", "13:30", "14:00", "16:30"
        ]
      }
    }
    ```
  - `400 Bad Request` (si la fecha es fin de semana o festivo):
    ```json
    {
      "status": "error",
      "code": "holiday_or_weekend",
      "message": "La fecha seleccionada corresponde a un fin de semana o dia festivo.",
      "details": null
    }
    ```

#### `POST /api/v1/turnos`
- Descripcion: Crea un nuevo turno odontologico. Valida colisiones y limite de 1 cita activa.
- Request Body:
  ```json
  {
    "nombre_paciente": "Camila Gomez",
    "telefono": "+573001234567",
    "email": "camila.gomez@ejemplo.com",
    "servicio": "diseno_sonrisa",
    "fecha": "2026-11-15",
    "hora_inicio": "10:00",
    "origen": "web_paciente"
  }
  ```
- Respuestas:
  - `201 Created`:
    ```json
    {
      "status": "success",
      "data": {
        "turno_id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
        "codigo_sala": "T-04",
        "servicio": "diseno_sonrisa",
        "fecha_inicio": "2026-11-15T10:00:00-05:00",
        "fecha_fin": "2026-11-15T11:00:00-05:00",
        "estado": "confirmado",
        "paciente": {
          "nombre": "Camila Gomez",
          "telefono": "+573001234567"
        }
      }
    }
    ```
  - `409 Conflict` (si el horario esta ocupado):
    ```json
    {
      "status": "error",
      "code": "slot_taken",
      "message": "El horario solicitado ya se encuentra reservado.",
      "details": {
        "available_alternatives": ["11:00", "14:00", "15:00"]
      }
    }
    ```
  - `409 Conflict` (si el paciente ya tiene cita activa):
    ```json
    {
      "status": "error",
      "code": "active_appointment_exists",
      "message": "El paciente ya cuenta con una cita activa y no puede agendar un turno adicional.",
      "details": null
    }
    ```

#### `GET /api/v1/turnos`
- Descripcion: Obtiene el listado de turnos dentro de un rango temporal (para FullCalendar.js y reportes). Requiere autenticacion de personal.
- Query Parameters:
  - `fecha_inicio` (requerido, ISO-8601 o `YYYY-MM-DD`)
  - `fecha_fin` (requerido, ISO-8601 o `YYYY-MM-DD`)
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "data": {
        "turnos": [
          {
            "id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
            "codigo_sala": "T-04",
            "paciente_nombre": "Camila Gomez",
            "paciente_telefono": "+573001234567",
            "servicio": "diseno_sonrisa",
            "fecha_inicio": "2026-11-15T10:00:00-05:00",
            "fecha_fin": "2026-11-15T11:00:00-05:00",
            "estado": "confirmado"
          }
        ]
      }
    }
    ```

#### `GET /api/v1/turnos/pantalla-tv`
- Descripcion: Listado anonimizado para visualizacion en Smart TV de la sala de espera.
- Rate Limiting: 60 peticiones/minuto.
- Query Parameters: `fecha` (opcional, formato `YYYY-MM-DD`, defecto dia actual).
- Respuestas:
  - `200 OK`:
    ```json
    [
      {
        "id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
        "codigo_sala": "T-04",
        "nombre_mostrar": "Camila G.",
        "estado": "confirmado",
        "llamado_at": null
      }
    ]
    ```

---

### 3.3. Modulo de Operacion Clinica (Doctor y Recepcion)

#### `PATCH /api/v1/operacion/turnos/{turno_id}/estado`
- Descripcion: Ejecuta una transicion de estado clinico sobre el turno.
- Request Body:
  ```json
  {
    "nuevo_estado": "llamando"
  }
  ```
- Reglas de transicion permitidas:
  - `confirmado` -> `en_sala`, `cancelado_paciente`, `cancelado_ausente`
  - `en_sala` -> `llamando`, `cancelado_ausente`
  - `llamando` -> `en_atencion`, `cancelado_ausente`
  - `en_atencion` -> `completado`
- Respuestas:
  - `200 OK`: Retorna turno actualizado.
  - `422 Unprocessable Entity`: Si la transicion viola `TRANSICIONES_VALIDAS`.

#### `POST /api/v1/operacion/retraso`
- Descripcion: Reporta un retraso en la atencion y desplaza en cascada los turnos del dia.
- Request Body:
  ```json
  {
    "minutos_retraso": 30
  }
  ```
  Valores validos: `15`, `30`, `45`, `60`.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "data": {
        "minutos_desplazados": 30,
        "turnos_afectados": 3,
        "notificaciones_encoladas": 3
      }
    }
    ```

#### `POST /api/v1/operacion/triage/{paciente_id}/resolver`
- Descripcion: Desactiva la bandera de emergencia clinica tras haber asistido al paciente de forma presencial o telefonica.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "message": "Alerta de triage resuelta exitosamente."
    }
    ```

#### `GET /api/v1/operacion/estado-actual`
- Descripcion: Endpoint consolidado en tiempo real para el Modo Enfoque del Doctor y la estacion de recepcion.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "data": {
        "paciente_actual": {
          "turno_id": "9a1b2c3d-...",
          "codigo_sala": "T-02",
          "nombre": "Jorge Morales",
          "servicio": "cirugia_implantes",
          "hora_inicio": "09:00",
          "hora_fin": "11:00",
          "estado": "en_atencion"
        },
        "siguiente_procedimiento": {
          "turno_id": "7f8b9c2a-...",
          "codigo_sala": "T-03",
          "nombre": "Ana Maria Diaz",
          "servicio": "profilaxis",
          "duracion_min": 30,
          "hora_inicio": "11:00",
          "requiere_preparacion_instrumental": "Bandeja de profilaxis, cavitron ultrasonico, pasta profilactica y copa de goma"
        },
        "sala_espera": [
          {
            "codigo_sala": "T-03",
            "nombre": "Ana Maria Diaz",
            "hora_llegada": "10:48",
            "estado": "en_sala"
          }
        ],
        "alertas_triage": []
      }
    }
    ```

#### `GET /api/v1/operacion/festivos`
- Descripcion: Listado de festivos y bloqueos extraordinarios en el calendario de la clinica.
- Permisos: Requiere autenticacion de personal (`ADMIN`, `DOCTOR`, `RECEPCION`).
- Query Parameters: `anio` (opcional, entero, defecto 2026).
- Respuestas:
  - `200 OK`: Retorna lista de objetos `FestivoBloqueoResponse`.

#### `POST /api/v1/operacion/festivos`
- Descripcion: Registro de fecha de cierre o bloqueo extraordinario de agenda.
- Permisos: Exclusivo para roles `ADMIN` y `DOCTOR`.
- Request Body:
  ```json
  {
    "fecha": "2026-12-24",
    "motivo": "Cierre institucional por festividades"
  }
  ```
- Respuestas:
  - `201 Created`: Retorna `FestivoBloqueoResponse`.
  - `403 Forbidden`: Si el rol no tiene privilegios de doctor o administrador.

---

### 3.4. Modulo de Webhooks de WhatsApp Cloud API

#### `GET /webhook/whatsapp`
- Descripcion: Verificacion obligatoria del reto (challenge) de Meta Webhooks (handshake inicial).
- Query Parameters:
  - `hub.mode`: Debe ser `"subscribe"`.
  - `hub.verify_token`: Debe coincidir estrictamente con `WHATSAPP_VERIFY_TOKEN` (comparado en tiempo constante con `hmac.compare_digest`).
  - `hub.challenge`: Cadena aleatoria provista por los servidores de Meta.
- Respuestas:
  - `200 OK`: Devuelve el valor textual de `hub.challenge` como `text/plain`.
  - `401 Unauthorized`: Si el token no coincide o el modo no es `subscribe`.

#### `POST /webhook/whatsapp`
- Descripcion: Recepcion asincrona de mensajes entrantes de usuarios y notificaciones de entrega.
- Headers requeridos:
  - `X-Hub-Signature-256`: Firma HMAC-SHA256 obligatoria calculada con `WHATSAPP_APP_SECRET` sobre el cuerpo binario crudo (`sha256=<hex>`).
- Validaciones y Controles de Seguridad:
  1. **Firma Criptografica (Punto #16 de Seguridad):** Si la firma falta, no inicia con `sha256=` o el hash calculado no coincide con comparacion en tiempo constante, se rechaza inmediatamente con `401 Unauthorized` (`CodigoError.UNAUTHORIZED_ACCESS`).
  2. **Tamano Maximo:** Cuerpos superiores a 64 KB se rechazan de inmediato.
  3. **Descarte de Estados (Statuses):** Notificaciones de entrega (`sent`, `delivered`, `read`) se ignoran silenciosamente retornando `{"status": "ok", "processed": 0}` para no desperdiciar ciclos ni saldo.
  4. **Deduplicacion Idempotente de Mensajes:** Cache LRU en memoria (`max_size=1000`, `ttl=3600s`) indexada por `wamid`. Si Meta reintenta la entrega por timeout de red (>3 segundos), se ignora el duplicado y responde `{"status": "ignored", "reason": "duplicate_message"}`.
  5. **Limitador de Tasa por Remitente (Anti Denial of Wallet):** Ventana deslizante en memoria con maximo 12 mensajes por minuto por numero telefonico E.164.
  6. **Defensa contra Archivos no Seguros (Punto #20 de Seguridad):** Archivos adjuntos (`image`, `audio`, `video`, `document`, `sticker`) NO son descargados, almacenados ni procesados. Se encola un mensaje explicativo al paciente indicando que el canal automatizado opera exclusivamente por texto.
  7. **Procesamiento de Texto e Interactivos:** Conecta con `procesar_mensaje_whatsapp` en `app/ai_agent.py`.
  8. **Despacho Asincrono de Respuestas:** La respuesta de la IA o advertencia de seguridad se despacha en segundo plano via `BackgroundTasks` llamando a `enviar_mensaje_whatsapp_texto`, garantizando una respuesta HTTP 200 a Meta en menos de 100 ms.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "ok",
      "processed": 1
    }
    ```
  - `401 Unauthorized`: Si la firma HMAC-SHA256 es invalida o ausente.

#### Notificaciones Salientes Clinicas de WhatsApp
1. `enviar_mensaje_whatsapp_texto(telefono, texto)`:
   - Endpoint de salida: `https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages`.
   - Modos:
     - En produccion: Peticion POST autenticada con Bearer Token, `preview_url: false`.
     - En desarrollo / credenciales simuladas: Registro estructurado en log `[WHATSAPP SIMULADO]` sin llamadas externas.
   - Sanitizacion estricta con `limpiar_respuesta_ia` garantizando CERO emojis en todo mensaje saliente.
2. `notificar_cancelacion_ausente_whatsapp(turno)`:
   - Disparado automaticamente en segundo plano desde `PATCH /api/v1/operacion/turnos/{turno_id}/estado` cuando un turno transiciona a `cancelado_ausente` (al expirar los 15 minutos de gracia de no-show).
   - Informa al paciente la liberacion de la cita y le ofrece reagendar directamente por el chat.
3. `notificar_retraso_masivo_whatsapp(turnos_afectados, minutos_retraso)`:
   - Disparado automaticamente en segundo plano desde `POST /api/v1/operacion/retraso`.
   - Notifica a cada paciente con cita posterior el ajuste de horario estimado en minutos y la nueva hora de atencion.

---

### 3.5. Modulo de Modo Demo Aislado (Tarea #11)

#### Guardarrail y Kill-Switch de Seguridad: `require_demo_mode`
- Condicion de ejecucion: Todos los endpoints bajo `/api/v1/demo/*` exigen que `DEMO_MODE=True`.
- Si `DEMO_MODE=False`, el servidor rechaza inmediatamente cualquier solicitud con `HTTP 403 Forbidden` (`CodigoError.UNAUTHORIZED_ACCESS`), impidiendo cualquier ejecucion accidental o deliberada en entornos productivos.

#### `POST /api/v1/demo/quick-login`
- Descripcion: Emite una cookie `HttpOnly` real firmada con JWT para alternar instantaneamente entre los perfiles `doctor`, `recepcion` y `admin` sin almacenar credenciales en `localStorage`.
- Rate Limiting: 20 peticiones por minuto.
- Request Body (`DemoQuickLoginRequest`):
  ```json
  {
    "rol": "doctor"
  }
  ```
- Respuestas:
  - `200 OK`: `StaffUserResponse` con cookie `lujo_access_token` y `access_token` inyectadas en los encabezados `Set-Cookie`.

#### `POST /api/v1/demo/seed-scenario`
- Descripcion: Puebla la base de datos con un escenario clinico realista para el dia habil actual (o siguiente habil si hoy es fin de semana/festivo) respetando la exclusion GiST. Incluye citas en `en_atencion`, `llamando`, `en_sala`, `confirmado`, una cancelacion por WhatsApp (`[CANCELADO POR PACIENTE]`) y una alerta de triage activa.
- Rate Limiting: 10 peticiones por minuto.
- Request Body (`DemoSeedRequest`):
  ```json
  {
    "fecha_objetivo": null,
    "limpiar_dia_antes": true
  }
  ```
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "success",
      "message": "Escenario clinico demo sembrado exitosamente.",
      "data": {
        "fecha_sembrada": "2026-11-11",
        "turnos_creados": 6,
        "pacientes_creados": 7,
        "triage_alerta": {
          "paciente": "Andres Mendoza",
          "telefono": "+573009998877",
          "motivo": "Dolor molar agudo e inflamacion severa reportada por WhatsApp",
          "activo": true
        },
        "turnos": [...]
      }
    }
    ```

#### `POST /api/v1/demo/fast-forward-grace/{turno_id}`
- Descripcion: Atrasa artificialmente la marca temporal `llamado_at` a 16 minutos atras (`now - 16 min`), permitiendo comprobar de inmediato el vencimiento del cronometro de 15 min y habilitar el boton de inasistencia (`cancelado_ausente`) en el Panel del Doctor sin esperar tiempo real.
- Rate Limiting: 20 peticiones por minuto.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "ok",
      "turno_id": "94130deb-6e39-4a3b-b564-2a0941aaea5e",
      "nuevo_estado": "llamando",
      "llamado_at": "2026-11-10T12:39:00-05:00",
      "minutos_transcurridos": 16,
      "message": "Temporizador de gracia adelantado a 16 minutos. La cita puede declararse cancelado_ausente."
    }
    ```

#### `POST /api/v1/demo/whatsapp-sim`
- Descripcion: Simula la recepcion de un mensaje de WhatsApp entrante interactuando con `procesar_mensaje_whatsapp` o ejecutando el enrutador determinista de respaldo ante contingencias tecnicas o ausencia de clave externa de IA.
- Rate Limiting: 30 peticiones por minuto.
- Request Body (`DemoWhatsAppSimRequest`):
  ```json
  {
    "telefono": "+573005550199",
    "nombre_perfil": "Laura Demo",
    "mensaje": "Tengo un dolor insoportable y sangrado abundante"
  }
  ```
- Respuestas:
  - `200 OK`:
    ```json
    {
      "status": "ok",
      "telefono": "+573005550199",
      "user_message": "Tengo un dolor insoportable y sangrado abundante",
      "bot_reply": "Hemos detectado una situacion de atencion medica prioritaria...",
      "tool_calls": ["solicitar_atencion_humana"],
      "triage_activado": true
    }
    ```

---

### 3.6. Modulo de Configuracion Publica y Vistas Web (Tarea #9)

#### `GET /api/v1/config/public`
- Descripcion: Retorna exclusivamente parametros publicos seguros requeridos para la inicializacion del cliente web SPA (Punto #2 de Seguridad).
- Autenticacion: Publico (sin credenciales requeridas).
- Blindaje: Jamas expone `SUPABASE_SERVICE_ROLE_KEY`, `SECRET_KEY`, `GEMINI_API_KEY` ni `WHATSAPP_TOKEN`.
- Respuestas:
  - `200 OK`:
    ```json
    {
      "clinic_name": "Lujo Luminoso",
      "timezone": "America/Bogota",
      "supabase_url": "https://tu-proyecto.supabase.co",
      "supabase_anon_key": "eyJhbGciOi...",
      "demo_mode": false,
      "whatsapp_number": "100000000000001",
      "whatsapp_contact_number": "100000000000001"
    }
    ```

#### `GET /`, `GET /admin`, `GET /doctor`, `GET /tv`
- Descripcion: Rutas HTML que sirven `templates/index.html` activando la vista correspondiente (`paciente`, `admin`, `doctor`, `tv`) segun la URL solicitada.
- Respuestas:
  - `200 OK`: Documento HTML5 con cabeceras de seguridad inyectadas (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`).

---

## 4. CONTRATOS DE HERRAMIENTAS IA (GEMINI FUNCTION CALLING)

El agente inteligente interactua con el sistema exclusivamente mediante declaraciones formales de herramientas (Function Calling).

### 4.1. Herramienta: `consultar_disponibilidad`
- Descripcion: Consulta los horarios libres en la agenda para una fecha y servicio especificos.
- Definicion de Parametros (JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "fecha": {
        "type": "string",
        "description": "Fecha a consultar en formato YYYY-MM-DD (ejemplo: '2026-11-20'). Solo de lunes a viernes."
      },
      "servicio": {
        "type": "string",
        "enum": ["profilaxis", "ortodoncia", "diseno_sonrisa", "cirugia_implantes"],
        "description": "Tipo de procedimiento odontologico solicitado."
      }
    },
    "required": ["fecha", "servicio"]
  }
  ```
- Retorno de la herramienta:
  ```json
  {
    "disponible": true,
    "fecha": "2026-11-20",
    "servicio": "profilaxis",
    "horarios": ["08:00", "08:30", "09:00", "14:00", "14:30"]
  }
  ```

### 4.2. Herramienta: `agendar_turno`
- Descripcion: Reserva un turno clinico tras confirmacion explicita del paciente.
- Definicion de Parametros (JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "fecha": {
        "type": "string",
        "description": "Fecha del turno en formato YYYY-MM-DD."
      },
      "hora_inicio": {
        "type": "string",
        "description": "Hora de inicio en formato militar HH:MM (ejemplo: '10:00')."
      },
      "servicio": {
        "type": "string",
        "enum": ["profilaxis", "ortodoncia", "diseno_sonrisa", "cirugia_implantes"],
        "description": "Tipo de procedimiento."
      },
      "nombre_paciente": {
        "type": "string",
        "description": "Nombre y apellido del paciente."
      },
      "email_paciente": {
        "type": "string",
        "description": "Correo electronico opcional para confirmacion y recordatorios."
      }
    },
    "required": ["fecha", "hora_inicio", "servicio", "nombre_paciente"]
  }
  ```
- Retorno de la herramienta:
  ```json
  {
    "exito": true,
    "turno_id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
    "codigo_sala": "T-05",
    "mensaje": "Cita agendada exitosamente para el 2026-11-20 a las 10:00."
  }
  ```

### 4.3. Herramienta: `solicitar_atencion_humana`
- Descripcion: Registra un caso de emergencia medica o atencion prioritaria para que el equipo humano intervenga de inmediato.
- Definicion de Parametros (JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "motivo_urgencia": {
        "type": "string",
        "description": "Descripcion sintomatica del paciente: sangrado activo, traumatismo severo, dolor agudo intolerable con inflamacion."
      }
    },
    "required": ["motivo_urgencia"]
  }
  ```
- Retorno de la herramienta:
  ```json
  {
    "alerta_creada": true,
    "instruccion_paciente": "Tu caso ha sido catalogado como prioridad clinica. Un miembro del equipo te contactara de inmediato. Por favor manten tu linea disponible."
  }
  ```

### 4.4. Herramienta: `cancelar_mi_turno`
- Descripcion: Cancela la cita activa actual del paciente en la clinica y libera el espacio en la agenda sin saltar turnos automaticamente.
- Definicion de Parametros (JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "motivo": {
        "type": "string",
        "description": "Razon de la cancelacion explicada por el paciente (ejemplo: 'Imprevisto laboral')."
      }
    }
  }
  ```
- Retorno de la herramienta:
  ```json
  {
    "status": "ok",
    "turno_id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
    "estado": "cancelado_paciente",
    "mensaje": "Cita cancelada. El horario fue liberado y el aviso con el motivo ya aparece en el panel del doctor y de la asistente sin saltar turnos automaticamente."
  }
  ```

### 4.5. Herramienta: `reportar_retraso_o_aviso_paciente`
- Descripcion: Registra una notificacion de retraso o aviso de camino en el panel del doctor sin cancelar la cita (tolerancia maxima de 15 minutos).
- Definicion de Parametros (JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "detalle_aviso": {
        "type": "string",
        "description": "Explicacion del paciente sobre su demora o estado de camino."
      },
      "minutos_retraso_estimado": {
        "type": "integer",
        "description": "Minutos aproximados de tardanza (tolerancia maxima de 15 minutos)."
      }
    },
    "required": ["detalle_aviso"]
  }
  ```
- Retorno de la herramienta:
  ```json
  {
    "status": "ok",
    "turno_id": "7f8b9c2a-5d1e-4c3a-8b9e-1a2b3c4d5e6f",
    "estado": "confirmado",
    "notas_internas": "[AVISO PACIENTE - DEMORA 10 MIN]: Trancon en la 7ma",
    "tolerancia_max_min": 15
  }
  ```

### 4.6. Contrato del Orquestador Conversacional (`procesar_mensaje_whatsapp`)
- Ubicacion: `app/ai_agent.py`
- Firma: `async def procesar_mensaje_whatsapp(telefono: str, mensaje_usuario: str, nombre_perfil_wa: str | None = None, repo: ClinicRepository | None = None) -> dict[str, Any]`
- Flujo de ejecucion:
  1. Sanitizacion de entrada del usuario (`sanitizar_entrada_usuario`) recortando a 1.000 caracteres y neutralizando Prompt Injection.
  2. Deteccion de palabras clave de emergencia (`detectar_keywords_emergencia`).
  3. Carga de memoria en ventana deslizante de 10 mensajes desde `sesiones_chat` (expiracion de 12 horas).
  4. Generacion con Gemini (`gemini-2.5-flash`) y hasta 3 rondas encadenadas de Function Calling.
  5. Ejecucion segura de herramientas inyectando forzosamente el `telefono` de la sesion (anti-suplantacion).
  6. Respaldo de triage clinico si el LLM omitio la urgencia medica o si la API experimenta fallas de conectividad.
  7. Sanitizacion post-generacion (`limpiar_respuesta_ia`) garantizando CERO EMOJIS y neutralizacion de etiquetas HTML.
  8. Persistencia del contexto en PostgreSQL y retorno estructurado:
     ```json
     {
       "reply": "Buenos dias. Con gusto le confirmo los horarios...",
       "tool_calls": ["consultar_disponibilidad"],
       "triage_activado": false
     }
     ```

---

## 5. SISTEMA DE DISENO UI/UX ("LUJO LUMINOSO")

Inspirado en la pulcritud, densidad y elegancia de herramientas profesionales modernas como Linear y Raycast.

### 5.1. Paleta de Colores y Estructura Visual
- Fondo general de aplicacion: Blanco Alabastro (`#F8FAFC` / `bg-slate-50`).
- Superficies y tarjetas: Blanco puro (`#FFFFFF` / `bg-white`) con sombra ultraligera (`shadow-sm`).
- Textos primarios: Gris Pizarra profundo (`#1E293B` / `text-slate-900`).
- Textos secundarios / metadatos: Gris Pizarra neutro (`#64748B` / `text-slate-500`).
- Acento Clinico Primario: Verde Salvia (`#4A6B5D` / `bg-emerald-800` o clase personalizada `bg-[#4A6B5D]`).
- Acento de Interaccion / Enfoque: Azul Acero (`#3B6E8C` / `bg-[#3B6E8C]`).
- Bordes: Grises sutiles y limpios (`border border-slate-200/80`).
- Tipografia: Inter o sistema nativo con tracking ajustado (`tracking-tight`, `font-medium`, `text-sm`).
- Botones: Bordes redondeados elegantes (`rounded-xl`), tamano compacto (`px-3 py-1.5` o `px-4 py-2`), microinteracciones sutiles con `transition-all duration-150`.
- Iconografia: Exclusivamente Lucide Icons vectoriales con trazo fino (`stroke-width="1.75"`).

### 5.2. Especificacion de las 4 Vistas Principales

#### Vista 1: Landing de Informacion y Reserva del Paciente
- Encabezado minimalista con logotipo vectorial de Lujo Luminoso.
- Selector visual de procedimientos odontologicos (tarjetas refinadas con duracion, descripcion y costo referencial).
- Selector de fecha con bloqueo de fines de semana y festivos colombianos.
- Rejilla dinamica de bloques horarios disponibles en tiempo real.
- Formulario de contacto seguro (Nombre, Telefono E.164, Correo).
- Dialogo modal de confirmacion con codigo de sala asignado (`T-XX`).

#### Vista 2: Dashboard de Administracion y Operacion
- Barra superior con estatus de conexion Realtime y selector de fecha.
- Panel principal con FullCalendar.js personalizado con la paleta Salvia/Pizarra.
- Banner flotante de Alerta de Triage (se activa con borde rojo sutil y sonido atenuado cuando un paciente requiere atencion prioritaria).
- Boton de accion rapida "Reportar Retraso" (selector modal de 15, 30, 45, 60 minutos con recalculo instantaneo).

#### Vista 3: Modo Enfoque del Doctor (Sillon Clinico)
- Interfaz de maximo contraste y cero distracciones.
- Tarjeta gigante del "Paciente Actual":
  - Nombre, codigo de sala, procedimiento y tiempo transcurrido en sillon.
- Tarjeta de anticipacion: "Siguiente Procedimiento":
  - Servicio, instrumental a esterilizar y preparar, y tiempo restante estimado.
- Panel de acciones clinicas directas:
  - Boton "Llamar Paciente" (acciona la pantalla TV e inicia la cuenta regresiva de 15 min de gracia).
  - Temporizador dinamico visible de los 15 minutos de gracia.
  - Boton "Marcar Ausente" (habilitado tras expirar la ventana de gracia).
  - Boton "Iniciar Atencion" y Boton "Finalizar Consulta".

#### Vista 4: Pantalla TV de Sala de Espera
- Fondo oscuro refinado (`#0F172A` / `bg-slate-900`) para descanso visual de pacientes en sala.
- Tipografia gigante y legible a distancia (`text-6xl`, `font-semibold`).
- Visualizacion en tiempo real impulsada por Supabase Realtime:
  - Turno llamado actualmente: Codigo de sala en gran tamano (`T-02`) acompanado del primer nombre e inicial del apellido (`Jorge M.`).
  - Lista de turnos en espera (`T-03`, `T-04`).
- Privacidad absoluta: Cero exposicion de procedimientos clinicos, telefonos ni historiales medicos.
- Senal auditiva de llamada: Tono sutil generado por Web Audio API (cero estridencias).

### 5.3. Contratos de Identificadores del DOM (Base para Tareas #9 y #10)

| Identificador (ID) | Vista / Componente | Descripcion y Proposito para la Tarea #10 |
| :--- | :--- | :--- |
| `#view-paciente` | Vista 1: Paciente | Contenedor principal de la landing y motor de reserva publica. |
| `#view-admin` | Vista 2: Admin | Contenedor principal del Dashboard operativo y recepcion. |
| `#view-doctor` | Vista 3: Doctor | Contenedor principal del Modo Enfoque en sillon clinico. |
| `#view-tv` | Vista 4: Pantalla TV | Contenedor de la pantalla publica de sala con fondo `#0F172A`. |
| `#fullcalendar-container` | Vista 2: Admin | Punto de anclaje de la instancia de FullCalendar.js v6. |
| `#triage-alerts-container`| Vista 2: Admin | Contenedor dinamico de banners de triage de alta prioridad. |
| `#delay-controls` | Vista 2: Admin | Contenedor para acciones de retraso masivo y contingencias. |
| `#current-patient-card` | Vista 3: Doctor | Tarjeta con datos y cronometro del paciente en atencion. |
| `#next-procedure-prep-card`| Vista 3: Doctor | Tarjeta de preparacion del instrumental para la proxima cita. |
| `#grace-timer-display` | Vista 3: Doctor | Cronometro visible de la ventana de gracia de 15 minutos. |
| `#waiting-queue-list` | Vista 3: Doctor | Cola de pacientes esperando en sala para llamado en un clic. |
| `#tv-calling-spotlight` | Vista 4: Pantalla TV | Foco visual gigante del turno llamado (`T-XX` y nombre anonimizado). |
| `#tv-upcoming-grid` | Vista 4: Pantalla TV | Lista de proximos turnos en espera de atencion. |
| `#modal-login` | Global / Autenticacion| Dialogo modal de autenticacion del personal con cookies HttpOnly. |
| `#slot-taken-banner` | Vista 1: Paciente | Banner reactivo ante colisiones GiST con botones de alternativas. |
| `#alternative-slots-list`| Vista 1: Paciente | Contenedor de chips clicables para `available_alternatives`. |

### 5.4. Arquitectura de Sincronizacion en Tiempo Real y Sintesis Acustica (Tarea #10)

1. **Suscripcion Hibrida:**
   - Canal Supabase: `lujo-luminoso-operacion` escuchando `postgres_changes` en `turnos` y `pacientes`.
   - Debounce de 300 ms para agrupar eventos y evitar ráfagas de consultas a FastAPI.
   - Respaldo de contingencia local: Polling en segundo plano cada 8 segundos cuando la pestana esta activa (`document.visibilityState === "visible"`).
2. **Sintesis Acustica con Web Audio API (`AudioContext`):**
   - Sin dependencias de archivos `.mp3` o descargas externas en la red local.
   - Secuencia de tonos sinusoidales armónicos: C5 (523.25 Hz, 0.5s), E5 (659.25 Hz, 0.5s) y G5 (783.99 Hz, 0.9s) con envolvente exponencial (`exponentialRampToValueAtTime`) para un timbre suave y distinguido.
   - Deteccion de nuevos llamados: Compara la clave `${turno.id}_${turno.llamado_at}`. Solo suena ante un cambio real en el turno llamado.
   - Boton `#btn-tv-audio-toggle`: Permite reanudar el contexto de audio (`audioCtx.resume()`) si el navegador bloquea el autoplay al encender el televisor.
3. **Cronometro de Gracia de 15 Minutos:**
   - Anclado a `turno_llamando.llamado_at`.
   - Calcula el tiempo restante: `Math.max(0, 900 - elapsed)`.
   - Mantiene deshabilitado el boton "Declarar Ausente" hasta que el cronometro llegue a `00:00`, evitando cancelaciones prematuras en la sala.

---

## 6. MATRIZ DE BLINDAJE DE LOS 20 PUNTOS DE SEGURIDAD

| # | Vector de Seguridad | Implementacion Especifica en Lujo Luminoso |
|---|---------------------|--------------------------------------------|
| 1 | Secretos fuera de Git | `.env` y `.env.*` bloqueados en `.gitignore`; unico archivo versionado es `.env.example` con llaves ficticias. |
| 2 | Proteccion por Rol (RBAC) | Decoradores y dependencias en FastAPI validan roles (`admin`, `doctor`, `recepcion`) en cada ruta. |
| 3 | Supabase Row Level Security | RLS activo en todas las tablas; la clave `anon` no puede leer pacientes ni historial de chat. |
| 4 | Validacion Backend Obligatoria | Toda regla de negocio (horarios, colisiones, 1 cita activa) se verifica en FastAPI, nunca en frontend. |
| 5 | Rate Limiting con SlowAPI | Limitacion estricta de peticiones por IP y por telefono en endpoints criticos (login, reserva, webhooks). |
| 6 | Prevencion de Inyeccion SQL | Consultas ejecutadas exclusivamente mediante el SDK parametrizado de Supabase; prohibido SQL concatenado. |
| 7 | Validacion Estricta de Esquemas | Modelos Pydantic V2 en todos los Request Bodies con tipos rigurosos y restricciones de longitud. |
| 8 | Mitigacion de XSS en DOM | Prohibido el uso de `innerHTML` con entradas de usuario; renderizado seguro mediante `textContent`. |
| 9 | Hashing Criptografico de Claves | Algoritmo Argon2id implementado via `pwdlib[argon2]` con parametros de memoria y coste recomendados por OWASP. |
| 10 | Tokens Seguros sin LocalStorage | Autenticacion JWT almacenada exclusivamente en cookies `HttpOnly`, `SameSite=Lax` y `Secure`. |
| 11 | Acceso Privado a Paneles | Rutas de Dashboard y Modo Enfoque protegidas con middleware de sesion obligatoria. |
| 12 | Restriccion Rigurosa de CORS | `ALLOWED_ORIGINS` explora origenes autorizados; prohibicion programatica del comodin `*` en produccion. |
| 13 | Validacion de Direcciones Email | Uso de `email-validator` con verificacion de formato estricto y rechazo de caracteres espurios. |
| 14 | Identificadores no Enumerables | Claves primarias generadas con UUID v4 criptografico para impedir scraping por fuerza bruta secuencial. |
| 15 | Limite de Request Body | FastAPI y servidor ASGI configurados con tamano maximo de carga util para mitigar ataques DoS. |
| 16 | HMAC-SHA256 en Webhooks | Verificacion de la cabecera `X-Hub-Signature-256` en Meta Webhook usando `WHATSAPP_APP_SECRET`. |
| 17 | Ocultamiento de Stack Traces | Manejador de excepciones global que en produccion retorna errores 500 genericos sin revelar trazas. |
| 18 | Dependencias Limpias y Auditadas | `requirements.txt` con librerias esenciales fijadas en versiones estables y sin paquetes no utilizados. |
| 19 | Politica de Contrasenas Robustas | Rechazo de contraseñas con menos de 8 caracteres o patrones triviales mediante validadores Pydantic. |
| 20 | Bloqueo de Carga de Archivos | La plataforma clinica no habilita endpoints de subida arbitraria de binarios ni scripts ejecutables. |

---

## 7. VARIABLES DE ENTORNO REQUERIDAS

| Variable | Tipo | Requerida en Prod | Descripcion |
|----------|------|-------------------|-------------|
| `APP_ENV` | `Literal['development', 'production']` | Si | Entorno de ejecucion. Define rigor de seguridad y manejo de errores. |
| `DEMO_MODE` | `bool` | No (default `false`) | Habilita endpoints de prueba de escenario clinico aislado. |
| `TIMEZONE` | `str` | Si (default `America/Bogota`) | Zona horaria para calculos de disponibilidad y turnos. |
| `SECRET_KEY` | `str` | Si (min 32 caracteres) | Llave secreta para firma y verificacion de tokens de sesion. |
| `ALLOWED_ORIGINS` | `str` | Si | Dominios autorizados para peticiones CORS (separados por coma). |
| `SUPABASE_URL` | `str` | Si | URL HTTPS del proyecto Supabase. |
| `SUPABASE_ANON_KEY` | `str` | Si | Clave anonima publica de Supabase para consultas basicas del cliente. |
| `SUPABASE_SERVICE_ROLE_KEY` | `str` | Si | Clave de servicio de Supabase con privilegios elevados para backend. |
| `GEMINI_API_KEY` | `str` | Si | Clave de acceso a la API de Google Gemini para procesamiento conversacional. |
| `GEMINI_MODEL` | `str` | No (default `gemini-2.5-flash`) | Modelo de Gemini utilizado para Function Calling. |
| `WHATSAPP_TOKEN` | `str` | Si | Bearer token de acceso para Meta WhatsApp Cloud API. |
| `WHATSAPP_PHONE_NUMBER_ID` | `str` | Si | Identificador unico del numero telefonico de Meta Developers. |
| `WHATSAPP_VERIFY_TOKEN` | `str` | Si | Token secreto de coincidencia para el handshake de verificacion Webhook. |
| `WHATSAPP_APP_SECRET` | `str` | Si | Secreto de la aplicacion Meta para validacion de firma HMAC-SHA256. |
| `CLOUDFLARE_TUNNEL_TOKEN` | `str` | No (opcional) | Token del tunel Cloudflare Zero Trust para conectar el PC local con dominio publico. |
