"""
Enrutador REST para disponibilidad, reserva de turnos, calendario y pantalla TV.

Implementa control de origen (blindaje web vs staff), proteccion contra spam
mediante rate limiting diferenciado y vista publica anonimizada para sala de espera.
"""

import logging
from datetime import date, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth import COOKIE_NAME, require_roles
from app.constants import CodigoError, NOMBRES_SERVICIOS, OrigenTurno, RolStaff, TipoServicio
from app.database import ClinicRepository, get_repository
from app.exceptions import DomainError
from app.logic import (
    calcular_disponibilidad,
    combinar_fecha_hora_colombia,
    now_colombia,
    obtener_turnos_pantalla_tv,
    procesar_nuevo_turno,
)
from app.schemas import (
    DisponibilidadResponse,
    StaffUserResponse,
    TurnoCreateRequest,
    TurnoPantallaTVResponse,
    TurnoResponse,
)
from app.security import decode_access_token, limiter

logger = logging.getLogger("app.routers.turnos")

router = APIRouter(prefix="/api/v1", tags=["Turnos y Disponibilidad"])


# ==============================================================================
# HELPER DE IDENTIFICACION NO BLOQUEANTE DE PERSONAL
# ==============================================================================

def _obtener_staff_opcional(
    request: Request,
    repo: ClinicRepository,
) -> StaffUserResponse | None:
    """
    Verifica si la peticion entrante proviene de un miembro de personal autenticado.
    No interrumpe el flujo con excepciones para permitir el agendamiento anonimo de pacientes.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return None

    try:
        payload = decode_access_token(token)
        staff_id_str = payload.get("sub")
        if not staff_id_str:
            return None
        staff_id = UUID(staff_id_str)
        staff = repo.get_staff_by_id(staff_id)
        if staff and staff.activo:
            return staff
        return None
    except Exception:
        return None


# ==============================================================================
# ENDPOINTS PUBLICOS CON RATE LIMITING
# ==============================================================================

@router.get(
    "/disponibilidad",
    response_model=DisponibilidadResponse,
    summary="Consultar horarios libres por fecha y servicio",
)
@limiter.limit("30/minute")
def get_disponibilidad(
    request: Request,
    fecha: date = Query(..., description="Fecha requerida (formato YYYY-MM-DD)"),
    servicio: TipoServicio = Query(..., description="Servicio clinico a reservar"),
    repo: ClinicRepository = Depends(get_repository),
) -> DisponibilidadResponse:
    """
    Calcula los intervalos horarios disponibles en franjas de 15 minutos.
    Excluye automaticamente fines de semana, festivos oficiales y receso de almuerzo.
    """
    return calcular_disponibilidad(fecha=fecha, servicio=servicio, repo=repo)


@router.post(
    "/turnos",
    response_model=TurnoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nuevo turno odontologico",
)
@limiter.limit("10/minute")
def crear_turno(
    request: Request,
    datos: TurnoCreateRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> TurnoResponse:
    """
    Crea un nuevo turno odontologico validando concurrencia y limite de 1 cita activa.

    Blindaje de Origen:
      - Si la peticion proviene de la web sin sesion de staff, se fuerza 'origen=web_paciente'
        y se eliminan notas internas para evitar inyeccion de privilegios.
      - Si proviene de personal autenticado, se respetan el origen y notas internas provistas.
    """
    staff = _obtener_staff_opcional(request, repo)
    if not staff:
        datos = datos.model_copy(
            update={
                "origen": OrigenTurno.WEB_PACIENTE,
                "notas_internas": None,
            }
        )

    return procesar_nuevo_turno(datos=datos, repo=repo)


@router.get(
    "/turnos/{turno_id}/ics",
    summary="Descargar cita odontologica en formato iCalendar (.ics)",
)
@limiter.limit("30/minute")
def descargar_turno_ics(
    request: Request,
    turno_id: UUID,
    repo: ClinicRepository = Depends(get_repository),
) -> Response:
    """
    Genera un archivo .ics estandar RFC 5545 para agregar la cita a calendarios personales
    (Google Calendar, Apple Calendar, Outlook) respetando la zona horaria America/Bogota.
    """
    turno = repo.get_turno_by_id(turno_id)
    if not turno:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="El turno solicitado no existe en el sistema.",
            status_code=404,
        )

    fmt_utc = "%Y%m%dT%H%M%SZ"
    dt_inicio_utc = turno.fecha_inicio.astimezone(timezone.utc).strftime(fmt_utc)
    dt_fin_utc = turno.fecha_fin.astimezone(timezone.utc).strftime(fmt_utc)
    dt_stamp = now_colombia().astimezone(timezone.utc).strftime(fmt_utc)
    nombre_proc = NOMBRES_SERVICIOS.get(turno.servicio, turno.servicio.value)

    ics_content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Clinica Odontologica Lujo Luminoso//Agendamiento Clinico//ES\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{turno.id}@lujoluminoso.co\r\n"
        f"DTSTAMP:{dt_stamp}\r\n"
        f"DTSTART:{dt_inicio_utc}\r\n"
        f"DTEND:{dt_fin_utc}\r\n"
        f"SUMMARY:Cita Odontologica: {nombre_proc} - Lujo Luminoso ({turno.codigo_sala})\r\n"
        f"DESCRIPTION:Cita confirmada en Clinica Odontologica Boutique Lujo Luminoso.\\nProcedimiento: {nombre_proc}\\nCodigo de Sala: {turno.codigo_sala}\\nPor favor presentarse 5 minutos antes de la hora programada.\\nZona Horaria: America/Bogota.\\r\n"
        "LOCATION:Clinica Odontologica Lujo Luminoso\\, Carrera 15 # 85-30\\, Consultorio 402\\, Bogota\\, Colombia\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": f'attachment; filename="cita_{turno.codigo_sala}.ics"',
            "Cache-Control": "no-cache",
        },
    )


@router.get(
    "/turnos/pantalla-tv",
    response_model=list[TurnoPantallaTVResponse],
    summary="Listado anonimizado para Smart TV en sala de espera",
)
@limiter.limit("60/minute")
def listar_turnos_pantalla_tv(
    request: Request,
    fecha: date | None = Query(default=None, description="Fecha de consulta (YYYY-MM-DD, defecto hoy)"),
    repo: ClinicRepository = Depends(get_repository),
) -> list[TurnoPantallaTVResponse]:
    """
    Retorna la lista de turnos activos del dia anonimizados para la sala de espera.
    Protege datos personales (PII) exponiendo unicamente iniciales y codigos de turno.
    """
    return obtener_turnos_pantalla_tv(fecha_referencia=fecha, repo=repo)


# ==============================================================================
# ENDPOINTS ADMINISTRATIVOS PROTEGIDOS CON RBAC
# ==============================================================================

@router.get(
    "/turnos",
    response_model=list[TurnoResponse],
    summary="Listado de turnos por rango para agenda administrativa",
)
def listar_turnos_rango(
    fecha_inicio: date = Query(..., description="Fecha inicial del rango (YYYY-MM-DD)"),
    fecha_fin: date = Query(..., description="Fecha final del rango (YYYY-MM-DD)"),
    solo_activos: bool = Query(default=False, description="Filtrar citas activas unicamente"),
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> list[TurnoResponse]:
    """
    Obtiene los turnos agendados en un rango de fechas para FullCalendar.js y reportes.
    Requiere autenticacion de personal y restringe el intervalo a un maximo de 62 dias.
    """
    if fecha_fin < fecha_inicio:
        raise DomainError(
            code=CodigoError.OUTSIDE_WORKING_HOURS,
            message="La fecha final no puede ser anterior a la fecha inicial.",
            status_code=400,
        )

    dias_rango = (fecha_fin - fecha_inicio).days
    if dias_rango > 62:
        raise DomainError(
            code=CodigoError.OUTSIDE_WORKING_HOURS,
            message="El rango de consulta no puede superar 62 dias continuos.",
            status_code=400,
        )

    dt_inicio = combinar_fecha_hora_colombia(fecha_inicio, time(0, 0, 0))
    dt_fin = combinar_fecha_hora_colombia(fecha_fin, time(23, 59, 59))

    return repo.list_turnos_rango(
        fecha_inicio=dt_inicio,
        fecha_fin=dt_fin,
        solo_activos=solo_activos,
    )
