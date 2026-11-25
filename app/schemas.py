"""
Esquemas Pydantic v2 para validacion estricta y sanitizacion de entrada y salida.

Implementa blindaje integral contra inyeccion XSS, normalizacion E.164,
tipado fuerte con UUID y rechazo de campos no autorizados (extra='forbid').
"""

import re
from datetime import date, datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.constants import (
    MINUTOS_RETRASO_VALIDOS,
    EstadoTurno,
    OrigenTurno,
    RolStaff,
    TipoServicio,
)


# ==============================================================================
# VALIDstatusADORES Y SANITIZADORES REUTILIZABLES
# ==============================================================================

RE_TELEFONO_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def validar_telefono_e164(v: str) -> str:
    """
    Normaliza y valida numeros telefonicos bajo el estandar internacional E.164.
    Admite auto-normalizacion para numeros moviles de Colombia (10 digitos iniciados en 3).
    """
    if not isinstance(v, str):
        raise ValueError("El telefono debe ser una cadena de texto.")

    # Remover espacios en blanco, guiones o parentesis comunes
    limpio = re.sub(r"[\s\-\(\)]", "", v.strip())

    # Auto-completar prefijo internacional para moviles en Colombia si vienen sin '+'
    if len(limpio) == 10 and limpio.startswith("3"):
        limpio = f"+57{limpio}"
    elif len(limpio) == 12 and limpio.startswith("573"):
        limpio = f"+{limpio}"

    if not RE_TELEFONO_E164.match(limpio):
        raise ValueError(
            "El telefono debe cumplir con el formato E.164 internacional (ejemplo: +573001234567)."
        )
    return limpio


def validar_texto_seguro(v: str | None) -> str | None:
    """
    Sanitiza cadenas de texto para prevenir XSS almacenado e inyecciones.
    Rechaza estrictamente etiquetas HTML ('<' o '>') y caracteres de control invisibles.
    """
    if v is None:
        return None

    texto = v.strip()
    if "<" in texto or ">" in texto:
        raise ValueError("El texto contiene caracteres no permitidos ('<' o '>') por proteccion anti-XSS.")

    # Bloquear caracteres de control ASCII (excepto saltos de linea y tabulaciones estandar)
    for char in texto:
        codigo = ord(char)
        if codigo < 32 and char not in ("\n", "\r", "\t"):
            raise ValueError("El texto contiene caracteres de control invisibles no permitidos.")

    return texto


# Tipos anotados reutilizables con validacion integrada
TelefonoE164 = Annotated[str, Field(description="Numero telefonico en formato E.164")]
TextoSeguro = Annotated[str, Field(description="Texto sanitizado libre de etiquetas HTML")]


# ==============================================================================
# CLASE BASE ESTRICTA
# ==============================================================================

class StrictBaseModel(BaseModel):
    """
    Clase base para todos los modelos de entrada (Request / Create / Update).
    Rechaza campos arbitrarios no declarados y recorta espacios automaticamente.
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        from_attributes=True,
    )


# ==============================================================================
# 1. ESQUEMAS DE AUTENTICACION, CAPTCHA Y PERSONAL (usuarios_staff)
# ==============================================================================

class CaptchaVerifyRequest(StrictBaseModel):
    """Payload de verificacion para el reto 'No soy un robot' (codigo o seleccion 3x3)."""
    captcha_token: str = Field(min_length=10, description="Token criptografico del reto")
    mode: Literal["code", "image_grid"] = Field(description="Modalidad resuelta")
    answer_code: str | None = Field(default=None, max_length=16, description="Codigo escrito por el usuario")
    selected_indices: list[int] | None = Field(default=None, description="Indices seleccionados en cuadricula 3x3")


class RegisterRequest(StrictBaseModel):
    """Payload de registro de nuevos usuarios en el sistema clinico."""
    nombre: str = Field(min_length=2, max_length=120, description="Nombre completo")
    telefono: TelefonoE164
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Contrasena de acceso")
    rol: RolStaff = Field(default=RolStaff.RECEPCION, description="Rol de acceso")
    captcha_verified_token: str | None = Field(default=None, description="Token de aprobacion del captcha")

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: EmailStr) -> str:
        return str(v).lower()

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        return validar_telefono_e164(v)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        res = validar_texto_seguro(v)
        if not res or len(res) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres legibles.")
        return res


class GoogleAuthRequest(StrictBaseModel):
    """Payload para autenticacion federada con Google o selector de cuentas."""
    email: EmailStr
    nombre: str = Field(min_length=2, max_length=120)
    telefono: str | None = None
    credential: str | None = None
    google_id: str | None = None

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: EmailStr) -> str:
        return str(v).lower()

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        res = validar_texto_seguro(v)
        if not res or len(res) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres legibles.")
        return res


class StaffToggleRequest(StrictBaseModel):
    """Payload para activar o desactivar cuenta de personal."""
    activo: bool


class ResenaCreate(StrictBaseModel):
    """Peticion de paciente para publicar una resena y calificacion."""
    nombre: str = Field(..., min_length=2, max_length=100, description="Nombre del paciente")
    servicio: str = Field(..., min_length=2, max_length=80, description="Tratamiento realizado")
    calificacion: int = Field(..., ge=1, le=5, description="Calificacion de 1 a 5 estrellas")
    comentario: str = Field(..., min_length=5, max_length=1000, description="Opinion y testimonio")


class ResenaResponse(StrictBaseModel):
    """Respuesta estructurada de resena clinica verificada."""
    id: str
    nombre: str
    servicio: str
    calificacion: int
    comentario: str
    fecha: str
    verificado: bool = True


class LoginRequest(StrictBaseModel):
    """Payload de autenticacion para miembros del personal clinico."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Contrasena de acceso")
    captcha_verified_token: str | None = Field(default=None, description="Token de captcha opcional")

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: EmailStr) -> str:
        return str(v).lower()


