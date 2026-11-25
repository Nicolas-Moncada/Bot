"""
Constantes inmutables de dominio y reglas de negocio de Lujo Luminoso.

Define las politicas de operacion clinica (1 doctor, 1 sillon),
los horarios de atencion, las duraciones de procedimientos, los estados
de turno con sus transiciones validas y los codigos de error estandarizados.
"""

from datetime import time
from enum import Enum


# ==============================================================================
# CONFIGURACION HORARIA Y PAIS
# ==============================================================================

DEFAULT_TIMEZONE: str = "America/Bogota"
HOLIDAYS_COUNTRY: str = "CO"


# ==============================================================================
# HORARIOS DE OPERACION CLINICA (LUNES A VIERNES)
# ==============================================================================
# Regla matematica inmutable:
#   hora_fin = hora_inicio + duracion_servicio
#
# Ninguna cita puede:
#   1. Iniciar antes de MORNING_START (07:00).
#   2. Iniciar o terminar dentro del intervalo de almuerzo [12:00, 13:00).
#   3. Terminar despues de MORNING_END (12:00) si inicio en la manana.
#   4. Iniciar antes de AFTERNOON_START (13:00) si es del bloque de la tarde.
#   5. Terminar despues de AFTERNOON_END (17:00).
#
# Ejemplos segun duracion:
#   - Profilaxis (30 min):
#       Ultimo turno manana: 11:30 -> 12:00
#       Ultimo turno tarde:  16:30 -> 17:00
#   - Ortodoncia (45 min):
#       Ultimo turno manana: 11:15 -> 12:00
#       Ultimo turno tarde:  16:15 -> 17:00
#   - Diseno de Sonrisa (60 min):
#       Ultimo turno manana: 11:00 -> 12:00
#       Ultimo turno tarde:  16:00 -> 17:00
#   - Cirugia / Implantes (120 min):
#       Ultimo turno manana: 10:00 -> 12:00
#       Ultimo turno tarde:  15:00 -> 17:00

MORNING_START: time = time(7, 0)
MORNING_END: time = time(12, 0)

LUNCH_START: time = time(12, 0)
LUNCH_END: time = time(13, 0)

AFTERNOON_START: time = time(13, 0)
AFTERNOON_END: time = time(17, 0)

# Dias laborales de la clinica: Lunes (0) a Viernes (4)
DIAS_LABORALES: tuple[int, ...] = (0, 1, 2, 3, 4)

# Minutos de gracia tras activar el llamado en sala de espera
NO_SHOW_GRACE_MINUTES: int = 15

# Minutos permitidos para el desplazamiento masivo por retraso clinico
MINUTOS_RETRASO_VALIDOS: tuple[int, ...] = (15, 30, 45, 60)


# ==============================================================================
# ENUMERACIONES DE DOMINIO
# ==============================================================================

class StrEnumBase(str, Enum):
    """Clase base para enumeraciones de texto con representacion limpia."""
    def __str__(self) -> str:
        return str(self.value)


class TipoServicio(StrEnumBase):
    """Procedimientos odontologicos habilitados en el consultorio."""
    PROFILAXIS = "profilaxis"
    ORTODONCIA = "ortodoncia"
    DISENO_SONRISA = "diseno_sonrisa"
    CIRUGIA_IMPLANTES = "cirugia_implantes"


class EstadoTurno(StrEnumBase):
    """
    Ciclo de vida de un turno odontologico.

    - confirmado: Cita agendada vigente. Bloquea horario y cuenta como cita activa.
    - en_sala: Paciente presente en sala de espera. Bloquea horario.
    - llamando: Doctor acciono llamado en pantalla TV. Dispara ventana de gracia de 15 min.
    - en_atencion: Paciente en sillon odontologico siendo intervenido.
    - completado: Procedimiento finalizado con exito por el doctor.
    - cancelado_ausente: Expiro ventana de 15 min o marcado ausente por doctor. Libera slot.
    - cancelado_paciente: Cancelado formalmente por el paciente. Libera slot.
    """
    CONFIRMADO = "confirmado"
    EN_SALA = "en_sala"
    LLAMANDO = "llamando"
    EN_ATENCION = "en_atencion"
    COMPLETADO = "completado"
    CANCELADO_AUSENTE = "cancelado_ausente"
    CANCELADO_PACIENTE = "cancelado_paciente"


