"""
Enrutador de Webhooks para Meta WhatsApp Cloud API.

Implementa verificacion criptografica de firma HMAC-SHA256 (X-Hub-Signature-256),
handshake de reto (hub.challenge), deduplicacion idempotente de wamid, limitador de tasa
por remitente, defensas contra archivos adjuntos no seguros y notificaciones clinicas salientes.
"""

import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.ai_agent import limpiar_respuesta_ia, procesar_mensaje_whatsapp
from app.config import get_settings
from app.constants import DEFAULT_TIMEZONE, NOMBRES_SERVICIOS
from app.database import ClinicRepository, get_repository
from app.exceptions import UnauthorizedAccessError
from app.logic import BOGOTA_TZ
from app.schemas import TurnoResponse, validar_telefono_e164
from app.security import limiter

logger = logging.getLogger("app.routers.whatsapp")

router = APIRouter(tags=["WhatsApp Cloud API"])


# ==============================================================================
# DEDUPLICADOR EN MEMORIA Y LIMITADOR POR NUMERO TELEFONICO
# ==============================================================================

class MessageDeduplicator:
    """
    Estructura LRU acotada en memoria para evitar el reprocesamiento de mensajes repetidos.
    Neutraliza los reintentos automaticos de Meta cuando las peticiones tardan mas de 3 segundos.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, message_id: str) -> bool:
        if not message_id:
            return False
        now = time.time()

        # Purgar si se supera el limite de capacidad
        if len(self.cache) >= self.max_size:
            self._purge_expired(now)
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)

        if message_id in self.cache:
            created_at = self.cache[message_id]
            if now - created_at < self.ttl_seconds:
                self.cache.move_to_end(message_id)
                return True
            else:
                del self.cache[message_id]

        self.cache[message_id] = now
        return False

    def _purge_expired(self, now: float) -> None:
        expired = [k for k, v in self.cache.items() if now - v >= self.ttl_seconds]
        for k in expired:
            del self.cache[k]


class PhoneRateLimiter:
    """
    Ventana deslizante en memoria para mitigar saturacion o abuso por numero individual.
    Previene ataques de denegacion de billetera (Denial of Wallet) contra la cuota de IA.
    """

    def __init__(self, max_per_minute: int = 12) -> None:
        self.max_per_minute = max_per_minute
        self.records: dict[str, list[float]] = {}

    def is_rate_limited(self, phone: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        timestamps = self.records.get(phone, [])
        valid = [t for t in timestamps if t > window_start]
        if len(valid) >= self.max_per_minute:
            self.records[phone] = valid
            return True
        valid.append(now)
        self.records[phone] = valid
        return False


deduplicator = MessageDeduplicator(max_size=1000, ttl_seconds=3600)
phone_rate_limiter = PhoneRateLimiter(max_per_minute=12)


# ==============================================================================
# VERIFICACION CRIPTOGRAFICA DE FIRMA HMAC-SHA256 (PUNTO #16 DE SEGURIDAD)
# ==============================================================================

def verify_whatsapp_signature(
    raw_body: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    """
    Verifica la cabecera X-Hub-Signature-256 calculando el hash HMAC-SHA256 sobre el cuerpo crudo.
    Aplica comparacion en tiempo constante para neutralizar ataques de temporizacion.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_hash = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    expected_sig = f"sha256={expected_hash}"
    return hmac.compare_digest(expected_sig, signature_header.strip())


# ==============================================================================
# CLIENTE HTTP ASINCRONO Y NOTIFICACIONES CLINICAS SALIENTES
# ==============================================================================

async def enviar_mensaje_whatsapp_texto(telefono: str, texto: str) -> bool:
    """
    Envia un mensaje de texto saliente al paciente a traves de Meta WhatsApp Cloud API.

    Garantias:
      - Sanitizacion previa con limpiar_respuesta_ia asegurando CERO emojis.
      - Simulacion transparente en entorno de desarrollo o con credenciales placeholder.
      - Peticion asincrona mediante httpx.AsyncClient sin bloquear el servidor.
    """
    settings = get_settings()
    texto_limpio = limpiar_respuesta_ia(texto)
    if not texto_limpio:
        return False

    token = settings.WHATSAPP_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID

    # Deteccion de credenciales de ejemplo o entorno local
    if (
        not token
        or token.startswith("tu_")
        or phone_id.startswith("10000000")
        or phone_id == "100000000000001"
    ):
        logger.info(
            "[WHATSAPP SIMULADO] Destino: %s | Mensaje: %s",
            telefono,
            texto_limpio,
        )
        return True

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    to_clean = telefono.replace("+", "").strip()
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_clean,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": texto_limpio,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error(
                    "Error de Meta Graph API al enviar a %s: status=%d, respuesta=%s",
                    telefono,
                    resp.status_code,
                    resp.text,
                )
                return False
            logger.info("Mensaje de WhatsApp entregado exitosamente a %s", telefono)
            return True
    except Exception as exc:
        logger.error("Fallo de comunicacion con Meta Graph API hacia %s: %s", telefono, str(exc))
        return False