class StaffUserResponse(BaseModel):
    """Datos publicos del personal autenticado (PROHIBIDO password_hash)."""
    id: UUID
    email: EmailStr
    nombre: str
    rol: RolStaff
    activo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StaffCreateRequest(StrictBaseModel):
    """Payload para creacion de nuevos miembros del personal clinico (requiere rol ADMIN)."""
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Contrasena de acceso inicial")
    nombre: str = Field(min_length=2, max_length=120, description="Nombre completo del colaborador")
    rol: RolStaff = Field(default=RolStaff.RECEPCION, description="Rol clinico asignado")

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: EmailStr) -> str:
        return str(v).lower()

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        res = validar_texto_seguro(v)
        if not res or len(res) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres legibles.")
        return res


# ==============================================================================
# 2. ESQUEMAS DE PACIENTES (pacientes)
# ==============================================================================

class PacienteCreate(StrictBaseModel):
    """Creacion o actualizacion directa de ficha de paciente."""
    telefono: TelefonoE164
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        return validar_telefono_e164(v)

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        res = validar_texto_seguro(v)
        if not res or len(res) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres legibles.")
        return res

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: EmailStr | None) -> str | None:
        return str(v).lower() if v else None


class PacienteTriageUpdate(StrictBaseModel):
    """Actualizacion del estado de emergencia y motivo de urgencia clinica."""
    requiere_atencion_humana: bool
    motivo_urgencia: str | None = Field(default=None, max_length=500)

    @field_validator("motivo_urgencia")
    @classmethod
    def sanitizar_motivo(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)


class PacienteResponse(BaseModel):
    """Representacion formal de la entidad paciente."""
    id: UUID
    telefono: str
    nombre: str
    email: EmailStr | None = None
    requiere_atencion_humana: bool = False
    motivo_urgencia: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# 3. ESQUEMAS DE TURNOS Y DISPONIBILIDAD (turnos)
# ==============================================================================

class DisponibilidadQuery(StrictBaseModel):
    """Parametros de consulta para verificacion de bloques libres."""
    fecha: date
    servicio: TipoServicio


class BloqueHorario(BaseModel):
    """Franja horaria calculada y disponible para reserva."""
    hora_inicio: str = Field(pattern=r"^\d{2}:\d{2}$", description="Hora de inicio HH:MM")
    hora_fin: str = Field(pattern=r"^\d{2}:\d{2}$", description="Hora de finalizacion HH:MM")
    fecha_inicio_iso: datetime
    fecha_fin_iso: datetime

    model_config = ConfigDict(from_attributes=True)


class DisponibilidadResponse(BaseModel):
    """Listado consolidado de alternativas horarias disponibles."""
    fecha: date
    servicio: TipoServicio
    nombre_servicio: str
    duracion_min: int
    bloques_disponibles: list[BloqueHorario]

    model_config = ConfigDict(from_attributes=True)


class TurnoCreateRequest(StrictBaseModel):
    """Solicitud de creacion de turno desde la web del paciente o canales externos."""
    telefono: TelefonoE164
    nombre_paciente: str = Field(min_length=2, max_length=120)
    email_paciente: EmailStr | None = None
    servicio: TipoServicio
    fecha: date
    hora_inicio: time
    origen: OrigenTurno = OrigenTurno.WEB_PACIENTE
    notas_internas: str | None = Field(default=None, max_length=500)
    captcha_verified_token: str | None = Field(default=None, description="Token de aprobacion del captcha")
    guardar_en_google_calendar: bool = Field(default=False, description="Bandera para indicar agendamiento en Google Calendar")

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        return validar_telefono_e164(v)

    @field_validator("nombre_paciente", "notas_internas")
    @classmethod
    def sanitizar_textos(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)

    @field_validator("email_paciente")
    @classmethod
    def normalizar_email(cls, v: EmailStr | None) -> str | None:
        return str(v).lower() if v else None


