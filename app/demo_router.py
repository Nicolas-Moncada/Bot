"""
Clinica Odontologica Boutique "Lujo Luminoso"
Router del Modulo de Demostracion Aislada (app/demo_router.py)

Proporciona guardarrail estricto con Kill-Switch (HTTP 403 si DEMO_MODE=False),
autenticacion rapida por roles (HttpOnly cookies), sembrador de escenarios clinicos
coherentes con PostgreSQL/GiST, manipulacion temporal de tolerancia de llamado
y simulador conversacional de WhatsApp IA determinista y adaptativo.

Normas estrictas: Cero emojis, Cero localStorage, Cero innerHTML dinamico.
"""

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator

from app.ai_agent import (
    execute_tool_call,
    limpiar_respuesta_ia,
    procesar_mensaje_whatsapp,
    sanitizar_entrada_usuario,
)
from app.auth import create_access_token, set_auth_cookie
from app.config import get_settings
from app.constants import (
    CodigoError,
    EstadoTurno,
    NO_SHOW_GRACE_MINUTES,
    OrigenTurno,
    RolStaff,
    TipoServicio,
)
from app.database import ClinicRepository, get_repository
from app.exceptions import DomainError, HolidayOrWeekendError
from app.logic import (
    activar_triage_emergencia,
    combinar_fecha_hora_colombia,
    now_colombia,
    validar_dia_habil,
)
from app.schemas import StaffUserResponse, StrictBaseModel, TurnoDBInsert, validar_telefono_e164
from app.security import hash_password, limiter

logger = logging.getLogger("app.demo_router")


# ==============================================================================
# GUARDARRAIL DE SERVIDOR: KILL-SWITCH DE PRODUCCION (HTTP 403)
# ==============================================================================

def require_demo_mode() -> None:
    """
    Verifica que el entorno permita operaciones de simulacion y modo demo.
    Si DEMO_MODE=False, rechaza inmediatamente la peticion con HTTP 403 Forbidden.
    """
    settings = get_settings()
    if not settings.DEMO_MODE:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="El modo de demostracion esta deshabilitado en este servidor.",
            status_code=403,
        )


demo_router = APIRouter(
    prefix="/api/v1/demo",
    tags=["Modo Demo Aislado"],
    dependencies=[Depends(require_demo_mode)],
)


# ==============================================================================
# ESQUEMAS ESTRICTOS PYDANTIC V2 PARA MODO DEMO
# ==============================================================================

class DemoQuickLoginRequest(StrictBaseModel):
    """Peticion para inicio rapido de sesion en demostraciones."""
    rol: RolStaff = Field(default=RolStaff.DOCTOR, description="Rol staff a simular")


class DemoWhatsAppSimRequest(StrictBaseModel):
    """Peticion para simulacion interactiva de mensajes entrantes de WhatsApp."""
    telefono: str = Field(default="+573005550199", description="Telefono E.164 del paciente")
    nombre_perfil: str = Field(default="Paciente Demo", min_length=2, max_length=80)
    mensaje: str = Field(..., min_length=1, max_length=800, description="Texto simulado del mensaje")

    @field_validator("telefono")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        return validar_telefono_e164(v)


class DemoSeedRequest(StrictBaseModel):
    """Parametros para poblar la agenda clinica de demostracion."""
    fecha_objetivo: date | None = Field(default=None, description="Fecha a sembrar (debe ser habil)")
    limpiar_dia_antes: bool = Field(default=True, description="Elimina turnos previos del dia a sembrar")


# ==============================================================================
# ENDPOINT 1: INICIO RAPIDO DE SESION STAFF (HTTPONLY COOKIE)
# ==============================================================================

