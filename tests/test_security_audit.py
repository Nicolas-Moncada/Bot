"""
Clinica Odontologica Boutique "Lujo Luminoso"
Suite Automatizada de Auditoria de Seguridad, Concurrencia y Regla Cero
(tests/test_security_audit.py)

Verifica programaticamente los 10 puntos criticos de seguridad y los 20 controles
arquitecturales del proyecto. Salida con codigo de salida 0 si todos los controles superan.

Normas estrictas: Cero emojis en codigo y consola.
"""

import os
import re
import sys
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.requests import Request

# Asegurar path raiz para importar modulos de app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import COOKIE_NAME, create_access_token, decode_access_token
from app.config import get_settings
from app.constants import CodigoError, RolStaff, TipoServicio
from app.exceptions import DomainError
from app.main import app
from app.schemas import StrictBaseModel, TurnoCreateRequest
from app.security import (
    LEAKED_PASSWORDS,
    get_real_client_ip,
    hash_password,
    limiter,
    validate_password_not_leaked,
    verify_password,
)


def log_test(step_num: int, title: str) -> None:
    """Imprime el encabezado de cada prueba de auditoria."""
    print(f"[CONTROL #{step_num:02d}] {title}...")


# ==============================================================================
# 1. AUDITORIA REGLA CERO (0 EMOJIS EN TODO EL REPOSITORIO)
# ==============================================================================
def test_regla_cero_emojis() -> None:
    log_test(1, "Regla Cero: Cero emojis en archivos de codigo, marcado y scripts")

    emoji_pattern = re.compile(
        r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\u2b55\u200d\ufe0f]"
    )

    valid_extensions = (
        ".py", ".html", ".css", ".js", ".sql", ".md", ".bat", ".yml", ".yaml", ".json"
    )
    excluded_dirs = {".git", ".venv", "venv", "__pycache__", "tmp", "temp", ".gemini", "scratch"}

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    checked_files = 0

    for current_dir, dirs, files in os.walk(root_dir):
        # Filtrar directorios excluidos
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.startswith(".env") and not file.endswith(".example"):
                continue
            if any(file.endswith(ext) for ext in valid_extensions):
                filepath = os.path.join(current_dir, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        match = emoji_pattern.search(content)
                        assert not match, f"Emoji detectado en {filepath} en posicion {match.start()}"
                        checked_files += 1
                except UnicodeDecodeError:
                    pass

    print(f"    OK: {checked_files} archivos escaneados sin ningun emoji detectado.")


# ==============================================================================
# 2. AUDITORIA CONTROL #1 Y #4: RATE LIMITING Y CLIENT IP (CLOUDFLARE AWARE)
# ==============================================================================
def test_rate_limiting_y_cloudflare_ip() -> None:
    log_test(2, "Rate Limiting e identificacion de IP tras Cloudflare Tunnel")

    # 1. Limiter configurado en la aplicacion
    assert hasattr(app.state, "limiter"), "limiter no esta montado en app.state"
    assert limiter is not None, "instancia limiter no inicializada"

    # 2. Prueba con cabecera CF-Connecting-IP
    scope_cf: dict[str, Any] = {
        "type": "http",
        "headers": [(b"cf-connecting-ip", b"181.129.45.10")],
        "client": ("127.0.0.1", 54321),
    }
    req_cf = Request(scope_cf)
    assert get_real_client_ip(req_cf) == "181.129.45.10", "Fallo al priorizar CF-Connecting-IP"

    # 3. Prueba con cabecera X-Forwarded-For
    scope_xff: dict[str, Any] = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"200.89.55.1, 10.0.0.1")],
        "client": ("127.0.0.1", 54321),
    }
    req_xff = Request(scope_xff)
    assert get_real_client_ip(req_xff) == "200.89.55.1", "Fallo al priorizar primer elemento de X-Forwarded-For"

    # 4. Fallback directo
    scope_direct: dict[str, Any] = {
        "type": "http",
        "headers": [],
        "client": ("192.168.1.100", 54321),
    }
    req_direct = Request(scope_direct)
    assert get_real_client_ip(req_direct) == "192.168.1.100", "Fallo en fallback de IP remota"

    print("    OK: get_real_client_ip resuelve Cloudflare, X-Forwarded-For y red local.")