class TurnoDBInsert(StrictBaseModel):
    """Modelo interno fuertemente tipado para insercion directa en tabla turnos."""
    codigo_sala: str = Field(min_length=2, max_length=20)
    paciente_id: UUID
    servicio: TipoServicio
    duracion_min: int
    fecha_inicio: datetime
    fecha_fin: datetime
    estado: EstadoTurno = EstadoTurno.CONFIRMADO
    origen: OrigenTurno
    notas_internas: str | None = None

    @field_validator("notas_internas")
    @classmethod
    def sanitizar_notas(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)


class TurnoEstadoUpdateRequest(StrictBaseModel):
    """Peticion para transicionar el estado clinico de un turno."""
    nuevo_estado: EstadoTurno
    notas_internas: str | None = Field(default=None, max_length=500)

    @field_validator("notas_internas")
    @classmethod
    def sanitizar_notas(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)


class TurnoResponse(BaseModel):
    """Detalle completo del turno clinico, incluyendo datos del paciente vinculado."""
    id: UUID
    codigo_sala: str
    paciente_id: UUID
    servicio: TipoServicio
    duracion_min: int
    fecha_inicio: datetime
    fecha_fin: datetime
    estado: EstadoTurno
    llamado_at: datetime | None = None
    origen: OrigenTurno
    notas_internas: str | None = None
    created_at: datetime
    paciente: PacienteResponse | None = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# 4. ESQUEMAS DE OPERACION CLINICA, RETRASOS, TRIAGE Y PANTALLA TV
# ==============================================================================

class RetrasoMasivoRequest(StrictBaseModel):
    """Reporte de contingencia para desplazar citas por retraso del doctor."""
    minutos_retraso: Literal[15, 30, 45, 60]
    motivo: str | None = Field(
        default="Complicacion clinica en procedimiento actual",
        max_length=300,
    )

    @field_validator("motivo")
    @classmethod
    def sanitizar_motivo(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)

    @field_validator("minutos_retraso")
    @classmethod
    def validar_minutos(cls, v: int) -> int:
        if v not in MINUTOS_RETRASO_VALIDOS:
            raise ValueError(f"Minutos de retraso deben ser uno de: {MINUTOS_RETRASO_VALIDOS}")
        return v


class RetrasoMasivoResponse(BaseModel):
    """Resultado de la operacion de desplazamiento masivo."""
    turnos_desplazados: int
    minutos_aplicados: int
    turnos_afectados: list[TurnoResponse]

    model_config = ConfigDict(from_attributes=True)


class TriageResolverRequest(StrictBaseModel):
    """Confirmacion de resolucion y atencion prioritaria humana para el paciente."""
    notas_resolucion: str | None = Field(default=None, max_length=500)

    @field_validator("notas_resolucion")
    @classmethod
    def sanitizar_notas(cls, v: str | None) -> str | None:
        return validar_texto_seguro(v)


class TurnoPantallaTVResponse(BaseModel):
    """Informacion minimalista y anonimizada para la pantalla TV en sala de espera."""
    id: UUID
    codigo_sala: str
    nombre_mostrar: str = Field(description="Primer nombre e inicial del apellido del paciente")
    estado: EstadoTurno
    llamado_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EstadoOperacionActualResponse(BaseModel):
    """Snapshot completo en tiempo real para el panel del doctor y recepcion."""
    turno_en_atencion: TurnoResponse | None = None
    turno_llamando: TurnoResponse | None = None
    siguiente_turno: TurnoResponse | None = None
    cola_espera: list[TurnoResponse] = Field(default_factory=list)
    alertas_triage: list[PacienteResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# 5. ESQUEMAS DE CHAT IA Y FESTIVOS
# ==============================================================================

class MensajeChat(StrictBaseModel):
    """Elemento individual del contexto conversacional de WhatsApp."""
    role: Literal["user", "model"]
    content: str = Field(min_length=1, max_length=4000)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("content")
    @classmethod
    def sanitizar_contenido(cls, v: str) -> str:
        # En mensajes de chat se verifica que no contenga caracteres nulos/control daninos
        return validar_texto_seguro(v) or v


class FestivoBloqueoCreate(StrictBaseModel):
    """Definicion de fecha no laborable extraordinaria."""
    fecha: date
    motivo: str = Field(min_length=3, max_length=200)

    @field_validator("motivo")
    @classmethod
    def sanitizar_motivo(cls, v: str) -> str:
        res = validar_texto_seguro(v)
        if not res or len(res) < 3:
            raise ValueError("El motivo debe tener al menos 3 caracteres validos.")
        return res


class FestivoBloqueoResponse(BaseModel):
    """Representacion de dia no laborable en la agenda."""
    id: UUID
    fecha: date
    motivo: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
