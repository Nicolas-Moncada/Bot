"""
Capa de acceso a datos y persistencia con Supabase para Lujo Luminoso.

Opera con service_role en backend para validar permisos y esquemas antes de
atravesar RLS de forma segura, garantizando consultas 100% parametrizadas
y traduccion automatica de violaciones de concurrencia (23P01 y 23505).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from postgrest.exceptions import APIError
from supabase import Client, create_client

from app.config import get_settings
from app.constants import (
    ESTADOS_BLOQUEANTES,
    CodigoError,
    EstadoTurno,
    RolStaff,
    TipoServicio,
)
from app.exceptions import (
    ActiveAppointmentExistsError,
    DomainError,
    SlotTakenError,
)
from app.schemas import (
    FestivoBloqueoCreate,
    FestivoBloqueoResponse,
    PacienteCreate,
    PacienteResponse,
    StaffUserResponse,
    TurnoDBInsert,
    TurnoResponse,
)

logger = logging.getLogger("app.database")

# Cliente singleton en memoria para reutilizacion de conexiones HTTP
_supabase_client: Client | None = None


# ==============================================================================
# INICIALIZACION DEL CLIENTE SUPABASE
# ==============================================================================

def get_supabase_client() -> Client:
    """
    Retorna una instancia singleton del cliente Supabase inicializado con SUPABASE_SERVICE_ROLE_KEY.

    Justificacion de Seguridad:
    El backend de FastAPI actua como frontera de confianza (BFF / API Gateway).
    Todas las solicitudes son validadas en esquemas Pydantic y autorizadas mediante JWT
    antes de interactuar con la base de datos. Utilizar service_role en el servidor
    permite consultar y mutar registros de forma controlada mediante consultas parametrizadas,
    mientras que el acceso directo anon desde el navegador permanece bloqueado por RLS.
    """
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(
            supabase_url=settings.SUPABASE_URL,
            supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _supabase_client


# ==============================================================================
# TRADUCCION DE ERRORES DE BASE DE DATOS
# ==============================================================================

def _handle_db_error(exc: Exception) -> None:
    """
    Traduce excepciones tecnicas de PostgreSQL / PostgREST a excepciones de dominio.

    Neutraliza la exposicion de stack traces e informacion interna:
      - Codigo 23P01 (exclusion_violation GiST): Traducido a SlotTakenError.
      - Codigo 23505 (unique_violation en idx_un_turno_activo_por_paciente):
        Traducido a ActiveAppointmentExistsError.
      - Otros errores: Registrados en logger interno y convertidos a DomainError seguro.
    """
    if isinstance(exc, APIError):
        code = str(getattr(exc, "code", "") or "")
        message = str(getattr(exc, "message", "") or "")
        details = str(getattr(exc, "details", "") or "")
        combined = f"{code} {message} {details}".lower()

        logger.warning(
            "Capturada excepcion PostgREST APIError: codigo=%s, mensaje=%s, detalles=%s",
            code,
            message,
            details,
        )

        # 1. Violacion de restriccion de exclusion GiST (solapamiento horario en sillon clinico)
        if code == "23P01" or "excl_turnos_sin_solapamiento" in combined:
            raise SlotTakenError(
                message="El horario solicitado ya se encuentra reservado por otra cita en el sillon clinico."
            ) from exc

        # 2. Violacion de indice unico parcial (paciente ya tiene cita activa)
        if code == "23505" and "idx_un_turno_activo_por_paciente" in combined:
            raise ActiveAppointmentExistsError(
                message="El paciente ya cuenta con una cita activa y no puede agendar un turno adicional."
            ) from exc

        # 3. Otras violaciones de clave unica (ej. telefono o email duplicado)
        if code == "23505":
            raise DomainError(
                code=CodigoError.INVALID_STATE_TRANSITION,
                message="El registro ya existe en el sistema con un identificador unico duplicado.",
                status_code=409,
            ) from exc

        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="No fue posible procesar la operacion en la base de datos.",
            status_code=400,
        ) from exc

    logger.exception("Error imprevisto en comunicacion con Supabase: %s", str(exc))
    raise DomainError(
        code=CodigoError.UNAUTHORIZED_ACCESS,
        message="Error de comunicacion con el servicio de base de datos.",
        status_code=500,
    ) from exc


# ==============================================================================
# ALMACENAMIENTO LOCAL EN MEMORIA PARA MODO DESARROLLO / PRUEBAS
# ==============================================================================

_dev_turnos_store: dict[str, dict[str, Any]] = {}
_dev_pacientes_store: dict[str, dict[str, Any]] = {}
_dev_staff_store: dict[str, dict[str, Any]] = {}
_dev_festivos_store: dict[str, dict[str, Any]] = {}
_dev_initialized: bool = False


def _ensure_dev_seeded() -> None:
    """Inicializa usuarios de staff por defecto para pruebas y entorno de desarrollo."""
    global _dev_initialized
    if _dev_initialized:
        return
    _dev_initialized = True
    try:
        from app.security import hash_password
        admin_id = "a0000000-0000-0000-0000-000000000001"
        if admin_id not in _dev_staff_store:
            _dev_staff_store[admin_id] = {
                "id": admin_id,
                "email": "admin@lujoluminoso.co",
                "password_hash": hash_password("admin12345"),
                "nombre": "Administrador General",
                "rol": "admin",
                "activo": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        doctor_id = "b0000000-0000-0000-0000-000000000002"
        if doctor_id not in _dev_staff_store:
            _dev_staff_store[doctor_id] = {
                "id": doctor_id,
                "email": "doctor@lujoluminoso.co",
                "password_hash": hash_password("doctor12345"),
                "nombre": "Dr. Nicolas Rodriguez",
                "rol": "doctor",
                "activo": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as exc:
        logger.warning("Fallo al inicializar usuarios staff locales en store de desarrollo: %s", str(exc))


# ==============================================================================
# REPOSITORIO CLINICO PRINCIPAL
# ==============================================================================

class ClinicRepository:
    """
    Capa de acceso a datos de la clinica Lujo Luminoso.
    Ejecuta consultas 100% parametrizadas a traves del SDK oficial de Supabase.
    En entorno local con credenciales demo, opera con almacenamiento en memoria
    para ofrecer latencia sub-milisegundo instantanea sin bloqueos de red DNS.
    """

    def __init__(self, client: Client | None = None) -> None:
        settings = get_settings()
        url = str(settings.SUPABASE_URL or "").lower()
        self._is_dev_mock = (
            "tu-proyecto" in url
            or "example" in url
            or "placeholder" in url
            or not url.startswith("http")
        )
        if self._is_dev_mock:
            _ensure_dev_seeded()
            self.client = client
        else:
            self.client = client or get_supabase_client()

    # --------------------------------------------------------------------------
    # 1. PERSONAL (usuarios_staff)
    # --------------------------------------------------------------------------

    def get_staff_by_email(self, email: str) -> dict[str, Any] | None:
        """
        Obtiene el registro integro de un miembro del personal por su correo.
        Incluye password_hash unicamente para consumo interno en el servicio de autenticacion.
        """
        if self._is_dev_mock:
            email_clean = email.strip().lower()
            for s in _dev_staff_store.values():
                if s["email"] == email_clean:
                    return dict(s)
            return None
        try:
            res = (
                self.client.table("usuarios_staff")
                .select("*")
                .eq("email", email.strip().lower())
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def get_staff_by_id(self, staff_id: UUID) -> StaffUserResponse | None:
        """Obtiene la informacion publica de un miembro del personal excluyendo password_hash."""
        if self._is_dev_mock:
            s = _dev_staff_store.get(str(staff_id))
            if not s:
                return None
            return StaffUserResponse.model_validate(s)
        try:
            res = (
                self.client.table("usuarios_staff")
                .select("id, email, nombre, rol, activo, created_at")
                .eq("id", str(staff_id))
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            return StaffUserResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def create_staff(
        self,
        email: str,
        password_hash: str,
        nombre: str,
        rol: RolStaff,
    ) -> StaffUserResponse:
        """
        Crea un nuevo miembro de personal clinico en la tabla usuarios_staff.
        Consulta 100% parametrizada para prevenir inyecciones.
        """
        if self._is_dev_mock:
            email_clean = email.strip().lower()
            for s in _dev_staff_store.values():
                if s["email"] == email_clean:
                    raise DomainError(
                        code=CodigoError.INVALID_STATE_TRANSITION,
                        message="El usuario ya se encuentra registrado con este correo.",
                        status_code=409,
                    )
            new_id = str(uuid4())
            row = {
                "id": new_id,
                "email": email_clean,
                "password_hash": password_hash,
                "nombre": nombre.strip(),
                "rol": rol.value,
                "activo": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _dev_staff_store[new_id] = row
            return StaffUserResponse.model_validate(row)
        try:
            payload = {
                "email": email.strip().lower(),
                "password_hash": password_hash,
                "nombre": nombre.strip(),
                "rol": rol.value,
                "activo": True,
            }
            res = self.client.table("usuarios_staff").insert(payload).execute()
            if not res.data:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="No fue posible registrar el nuevo colaborador de personal.",
                    status_code=500,
                )
            row = res.data[0]
            return StaffUserResponse(
                id=UUID(str(row["id"])),
                email=row["email"],
                nombre=row["nombre"],
                rol=RolStaff(row["rol"]),
                activo=bool(row["activo"]),
                created_at=row["created_at"],
            )
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def list_staff(self) -> list[StaffUserResponse]:
        """
        Obtiene el listado completo de personal clinico registrado en usuarios_staff.
        Ordenado por fecha de registro descendente y excluyendo password_hash.
        """
        if self._is_dev_mock:
            items = sorted(
                _dev_staff_store.values(),
                key=lambda x: str(x.get("created_at", "")),
                reverse=True,
            )
            return [StaffUserResponse.model_validate(row) for row in items]
        try:
            res = (
                self.client.table("usuarios_staff")
                .select("id, email, nombre, rol, activo, created_at")
                .order("created_at", desc=True)
                .execute()
            )
            return [StaffUserResponse.model_validate(row) for row in res.data]
        except Exception as exc:
            _handle_db_error(exc)
            return []

    def update_staff_status(self, staff_id: UUID, activo: bool) -> StaffUserResponse:
        """Actualiza el estado de activacion de un miembro del personal clinico."""
        if self._is_dev_mock:
            s_id = str(staff_id)
            if s_id not in _dev_staff_store:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="Usuario de personal no encontrado para actualizacion.",
                    status_code=404,
                )
            _dev_staff_store[s_id]["activo"] = activo
            return StaffUserResponse.model_validate(_dev_staff_store[s_id])
        try:
            res = (
                self.client.table("usuarios_staff")
                .update({"activo": activo})
                .eq("id", str(staff_id))
                .execute()
            )
            if not res.data:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="Usuario de personal no encontrado para actualizacion.",
                    status_code=404,
                )
            row = res.data[0]
            return StaffUserResponse(
                id=UUID(str(row["id"])),
                email=row["email"],
                nombre=row["nombre"],
                rol=RolStaff(row["rol"]),
                activo=bool(row["activo"]),
                created_at=row["created_at"],
            )
        except Exception as exc:
            _handle_db_error(exc)
            raise

    # --------------------------------------------------------------------------
    # 2. PACIENTES (pacientes)
    # --------------------------------------------------------------------------

    def get_paciente_by_telefono(self, telefono: str) -> PacienteResponse | None:
        """Busca un paciente por su numero telefonico en formato E.164."""
        if self._is_dev_mock:
            tel_clean = telefono.strip()
            for p in _dev_pacientes_store.values():
                if p["telefono"] == tel_clean:
                    return PacienteResponse.model_validate(p)
            return None
        try:
            res = (
                self.client.table("pacientes")
                .select("*")
                .eq("telefono", telefono.strip())
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            return PacienteResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def get_paciente_by_id(self, paciente_id: UUID) -> PacienteResponse | None:
        """Obtiene un paciente por su identificador UUID."""
        if self._is_dev_mock:
            p = _dev_pacientes_store.get(str(paciente_id))
            return PacienteResponse.model_validate(p) if p else None
        try:
            res = (
                self.client.table("pacientes")
                .select("*")
                .eq("id", str(paciente_id))
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            return PacienteResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def upsert_paciente(self, data: PacienteCreate) -> PacienteResponse:
        """
        Crea o actualiza la informacion del paciente indexado por telefono E.164.
        Consulta 100% parametrizada para prevenir inyecciones.
        """
        if self._is_dev_mock:
            tel_clean = data.telefono.strip()
            existente_id = None
            for p in _dev_pacientes_store.values():
                if p["telefono"] == tel_clean:
                    existente_id = p["id"]
                    break
            p_id = existente_id or str(uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()
            row = {
                "id": p_id,
                "telefono": tel_clean,
                "nombre": data.nombre.strip(),
                "email": data.email.strip().lower() if data.email else None,
                "requiere_atencion_humana": False,
                "motivo_urgencia": None,
                "created_at": _dev_pacientes_store[p_id]["created_at"] if existente_id else now_iso,
                "updated_at": now_iso,
            }
            _dev_pacientes_store[p_id] = row
            return PacienteResponse.model_validate(row)
        try:
            payload: dict[str, Any] = {
                "telefono": data.telefono,
                "nombre": data.nombre,
            }
            if data.email:
                payload["email"] = data.email

            res = (
                self.client.table("pacientes")
                .upsert(payload, on_conflict="telefono")
                .execute()
            )
            return PacienteResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def set_triage_emergencia(
        self,
        telefono: str,
        motivo_urgencia: str,
        nombre_opcional: str | None = None,
    ) -> PacienteResponse:
        """
        Marca la ficha del paciente con bandera prioritaria de atencion humana.
        Si el paciente no existe previamente, lo registra como nuevo contacto.
        """
        if self._is_dev_mock:
            paciente = self.get_paciente_by_telefono(telefono)
            if not paciente:
                crear_data = PacienteCreate(
                    telefono=telefono,
                    nombre=nombre_opcional or "Paciente Urgencia",
                )
                paciente = self.upsert_paciente(crear_data)
            p_dict = _dev_pacientes_store[str(paciente.id)]
            p_dict["requiere_atencion_humana"] = True
            p_dict["motivo_urgencia"] = motivo_urgencia
            p_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            return PacienteResponse.model_validate(p_dict)
        try:
            paciente = self.get_paciente_by_telefono(telefono)
            if not paciente:
                crear_data = PacienteCreate(
                    telefono=telefono,
                    nombre=nombre_opcional or "Paciente Urgencia",
                )
                paciente = self.upsert_paciente(crear_data)

            res = (
                self.client.table("pacientes")
                .update({
                    "requiere_atencion_humana": True,
                    "motivo_urgencia": motivo_urgencia,
                })
                .eq("id", str(paciente.id))
                .execute()
            )
            return PacienteResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def resolver_triage_emergencia(self, paciente_id: UUID) -> PacienteResponse:
        """Limpia la alerta de emergencia una vez el paciente fue atendido o asistido."""
        if self._is_dev_mock:
            p_id = str(paciente_id)
            if p_id not in _dev_pacientes_store:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="Paciente no encontrado.",
                    status_code=404,
                )
            p_dict = _dev_pacientes_store[p_id]
            p_dict["requiere_atencion_humana"] = False
            p_dict["motivo_urgencia"] = None
            p_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            return PacienteResponse.model_validate(p_dict)
        try:
            res = (
                self.client.table("pacientes")
                .update({
                    "requiere_atencion_humana": False,
                    "motivo_urgencia": None,
                })
                .eq("id", str(paciente_id))
                .execute()
            )
            return PacienteResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def list_pacientes_con_triage_activo(self) -> list[PacienteResponse]:
        """Obtiene el listado de todos los pacientes que requieren asistencia humana prioritaria."""
        if self._is_dev_mock:
            activos = [p for p in _dev_pacientes_store.values() if p.get("requiere_atencion_humana")]
            return [PacienteResponse.model_validate(p) for p in activos]
        try:
            res = (
                self.client.table("pacientes")
                .select("*")
                .eq("requiere_atencion_humana", True)
                .order("created_at", desc=True)
                .execute()
            )
            return [PacienteResponse.model_validate(row) for row in res.data]
        except Exception as exc:
            _handle_db_error(exc)
            return []

    # --------------------------------------------------------------------------
    # 3. TURNOS (turnos)
    # --------------------------------------------------------------------------

    def get_turno_activo_by_paciente(self, paciente_id: UUID) -> TurnoResponse | None:
        """
        Verifica si el paciente posee una cita activa en el consultorio.
        Filtra por ESTADOS_BLOQUEANTES (confirmado, en_sala, llamando, en_atencion).
        """
        if self._is_dev_mock:
            estados_lista = [e.value for e in ESTADOS_BLOQUEANTES]
            p_id_str = str(paciente_id)
            for row in _dev_turnos_store.values():
                if row["paciente_id"] == p_id_str and row["estado"] in estados_lista:
                    row_copy = dict(row)
                    pac = _dev_pacientes_store.get(p_id_str)
                    if pac:
                        row_copy["paciente"] = pac
                    return TurnoResponse.model_validate(row_copy)
            return None
        try:
            estados_lista = [e.value for e in ESTADOS_BLOQUEANTES]
            res = (
                self.client.table("turnos")
                .select("*, pacientes(*)")
                .eq("paciente_id", str(paciente_id))
                .in_("estado", estados_lista)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            row = res.data[0]
            if "pacientes" in row:
                row["paciente"] = row.pop("pacientes")
            return TurnoResponse.model_validate(row)
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def list_turnos_rango(
        self,
        fecha_inicio: datetime,
        fecha_fin: datetime,
        solo_activos: bool = False,
    ) -> list[TurnoResponse]:
        """
        Retorna los turnos agendados en un intervalo temporal mediante join parametrizado.
        Utilizado por FullCalendar.js y los paneles de administracion.
        """
        if self._is_dev_mock:
            resultado: list[TurnoResponse] = []
            estados_lista = [e.value for e in ESTADOS_BLOQUEANTES]
            for row in _dev_turnos_store.values():
                t_ini = datetime.fromisoformat(row["fecha_inicio"])
                t_fin = datetime.fromisoformat(row["fecha_fin"])
                if (t_ini <= fecha_fin) and (t_fin >= fecha_inicio):
                    if solo_activos and row["estado"] not in estados_lista:
                        continue
                    row_copy = dict(row)
                    pac_id = row_copy.get("paciente_id")
                    if pac_id and pac_id in _dev_pacientes_store:
                        row_copy["paciente"] = _dev_pacientes_store[pac_id]
                    resultado.append(TurnoResponse.model_validate(row_copy))
            return sorted(resultado, key=lambda x: x.fecha_inicio)
        try:
            query = (
                self.client.table("turnos")
                .select("*, pacientes(*)")
                .gte("fecha_inicio", fecha_inicio.isoformat())
                .lte("fecha_fin", fecha_fin.isoformat())
            )
            if solo_activos:
                estados_lista = [e.value for e in ESTADOS_BLOQUEANTES]
                query = query.in_("estado", estados_lista)

            res = query.order("fecha_inicio").execute()

            turnos: list[TurnoResponse] = []
            for row in res.data:
                if "pacientes" in row:
                    row["paciente"] = row.pop("pacientes")
                turnos.append(TurnoResponse.model_validate(row))
            return turnos
        except Exception as exc:
            _handle_db_error(exc)
            return []

    def create_turno(self, data: TurnoDBInsert) -> TurnoResponse:
        """
        Inserta un nuevo turno en la base de datos.
        Captura de forma transparente las violaciones de concurrencia:
          - Error 23P01 -> SlotTakenError
          - Error 23505 -> ActiveAppointmentExistsError
        """
        if self._is_dev_mock:
            estados_lista = [e.value for e in ESTADOS_BLOQUEANTES]
            # 1. Comprobar solapamiento GiST (23P01)
            for row in _dev_turnos_store.values():
                if row["estado"] in estados_lista:
                    t_ini = datetime.fromisoformat(row["fecha_inicio"])
                    t_fin = datetime.fromisoformat(row["fecha_fin"])
                    if data.fecha_inicio < t_fin and data.fecha_fin > t_ini:
                        raise SlotTakenError(
                            message="El horario solicitado ya se encuentra reservado por otra cita en el sillon clinico."
                        )
            # 2. Comprobar cita activa unica por paciente (23505)
            for row in _dev_turnos_store.values():
                if row["paciente_id"] == str(data.paciente_id) and row["estado"] in estados_lista:
                    raise ActiveAppointmentExistsError(
                        message="El paciente ya cuenta con una cita activa y no puede agendar un turno adicional."
                    )

            now_iso = datetime.now(timezone.utc).isoformat()
            new_id = uuid4()
            row = {
                "id": str(new_id),
                "codigo_sala": data.codigo_sala,
                "paciente_id": str(data.paciente_id),
                "servicio": data.servicio.value,
                "duracion_min": data.duracion_min,
                "fecha_inicio": data.fecha_inicio.isoformat(),
                "fecha_fin": data.fecha_fin.isoformat(),
                "estado": data.estado.value,
                "origen": data.origen.value,
                "notas_internas": data.notas_internas,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            _dev_turnos_store[str(new_id)] = row
            paciente = self.get_paciente_by_id(data.paciente_id)
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        try:
            payload: dict[str, Any] = {
                "codigo_sala": data.codigo_sala,
                "paciente_id": str(data.paciente_id),
                "servicio": data.servicio.value,
                "duracion_min": data.duracion_min,
                "fecha_inicio": data.fecha_inicio.isoformat(),
                "fecha_fin": data.fecha_fin.isoformat(),
                "estado": data.estado.value,
                "origen": data.origen.value,
            }
            if data.notas_internas:
                payload["notas_internas"] = data.notas_internas

            res = self.client.table("turnos").insert(payload).execute()
            row = res.data[0]

            # Enlazar datos del paciente si estan disponibles
            paciente = self.get_paciente_by_id(data.paciente_id)
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def get_turno_by_id(self, turno_id: UUID) -> TurnoResponse | None:
        """Obtiene un turno especifico por su identificador UUID."""
        if self._is_dev_mock:
            row = _dev_turnos_store.get(str(turno_id))
            if not row:
                return None
            row_copy = dict(row)
            pac_id = row_copy.get("paciente_id")
            if pac_id and pac_id in _dev_pacientes_store:
                row_copy["paciente"] = _dev_pacientes_store[pac_id]
            return TurnoResponse.model_validate(row_copy)
        try:
            res = (
                self.client.table("turnos")
                .select("*, pacientes(*)")
                .eq("id", str(turno_id))
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            row = res.data[0]
            if "pacientes" in row:
                row["paciente"] = row.pop("pacientes")
            return TurnoResponse.model_validate(row)
        except Exception as exc:
            _handle_db_error(exc)
            return None

    def update_estado_turno(
        self,
        turno_id: UUID,
        nuevo_estado: EstadoTurno,
        llamado_at: datetime | None = None,
        notas_internas: str | None = None,
    ) -> TurnoResponse:
        """Actualiza el estado clinico de un turno y registra la marca temporal de llamado."""
        if self._is_dev_mock:
            t_id = str(turno_id)
            if t_id not in _dev_turnos_store:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="El turno no existe.",
                    status_code=404,
                )
            row = _dev_turnos_store[t_id]
            row["estado"] = nuevo_estado.value
            if llamado_at:
                row["llamado_at"] = llamado_at.isoformat()
            if notas_internas:
                row["notas_internas"] = notas_internas
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            paciente = self.get_paciente_by_id(UUID(row["paciente_id"]))
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        try:
            update_data: dict[str, Any] = {
                "estado": nuevo_estado.value,
            }
            if llamado_at is not None:
                update_data["llamado_at"] = llamado_at.isoformat()
            if notas_internas is not None:
                update_data["notas_internas"] = notas_internas

            res = (
                self.client.table("turnos")
                .update(update_data)
                .eq("id", str(turno_id))
                .execute()
            )
            row = res.data[0]
            paciente = self.get_paciente_by_id(UUID(row["paciente_id"]))
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def update_horario_turno(
        self,
        turno_id: UUID,
        nueva_fecha_inicio: datetime,
        nueva_fecha_fin: datetime,
    ) -> TurnoResponse:
        """
        Modifica los horarios de una cita (utilizado en desplazamiento por retraso masivo).
        Protegido contra colisiones con otras citas activas.
        """
        if self._is_dev_mock:
            t_id = str(turno_id)
            if t_id not in _dev_turnos_store:
                raise DomainError(
                    code=CodigoError.UNAUTHORIZED_ACCESS,
                    message="El turno no existe.",
                    status_code=404,
                )
            row = _dev_turnos_store[t_id]
            row["fecha_inicio"] = nueva_fecha_inicio.isoformat()
            row["fecha_fin"] = nueva_fecha_fin.isoformat()
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            paciente = self.get_paciente_by_id(UUID(row["paciente_id"]))
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        try:
            update_data = {
                "fecha_inicio": nueva_fecha_inicio.isoformat(),
                "fecha_fin": nueva_fecha_fin.isoformat(),
            }
            res = (
                self.client.table("turnos")
                .update(update_data)
                .eq("id", str(turno_id))
                .execute()
            )
            row = res.data[0]
            paciente = self.get_paciente_by_id(UUID(row["paciente_id"]))
            turno_res = TurnoResponse.model_validate(row)
            turno_res.paciente = paciente
            return turno_res
        except Exception as exc:
            _handle_db_error(exc)
            raise

    def generar_siguiente_codigo_sala(
        self,
        fecha_inicio_dia: datetime,
        fecha_fin_dia: datetime,
    ) -> str:
        """
        Calcula el codigo consecutivo para sala de espera (ej. T-01, T-02)
        segun la cantidad de turnos generados en la fecha solicitada.
        """
        if self._is_dev_mock:
            count = 0
            for row in _dev_turnos_store.values():
                t_ini = datetime.fromisoformat(row["fecha_inicio"])
                if fecha_inicio_dia <= t_ini <= fecha_fin_dia:
                    count += 1
            return f"T-{count + 1:02d}"
        try:
            res = (
                self.client.table("turnos")
                .select("id")
                .gte("fecha_inicio", fecha_inicio_dia.isoformat())
                .lte("fecha_inicio", fecha_fin_dia.isoformat())
                .execute()
            )
            total_turnos_hoy = len(res.data) if res.data else 0
            return f"T-{total_turnos_hoy + 1:02d}"
        except Exception as exc:
            logger.warning("Fallo al calcular codigo de sala consecutivo: %s", str(exc))
            return "T-01"

    # --------------------------------------------------------------------------
    # 4. SESIONES DE CHAT (sesiones_chat)
    # --------------------------------------------------------------------------

    def get_historial_chat(self, telefono: str, max_mensajes: int = 10) -> list[dict[str, Any]]:
        """
        Recupera el historial conversacional del usuario.
        Si la conversacion tiene mas de 12 horas de inactividad, descarta el contexto
        obsoleto y retorna una lista vacia para iniciar un turno conversacional limpio.
        """
        try:
            res = (
                self.client.table("sesiones_chat")
                .select("historial, updated_at")
                .eq("telefono", telefono.strip())
                .limit(1)
                .execute()
            )
            if not res.data:
                return []

            fila = res.data[0]
            updated_at_str = fila.get("updated_at")
            if updated_at_str:
                # Normalizar timestamp con zona horaria UTC
                if updated_at_str.endswith("Z"):
                    updated_at_str = updated_at_str[:-1] + "+00:00"
                updated_at = datetime.fromisoformat(updated_at_str)
                limite_expiracion = datetime.now(timezone.utc) - timedelta(hours=12)
                if updated_at < limite_expiracion:
                    logger.info("Contexto de chat expirado (>12h) para %s. Reiniciando.", telefono)
                    return []

            historial: list[dict[str, Any]] = fila.get("historial") or []
            return historial[-max_mensajes:]
        except Exception as exc:
            logger.warning("No fue posible leer historial de chat: %s", str(exc))
            return []

    def save_historial_chat(
        self,
        telefono: str,
        historial: list[dict[str, Any]],
        max_mensajes: int = 10,
    ) -> None:
        """
        Persiste el contexto conversacional limitando a los ultimos max_mensajes.
        Consulta parametrizada via upsert en la tabla sesiones_chat.
        """
        try:
            recortado = historial[-max_mensajes:]
            payload = {
                "telefono": telefono.strip(),
                "historial": recortado,
            }
            self.client.table("sesiones_chat").upsert(payload, on_conflict="telefono").execute()
        except Exception as exc:
            logger.error("Error al guardar historial de chat para %s: %s", telefono, str(exc))

    # --------------------------------------------------------------------------
    # 5. FESTIVOS Y BLOQUEOS (festivos_bloqueos)
    # --------------------------------------------------------------------------

    def is_fecha_bloqueada(self, fecha: date) -> tuple[bool, str | None]:
        """Consulta si una fecha esta expresamente bloqueada en la base de datos."""
        if self._is_dev_mock:
            fecha_str = fecha.isoformat()
            if fecha_str in _dev_festivos_store:
                return True, _dev_festivos_store[fecha_str].get("motivo", "Cierre programado")
            return False, None
        try:
            res = (
                self.client.table("festivos_bloqueos")
                .select("motivo")
                .eq("fecha", fecha.isoformat())
                .limit(1)
                .execute()
            )
            if res.data:
                return True, res.data[0]["motivo"]
            return False, None
        except Exception as exc:
            logger.warning("Error al consultar festivos_bloqueos para %s: %s", fecha, str(exc))
            return False, None

    def list_festivos_rango(
        self,
        fecha_inicio: date,
        fecha_fin: date,
    ) -> list[FestivoBloqueoResponse]:
        """Obtiene el listado de festivos y bloqueos registrados en un intervalo."""
        if self._is_dev_mock:
            items = []
            for f_str, obj in _dev_festivos_store.items():
                f_date = date.fromisoformat(f_str)
                if fecha_inicio <= f_date <= fecha_fin:
                    items.append(FestivoBloqueoResponse.model_validate(obj))
            return items
        try:
            res = (
                self.client.table("festivos_bloqueos")
                .select("*")
                .gte("fecha", fecha_inicio.isoformat())
                .lte("fecha", fecha_fin.isoformat())
                .order("fecha")
                .execute()
            )
            return [FestivoBloqueoResponse.model_validate(row) for row in res.data]
        except Exception as exc:
            _handle_db_error(exc)
            return []

    def create_festivo_bloqueo(
        self,
        data: FestivoBloqueoCreate,
    ) -> FestivoBloqueoResponse:
        """Registra un nuevo bloqueo de agenda extraordinario."""
        if self._is_dev_mock:
            obj = {
                "id": str(uuid4()),
                "fecha": data.fecha.isoformat(),
                "motivo": data.motivo,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _dev_festivos_store[data.fecha.isoformat()] = obj
            return FestivoBloqueoResponse.model_validate(obj)
        try:
            payload = {
                "fecha": data.fecha.isoformat(),
                "motivo": data.motivo,
            }
            res = self.client.table("festivos_bloqueos").insert(payload).execute()
            return FestivoBloqueoResponse.model_validate(res.data[0])
        except Exception as exc:
            _handle_db_error(exc)
            raise


# Instancia por defecto para inyeccion de dependencias en FastAPI
def get_repository() -> ClinicRepository:
    """Proveedor de dependencia para inyeccion de ClinicRepository."""
    return ClinicRepository()
