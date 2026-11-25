"""
Manejador centralizado de excepciones y respuestas de error para Lujo Luminoso.

Garantiza que ningun stack trace ni detalle interno de SQL/Python se exponga
al cliente en produccion, manteniendo respuestas JSON estandarizadas y predecibles.
"""

import logging
from typing import Any
from fastapi import Request
from fastapi.responses import JSONResponse

from app.constants import CodigoError
from app.config import get_settings

logger = logging.getLogger("app.exceptions")


# ==============================================================================
# EXCEPCION BASE DE DOMINIO Y SUBCLASES
# ==============================================================================

class DomainError(Exception):
    """
    Excepcion base para violaciones de reglas de negocio en la clinica.

    Atributos:
        code: Codigo de error formal tipado con CodigoError.
        message: Descripcion amigable y segura para el cliente o agente.
        status_code: Codigo HTTP correspondiente (por defecto 400).
        details: Diccionario opcional con metadatos (e.g. alternativas de horario).
    """

    def __init__(
        self,
        code: CodigoError,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serializa la excepcion a una estructura de diccionario estandar."""
        return {
            "status": "error",
            "code": str(self.code),
            "message": self.message,
            "details": self.details if self.details else None,
        }


class SlotTakenError(DomainError):
    """Disparada cuando el horario solicitado ya esta ocupado."""
    def __init__(
        self,
        message: str = "El horario solicitado ya se encuentra reservado.",
        available_alternatives: list[str] | None = None,
    ) -> None:
        details = {"available_alternatives": available_alternatives or []}
        super().__init__(
            code=CodigoError.SLOT_TAKEN,
            message=message,
            status_code=409,
            details=details,
        )


class OutsideWorkingHoursError(DomainError):
    """Disparada cuando la solicitud esta fuera del horario habil."""
    def __init__(
        self,
        message: str = "El horario solicitado esta fuera de la jornada de atencion (07:00-12:00 o 13:00-17:00).",
    ) -> None:
        super().__init__(
            code=CodigoError.OUTSIDE_WORKING_HOURS,
            message=message,
            status_code=400,
        )


class LunchBreakConflictError(DomainError):
    """Disparada cuando el turno colisiona con el receso de almuerzo (12:00-13:00)."""
    def __init__(
        self,
        message: str = "El procedimiento no puede iniciar ni finalizar dentro del horario de almuerzo (12:00-13:00).",
    ) -> None:
        super().__init__(
            code=CodigoError.LUNCH_BREAK_CONFLICT,
            message=message,
            status_code=400,
        )


class HolidayOrWeekendError(DomainError):
    """Disparada si la fecha corresponde a sabado, domingo o festivo oficial."""
    def __init__(
        self,
        message: str = "No hay atencion clinica en fines de semana ni dias festivos oficiales.",
    ) -> None:
        super().__init__(
            code=CodigoError.HOLIDAY_OR_WEEKEND,
            message=message,
            status_code=400,
        )


class ActiveAppointmentExistsError(DomainError):
    """Disparada cuando un paciente ya posee un turno activo en agenda."""
    def __init__(
        self,
        message: str = "El paciente ya cuenta con una cita activa y no puede agendar un turno adicional.",
    ) -> None:
        super().__init__(
            code=CodigoError.ACTIVE_APPOINTMENT_EXISTS,
            message=message,
            status_code=409,
        )


class EmergencyTriageError(DomainError):
    """Disparada cuando se detecta una urgencia clinica que requiere atencion humana inmediata."""
    def __init__(
        self,
        message: str = "Se ha identificado una posible emergencia odontologica. Se suspende la atencion automatizada para coordinar asistencia humana prioritaria.",
        motivo_urgencia: str | None = None,
    ) -> None:
        super().__init__(
            code=CodigoError.EMERGENCY_TRIAGE_TRIGGERED,
            message=message,
            status_code=400,
            details={"motivo_urgencia": motivo_urgencia} if motivo_urgencia else {},
        )


class GracePeriodNotElapsedError(DomainError):
    """Disparada al intentar cancelar por ausencia antes de transcurrir los 15 minutos."""
    def __init__(
        self,
        message: str = "No ha transcurrido la ventana de gracia de 15 minutos desde el llamado del paciente.",
    ) -> None:
        super().__init__(
            code=CodigoError.GRACE_PERIOD_NOT_ELAPSED,
            message=message,
            status_code=400,
        )


class InvalidStateTransitionError(DomainError):
    """Disparada al intentar una transicion de estado no permitida en el flujo clinico."""
    def __init__(
        self,
        message: str = "La transicion de estado solicitada no es valida en el flujo de atencion.",
    ) -> None:
        super().__init__(
            code=CodigoError.INVALID_STATE_TRANSITION,
            message=message,
            status_code=422,
        )


class UnauthorizedAccessError(DomainError):
    """Disparada cuando el usuario no cuenta con credenciales o permisos suficientes."""
    def __init__(
        self,
        message: str = "Acceso no autorizado o credenciales invalidas.",
    ) -> None:
        super().__init__(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message=message,
            status_code=401,
        )


class RateLimitExceededError(DomainError):
    """Disparada cuando se supera el limite de peticiones permitidas."""
    def __init__(
        self,
        message: str = "Limite de peticiones excedido. Por favor espere antes de intentar nuevamente.",
    ) -> None:
        super().__init__(
            code=CodigoError.RATE_LIMIT_EXCEEDED,
            message=message,
            status_code=429,
        )


# ==============================================================================
# GENERADORES DE RESPUESTAS JSON ESTANDARIZADAS
# ==============================================================================

def create_error_response(
    code: str | CodigoError,
    message: str,
    status_code: int = 400,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """
    Construye una respuesta JSON estandarizada para errores de la aplicacion.
    Formato uniforme: {"status": "error", "code": ..., "message": ..., "details": ...}
    """
    content: dict[str, Any] = {
        "status": "error",
        "code": str(code),
        "message": message,
        "details": details if details else None,
    }
    return JSONResponse(status_code=status_code, content=content)


# ==============================================================================
# MANEJADORES DE EXCEPCIONES PARA FASTAPI
# ==============================================================================

async def domain_exception_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Manejador especializado para excepciones de reglas de negocio."""
    logger.warning(
        "Violacion de regla de dominio capturada en %s %s: codigo=%s, mensaje=%s",
        request.method,
        request.url.path,
        exc.code,
        exc.message,
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Manejador global para cualquier excepcion imprevista no capturada.

    En produccion (APP_ENV == 'production'):
      - Oculta completamente el stack trace y mensajes internos del motor SQL o runtime.
      - Retorna un error 500 generico y seguro.
      - Registra la traza completa unicamente en el logger interno del servidor.

    En desarrollo:
      - Expone el mensaje para facilitar depuracion rapida.
    """
    logger.exception(
        "Excepcion no controlada en peticion %s %s: %s",
        request.method,
        request.url.path,
        str(exc),
    )

    settings = get_settings()
    if settings.is_production:
        return create_error_response(
            code="internal_server_error",
            message="Ocurrio un error interno en el servidor. Por favor intente mas tarde.",
            status_code=500,
            details=None,
        )

    # Entorno de desarrollo: mensaje descriptivo sin exponer datos confidenciales
    return create_error_response(
        code="internal_server_error",
        message=f"Error interno (modo depuracion): {str(exc)}",
        status_code=500,
        details={"exception_type": exc.__class__.__name__},
    )
