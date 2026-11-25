"""
Modulo de autenticacion, captcha interactivo 'No soy un robot', cookies HttpOnly y RBAC en servidor.

Garantiza sesion exclusiva mediante cookies seguras (cero almacenamiento en localStorage),
defensa contra ataques de fuerza bruta con rate limiting, verificacion de captcha (codigo canvas y 3x3)
y registro y federacion de usuarios de pacientes y colaboradores staff.
"""

import logging
import random
import secrets
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import get_settings
from app.constants import CodigoError, RolStaff
from app.database import ClinicRepository, get_repository
from app.exceptions import DomainError, UnauthorizedAccessError
from app.schemas import (
    CaptchaVerifyRequest,
    GoogleAuthRequest,
    LoginRequest,
    PacienteCreate,
    RegisterRequest,
    StaffCreateRequest,
    StaffToggleRequest,
    StaffUserResponse,
)
from app.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DUMMY_PASSWORD_HASH,
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    limiter,
    validate_password_not_leaked,
    verify_password,
)

logger = logging.getLogger("app.auth")

# Nombre formal de la cookie de sesion segura HttpOnly
COOKIE_NAME: str = "access_token"

router = APIRouter(prefix="/api/v1/auth", tags=["Autenticacion"])

# Conjunto de caracteres legibles para captcha alfanumerico (sin caracteres ambiguos 0, O, 1, I)
CAPTCHA_CHAR_POOL: str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

# Bancos de imagenes en alta definicion para la cuadricula visual 3x3
CAPTCHA_CORRECT_ITEMS: list[dict[str, str]] = [
    {
        "label": "Sonrisa Estetica y Saludable",
        "image": "https://images.unsplash.com/photo-1588776814546-1ffcf47267a5?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Tratamiento de Carillas y Estetica",
        "image": "https://images.unsplash.com/photo-1606811841689-23dfddce3e95?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Alineacion y Cuidado Dental",
        "image": "https://images.unsplash.com/photo-1598256989800-fe5f95da9787?auto=format&fit=crop&w=300&q=80",
    },
]

CAPTCHA_DISTRACTOR_ITEMS: list[dict[str, str]] = [
    {
        "label": "Reloj de Precision",
        "image": "https://images.unsplash.com/photo-1508057198894-247b23fe5ade?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Edificio Arquitectonico",
        "image": "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Paisaje Natural Montanoso",
        "image": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Taza de Cafe Matutino",
        "image": "https://images.unsplash.com/photo-1544787219-7f47ccb76574?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Automovil de Diseno",
        "image": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=300&q=80",
    },
    {
        "label": "Planta Decorativa de Interior",
        "image": "https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=300&q=80",
    },
]


# ==============================================================================
# GESTION DE COOKIES HTTPONLY (PUNTO #10 DE SEGURIDAD)
# ==============================================================================

def set_auth_cookie(response: Response, token: str) -> None:
    """
    Inyecta el token JWT en una cookie HttpOnly con directivas de maxima seguridad.

    Parametros de blindaje:
      - httponly=True: Impide que cualquier script JS en el navegador acceda al token (anti-XSS).
      - samesite="lax": Protege contra falsificacion de peticiones entre sitios (anti-CSRF).
      - secure=settings.is_production: Requiere canal cifrado HTTPS en entorno de produccion.
      - path="/": Disponible para todas las rutas autorizadas del consultorio.
      - max_age: 28800 segundos (8 horas equivalentes a un turno clinico).
    """
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def clear_auth_cookie(response: Response) -> None:
    """Elimina la cookie de autenticacion cerrando formalmente la sesion del personal."""
    settings = get_settings()
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


# ==============================================================================
# DEPENDENCIAS DE AUTENTICACION Y RBAC EN SERVIDOR
# ==============================================================================

