"""
Enrutador REST para operacion clinica, modo enfoque del doctor, contingencias y triage.

Gestiona las transiciones de estados del sillon, el retraso masivo anti-colision GiST,
la atencion prioritaria humana y el mantenimiento de fechas no laborables.
"""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.auth import require_roles
from app.constants import CodigoError, EstadoTurno, RolStaff
from app.database import ClinicRepository, get_repository
from app.exceptions import DomainError
from app.logic import (
    aplicar_retraso_masivo,
    cambiar_estado_turno,
    obtener_estado_operacion_actual,
    resolver_triage_paciente,
)
from app.routers.whatsapp import (
    notificar_cancelacion_ausente_whatsapp,
    notificar_retraso_masivo_whatsapp,
)
from app.schemas import (
    EstadoOperacionActualResponse,
    FestivoBloqueoCreate,
    FestivoBloqueoResponse,
    PacienteResponse,
    RetrasoMasivoRequest,
    RetrasoMasivoResponse,
    StaffUserResponse,
    TriageResolverRequest,
    TurnoEstadoUpdateRequest,
    TurnoResponse,
)

logger = logging.getLogger("app.routers.operacion")

router = APIRouter(prefix="/api/v1/operacion", tags=["Operacion Clinica"])


# ==============================================================================
# ESTADO DE OPERACION EN TIEMPO REAL
# ==============================================================================

@router.get(
    "/estado-actual",
    response_model=EstadoOperacionActualResponse,
    summary="Obtener estado actual de operacion clinica",
)
@router.get(
    "/actual",
    response_model=EstadoOperacionActualResponse,
    include_in_schema=False,
)
def get_estado_operacion(
    fecha: date | None = Query(default=None, description="Fecha de operacion (YYYY-MM-DD, defecto hoy)"),
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> EstadoOperacionActualResponse:
    """
    Retorna el snapshot clinico en vivo:
      - Turno en atencion en sillon.
      - Turno llamando a sala de espera.
      - Siguiente turno con detalle del servicio (preparacion de instrumental).
      - Cola de espera consolidada.
      - Alertas activas de triage de urgencia medica.
    """
    return obtener_estado_operacion_actual(fecha_referencia=fecha, repo=repo)


# ==============================================================================
# MAQUINA DE ESTADOS Y CONTROL DE TURNOS
# ==============================================================================

@router.patch(
    "/turnos/{turno_id}/estado",
    response_model=TurnoResponse,
    summary="Transicionar estado clinico de un turno",
)
def actualizar_estado_turno(
    turno_id: UUID,
    peticion: TurnoEstadoUpdateRequest,
    background_tasks: BackgroundTasks,
    forzar_sin_espera: bool = Query(
        default=False,
        description="Omitir ventana de espera de 15 min (exclusivo para DOCTOR y ADMIN)",
    ),
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> TurnoResponse:
    """
    Ejecuta una transicion de estado respetando el grafo estricto del dominio clinico.

    Garantia Operativa:
      - Al completar o cancelar un turno, ningun otro turno es promovido automaticamente.
      - El doctor y la asistente conservan el control humano para llamar al siguiente paciente.
      - La omision de la ventana de espera de 15 min solo es permitida para roles DOCTOR y ADMIN.
      - Si el turno es cancelado por ausencia, se dispara notificacion saliente en segundo plano.
    """
    forzar_permitido = False
    if forzar_sin_espera:
        if current_staff.rol not in (RolStaff.DOCTOR, RolStaff.ADMIN):
            raise DomainError(
                code=CodigoError.UNAUTHORIZED_ACCESS,
                message="Solo el doctor o administrador pueden forzar la transicion omitiendo la ventana de espera.",
                status_code=403,
            )
        forzar_permitido = True

    turno_actualizado = cambiar_estado_turno(
        turno_id=turno_id,
        peticion=peticion,
        forzar_sin_espera=forzar_permitido,
        repo=repo,
    )

    if turno_actualizado.estado == EstadoTurno.CANCELADO_AUSENTE:
        background_tasks.add_task(notificar_cancelacion_ausente_whatsapp, turno_actualizado)

    return turno_actualizado


# ==============================================================================
# CONTINGENCIA Y RETRASO MASIVO (ANTI-GIST 23P01)
# ==============================================================================

@router.post(
    "/retraso",
    response_model=RetrasoMasivoResponse,
    summary="Aplicar desplazamiento masivo por retraso clinico",
)
def registrar_retraso_masivo(
    peticion: RetrasoMasivoRequest,
    background_tasks: BackgroundTasks,
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> RetrasoMasivoResponse:
    """
    Desplaza en bloque las citas pendientes del dia ante una complicacion quirurgica.
    Ejecuta las mutaciones en orden cronologico inverso para evitar auto-colisiones GiST 23P01
    y encola notificaciones salientes de WhatsApp a los pacientes afectados.
    """
    resultado = aplicar_retraso_masivo(peticion=peticion, repo=repo)

    if resultado.turnos_afectados:
        background_tasks.add_task(
            notificar_retraso_masivo_whatsapp,
            resultado.turnos_afectados,
            resultado.minutos_aplicados,
        )

    return resultado


# ==============================================================================
# RESOLUCION DE TRIAGE MEDICO DE URGENCIA
# ==============================================================================

@router.post(
    "/triage/{paciente_id}/resolver",
    response_model=PacienteResponse,
    summary="Resolver alerta de triage y atencion medica humana",
)
def resolver_triage(
    paciente_id: UUID,
    peticion: TriageResolverRequest | None = None,
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> PacienteResponse:
    """
    Marca como resuelta la alerta medica del paciente una vez coordinada su atencion.
    Limpia la bandera de atencion prioritaria humana en el registro clinico.
    """
    return resolver_triage_paciente(paciente_id=paciente_id, peticion=peticion, repo=repo)


# ==============================================================================
# GESTION DE FESTIVOS Y BLOQUEOS EXTRAORDINARIOS
# ==============================================================================

@router.get(
    "/festivos",
    response_model=list[FestivoBloqueoResponse],
    summary="Listar festivos y bloqueos extraordinarios de agenda",
)
def listar_festivos(
    anio: int = Query(default=2026, ge=2020, le=2050, description="Ano de consulta"),
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR, RolStaff.RECEPCION)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> list[FestivoBloqueoResponse]:
    """Retorna los dias no laborables registrados en base de datos para el ano consultado."""
    fecha_inicio = date(anio, 1, 1)
    fecha_fin = date(anio, 12, 31)
    return repo.list_festivos_rango(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)


@router.post(
    "/festivos",
    response_model=FestivoBloqueoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nuevo bloqueo extraordinario de agenda",
)
def crear_festivo_bloqueo(
    datos: FestivoBloqueoCreate,
    current_staff: StaffUserResponse = Depends(
        require_roles(RolStaff.ADMIN, RolStaff.DOCTOR)
    ),
    repo: ClinicRepository = Depends(get_repository),
) -> FestivoBloqueoResponse:
    """
    Registra una fecha de cierre no laborable extraordinaria en el consultorio.
    Acceso restringido exclusivamente a roles DOCTOR y ADMIN.
    """
    return repo.create_festivo_bloqueo(data=datos)