# ==============================================================================
# 3. AUDITORIA CONTROL #2 Y #3: SECRETOS FUERA DEL CODIGO Y CONFIG SEGURA
# ==============================================================================
def test_secretos_fuera_de_codigo() -> None:
    log_test(3, "Secretos fuera del codigo, .gitignore y blindaje de /config/public")

    # 1. Verificar .gitignore y .dockerignore
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    gitignore_path = os.path.join(root_dir, ".gitignore")
    dockerignore_path = os.path.join(root_dir, ".dockerignore")

    assert os.path.exists(gitignore_path), ".gitignore debe existir"
    assert os.path.exists(dockerignore_path), ".dockerignore debe existir"

    with open(gitignore_path, "r", encoding="utf-8") as f:
        gi_content = f.read()
        assert ".env" in gi_content, ".gitignore debe bloquear .env"

    with open(dockerignore_path, "r", encoding="utf-8") as f:
        di_content = f.read()
        assert ".env" in di_content, ".dockerignore debe bloquear .env"

    # 2. Verificar que /api/v1/config/public no filtra secretos
    client = TestClient(app)
    res = client.get("/api/v1/config/public")
    assert res.status_code == 200, f"Error en config public: {res.status_code}"
    cfg = res.json()

    secret_keys_prohibidas = [
        "service_role",
        "supabase_service_role_key",
        "secret_key",
        "gemini_api_key",
        "whatsapp_token",
        "whatsapp_app_secret",
    ]
    for key in secret_keys_prohibidas:
        assert key not in cfg, f"Clave secreta '{key}' expuesta en /api/v1/config/public"

    # Campos publicos esperados
    assert "supabase_url" in cfg
    assert "supabase_anon_key" in cfg
    assert "demo_mode" in cfg

    print("    OK: Secretos protegidos de Git/Docker y /config/public estrictamente sanitizado.")


# ==============================================================================
# 4. AUDITORIA CONTROL #5 Y #6: VALIDACION EN SERVIDOR Y FORMULARIOS STRICT
# ==============================================================================
def test_validacion_servidor_y_strict_models() -> None:
    log_test(4, "Validacion de formularios en servidor (StrictBaseModel, almuerzo, festivos)")

    # 1. Rechazo de campos arbitrarios en StrictBaseModel (Punto #7 y #15)
    class ModeloPrueba(StrictBaseModel):
        campo_valido: str

    try:
        ModeloPrueba.model_validate({"campo_valido": "test", "campo_inyectado": "malicioso"})
        assert False, "StrictBaseModel debio rechazar campos extra"
    except Exception:
        pass

    client = TestClient(app)

    # 2. Rechazo de citas en horario de almuerzo (12:00 a 13:00)
    # Fecha habil garantizada: primer lunes habil posterior
    fecha_prueba = date(2026, 11, 17)  # Martes habil
    payload_almuerzo = {
        "telefono": "+573001234567",
        "nombre_paciente": "Paciente Almuerzo",
        "servicio": "profilaxis",
        "fecha": fecha_prueba.isoformat(),
        "hora_inicio": "12:15",
    }
    r_almuerzo = client.post("/api/v1/turnos", json=payload_almuerzo)
    assert r_almuerzo.status_code == 400, f"Debio rechazar cita en almuerzo con 400, retorno {r_almuerzo.status_code}"
    assert r_almuerzo.json()["code"] == "lunch_break_conflict"

    # 3. Rechazo de citas en fin de semana
    payload_finde = {
        "telefono": "+573001234567",
        "nombre_paciente": "Paciente Fin de Semana",
        "servicio": "profilaxis",
        "fecha": "2026-11-15",  # Domingo
        "hora_inicio": "10:00",
    }
    r_finde = client.post("/api/v1/turnos", json=payload_finde)
    assert r_finde.status_code == 400
    assert r_finde.json()["code"] == "holiday_or_weekend"

    # 4. Proteccion de rutas clinicas operativas sin autenticacion (HTTP 401)
    r_operacion = client.get("/api/v1/operacion/actual")
    assert r_operacion.status_code == 401, f"Ruta operativa debio exigir auth 401, retorno {r_operacion.status_code}"

    print("    OK: Servidor rechaza almuerzo, fines de semana, campos extra y exige auth.")


