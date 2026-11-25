"""
Capa de seguridad criptografica, hashing Argon2id, tokens JWT y rate limiting.

Neutraliza ataques de enumeracion por tiempo, inyeccion de contrasenas filtradas
y coordina la limitacion de peticiones considerando tuneles seguros de Cloudflare.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import ExpiredSignatureError, JWTError, jwt
from pwdlib import PasswordHash
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.constants import CodigoError, RolStaff
from app.exceptions import DomainError, UnauthorizedAccessError, create_error_response

logger = logging.getLogger("app.security")

# Parametros criptograficos de sesion
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas continuas (jornada laboral)

# Lista negra de contrasenas comunes o previamente filtradas en brechas (Punto #19 de Seguridad)
LEAKED_PASSWORDS: frozenset[str] = frozenset({
    "12345678",
    "123456789",
    "1234567890",
    "password",
    "password123",
    "admin123",
    "admin1234",
    "qwerty123",
    "colombia123",
    "odontologia123",
    "lujoluminoso",
    "clinica123",
    "doctor123",
    "welcome123",
    "letmein123",
})

# Hasher de contrasenas basado en Argon2id (Punto #9 de Seguridad)
_pwd_hasher: PasswordHash = PasswordHash.recommended()


# ==============================================================================
# HASHING DE CONTRASENAS (ARGON2ID) Y MITIGACION DE TIMING ATTACKS
# ==============================================================================

def hash_password(plain_password: str) -> str:
    """Genera un hash seguro Argon2id para almacenamiento en base de datos."""
    return _pwd_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica una contrasena en texto plano contra su hash Argon2id.
    Retorna False de forma segura ante cualquier fallo sin filtrar excepciones.
    """
    try:
        return _pwd_hasher.verify(plain_password, hashed_password)
    except Exception as exc:
        logger.debug("Fallo en verificacion de hash de contrasena: %s", str(exc))
        return False


# Hash senuelo generado al inicio para mitigar ataques de enumeracion por tiempo (Timing Attacks)
DUMMY_PASSWORD_HASH: str = hash_password("dummy_constant_password_hash_timing_mitigation_123!")


# ==============================================================================
# VALIDACION DE FORTALEZA Y DEFENSA CONTRA CONTRASENAS FILTRADAS
# ==============================================================================

def validate_password_not_leaked(password: str, email: str | None = None) -> None:
    """
    Valida que la contrasena cumpla con politicas de complejidad y no este comprometida.

    Reglas:
      - Minimo 10 caracteres.
      - Al menos una letra mayuscula, una minuscula y un digito o simbolo.
      - No figurar en listas de credenciales filtradas o patrones triviales.
      - No contener la parte local del correo institucional del usuario.
    """
    if len(password) < 10:
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="La contrasena debe tener al menos 10 caracteres.",
            status_code=400,
        )

    if not re.search(r"[A-Z]", password):
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="La contrasena debe contener al menos una letra mayuscula.",
            status_code=400,
        )

    if not re.search(r"[a-z]", password):
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="La contrasena debe contener al menos una letra minuscula.",
            status_code=400,
        )

    if not re.search(r"[\d\W_]", password):
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="La contrasena debe contener al menos un numero o simbolo especial.",
            status_code=400,
        )

    password_lower = password.lower()

    for leaked in LEAKED_PASSWORDS:
        if leaked in password_lower:
            raise DomainError(
                code=CodigoError.UNAUTHORIZED_ACCESS,
                message="La contrasena no cumple las politicas de seguridad o se encuentra en listas de credenciales comprometidas.",
                status_code=400,
            )

    if email:
        local_part = email.split("@")[0].lower()
        if len(local_part) >= 3 and local_part in password_lower:
            raise DomainError(
                code=CodigoError.UNAUTHORIZED_ACCESS,
                message="La contrasena no puede contener partes de su direccion de correo electronico.",
                status_code=400,
            )


# ==============================================================================
# TOKENS JWT FIRMADOS (PYTHON-JOSE)
# ==============================================================================

def create_access_token(
    staff_id: UUID,
    email: str,
    rol: RolStaff,
    expires_delta: timedelta | None = None,
) -> str:
    """Construye y firma criptograficamente un token JWT con expiracion en UTC."""
    settings = get_settings()
    now_utc = datetime.now(timezone.utc)
    expiration = now_utc + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    payload: dict[str, Any] = {
        "sub": str(staff_id),
        "email": email.strip().lower(),
        "rol": str(rol),
        "iat": int(now_utc.timestamp()),
        "exp": int(expiration.timestamp()),
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decodifica y valida la firma y vigencia del JWT.
    Lanza UnauthorizedAccessError si el token fue alterado o ha expirado.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if "sub" not in payload:
            raise UnauthorizedAccessError("Token de acceso no contiene identificador valido.")
        return payload
    except ExpiredSignatureError as exc:
        raise UnauthorizedAccessError("La sesion ha expirado. Por favor inicie sesion nuevamente.") from exc
    except JWTError as exc:
        raise UnauthorizedAccessError("Sesion invalida o token adulterado.") from exc


# ==============================================================================
# RATE LIMITING CONSCIENTE DE CLOUDFLARE TUNNEL (SLOWAPI)
# ==============================================================================

def get_real_client_ip(request: Request) -> str:
    """
    Extrae la direccion IP real del cliente considerando tuneles Cloudflare en PC local.

    Prioridad:
      1. Cabecera 'CF-Connecting-IP' provista por Cloudflare Tunnel (cloudflared).
      2. Primer valor de la cabecera estandar 'X-Forwarded-For'.
      3. IP directa de la conexion local (127.0.0.1) como fallback.
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    x_forwarded = request.headers.get("X-Forwarded-For")
    if x_forwarded and x_forwarded.strip():
        return x_forwarded.split(",")[0].strip()

    return get_remote_address(request) or "127.0.0.1"


# Instancia del limitador de tasa de peticiones con limite global por defecto
limiter: Limiter = Limiter(
    key_func=get_real_client_ip,
    default_limits=["120/minute"],
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Genera una respuesta JSON estandarizada ante peticiones que superen la tasa limite."""
    retry_after = getattr(exc, "detail", "60 segundos")
    logger.warning(
        "Tasa de peticiones excedida desde IP=%s en ruta %s: %s",
        get_real_client_ip(request),
        request.url.path,
        retry_after,
    )
    return create_error_response(
        code=CodigoError.RATE_LIMIT_EXCEEDED,
        message="Limite de peticiones excedido. Por favor espere antes de intentar nuevamente.",
        status_code=429,
        details={"retry_after": retry_after},
    )