def get_current_staff(
    request: Request,
    repo: ClinicRepository = Depends(get_repository),
) -> StaffUserResponse:
    """
    Dependencia de seguridad que valida la sesion del personal clinico.
    Extrae el token prioritariamente de la cookie HttpOnly y valida la firma.
    """
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise UnauthorizedAccessError(
            message="Se requiere autenticacion para acceder a este recurso."
        )

    payload = decode_access_token(token)
    staff_id_str = payload.get("sub")
    if not staff_id_str:
        raise UnauthorizedAccessError("Token de sesion no contiene sujeto valido.")

    try:
        staff_id = UUID(staff_id_str)
    except ValueError as exc:
        raise UnauthorizedAccessError("Identificador de usuario corrupto en token.") from exc

    staff = repo.get_staff_by_id(staff_id)
    if not staff:
        raise UnauthorizedAccessError("El usuario de personal no existe o fue eliminado.")

    if not staff.activo:
        raise UnauthorizedAccessError("La cuenta de personal se encuentra desactivada.")

    return staff


def require_roles(*roles_permitidos: RolStaff) -> Callable[..., StaffUserResponse]:
    """Generador de dependencias RBAC para validar permisos en el servidor."""
    def role_dependency(staff: StaffUserResponse = Depends(get_current_staff)) -> StaffUserResponse:
        if staff.rol not in roles_permitidos:
            roles_validos_str = ", ".join([r.value for r in roles_permitidos])
            logger.warning(
                "Acceso denegado: usuario=%s con rol=%s intento acceder a recurso que exige rol en [%s]",
                staff.email,
                staff.rol,
                roles_validos_str,
            )
            raise DomainError(
                code=CodigoError.UNAUTHORIZED_ACCESS,
                message="No tiene permisos suficientes para realizar esta operacion clinica.",
                status_code=403,
            )
        return staff

    return role_dependency


# ==============================================================================
# LOGICA CRIPTOGRAFICA DE CAPTCHA "NO SOY UN ROBOT"
# ==============================================================================

