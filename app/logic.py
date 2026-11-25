"""
Motor determinista de logica clinica, concurrencia y operacion de Lujo Luminoso.

Implementa las politicas inmutables del consultorio:
  - Horario quebrado (07:00-12:00 y 13:00-17:00) y bloqueo estricto del almuerzo (12:00-13:00).
  - Bloqueo de fines de semana y festivos oficiales de Colombia via holidays y festivos_bloqueos.
  - Calculo de disponibilidad cada 15 min y busqueda de alternativas reales ante colisiones.
  - Maquina de estados con ventana de gracia de 15 min para ausentismo (No-Show).
  - Desplazamiento masivo por retrasos clinicos en orden cronologico inverso (anti-23P01).
  - Gestion en vivo del panel del doctor, triage de urgencias y sala de espera.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import holidays

from app.constants import (
    AFTERNOON_END,
    AFTERNOON_START,
    DEFAULT_TIMEZONE,
    DIAS_LABORALES,
    DURACION_SERVICIOS_MIN,
    ESTADOS_BLOQUEANTES,
    HOLIDAYS_COUNTRY,
    LUNCH_END,
    LUNCH_START,
    MINUTOS_RETRASO_VALIDOS,
    MORNING_END,
    MORNING_START,
    NO_SHOW_GRACE_MINUTES,
    NOMBRES_SERVICIOS,
    TRANSICIONES_VALIDAS,
    CodigoError,
    EstadoTurno,
    TipoServicio,
)
from app.database import ClinicRepository, get_repository
from app.exceptions import (
    ActiveAppointmentExistsError,
    DomainError,
    GracePeriodNotElapsedError,
    HolidayOrWeekendError,
    InvalidStateTransitionError,
    LunchBreakConflictError,
    OutsideWorkingHoursError,
    SlotTakenError,
)
from app.schemas import (
    BloqueHorario,
    DisponibilidadResponse,
    EstadoOperacionActualResponse,
    PacienteCreate,
    PacienteResponse,
    RetrasoMasivoRequest,
    RetrasoMasivoResponse,
    TriageResolverRequest,
    TurnoCreateRequest,
    TurnoDBInsert,
    TurnoEstadoUpdateRequest,
    TurnoPantallaTVResponse,
    TurnoResponse,
)

logger = logging.getLogger("app.logic")

# Zona horaria inmutable de operacion clinica
BOGOTA_TZ = ZoneInfo(DEFAULT_TIMEZONE)


# ==============================================================================
# PASO 1: UTILIDADES DE ZONA HORARIA Y CALENDARIO COLOMBIANO
# ==============================================================================

def now_colombia() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria America/Bogota."""
    return datetime.now(BOGOTA_TZ)


def combinar_fecha_hora_colombia(fecha: date, hora: time) -> datetime:
    """Combina fecha y hora produciendo un datetime consciente en America/Bogota."""
    return datetime.combine(fecha, hora, tzinfo=BOGOTA_TZ)


# ==============================================================================
# PASO 2: VALIDACION DE DIA HABIL Y FESTIVOS
# ==============================================================================

def validar_dia_habil(fecha: date, repo: ClinicRepository | None = None) -> None:
    """
    Verifica que la fecha corresponda a un dia habil de atencion.

    Lanza:
      - HolidayOrWeekendError si es sabado o domingo.
      - HolidayOrWeekendError si es festivo oficial en Colombia (paquete holidays).
      - HolidayOrWeekendError si la fecha esta expresamente bloqueada en base de datos.
    """
    # 1. Validar que sea de lunes a viernes (indices 0 a 4)
    if fecha.weekday() not in DIAS_LABORALES:
        raise HolidayOrWeekendError(
            message="La clinica solo atiende de lunes a viernes (fines de semana cerrados)."
        )

    # 2. Validar festivos oficiales en Colombia
    co_holidays = holidays.country_holidays(HOLIDAYS_COUNTRY, years=fecha.year)
    if fecha in co_holidays:
        nombre_festivo = co_holidays.get(fecha, "Festivo Oficial")
        raise HolidayOrWeekendError(
            message=f"No hay atencion clinica por festivo oficial en Colombia ({nombre_festivo})."
        )

    # 3. Validar bloqueos registrados en la base de datos
    try:
        repositorio = repo or get_repository()
        bloqueado, motivo = repositorio.is_fecha_bloqueada(fecha)
        if bloqueado:
            raise HolidayOrWeekendError(
                message=f"La agenda clinica se encuentra bloqueada en esta fecha ({motivo or 'Cierre programado'})."
            )
    except HolidayOrWeekendError:
        raise
    except Exception as exc:
        logger.warning("No fue posible consultar festivos_bloqueos en BD para %s: %s", fecha, str(exc))