async def notificar_cancelacion_ausente_whatsapp(turno: TurnoResponse) -> bool:
    """
    Notifica al paciente por WhatsApp cuando su turno es cancelado por inasistencia (No-Show)
    tras expirar los 15 minutos de espera posteriores al llamado en sala.
    """
    repo = get_repository()
    telefono = None
    nombre = "Paciente"

    if turno.paciente and turno.paciente.telefono:
        telefono = turno.paciente.telefono
        nombre = turno.paciente.nombre or "Paciente"
    elif turno.paciente_id:
        p = repo.get_paciente_by_id(turno.paciente_id)
        if p:
            telefono = p.telefono
            nombre = p.nombre or "Paciente"

    if not telefono:
        logger.warning("No fue posible notificar cancelacion ausente: turno %s no posee telefono", turno.id)
        return False

    nombre_servicio = NOMBRES_SERVICIOS.get(turno.servicio, str(turno.servicio.value))
    mensaje = (
        f"Estimado(a) {nombre}, le informamos desde la clinica Lujo Luminoso que, "
        f"tras haber transcurrido los 15 minutos de espera luego del llamado en sala para su cita de "
        f"{nombre_servicio}, su turno ha sido liberado para no afectar el resto de la jornada. "
        f"Si desea reagendar su cita para una nueva fecha u horario, puede escribirnos directamente por este chat."
    )

    return await enviar_mensaje_whatsapp_texto(telefono=telefono, texto=mensaje)


async def notificar_retraso_masivo_whatsapp(
    turnos_afectados: list[TurnoResponse],
    minutos_retraso: int,
) -> int:
    """
    Envia un aviso preventivo a cada paciente afectado por un desplazamiento de agenda en bloque.
    """
    repo = get_repository()
    notificados = 0

    for turno in turnos_afectados:
        telefono = None
        nombre = "Paciente"

        if turno.paciente and turno.paciente.telefono:
            telefono = turno.paciente.telefono
            nombre = turno.paciente.nombre or "Paciente"
        elif turno.paciente_id:
            p = repo.get_paciente_by_id(turno.paciente_id)
            if p:
                telefono = p.telefono
                nombre = p.nombre or "Paciente"

        if not telefono:
            continue

        nueva_hora = turno.fecha_inicio.astimezone(BOGOTA_TZ).strftime("%H:%M")
        nombre_servicio = NOMBRES_SERVICIOS.get(turno.servicio, str(turno.servicio.value))

        mensaje = (
            f"Estimado(a) {nombre}, le informamos desde la clinica Lujo Luminoso que debido a una "
            f"extension clinica en un procedimiento previo, la agenda presenta un ajuste de {minutos_retraso} minutos. "
            f"El nuevo horario estimado para su cita de {nombre_servicio} hoy es a las {nueva_hora}. "
            f"Si requiere reprogramar para otro dia sin costo, respondanos por este medio."
        )

        ok = await enviar_mensaje_whatsapp_texto(telefono=telefono, texto=mensaje)
        if ok:
            notificados += 1

    logger.info("Notificaciones de retraso masivo entregadas a %d pacientes", notificados)
    return notificados


# ==============================================================================
# ENDPOINTS DE WEBHOOK DE WHATSAPP (/webhook/whatsapp)
# ==============================================================================

@router.get("/webhook/whatsapp", response_class=PlainTextResponse)
def verificar_reto_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    """
    Atiende el handshake de verificacion de URL exigido por Meta Developers.
    Compara en tiempo constante el token secreto configurado en el servidor.
    """
    settings = get_settings()

    if (
        hub_mode == "subscribe"
        and hub_challenge
        and hmac.compare_digest(hub_verify_token or "", settings.WHATSAPP_VERIFY_TOKEN)
    ):
        logger.info("Handshake de Meta WhatsApp Cloud API verificado exitosamente.")
        return PlainTextResponse(content=str(hub_challenge), status_code=status.HTTP_200_OK)

    logger.warning(
        "Rechazo en handshake de Meta WhatsApp: modo=%s, token_coincide=%s",
        hub_mode,
        hmac.compare_digest(hub_verify_token or "", settings.WHATSAPP_VERIFY_TOKEN),
    )
    raise UnauthorizedAccessError("Token de verificacion de webhook invalido.")