class RolStaff(StrEnumBase):
    """Roles de acceso para el personal clinico y administrativo."""
    ADMIN = "admin"
    DOCTOR = "doctor"
    RECEPCION = "recepcion"


class OrigenTurno(StrEnumBase):
    """Canal de captura que dio origen a la reserva."""
    WHATSAPP_IA = "whatsapp_ia"
    WEB_PACIENTE = "web_paciente"
    PANEL_ADMIN = "panel_admin"
    DEMO = "demo"


class CodigoError(StrEnumBase):
    """Codigos estandarizados de error de negocio para APIs y agentes."""
    SLOT_TAKEN = "slot_taken"
    OUTSIDE_WORKING_HOURS = "outside_working_hours"
    LUNCH_BREAK_CONFLICT = "lunch_break_conflict"
    HOLIDAY_OR_WEEKEND = "holiday_or_weekend"
    ACTIVE_APPOINTMENT_EXISTS = "active_appointment_exists"
    EMERGENCY_TRIAGE_TRIGGERED = "emergency_triage_triggered"
    GRACE_PERIOD_NOT_ELAPSED = "grace_period_not_elapsed"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


# ==============================================================================
# MAPEOS Y AGRUPACIONES TIPADAS
# ==============================================================================

# Duracion exacta en minutos por tipo de procedimiento
DURACION_SERVICIOS_MIN: dict[TipoServicio, int] = {
    TipoServicio.PROFILAXIS: 30,
    TipoServicio.ORTODONCIA: 45,
    TipoServicio.DISENO_SONRISA: 60,
    TipoServicio.CIRUGIA_IMPLANTES: 120,
}

# Etiquetas formales para interfaz grafica y notificaciones
NOMBRES_SERVICIOS: dict[TipoServicio, str] = {
    TipoServicio.PROFILAXIS: "Profilaxis / Limpieza",
    TipoServicio.ORTODONCIA: "Control de Ortodoncia",
    TipoServicio.DISENO_SONRISA: "Diseño de Sonrisa",
    TipoServicio.CIRUGIA_IMPLANTES: "Cirugía / Implantes",
}

# Estados que ocupan el sillon o bloquean el calendario clinico
ESTADOS_BLOQUEANTES: frozenset[EstadoTurno] = frozenset({
    EstadoTurno.CONFIRMADO,
    EstadoTurno.EN_SALA,
    EstadoTurno.LLAMANDO,
    EstadoTurno.EN_ATENCION,
})

# Estados finales que liberan el sillon y no cuentan como cita activa
ESTADOS_LIBERADOS: frozenset[EstadoTurno] = frozenset({
    EstadoTurno.COMPLETADO,
    EstadoTurno.CANCELADO_AUSENTE,
    EstadoTurno.CANCELADO_PACIENTE,
})

# Grafo de transiciones validas en el flujo clinico
TRANSICIONES_VALIDAS: dict[EstadoTurno, frozenset[EstadoTurno]] = {
    EstadoTurno.CONFIRMADO: frozenset({
        EstadoTurno.EN_SALA,
        EstadoTurno.CANCELADO_PACIENTE,
        EstadoTurno.CANCELADO_AUSENTE,
    }),
    EstadoTurno.EN_SALA: frozenset({
        EstadoTurno.LLAMANDO,
        EstadoTurno.CANCELADO_AUSENTE,
    }),
    EstadoTurno.LLAMANDO: frozenset({
        EstadoTurno.EN_ATENCION,
        EstadoTurno.CANCELADO_AUSENTE,
    }),
    EstadoTurno.EN_ATENCION: frozenset({
        EstadoTurno.COMPLETADO,
    }),
    EstadoTurno.COMPLETADO: frozenset(),
    EstadoTurno.CANCELADO_AUSENTE: frozenset(),
    EstadoTurno.CANCELADO_PACIENTE: frozenset(),
}