# ==============================================================================
# PASO 3: VALIDACION MATEMATICA DE HORARIO QUEBRADO Y ALMUERZO
# ==============================================================================

def validar_horario_servicio(
    fecha: date,
    hora_inicio: time,
    servicio: TipoServicio,
) -> tuple[datetime, datetime, int]:
    """
    Valida rigurosamente que el procedimiento se ajuste a la jornada clinica.

    Regla matematica: hora_fin = hora_inicio + duracion_servicio

    Restricciones inmutables:
      - Mañana: [07:00, 12:00]
      - Receso de almuerzo estrictamente cerrado: [12:00, 13:00)
      - Tarde: [13:00, 17:00]
      - Ninguna cita puede iniciar, terminar o cruzar el intervalo de almuerzo.
      - Todo procedimiento debe caber de forma continua dentro de la manana o dentro de la tarde.

    Retorna:
      (dt_inicio, dt_fin, duracion_min)
    """
    duracion_min = DURACION_SERVICIOS_MIN[servicio]
    dt_inicio = combinar_fecha_hora_colombia(fecha, hora_inicio)
    dt_fin = dt_inicio + timedelta(minutes=duracion_min)

    # Asegurar que el procedimiento no cruce al dia siguiente
    if dt_fin.date() != fecha:
        raise OutsideWorkingHoursError(
            message="El procedimiento no puede finalizar fuera del mismo dia calendario."
        )

    # Limites formales del dia en America/Bogota
    dt_morning_start = combinar_fecha_hora_colombia(fecha, MORNING_START)      # 07:00
    dt_morning_end = combinar_fecha_hora_colombia(fecha, MORNING_END)          # 12:00
    dt_lunch_start = combinar_fecha_hora_colombia(fecha, LUNCH_START)          # 12:00
    dt_lunch_end = combinar_fecha_hora_colombia(fecha, LUNCH_END)              # 13:00
    dt_afternoon_start = combinar_fecha_hora_colombia(fecha, AFTERNOON_START)  # 13:00
    dt_afternoon_end = combinar_fecha_hora_colombia(fecha, AFTERNOON_END)      # 17:00

    # 1. Bloqueo si la hora de inicio cae dentro del receso de almuerzo
    if hora_inicio >= LUNCH_START and hora_inicio < LUNCH_END:
        raise LunchBreakConflictError(
            message="No se pueden agendar citas durante el receso obligatorio de almuerzo (12:00-13:00)."
        )

    # 2. Bloqueo si la cita inicia antes de apertura (07:00) o finaliza despues de cierre (17:00)
    if dt_inicio < dt_morning_start or dt_fin > dt_afternoon_end:
        raise OutsideWorkingHoursError(
            message="El horario solicitado esta fuera de la jornada de atencion (07:00-12:00 o 13:00-17:00)."
        )

    # 3. Bloqueo si el intervalo semiabierto [dt_inicio, dt_fin) solapa con [12:00, 13:00)
    # Solapamiento semiabierto: max(inicio1, inicio2) < min(fin1, fin2)
    if max(dt_inicio, dt_lunch_start) < min(dt_fin, dt_lunch_end):
        raise LunchBreakConflictError(
            message="El procedimiento colisiona con el receso de almuerzo (12:00-13:00) y excede el cierre matutino."
        )

    # 4. Verificacion de pertenencia integra a jornada continua
    en_manana = (dt_inicio >= dt_morning_start and dt_fin <= dt_morning_end)
    en_tarde = (dt_inicio >= dt_afternoon_start and dt_fin <= dt_afternoon_end)

    if not (en_manana or en_tarde):
        if dt_inicio < dt_morning_end and dt_fin > dt_morning_end:
            raise LunchBreakConflictError(
                message="El procedimiento excede las 12:00 invadiendo el receso de almuerzo."
            )
        raise OutsideWorkingHoursError(
            message="El procedimiento no cabe dentro de una jornada clinica continua sin interrupciones."
        )

    return dt_inicio, dt_fin, duracion_min