@router.post("/webhook/whatsapp")
@limiter.limit("60/minute")
async def recibir_eventos_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Punto de recepcion de eventos entrantes de WhatsApp Cloud API.

    Controles de seguridad:
      1. Validacion de firma HMAC-SHA256 con WHATSAPP_APP_SECRET.
      2. Deduplicacion de message_id para neutralizar reintentos de Meta.
      3. Rate limiting por telefono para proteger la cuota de Gemini.
      4. Rechazo preventivo de binarios/multimedia sin almacenar archivos.
    """
    settings = get_settings()
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    # 1. Validacion criptografica estricta de firma HMAC-SHA256 (Punto #16)
    if not verify_whatsapp_signature(raw_body, signature_header, settings.WHATSAPP_APP_SECRET):
        logger.warning("Firma HMAC-SHA256 de WhatsApp ausente o invalida.")
        raise UnauthorizedAccessError("Firma criptografica X-Hub-Signature-256 invalida o ausente.")

    if len(raw_body) > 65536:
        return {"status": "error", "message": "Payload excede tamano maximo"}

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        logger.warning("Error al deserializar JSON de webhook WhatsApp: %s", str(exc))
        return {"status": "error", "message": "JSON malformado"}

    entries = data.get("entry", [])
    processed_count = 0
    duplicate_detected = False

    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # Si es solo actualizacion de estado (sent, delivered, read), no hay mensaje que responder
            if "statuses" in value and "messages" not in value:
                continue

            contacts = value.get("contacts", [])
            profile_name = None
            if contacts and isinstance(contacts, list) and len(contacts) > 0:
                profile_name = contacts[0].get("profile", {}).get("name")

            messages = value.get("messages", [])
            for msg in messages:
                msg_id = msg.get("id")

                # 2. Deduplicacion idempotente (anti-reintentos de Meta)
                if msg_id and deduplicator.is_duplicate(msg_id):
                    logger.info("Mensaje duplicado ignorado por wamid: %s", msg_id)
                    duplicate_detected = True
                    continue

                raw_from = str(msg.get("from", "")).strip()
                if not raw_from:
                    continue

                telefono_e164 = f"+{raw_from}" if not raw_from.startswith("+") else raw_from
                try:
                    telefono = validar_telefono_e164(telefono_e164)
                except Exception:
                    telefono = telefono_e164

                # 3. Limitador de tasa por telefono remitente
                if phone_rate_limiter.is_rate_limited(telefono):
                    logger.warning("Tasa de mensajes excedida para telefono %s", telefono)
                    continue

                msg_type = msg.get("type", "text")

                # 4. Defensa contra archivos no seguros (Punto #20 de Seguridad)
                if msg_type == "text":
                    user_text = msg.get("text", {}).get("body", "").strip()
                elif msg_type in ("interactive", "button"):
                    interactive = msg.get("interactive", {})
                    button_reply = interactive.get("button_reply", {})
                    list_reply = interactive.get("list_reply", {})
                    user_text = (
                        button_reply.get("title")
                        or list_reply.get("title")
                        or msg.get("button", {}).get("text", "")
                    )
                else:
                    # Multimedia o binarios: NO descargar ni ejecutar nada
                    logger.info("Mensaje multimedia '%s' recibido de %s. Enviando advertencia.", msg_type, telefono)
                    aviso_seguridad = (
                        "Por politicas de seguridad clinica, este canal automatizado solo procesa "
                        "mensajes de texto. Por favor escribanos su solicitud en texto para asistirle con su cita."
                    )
                    background_tasks.add_task(enviar_mensaje_whatsapp_texto, telefono, aviso_seguridad)
                    processed_count += 1
                    continue

                if not user_text:
                    continue

                # 5. Orquestacion con el agente conversacional de IA
                resultado = await procesar_mensaje_whatsapp(
                    telefono=telefono,
                    mensaje_usuario=user_text,
                    nombre_perfil_wa=profile_name,
                    repo=repo,
                )

                reply_text = resultado.get("reply", "")
                if reply_text:
                    background_tasks.add_task(enviar_mensaje_whatsapp_texto, telefono, reply_text)
                processed_count += 1

    if duplicate_detected and processed_count == 0:
        return {"status": "ignored", "reason": "duplicate_message"}

    return {"status": "ok", "processed": processed_count}