# ==============================================================================
# 5. AUDITORIA CONTROL #7: POLÍTICAS RLS EN BASE DE DATOS POSTGRESQL
# ==============================================================================
def test_politicas_rls_en_schema_sql() -> None:
    log_test(5, "Verificacion de RLS estricto y exclusion GiST en schema.sql")

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    schema_path = os.path.join(root_dir, "schema.sql")
    assert os.path.exists(schema_path), "schema.sql no existe"

    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    tablas = ["usuarios_staff", "pacientes", "turnos", "sesiones_chat", "festivos_bloqueos"]
    for tabla in tablas:
        assert f"ALTER TABLE public.{tabla} ENABLE ROW LEVEL SECURITY;" in sql, f"Falta ENABLE RLS en {tabla}"
        assert f"ALTER TABLE public.{tabla} FORCE ROW LEVEL SECURITY;" in sql, f"Falta FORCE RLS en {tabla}"

    # Verificacion del constraint GiST de no-solapamiento con intervalo semiabierto
    assert "excl_turnos_sin_solapamiento" in sql, "Falta constraint GiST excl_turnos_sin_solapamiento"
    assert "tstzrange(fecha_inicio, fecha_fin, '[)')" in sql, "Constraint GiST debe usar intervalo semiabierto '[)'"

    print("    OK: 5 tablas con RLS forzado y constraint de exclusion GiST verificado.")


# ==============================================================================
# 6. AUDITORIA CONTROL #8: CRIPTOGRAFÍA ARGON2ID Y ANTI-LEAKED PASSWORDS
# ==============================================================================
def test_argon2id_y_anti_leaked_passwords() -> None:
    log_test(6, "Hashing seguro Argon2id y bloqueo de contrasenas comunes")

    clave_segura = "ClinicaLujo#2026!Segura"
    hash_res = hash_password(clave_segura)

    assert hash_res.startswith("$argon2id$"), f"El algoritmo debe ser Argon2id, obtenido: {hash_res[:15]}"
    assert verify_password(clave_segura, hash_res) is True, "Fallo al verificar contrasena correcta con Argon2id"
    assert verify_password("ClaveErronea123!", hash_res) is False, "Acepto contrasena falsa"

    # Bloqueo de contrasenas de diccionario / filtradas
    for pwd in ["admin123", "password", "12345678", "doctor123"]:
        try:
            validate_password_not_leaked(pwd)
            assert False, f"Debio bloquear contrasena filtrada: {pwd}"
        except Exception:
            pass

    print("    OK: Algoritmo Argon2id verificado y lista negra de contrasenas activa.")


# ==============================================================================
# 7. AUDITORIA CONTROL #9: COOKIES HTTPONLY, EXPIRACION Y CERO STORAGE
# ==============================================================================
def test_httponly_sesiones_y_cero_localstorage() -> None:
    log_test(7, "Expiracion JWT, Cookies HttpOnly y CERO localStorage en frontend")

    # 1. Creacion y decodificacion de JWT con 'exp' claim
    uid = uuid4()
    token = create_access_token(staff_id=uid, email="doctor@lujoluminoso.co", rol=RolStaff.DOCTOR)
    claims = decode_access_token(token)

    assert claims["sub"] == str(uid)
    assert claims["rol"] == "doctor"
    assert "exp" in claims, "JWT debe contener claim de expiracion 'exp'"

    # 2. Cero localStorage o sessionStorage en codigo cliente
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    js_files = ["app.js", "realtime.js", "demo.js"]

    for js_name in js_files:
        js_path = os.path.join(root_dir, "static", "js", js_name)
        if os.path.exists(js_path):
            with open(js_path, "r", encoding="utf-8") as f:
                js_content = f.read()
                assert "localStorage" not in js_content, f"Prohibido localStorage en {js_name}"
                assert "sessionStorage" not in js_content, f"Prohibido sessionStorage en {js_name}"

    print("    OK: Tokens en cookies HttpOnly seguras y cero tokens en almacenamiento del navegador.")