# ==============================================================================
# PASO 4: MOTOR DE DISPONIBILIDAD Y BUSQUEDA DE ALTERNATIVAS
# ==============================================================================

def calcular_disponibilidad(
    fecha: date,
    servicio: TipoServicio,
    repo: ClinicRepository | None = None,
) -> DisponibilidadResponse:
    """
    Calcula los bloques horarios disponibles cada 15 minutos respetando:
      - Dias habiles y festivos.
      - Horario quebrado y duracion del procedimiento.
      - Citas activas agendadas en la base de datos (exclusion semiabierta).
    """
    validar_dia_habil(fecha, repo)
    duracion_min = DURACION_SERVICIOS_MIN[servicio]

    repositorio = repo or get_repository()
    dt_dia_inicio = combinar_fecha_hora_colombia(fecha, time(0, 0))
    dt_dia_fin = combinar_fecha_hora_colombia(fecha, time(23, 59, 59))

    # Obtener turnos activos del dia
    try:
        turnos_activos = repositorio.list_turnos_rango(dt_dia_inicio, dt_dia_fin, solo_activos=True)
    except Exception as exc:
        logger.warning("No fue posible consultar turnos activos en base de datos: %s", str(exc))
        turnos_activos = []

    bloques_disponibles: list[BloqueHorario] = []

    # Generar candidatos en pasos de 15 minutos:
    # Bloque manana: 07:00 a 11:45
    # Bloque tarde:  13:00 a 16:45
    franjas_horas = [
        # Manana
        (7, 0), (7, 15), (7, 30), (7, 45),
        (8, 0), (8, 15), (8, 30), (8, 45),
        (9, 0), (9, 15), (9, 30), (9, 45),
        (10, 0), (10, 15), (10, 30), (10, 45),
        (11, 0), (11, 15), (11, 30), (11, 45),
        # Tarde
        (13, 0), (13, 15), (13, 30), (13, 45),
        (14, 0), (14, 15), (14, 30), (14, 45),
        (15, 0), (15, 15), (15, 30), (15, 45),
        (16, 0), (16, 15), (16, 30), (16, 45),
    ]

    for h, m in franjas_horas:
        hora_cand = time(h, m)
        try:
            dt_cand_inicio, dt_cand_fin, _ = validar_horario_servicio(fecha, hora_cand, servicio)
        except (LunchBreakConflictError, OutsideWorkingHoursError):
            # El bloque no cabe dentro de la jornada o invade el almuerzo
            continue

        # Verificar solapamiento con turnos activos existentes usando intervalo semiabierto '[)'
        # solapamiento = (cand_inicio < turno_fin) and (cand_fin > turno_inicio)
        colision = False
        for turno in turnos_activos:
            turno_inicio = turno.fecha_inicio.astimezone(BOGOTA_TZ)
            turno_fin = turno.fecha_fin.astimezone(BOGOTA_TZ)

            if dt_cand_inicio < turno_fin and dt_cand_fin > turno_inicio:
                colision = True
                break

        if not colision:
            bloques_disponibles.append(
                BloqueHorario(
                    hora_inicio=dt_cand_inicio.strftime("%H:%M"),
                    hora_fin=dt_cand_fin.strftime("%H:%M"),
                    fecha_inicio_iso=dt_cand_inicio,
                    fecha_fin_iso=dt_cand_fin,
                )
            )

    return DisponibilidadResponse(
        fecha=fecha,
        servicio=servicio,
        nombre_servicio=NOMBRES_SERVICIOS[servicio],
        duracion_min=duracion_min,
        bloques_disponibles=bloques_disponibles,
    )