def _generate_captcha_token(code: str, correct_indices: list[int]) -> str:
    """Genera un token firmado con expiracion de 5 minutos para el reto de captcha."""
    settings = get_settings()
    expira = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": "captcha_challenge",
        "code": code.upper(),
        "correct_indices": correct_indices,
        "exp": int(expira.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def _generate_verified_token() -> str:
    """Genera un token de aprobacion de captcha valido por 10 minutos."""
    settings = get_settings()
    expira = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "sub": "captcha_verified",
        "verified": True,
        "exp": int(expira.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_captcha_token(token: str) -> dict[str, Any]:
    """Decodifica y valida la firma y vigencia del token de captcha."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except ExpiredSignatureError as exc:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="El reto de seguridad ha expirado. Por favor solicite un nuevo codigo.",
            status_code=400,
        ) from exc
    except JWTError as exc:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="Token de reto de seguridad invalido o manipulado.",
            status_code=400,
        ) from exc


# ==============================================================================
# ENDPOINTS DE CAPTCHA INTERACTIVO (/api/v1/auth/captcha)
# ==============================================================================

@router.get("/captcha/new")
@limiter.limit("60/minute")
def obtener_nuevo_captcha(request: Request) -> dict[str, Any]:
    """
    Genera un nuevo reto criptografico para 'No soy un robot'.
    Soporta alternancia instantanea entre modo codigo canvas y cuadricula visual 3x3.
    """
    # 1. Modo 1: Codigo alfanumerico de 6 caracteres aleatorios
    codigo = "".join(secrets.choice(CAPTCHA_CHAR_POOL) for _ in range(6))

    # 2. Modo 2: Cuadricula 3x3 de imagenes (3 correctas + 6 distractoras)
    correct_sample = random.sample(CAPTCHA_CORRECT_ITEMS, 3)
    distractor_sample = random.sample(CAPTCHA_DISTRACTOR_ITEMS, 6)

    combined_items: list[dict[str, Any]] = []
    for item in correct_sample:
        combined_items.append({"label": item["label"], "image": item["image"], "_correct": True})
    for item in distractor_sample:
        combined_items.append({"label": item["label"], "image": item["image"], "_correct": False})

    random.shuffle(combined_items)

    correct_indices: list[int] = [i for i, item in enumerate(combined_items) if item["_correct"]]

    # Sanitizar items removiendo el flag privado antes de enviar al cliente
    client_items: list[dict[str, Any]] = [
        {"id": i, "label": item["label"], "image": item["image"]}
        for i, item in enumerate(combined_items)
    ]

    captcha_token = _generate_captcha_token(code=codigo, correct_indices=correct_indices)

    return {
        "status": "success",
        "data": {
            "captcha_token": captcha_token,
            "code": codigo,
            "grid_target": "Sonrisa / Odontologia Estetica",
            "grid_instruction": "Selecciona las 3 imagenes que correspondan a: Sonrisa / Odontologia Estetica",
            "grid_items": client_items,
            "expires_in_seconds": 300,
        },
    }


@router.post("/captcha/verify")
@limiter.limit("30/minute")
def verificar_captcha(request: Request, datos: CaptchaVerifyRequest) -> dict[str, Any]:
    """
    Verifica la respuesta del usuario (codigo escrito o seleccion 3x3) contra el token firmado.
    Retorna un token de captcha_verified_token valido por 10 minutos.
    """
    payload = _decode_captcha_token(datos.captcha_token)
    if payload.get("sub") != "captcha_challenge":
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="Tipo de token invalido para verificacion de captcha.",
            status_code=400,
        )

    verificado = False

    if datos.mode == "code":
        codigo_esperado = str(payload.get("code", "")).upper()
        codigo_usuario = (datos.answer_code or "").strip().upper()
        if codigo_usuario and codigo_usuario == codigo_esperado:
            verificado = True
    elif datos.mode == "image_grid":
        indices_esperados = set(payload.get("correct_indices", []))
        indices_usuario = set(datos.selected_indices or [])
        if indices_usuario and indices_usuario == indices_esperados:
            verificado = True

    if not verificado:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="Verificacion fallida. El codigo o la seleccion de imagenes no coincide.",
            status_code=400,
        )

    verified_token = _generate_verified_token()
    return {
        "status": "success",
        "message": "Verificacion 'No soy un robot' superada con exito.",
        "data": {
            "captcha_verified_token": verified_token,
        },
    }


# ==============================================================================
# REGISTRO Y FEDERACION DE USUARIOS (/api/v1/auth/register, /api/v1/auth/google)
# ==============================================================================

@router.post("/register", status_code=201)
@limiter.limit("10/minute")
def registrar_usuario(
    request: Request,
    response: Response,
    datos: RegisterRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Registra una cuenta de usuario nueva con cifrado Argon2id e inicia sesion de inmediato.
    Asocia o crea la ficha de paciente correspondiente en la base de datos.
    """
    validate_password_not_leaked(datos.password)

    existente = repo.get_staff_by_email(datos.email)
    if existente:
        raise DomainError(
            code=CodigoError.INVALID_STATE_TRANSITION,
            message=f"El correo electronico '{datos.email}' ya se encuentra registrado.",
            status_code=409,
        )

    hashed_pw = hash_password(datos.password)

    nuevo_staff = repo.create_staff(
        email=datos.email,
        password_hash=hashed_pw,
        nombre=datos.nombre,
        rol=datos.rol,
    )

    # Asegurar registro de paciente indexado por telefono
    try:
        repo.upsert_paciente(
            PacienteCreate(
                telefono=datos.telefono,
                nombre=datos.nombre,
                email=datos.email,
            )
        )
    except Exception as exc:
        logger.warning("Aviso no critico al sincronizar paciente durante registro: %s", exc)

    token = create_access_token(
        staff_id=nuevo_staff.id,
        email=nuevo_staff.email,
        rol=nuevo_staff.rol,
    )
    set_auth_cookie(response, token)

    logger.info("Registro de usuario exitoso: %s (rol=%s)", nuevo_staff.email, nuevo_staff.rol)
    return {
        "status": "success",
        "message": "Usuario registrado exitosamente. Sesion iniciada.",
        "data": {
            "usuario": nuevo_staff.model_dump(),
        },
    }


@router.post("/google")
@limiter.limit("20/minute")
def login_o_registro_con_google(
    request: Request,
    response: Response,
    datos: GoogleAuthRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Inicia sesion o aprovisiona usuario mediante Google Identity o selector seguro de cuentas.
    Emite cookie HttpOnly segura (cero tokens en localStorage).
    """
    email_normalizado = datos.email.lower()
    staff_dict = repo.get_staff_by_email(email_normalizado)

    if staff_dict:
        staff_id = UUID(str(staff_dict["id"]))
        staff_rol = RolStaff(staff_dict["rol"])
        nombre = staff_dict["nombre"]
        activo = bool(staff_dict.get("activo", True))
        if not activo:
            raise UnauthorizedAccessError("La cuenta asociada a este correo se encuentra desactivada.")
    else:
        # Registrar como nuevo usuario
        random_pwd = secrets.token_urlsafe(32) + "!A1"
        hashed_pw = hash_password(random_pwd)
        nuevo_user = repo.create_staff(
            email=email_normalizado,
            password_hash=hashed_pw,
            nombre=datos.nombre,
            rol=RolStaff.RECEPCION,
        )
        staff_id = nuevo_user.id
        staff_rol = nuevo_user.rol
        nombre = nuevo_user.nombre
        activo = True

    # Si se suministra telefono, sincronizar ficha de paciente
    if datos.telefono:
        try:
            repo.upsert_paciente(
                PacienteCreate(
                    telefono=datos.telefono,
                    nombre=nombre,
                    email=email_normalizado,
                )
            )
        except Exception as exc:
            logger.warning("Aviso no critico al sincronizar paciente Google: %s", exc)

    token = create_access_token(
        staff_id=staff_id,
        email=email_normalizado,
        rol=staff_rol,
    )
    set_auth_cookie(response, token)

    usuario_res = StaffUserResponse(
        id=staff_id,
        email=email_normalizado,
        nombre=nombre,
        rol=staff_rol,
        activo=activo,
        created_at=datetime.now(timezone.utc),
    )

    logger.info("Autenticacion con Google exitosa: %s (rol=%s)", usuario_res.email, usuario_res.rol)
    return {
        "status": "success",
        "message": "Autenticacion con Google completada correctamente.",
        "data": {
            "usuario": usuario_res.model_dump(),
        },
    }


# ==============================================================================
# ENDPOINTS TRADICIONALES DE SESION (/api/v1/auth/login, logout, me)
# ==============================================================================

@router.post("/login")
@limiter.limit("15/minute")
def login(
    request: Request,
    response: Response,
    credenciales: LoginRequest,
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Autentica al personal clinico mediante correo y contrasena.
    Protegido contra fuerza bruta con rate limiting y hash senuelo contra timing attacks.
    """
    staff_dict = repo.get_staff_by_email(credenciales.email)

    if not staff_dict:
        verify_password(credenciales.password, DUMMY_PASSWORD_HASH)
        raise UnauthorizedAccessError("Credenciales invalidas o cuenta inactiva.")

    password_valida = verify_password(credenciales.password, staff_dict["password_hash"])
    cuenta_activa = bool(staff_dict.get("activo", True))

    if not password_valida or not cuenta_activa:
        raise UnauthorizedAccessError("Credenciales invalidas o cuenta inactiva.")

    staff_id = UUID(str(staff_dict["id"]))
    staff_rol = RolStaff(staff_dict["rol"])

    token = create_access_token(
        staff_id=staff_id,
        email=staff_dict["email"],
        rol=staff_rol,
    )
    set_auth_cookie(response, token)

    usuario_res = StaffUserResponse(
        id=staff_id,
        email=staff_dict["email"],
        nombre=staff_dict["nombre"],
        rol=staff_rol,
        activo=cuenta_activa,
        created_at=staff_dict["created_at"],
    )

    logger.info("Inicio de sesion exitoso: %s (rol=%s)", usuario_res.email, usuario_res.rol)
    return {
        "status": "success",
        "data": {
            "usuario": usuario_res.model_dump(),
        },
    }


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    """Cierra la sesion del personal limpiando la cookie HttpOnly."""
    clear_auth_cookie(response)
    return {
        "status": "success",
        "message": "Sesion cerrada correctamente.",
    }


@router.get("/me")
def get_current_user_profile(
    current_staff: StaffUserResponse = Depends(get_current_staff),
) -> dict[str, Any]:
    """Obtiene el perfil autenticado del usuario en sesion validado en servidor."""
    return {
        "status": "success",
        "data": {
            "usuario": current_staff.model_dump(),
        },
    }


# ==============================================================================
# GESTION ADMINISTRATIVA DE PERSONAL STAFF (/api/v1/auth/staff)
# ==============================================================================

@router.post("/staff", status_code=201)
@limiter.limit("15/minute")
def crear_nuevo_colaborador(
    request: Request,
    datos: StaffCreateRequest,
    current_staff: StaffUserResponse = Depends(require_roles(RolStaff.ADMIN)),
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Registra un nuevo miembro del personal clinico (doctor, recepcion o admin).
    Ruta protegida exclusivamente para usuarios con rol ADMIN.
    """
    validate_password_not_leaked(datos.password)

    existente = repo.get_staff_by_email(datos.email)
    if existente:
        raise DomainError(
            code=CodigoError.INVALID_STATE_TRANSITION,
            message=f"El correo '{datos.email}' ya se encuentra registrado para otro colaborador.",
            status_code=409,
        )

    hashed_pw = hash_password(datos.password)
    nuevo_staff = repo.create_staff(
        email=datos.email,
        password_hash=hashed_pw,
        nombre=datos.nombre,
        rol=datos.rol,
    )

    logger.info("Nuevo colaborador creado por %s: %s (rol=%s)", current_staff.email, nuevo_staff.email, nuevo_staff.rol)
    return {
        "status": "success",
        "message": "Usuario de personal creado correctamente.",
        "data": {
            "usuario": nuevo_staff.model_dump(),
        },
    }


@router.get("/staff")
def listar_personal_clinico(
    current_staff: StaffUserResponse = Depends(require_roles(RolStaff.ADMIN)),
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Obtiene el listado completo de colaboradores de la clinica.
    Ruta protegida exclusivamente para usuarios con rol ADMIN.
    """
    lista = repo.list_staff()
    return {
        "status": "success",
        "data": {
            "staff": [u.model_dump() for u in lista],
        },
    }


@router.patch("/staff/{staff_id}/toggle")
def alternar_estado_personal(
    staff_id: UUID,
    datos: StaffToggleRequest,
    current_staff: StaffUserResponse = Depends(require_roles(RolStaff.ADMIN)),
    repo: ClinicRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Activa o desactiva la cuenta de un colaborador del consultorio."""
    if staff_id == current_staff.id:
        raise DomainError(
            code=CodigoError.INVALID_STATE_TRANSITION,
            message="No puede desactivar su propia cuenta de administrador en sesion.",
            status_code=400,
        )
    actualizado = repo.update_staff_status(staff_id=staff_id, activo=datos.activo)
    return {
        "status": "success",
        "message": f"Cuenta de '{actualizado.email}' {'activada' if datos.activo else 'desactivada'} correctamente.",
        "data": {
            "usuario": actualizado.model_dump(),
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m app.auth \"<contrasena_a_hashear>\"")
        sys.exit(1)

    pass_input = sys.argv[1]
    try:
        validate_password_not_leaked(pass_input)
        hashed_output = hash_password(pass_input)
        print(f"Hash Argon2id generado exitosamente:\n{hashed_output}")
    except Exception as error:
        print(f"Error de validacion de contrasena: {error}")
        sys.exit(1)