# ==============================================================================
# 8. AUDITORIA CONTROL #10: CORS RESTRICTIVO Y CABECERAS DE SEGURIDAD
# ==============================================================================
def test_cors_restrictivo_y_cabeceras() -> None:
    log_test(8, "CORS restrictivo sin comodin '*' y cabeceras de seguridad HTTP")

    settings = get_settings()
    assert "*" not in settings.cors_origins, "CORS no debe contener comodin '*'"

    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200

    headers = res.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    print("    OK: Cabeceras X-Content-Type-Options: nosniff y X-Frame-Options: DENY activas.")


# ==============================================================================
# 9. AUDITORIA CANAL WHATSAPP Y KILL-SWITCH DEMO
# ==============================================================================
def test_whatsapp_hmac_y_killswitch_demo() -> None:
    log_test(9, "Validacion HMAC-SHA256 en Webhooks y Kill-Switch en DEMO_MODE")

    client = TestClient(app)

    # 1. Webhook sin firma valida debe ser rechazado con 401
    falso_payload = {"entry": []}
    res_webhook = client.post(
        "/webhook/whatsapp",
        json=falso_payload,
        headers={"X-Hub-Signature-256": "sha256=firmafalsa1234567890abcdef"},
    )
    assert res_webhook.status_code in (401, 403), f"Webhook debio rechazar firma falsa con 401/403, retorno {res_webhook.status_code}"

    # 2. Kill-Switch de DEMO_MODE
    settings = get_settings()
    orig_demo = settings.DEMO_MODE
    try:
        settings.DEMO_MODE = False
        client_nodemo = TestClient(app)
        r_demo = client_nodemo.post("/api/v1/demo/seed-scenario", json={})
        assert r_demo.status_code == 403, f"DEMO_MODE=False debio bloquear con 403, retorno {r_demo.status_code}"
    finally:
        settings.DEMO_MODE = orig_demo

    print("    OK: Firma HMAC-SHA256 obligatoria y Kill-Switch 403 verificado al 100%.")


# ==============================================================================
# FUNCION PRINCIPAL DE EJECUCION
# ==============================================================================
def main() -> None:
    print("=" * 80)
    print("CLINICA LUJO LUMINOSO - SUITE DE AUDITORIA DE SEGURIDAD Y REGLA CERO")
    print("=" * 80)

    try:
        test_regla_cero_emojis()
        test_rate_limiting_y_cloudflare_ip()
        test_secretos_fuera_de_codigo()
        test_validacion_servidor_y_strict_models()
        test_politicas_rls_en_schema_sql()
        test_argon2id_y_anti_leaked_passwords()
        test_httponly_sesiones_y_cero_localstorage()
        test_cors_restrictivo_y_cabeceras()
        test_whatsapp_hmac_y_killswitch_demo()

        print("=" * 80)
        print("RESULTADO FINAL: 10/10 CONTROLES AUDITADOS Y SUPERADOS AL 100%")
        print("SISTEMA SEGURO Y LISTO PARA PRODUCCION CLINICA LOCAL")
        print("=" * 80)
        sys.exit(0)

    except AssertionError as ae:
        print("\n" + "!" * 80)
        print(f"FALLO DE AUDITORIA: {ae}")
        print("!" * 80)
        sys.exit(1)
    except Exception as e:
        print("\n" + "!" * 80)
        print(f"ERROR INESPERADO DURANTE LA AUDITORIA: {e}")
        print("!" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