def obtener_alternativas_cercanas(
    fecha: date,
    servicio: TipoServicio,
    hora_deseada: time,
    max_alternativas: int = 4,
    repo: ClinicRepository | None = None,
) -> list[str]:
    """
    Retorna los horarios disponibles mas cercanos a la hora solicitada cuando
    ocurre una colision horaria.
    """
    try:
        disp = calcular_disponibilidad(fecha, servicio, repo)
        if not disp.bloques_disponibles:
            return []

        minutos_deseados = hora_deseada.hour * 60 + hora_deseada.minute

        def distancia_en_minutos(b: BloqueHorario) -> int:
            partes = b.hora_inicio.split(":")
            mins = int(partes[0]) * 60 + int(partes[1])
            return abs(mins - minutos_deseados)

        ordenados = sorted(disp.bloques_disponibles, key=distancia_en_minutos)
        return [b.hora_inicio for b in ordenados[:max_alternativas]]
    except Exception as exc:
        logger.warning("No fue posible calcular alternativas cercanas: %s", str(exc))
        return []


# ==============================================================================
# PASO 5: AGENDAMIENTO TRANSACCIONAL CON ENRIQUECIMIENTO DE slot_taken
# ==============================================================================

def procesar_nuevo_turno(
    datos: TurnoCreateRequest,
    repo: ClinicRepository | None = None,
) -> TurnoResponse:
    """
    Coordina el ciclo de reserva clinica con blindaje de negocio y concurrencia.

    Flujo:
      1. Valida dia habil y festivos.
      2. Valida matematicamente horario quebrado y duracion.
      3. Registra o actualiza ficha del paciente (upsert).
      4. Verifica politica de maximo 1 cita activa por paciente.
      5. Genera codigo consecutivo de sala (ej. T-01).
      6. Inserta turno. Si ocurre colision (SlotTakenError o 23P01), enriquece
         la excepcion con alternativas reales calculadas al instante.
    """
    repositorio = repo or get_repository()

    # 1. Validar dia habil
    validar_dia_habil(datos.fecha, repositorio)

    # 2. Validar horario quebrado y duracion
    dt_inicio, dt_fin, duracion_min = validar_horario_servicio(
        datos.fecha,
        datos.hora_inicio,
        datos.servicio,
    )

    # 3. Registrar o actualizar paciente
    paciente = repositorio.upsert_paciente(
        PacienteCreate(
            telefono=datos.telefono,
            nombre=datos.nombre_paciente,
            email=datos.email_paciente,
        )
    )

    # 4. Validar que no tenga ya un turno activo en el consultorio
    turno_activo = repositorio.get_turno_activo_by_paciente(paciente.id)
    if turno_activo:
        fecha_str = turno_activo.fecha_inicio.astimezone(BOGOTA_TZ).strftime("%Y-%m-%d a las %H:%M")
        raise ActiveAppointmentExistsError(
            message=f"El paciente ya posee una cita activa ({NOMBRES_SERVICIOS.get(turno_activo.servicio, turno_activo.servicio)} para el {fecha_str})."
        )

    # 5. Calcular consecutivo diario para pantalla TV
    dt_dia_inicio = combinar_fecha_hora_colombia(datos.fecha, time(0, 0))
    dt_dia_fin = combinar_fecha_hora_colombia(datos.fecha, time(23, 59, 59))
    codigo_sala = repositorio.generar_siguiente_codigo_sala(dt_dia_inicio, dt_dia_fin)

    insert_data = TurnoDBInsert(
        codigo_sala=codigo_sala,
        paciente_id=paciente.id,
        servicio=datos.servicio,
        duracion_min=duracion_min,
        fecha_inicio=dt_inicio,
        fecha_fin=dt_fin,
        estado=EstadoTurno.CONFIRMADO,
        origen=datos.origen,
        notas_internas=datos.notas_internas,
    )

    # 6. Insertar en base de datos capturando colisiones GiST
    try:
        return repositorio.create_turno(insert_data)
    except SlotTakenError:
        alternativas = obtener_alternativas_cercanas(
            datos.fecha,
            datos.servicio,
            datos.hora_inicio,
            max_alternativas=4,
            repo=repositorio,
        )
        raise SlotTakenError(
            message="El horario solicitado ya se encuentra reservado por otra cita.",
            available_alternatives=alternativas,
        )


# ==============================================================================
# PASO 6: MAQUINA DE ESTADOS Y VENTANA DE 15 MINUTOS
# ==============================================================================