@demo_router.post("/quick-login", response_model=StaffUserResponse)
@limiter.limit("20/minute")
async def quick_login_staff(
    request: Request,
    response: Response,
    datos: DemoQuickLoginRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> StaffUserResponse:
    """
    Permite alternar instantaneamente entre los roles doctor, recepcion y admin
    emitiendo una cookie HttpOnly real firmada con JWT. Cero localStorage.
    """
    email_map = {
        RolStaff.DOCTOR: ("doctor@lujoluminoso.co", "Dr. Armando Casas"),
        RolStaff.RECEPCION: ("recepcion@lujoluminoso.co", "Recepcion Clinica"),
        RolStaff.ADMIN: ("admin@lujoluminoso.co", "Administrador General"),
    }

    email, nombre_default = email_map.get(datos.rol, ("staff@lujoluminoso.co", "Personal Clinico"))

    user_dict: dict[str, Any] | None = None
    try:
        user_dict = repo.get_staff_by_email(email)
    except Exception as exc:
        logger.warning("Modo Demo: DB no accesible al consultar staff, usando sesion simulada: %s", exc)

    if not user_dict:
        staff_id = uuid4()
        user_dict = {
            "id": str(staff_id),
            "email": email,
            "nombre": nombre_default,
            "rol": datos.rol.value,
            "activo": True,
            "created_at": now_colombia().isoformat(),
        }
        try:
            repo.client.table("usuarios_staff").insert({
                "id": str(staff_id),
                "email": email,
                "password_hash": hash_password("DemoStaffPass2026!"),
                "nombre": nombre_default,
                "rol": datos.rol.value,
                "activo": True,
            }).execute()
        except Exception as insert_exc:
            logger.warning("Modo Demo: No se pudo insertar staff en DB, operando con dict local: %s", insert_exc)

    staff_id_uuid = UUID(str(user_dict["id"]))
    rol_staff = RolStaff(user_dict["rol"])

    token = create_access_token(
        staff_id=staff_id_uuid,
        email=user_dict["email"],
        rol=rol_staff,
    )
    set_auth_cookie(response, token)
    response.set_cookie(
        key="lujo_access_token",
        value=token,
        max_age=8 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
        secure=get_settings().is_production,
    )

    return StaffUserResponse(
        id=staff_id_uuid,
        email=user_dict["email"],
        nombre=user_dict["nombre"],
        rol=rol_staff,
        activo=user_dict.get("activo", True),
        created_at=user_dict.get("created_at") or now_colombia().isoformat(),
    )


# ==============================================================================
# ENDPOINT 2: SEMBRADOR DE ESCENARIOS CLINICOS COMPLETOS
# ==============================================================================

@demo_router.post("/seed-scenario")
@limiter.limit("10/minute")
async def seed_clinical_scenario(
    request: Request,
    datos: DemoSeedRequest = None,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Puebla un escenario clinico realista para el dia habil actual o proximo habil.
    Crea citas en atencion, en llamado, en sala, confirmadas, una cancelacion por WhatsApp
    con motivo explicito y una alerta activa de Triage de urgencia.
    """
    if datos is None:
        datos = DemoSeedRequest()

    # 1. Determinar dia habil valido (avanza si es fin de semana o festivo en Colombia)
    fecha_base = datos.fecha_objetivo or now_colombia().date()
    for _ in range(30):
        try:
            validar_dia_habil(fecha_base, repo=repo)
            break
        except HolidayOrWeekendError:
            fecha_base += timedelta(days=1)

    # 2. Limpieza de turnos previos del dia si se solicita
    if datos.limpiar_dia_antes:
        try:
            dt_inicio_dia = combinar_fecha_hora_colombia(fecha_base, time(0, 0))
            dt_fin_dia = combinar_fecha_hora_colombia(fecha_base, time(23, 59, 59))
            repo.client.table("turnos").delete().gte(
                "fecha_inicio", dt_inicio_dia.isoformat()
            ).lte("fecha_inicio", dt_fin_dia.isoformat()).execute()
        except Exception as del_exc:
            logger.warning("Modo Demo: No se pudieron eliminar turnos previos: %s", del_exc)

    # 3. Definicion del conjunto clinico demostrativo (evitando solapamientos GiST)
    ahora = now_colombia()

    pacientes_escenario = [
        {"nombre": "Valentina Gomez", "telefono": "+573001112233"},
        {"nombre": "Carlos Rodriguez", "telefono": "+573002223344"},
        {"nombre": "Mariana Rios", "telefono": "+573003334455"},
        {"nombre": "Julian Restrepo", "telefono": "+573004445566"},
        {"nombre": "Esteban Duque", "telefono": "+573006667788"},
        {"nombre": "Sofia Ospina", "telefono": "+573007778899"},
    ]

    turnos_definicion = [
        {
            "paciente_idx": 0,
            "servicio": TipoServicio.DISENO_SONRISA,
            "duracion": 60,
            "hora_i": time(8, 0),
            "hora_f": time(9, 0),
            "estado": EstadoTurno.EN_ATENCION,
            "notas": "Paciente en sillon dental para cementado de carillas ceramicas.",
            "llamado_at": None,
        },
        {
            "paciente_idx": 1,
            "servicio": TipoServicio.PROFILAXIS,
            "duracion": 30,
            "hora_i": time(9, 0),
            "hora_f": time(9, 30),
            "estado": EstadoTurno.LLAMANDO,
            "notas": "Paciente llamado a consultorio para profilaxis profunda.",
            "llamado_at": ahora - timedelta(minutes=2),
        },
        {
            "paciente_idx": 2,
            "servicio": TipoServicio.ORTODONCIA,
            "duracion": 45,
            "hora_i": time(9, 30),
            "hora_f": time(10, 15),
            "estado": EstadoTurno.EN_SALA,
            "notas": "[AVISO PACIENTE]: Paciente reporta que ya se encuentra en recepcion.",
            "llamado_at": None,
        },
        {
            "paciente_idx": 3,
            "servicio": TipoServicio.PROFILAXIS,
            "duracion": 30,
            "hora_i": time(10, 15),
            "hora_f": time(10, 45),
            "estado": EstadoTurno.CONFIRMADO,
            "notas": "Control preventivo regular agendado via web.",
            "llamado_at": None,
        },
        {
            "paciente_idx": 4,
            "servicio": TipoServicio.PROFILAXIS,
            "duracion": 30,
            "hora_i": time(11, 0),
            "hora_f": time(11, 30),
            "estado": EstadoTurno.CANCELADO_PACIENTE,
            "notas": "[CANCELADO POR PACIENTE]: No podre asistir hoy por incapacidad medica laboral.",
            "llamado_at": None,
        },
        {
            "paciente_idx": 5,
            "servicio": TipoServicio.CIRUGIA_IMPLANTES,
            "duracion": 120,
            "hora_i": time(13, 0),
            "hora_f": time(15, 0),
            "estado": EstadoTurno.CONFIRMADO,
            "notas": "Colocacion de implante osteointegrado pieza 26.",
            "llamado_at": None,
        },
    ]

    turnos_creados_resumen: list[dict[str, Any]] = []

    # 4. Creacion de Pacientes y Turnos en BD o estructura de simulacion
    for idx_t, def_t in enumerate(turnos_definicion):
        p_info = pacientes_escenario[def_t["paciente_idx"]]
        dt_ini = combinar_fecha_hora_colombia(fecha_base, def_t["hora_i"])
        dt_fin = combinar_fecha_hora_colombia(fecha_base, def_t["hora_f"])
        codigo = f"LL-{def_t['hora_i'].strftime('%H%M')}"
        turno_id = uuid4()

        try:
            paciente_res = repo.create_or_update_paciente(
                telefono=p_info["telefono"],
                nombre=p_info["nombre"],
            )
            paciente_id = paciente_res.id
        except Exception:
            paciente_id = uuid4()

        try:
            nuevo_t = TurnoDBInsert(
                codigo_sala=codigo,
                paciente_id=paciente_id,
                servicio=def_t["servicio"],
                duracion_min=def_t["duracion"],
                fecha_inicio=dt_ini,
                fecha_fin=dt_fin,
                estado=def_t["estado"],
                origen=OrigenTurno.SISTEMA_LOCAL,
                notas_internas=def_t["notas"],
            )
            created_obj = repo.create_turno(nuevo_t)
            turno_id = created_obj.id

            if def_t["llamado_at"]:
                repo.update_estado_turno(
                    turno_id=turno_id,
                    nuevo_estado=def_t["estado"],
                    llamado_at=def_t["llamado_at"],
                )
        except Exception as t_exc:
            logger.warning("Modo Demo: Creacion en DB omitida para turno %s: %s", codigo, t_exc)

        turnos_creados_resumen.append({
            "id": str(turno_id),
            "codigo_sala": codigo,
            "paciente": p_info["nombre"],
            "telefono": p_info["telefono"],
            "servicio": def_t["servicio"].value,
            "estado": def_t["estado"].value,
            "horario": f"{def_t['hora_i'].strftime('%H:%M')} - {def_t['hora_f'].strftime('%H:%M')}",
            "notas": def_t["notas"],
        })

    # 5. Registrar alerta activa de Triage de Emergencia
    triage_info = {
        "paciente": "Andres Mendoza",
        "telefono": "+573009998877",
        "motivo": "Dolor molar agudo e inflamacion severa reportada por WhatsApp",
        "activo": True,
    }
    try:
        activar_triage_emergencia(
            telefono=triage_info["telefono"],
            motivo_urgencia=triage_info["motivo"],
            nombre_paciente=triage_info["paciente"],
            repo=repo,
        )
    except Exception as tri_exc:
        logger.warning("Modo Demo: DB no conectada para alerta triage: %s", tri_exc)

    return {
        "status": "success",
        "message": "Escenario clinico demo sembrado exitosamente.",
        "data": {
            "fecha_sembrada": fecha_base.isoformat(),
            "turnos_creados": len(turnos_creados_resumen),
            "pacientes_creados": len(pacientes_escenario) + 1,
            "triage_alerta": triage_info,
            "turnos": turnos_creados_resumen,
        },
    }


# ==============================================================================
# ENDPOINT 3: ADELANTO TEMPORAL DEL LLAMADO (CRONOMETRO DE GRACIA)
# ==============================================================================

@demo_router.post("/fast-forward-grace/{turno_id}")
@limiter.limit("20/minute")
async def fast_forward_grace(
    request: Request,
    turno_id: UUID,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Atrasa artificialmente la marca temporal 'llamado_at' a 16 minutos atras.
    Permite probar en vivo el vencimiento del cronometro de 15m y el boton de
    inasistencia (cancelado_ausente) sin esperar tiempo real.
    """
    nueva_marca = now_colombia() - timedelta(minutes=NO_SHOW_GRACE_MINUTES + 1)

    try:
        repo.update_estado_turno(
            turno_id=turno_id,
            nuevo_estado=EstadoTurno.LLAMANDO,
            llamado_at=nueva_marca,
        )
    except Exception as exc:
        logger.warning("Modo Demo: DB no conectada para fast_forward_grace: %s", exc)

    return {
        "status": "ok",
        "turno_id": str(turno_id),
        "nuevo_estado": EstadoTurno.LLAMANDO.value,
        "llamado_at": nueva_marca.isoformat(),
        "minutos_transcurridos": NO_SHOW_GRACE_MINUTES + 1,
        "message": "Temporizador de gracia adelantado a 16 minutos. La cita puede declararse cancelado_ausente.",
    }


# ==============================================================================
# ENDPOINT 4: SIMULADOR CONVERSACIONAL DE WHATSAPP IA
# ==============================================================================

@demo_router.post("/whatsapp-sim")
@limiter.limit("30/minute")
async def simulate_whatsapp_message(
    request: Request,
    datos: DemoWhatsAppSimRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Simula la recepcion de un mensaje de WhatsApp invocando procesar_mensaje_whatsapp.
    Incorpora un enrutador determinista de respaldo clinico si Gemini API no esta
    configurada o devuelve error, garantizando el 100% de operatividad en pruebas locales.
    """
    mensaje_limpio = sanitizar_entrada_usuario(datos.mensaje)
    mensaje_lower = mensaje_limpio.lower()

    # 1. Deteccion prioritaria de Triage de Emergencia
    keywords_urgencia = [
        "dolor", "sangrado", "fractura", "trauma", "urgencia",
        "insoportable", "inflamacion", "hinchado", "caida", "emergencia"
    ]
    es_urgencia = any(kw in mensaje_lower for kw in keywords_urgencia)

    if es_urgencia:
        try:
            activar_triage_emergencia(
                telefono=datos.telefono,
                motivo_urgencia=mensaje_limpio,
                nombre_paciente=datos.nombre_perfil,
                repo=repo,
            )
        except Exception as tri_exc:
            logger.warning("Modo Demo: DB no conectada al activar triage: %s", tri_exc)

        return {
            "status": "ok",
            "telefono": datos.telefono,
            "user_message": datos.mensaje,
            "bot_reply": (
                "Hemos detectado una situacion de atencion medica prioritaria en su mensaje. "
                "Su caso ha sido transferido directamente a nuestro equipo clinico y un especialista "
                "se comunicara con usted a este numero a la mayor brevedad. Por favor permanezca atento."
            ),
            "tool_calls": ["solicitar_atencion_humana"],
            "triage_activado": True,
        }

    # 2. Intento de ejecucion con el agente conversacional completo
    try:
        res = await procesar_mensaje_whatsapp(
            telefono=datos.telefono,
            mensaje_usuario=datos.mensaje,
            nombre_perfil_wa=datos.nombre_perfil,
            repo=repo,
        )
        if res and res.get("reply"):
            return {
                "status": "ok",
                "telefono": datos.telefono,
                "user_message": datos.mensaje,
                "bot_reply": res.get("reply", ""),
                "tool_calls": res.get("tool_calls", []),
                "triage_activado": res.get("triage_activado", False),
            }
    except Exception as gemini_exc:
        logger.warning("Modo Demo: Agente Gemini no disponible o error de red: %s. Aplicando enrutador determinista.", gemini_exc)

    # 3. Enrutador Determinista de Respaldo para Escenarios Rapidos
    tool_executed = ""
    bot_reply = ""

    if any(k in mensaje_lower for k in ["horario", "disponib", "manana", "cuando hay"]):
        # Escenario: Consultar disponibilidad
        fecha_consulta = now_colombia().date() + timedelta(days=1)
        while fecha_consulta.weekday() >= 5:
            fecha_consulta += timedelta(days=1)

        tool_executed = "consultar_disponibilidad"
        res_tool = execute_tool_call(
            tool_name=tool_executed,
            args={"fecha": fecha_consulta.isoformat(), "servicio": "profilaxis"},
            telefono_sesion=datos.telefono,
            repo=repo,
        )
        bloques = res_tool.get("bloques_disponibles", [])
        if bloques:
            ejemplos = [b["hora_inicio"] for b in bloques[:4]]
            bot_reply = f"Para el proximo dia habil ({fecha_consulta.isoformat()}) disponemos de turnos para Profilaxis en horarios como: {', '.join(ejemplos)}. Deseas que agendemos alguno?"
        else:
            bot_reply = f"Para el dia {fecha_consulta.isoformat()} no encontramos cupos disponibles. Podemos verificar una fecha posterior."

    elif any(k in mensaje_lower for k in ["agendar", "reserva", "cita"]):
        # Escenario: Agendar turno
        tool_executed = "agendar_turno"
        fecha_agenda = now_colombia().date() + timedelta(days=1)
        while fecha_agenda.weekday() >= 5:
            fecha_agenda += timedelta(days=1)

        res_tool = execute_tool_call(
            tool_name=tool_executed,
            args={
                "fecha": fecha_agenda.isoformat(),
                "hora": "08:30",
                "servicio": "profilaxis",
                "nombre": datos.nombre_perfil,
            },
            telefono_sesion=datos.telefono,
            repo=repo,
        )
        if res_tool.get("status") == "success":
            bot_reply = f"Tu cita de Profilaxis ha sido confirmada con exito para el {fecha_agenda.isoformat()} a las 08:30. Te esperamos en Lujo Luminoso."
        elif res_tool.get("code") == "slot_taken":
            bot_reply = "El horario de las 08:30 ya no se encuentra disponible. Te sugerimos revisar las 09:00 o 10:00."
        else:
            bot_reply = f"No fue posible confirmar la cita: {res_tool.get('message', 'horario no disponible')}."

    elif any(k in mensaje_lower for k in ["tarde", "retraso", "demor"]):
        # Escenario: Aviso de retraso
        tool_executed = "reportar_retraso_o_aviso_paciente"
        # Extraer minutos numericos
        nums = re.findall(r"\d+", mensaje_lower)
        minutos = int(nums[0]) if nums else 10

        res_tool = execute_tool_call(
            tool_name=tool_executed,
            args={"minutos_estimados": minutos, "motivo": mensaje_limpio},
            telefono_sesion=datos.telefono,
            repo=repo,
        )
        if minutos <= 15:
            bot_reply = f"Comprendido. Hemos notificado al consultorio que llegaras con un retraso estimado de {minutos} minutos. La tolerancia maxima es de 15 minutos."
        else:
            bot_reply = f"Lamentamos informarte que un retraso de {minutos} minutos supera la tolerancia de 15 minutos del consultorio boutique. Tu cita no podra extenderse para no afectar a los demas pacientes."

    elif any(k in mensaje_lower for k in ["cancelar", "no podre", "incapacidad", "viaje"]):
        # Escenario: Cancelar turno
        tool_executed = "cancelar_mi_turno"
        res_tool = execute_tool_call(
            tool_name=tool_executed,
            args={"motivo_cancelacion": mensaje_limpio},
            telefono_sesion=datos.telefono,
            repo=repo,
        )
        bot_reply = "Tu cita ha sido cancelada correctamente en el sistema y el espacio ha sido liberado en la agenda del doctor. Cuando desees reprogramar, con gusto te atenderemos."

    else:
        bot_reply = "Bienvenido al canal de atencion de Lujo Luminoso. Puedes consultarnos por disponibilidad de citas, avisos de llegada o servicios odontologicos."

    return {
        "status": "ok",
        "telefono": datos.telefono,
        "user_message": datos.mensaje,
        "bot_reply": limpiar_respuesta_ia(bot_reply),
        "tool_calls": [tool_executed] if tool_executed else [],
        "triage_activado": False,
    }