def cambiar_estado_turno(
    turno_id: UUID,
    peticion: TurnoEstadoUpdateRequest,
    forzar_sin_espera: bool = False,
    repo: ClinicRepository | None = None,
) -> TurnoResponse:
    """
    Ejecuta una transicion de estado validada en la maquina de estados clinica.

    Reglas especiales:
      - Al pasar a 'llamando': registra llamado_at con la hora actual en Bogota.
      - Al pasar a 'cancelado_ausente' desde 'llamando': exige que hayan transcurrido
        al menos 15 minutos desde el llamado (salvo override forzar_sin_espera).
    """
    repositorio = repo or get_repository()
    turno = repositorio.get_turno_by_id(turno_id)
    if not turno:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="El turno solicitado no fue encontrado en la agenda.",
            status_code=404,
        )

    # Validar transicion segun el grafo formal TRANSICIONES_VALIDAS
    transiciones_permitidas = TRANSICIONES_VALIDAS.get(turno.estado, frozenset())
    if peticion.nuevo_estado not in transiciones_permitidas:
        raise InvalidStateTransitionError(
            message=f"No se permite transicionar el turno de '{turno.estado.value}' a '{peticion.nuevo_estado.value}'."
        )

    llamado_at: datetime | None = None

    # Si se acciona el llamado al paciente
    if peticion.nuevo_estado == EstadoTurno.LLAMANDO:
        llamado_at = now_colombia()

    # Si se marca ausente tras ser llamado
    if (
        peticion.nuevo_estado == EstadoTurno.CANCELADO_AUSENTE
        and turno.estado == EstadoTurno.LLAMANDO
        and not forzar_sin_espera
    ):
        if not turno.llamado_at:
            raise GracePeriodNotElapsedError(
                message="No se ha registrado la marca temporal de llamado previo del paciente."
            )

        llamado_tz = turno.llamado_at.astimezone(BOGOTA_TZ)
        tiempo_transcurrido = now_colombia() - llamado_tz
        minutos_esperados = timedelta(minutes=NO_SHOW_GRACE_MINUTES)

        if tiempo_transcurrido < minutos_esperados:
            segundos_restantes = (minutos_esperados - tiempo_transcurrido).total_seconds()
            minutos_restantes = max(1, int(segundos_restantes // 60))
            raise GracePeriodNotElapsedError(
                message=f"No ha transcurrido la ventana de gracia de 15 minutos desde el llamado (restan aproximadamente {minutos_restantes} min)."
            )

    return repositorio.update_estado_turno(
        turno_id=turno_id,
        nuevo_estado=peticion.nuevo_estado,
        llamado_at=llamado_at,
        notas_internas=peticion.notas_internas,
    )


# ==============================================================================
# PASO 7: DESPLAZAMIENTO MASIVO POR RETRASO CLINICO (ORDEN INVERSO ANTI-GiST)
# ==============================================================================

def aplicar_retraso_masivo(
    peticion: RetrasoMasivoRequest,
    momento_actual: datetime | None = None,
    repo: ClinicRepository | None = None,
) -> RetrasoMasivoResponse:
    """
    Desplaza en cascada los turnos pendientes del dia cuando el doctor reporta un retraso.

    Blindaje de Concurrencia Crucial:
    Los turnos deben actualizarse en ORDEN CRONOLOGICO INVERSO (fecha_inicio descendente).
    De este modo, se mueve primero el turno mas tardio (ej. 15:00 a 15:30), liberando
    el bloque intermedio para que el turno contiguo anterior (ej. 14:30 a 15:00) pueda
    moverse sin disparar la violacion de exclusion GiST (error 23P01) en PostgreSQL.
    """
    repositorio = repo or get_repository()
    ahora = momento_actual or now_colombia()
    fecha_hoy = ahora.date()

    dt_inicio_dia = combinar_fecha_hora_colombia(fecha_hoy, time(0, 0))
    dt_fin_dia = combinar_fecha_hora_colombia(fecha_hoy, time(23, 59, 59))

    turnos_dia = repositorio.list_turnos_rango(dt_inicio_dia, dt_fin_dia, solo_activos=False)

    # Filtrar turnos pendientes que inicien desde el momento del retraso
    # (estados confirmado o en_sala)
    turnos_candidatos: list[TurnoResponse] = []
    for t in turnos_dia:
        if t.estado in (EstadoTurno.CONFIRMADO, EstadoTurno.EN_SALA):
            t_inicio = t.fecha_inicio.astimezone(BOGOTA_TZ)
            # Se consideran turnos a partir de la hora actual (con margen de 15 min de gracia)
            if t_inicio >= ahora - timedelta(minutes=15):
                turnos_candidatos.append(t)

    # Ordenamiento cronologico inverso OBLIGATORIO para evitar auto-colision GiST
    turnos_ordenados_inverso = sorted(
        turnos_candidatos,
        key=lambda t: t.fecha_inicio,
        reverse=True,
    )

    turnos_desplazados: list[TurnoResponse] = []
    delta_retraso = timedelta(minutes=peticion.minutos_retraso)

    for turno in turnos_ordenados_inverso:
        nueva_inicio = turno.fecha_inicio.astimezone(BOGOTA_TZ) + delta_retraso
        nueva_fin = turno.fecha_fin.astimezone(BOGOTA_TZ) + delta_retraso

        turno_actualizado = repositorio.update_horario_turno(
            turno_id=turno.id,
            nueva_fecha_inicio=nueva_inicio,
            nueva_fecha_fin=nueva_fin,
        )
        turnos_desplazados.append(turno_actualizado)

    # Ordenar cronologicamente ascendente para la respuesta en la interfaz
    turnos_vista = sorted(turnos_desplazados, key=lambda t: t.fecha_inicio)

    return RetrasoMasivoResponse(
        turnos_desplazados=len(turnos_vista),
        minutos_aplicados=peticion.minutos_retraso,
        turnos_afectados=turnos_vista,
    )


# ==============================================================================
# PASO 8: ESTADO OPERATIVO, TRIAGE Y ENFOQUE DEL DOCTOR
# ==============================================================================

def obtener_estado_operacion_actual(
    fecha_referencia: date | None = None,
    repo: ClinicRepository | None = None,
) -> EstadoOperacionActualResponse:
    """
    Genera el snapshot en vivo del consultorio para el Panel del Doctor y Recepcion.
    """
    repositorio = repo or get_repository()
    fecha = fecha_referencia or now_colombia().date()

    dt_inicio_dia = combinar_fecha_hora_colombia(fecha, time(0, 0))
    dt_fin_dia = combinar_fecha_hora_colombia(fecha, time(23, 59, 59))

    try:
        turnos_dia = repositorio.list_turnos_rango(dt_inicio_dia, dt_fin_dia, solo_activos=False)
    except Exception as exc:
        logger.warning("No fue posible consultar turnos para operacion actual: %s", str(exc))
        turnos_dia = []

    turnos_ordenados = sorted(turnos_dia, key=lambda t: t.fecha_inicio)

    turno_en_atencion: TurnoResponse | None = None
    turno_llamando: TurnoResponse | None = None
    siguiente_turno: TurnoResponse | None = None
    cola_espera: list[TurnoResponse] = []

    for t in turnos_ordenados:
        if t.estado == EstadoTurno.EN_ATENCION and turno_en_atencion is None:
            turno_en_atencion = t
        elif t.estado == EstadoTurno.LLAMANDO and turno_llamando is None:
            turno_llamando = t
        elif t.estado in (EstadoTurno.EN_SALA, EstadoTurno.CONFIRMADO):
            if siguiente_turno is None:
                siguiente_turno = t
            cola_espera.append(t)

    try:
        alertas_triage = repositorio.list_pacientes_con_triage_activo()
    except Exception as exc:
        logger.warning("No fue posible consultar alertas de triage: %s", str(exc))
        alertas_triage = []

    return EstadoOperacionActualResponse(
        turno_en_atencion=turno_en_atencion,
        turno_llamando=turno_llamando,
        siguiente_turno=siguiente_turno,
        cola_espera=cola_espera,
        alertas_triage=alertas_triage,
    )


def activar_triage_emergencia(
    telefono: str,
    motivo_urgencia: str,
    nombre_paciente: str | None = None,
    repo: ClinicRepository | None = None,
) -> PacienteResponse:
    """Registra una alerta medica de urgencia encendiendo requiere_atencion_humana."""
    repositorio = repo or get_repository()
    return repositorio.set_triage_emergencia(
        telefono=telefono,
        motivo_urgencia=motivo_urgencia,
        nombre_opcional=nombre_paciente,
    )


def resolver_triage_paciente(
    paciente_id: UUID,
    peticion: TriageResolverRequest | None = None,
    repo: ClinicRepository | None = None,
) -> PacienteResponse:
    """Limpia la bandera de urgencia tras coordinar la asistencia medica humana."""
    repositorio = repo or get_repository()
    return repositorio.resolver_triage_emergencia(paciente_id)


# ==============================================================================
# PASO 8: EXTENSIONES PARA PANTALLA TV Y GESTION HUMANA DEL PACIENTE (TAREA #6)
# ==============================================================================

def anonimizar_nombre_sala(nombre_completo: str) -> str:
    """
    Convierte un nombre completo en formato discreto para la pantalla TV en sala de espera.
    Ejemplo: 'Maria Fernanda Lopez' -> 'Maria L.', 'Valentina' -> 'Valentina'.
    """
    palabras = [p for p in nombre_completo.strip().split() if p]
    if len(palabras) <= 1:
        return nombre_completo.strip()
    primer_nombre = palabras[0]
    inicial_apellido = palabras[-1][0].upper()
    return f"{primer_nombre} {inicial_apellido}."


def obtener_turnos_pantalla_tv(
    fecha_referencia: date | None = None,
    repo: ClinicRepository | None = None,
) -> list[TurnoPantallaTVResponse]:
    """
    Obtiene los turnos activos del dia en orden cronologico para la Smart TV de sala de espera.
    Anonimiza el nombre del paciente y excluye por completo datos sensibles (PII).
    """
    repositorio = repo or get_repository()
    fecha = fecha_referencia or now_colombia().date()

    dt_inicio = combinar_fecha_hora_colombia(fecha, time(0, 0, 0))
    dt_fin = combinar_fecha_hora_colombia(fecha, time(23, 59, 59))

    try:
        turnos_activos = repositorio.list_turnos_rango(dt_inicio, dt_fin, solo_activos=True)
    except Exception as exc:
        logger.warning("No fue posible consultar turnos activos para pantalla TV: %s", str(exc))
        turnos_activos = []

    turnos_ordenados = sorted(turnos_activos, key=lambda t: t.fecha_inicio)

    pantalla_tv: list[TurnoPantallaTVResponse] = []
    for t in turnos_ordenados:
        nombre_raw = t.paciente.nombre if t.paciente and t.paciente.nombre else "Paciente"
        nombre_discreto = anonimizar_nombre_sala(nombre_raw)
        pantalla_tv.append(
            TurnoPantallaTVResponse(
                id=t.id,
                codigo_sala=t.codigo_sala,
                nombre_mostrar=nombre_discreto,
                estado=t.estado,
                llamado_at=t.llamado_at,
            )
        )

    return pantalla_tv


def cancelar_turno_activo_por_paciente(
    telefono: str,
    motivo: str | None = None,
    repo: ClinicRepository | None = None,
) -> TurnoResponse:
    """
    Cancela el turno activo de un paciente a solicitud de este via WhatsApp o canal web.

    Garantia clinica y de flujo:
      - El bloque horario se libera de inmediato en la base de datos (PostgreSQL GiST).
      - La fila se actualiza a 'cancelado_paciente' registrando el motivo en notas_internas.
      - Supabase Realtime emite el evento para alertar al doctor y a la recepcion.
      - JAMAS se promueve de forma automatica el siguiente turno: el equipo humano
        conserva el control absoluto para decidir cuando llamar al proximo paciente.
    """
    repositorio = repo or get_repository()
    paciente = repositorio.get_paciente_by_telefono(telefono)
    if not paciente:
        raise DomainError(
            code=CodigoError.APPOINTMENT_NOT_FOUND,
            message="No se encontro un paciente registrado con el numero de telefono provisto.",
            status_code=404,
        )

    turno_activo = repositorio.get_turno_activo_by_paciente(paciente.id)
    if not turno_activo:
        raise DomainError(
            code=CodigoError.APPOINTMENT_NOT_FOUND,
            message="El paciente no tiene ninguna cita medica activa pendiente de atencion.",
            status_code=404,
        )

    if turno_activo.estado == EstadoTurno.EN_ATENCION:
        raise DomainError(
            code=CodigoError.INVALID_STATE_TRANSITION,
            message="El turno ya se encuentra en atencion en el sillon clinico y no puede ser cancelado por esta via.",
            status_code=400,
        )

    motivo_texto = motivo.strip() if motivo and motivo.strip() else "Sin motivo especificado"
    nota_cancelacion = f"[CANCELADO POR PACIENTE]: {motivo_texto}"

    if turno_activo.notas_internas and turno_activo.notas_internas.strip():
        notas_actualizadas = f"{turno_activo.notas_internas.strip()} | {nota_cancelacion}"
    else:
        notas_actualizadas = nota_cancelacion

    turno_actualizado = repositorio.update_estado_turno(
        turno_id=turno_activo.id,
        nuevo_estado=EstadoTurno.CANCELADO_PACIENTE,
        notas_internas=notas_actualizadas,
    )
    logger.info(
        "Turno %s (paciente=%s) cancelado a peticion del paciente. Motivo: %s",
        turno_activo.id,
        paciente.telefono,
        motivo_texto,
    )
    return turno_actualizado


def registrar_aviso_asistencia_paciente(
    telefono: str,
    detalle_aviso: str,
    minutos_retraso_estimado: int | None = None,
    repo: ClinicRepository | None = None,
) -> TurnoResponse:
    """
    Registra una notificacion de retraso o aviso del paciente en las notas del turno en vivo.

    Reglas:
      - Si el retraso estimado supera la tolerancia maxima (15 min), se rechaza informando
        que debe reprogramarse para evitar afectar la calidad del procedimiento odontologico.
      - Si el retraso es tolerable o se trata de una confirmacion de camino, se anexa a notas_internas.
      - Se emite en tiempo real hacia la pantalla del doctor y recepcion sin alterar el orden de citas.
    """
    repositorio = repo or get_repository()
    paciente = repositorio.get_paciente_by_telefono(telefono)
    if not paciente:
        raise DomainError(
            code=CodigoError.APPOINTMENT_NOT_FOUND,
            message="No se encontro un paciente registrado con el numero provisto.",
            status_code=404,
        )

    turno_activo = repositorio.get_turno_activo_by_paciente(paciente.id)
    if not turno_activo or turno_activo.estado not in (EstadoTurno.CONFIRMADO, EstadoTurno.EN_SALA):
        raise DomainError(
            code=CodigoError.APPOINTMENT_NOT_FOUND,
            message="No se encontro un turno activo en espera o confirmado para asociar este aviso.",
            status_code=404,
        )

    if minutos_retraso_estimado is not None and minutos_retraso_estimado > NO_SHOW_GRACE_MINUTES:
        raise DomainError(
            code=CodigoError.OUTSIDE_WORKING_HOURS,
            message=(
                f"El retraso estimado ({minutos_retraso_estimado} min) supera la tolerancia maxima "
                f"de {NO_SHOW_GRACE_MINUTES} minutos de la clinica. Se recomienda cancelar o reagendar "
                f"la cita para no comprometer el tiempo quirurgico del tratamiento."
            ),
            status_code=400,
            details={
                "tolerancia_maxima_min": NO_SHOW_GRACE_MINUTES,
                "retraso_reportado_min": minutos_retraso_estimado,
            },
        )

    aviso_limpio = detalle_aviso.strip()
    if minutos_retraso_estimado is not None and minutos_retraso_estimado > 0:
        fragmento_aviso = f"[AVISO PACIENTE - DEMORA {minutos_retraso_estimado} MIN]: {aviso_limpio}"
    else:
        fragmento_aviso = f"[AVISO PACIENTE]: {aviso_limpio}"

    if turno_activo.notas_internas and turno_activo.notas_internas.strip():
        notas_actualizadas = f"{turno_activo.notas_internas.strip()} | {fragmento_aviso}"
    else:
        notas_actualizadas = fragmento_aviso

    turno_actualizado = repositorio.update_estado_turno(
        turno_id=turno_activo.id,
        nuevo_estado=turno_activo.estado,
        notas_internas=notas_actualizadas,
    )
    logger.info(
        "Aviso de paciente registrado en turno %s: %s",
        turno_activo.id,
        fragmento_aviso,
    )
    return turno_actualizado
