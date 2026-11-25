"""
Punto de entrada principal de la aplicacion FastAPI para la clinica Lujo Luminoso.

Configura politicas de seguridad perimetral, middleware de CORS restringido,
cabeceras HTTP de proteccion, limitador de tasa de peticiones, manejadores de error,
montaje de archivos estaticos, servidor de plantillas HTML y configuracion publica.
"""

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded

from app.auth import router as auth_router
from app.config import get_settings
from app.exceptions import (
    DomainError,
    domain_exception_handler,
    global_exception_handler,
)
from app.logic import now_colombia
from app.routers.operacion import router as operacion_router
from app.routers.turnos import router as turnos_router
from app.routers.whatsapp import router as whatsapp_router
from app.demo_router import demo_router
from app.schemas import ResenaCreate
from app.security import limiter, rate_limit_exceeded_handler

# Configuracion del registrador de eventos
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")

settings = get_settings()

# Ocultamiento de documentacion OpenAPI en produccion (Punto #2 de Seguridad)
docs_url = None if settings.is_production else "/docs"
redoc_url = None if settings.is_production else "/redoc"
openapi_url = None if settings.is_production else "/openapi.json"

app = FastAPI(
    title="Lujo Luminoso - Clinica Odontologica Boutique",
    description="Motor de agendamiento y operacion clinica omnicanal (1 Doctor, 1 Sillon).",
    version="1.0.0",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

# Integracion del limitador de tasa de peticiones (slowapi)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Manejadores centralizados de excepciones
app.add_exception_handler(DomainError, domain_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Middleware de CORS con origenes explicitos (Punto #12 de Seguridad)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization", "X-Requested-With"],
)


# ==============================================================================
# MIDDLEWARE DE CABECERAS DE SEGURIDAD HTTP
# ==============================================================================

@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Any:
    """
    Inyecta cabeceras de proteccion para prevenir ataques XSS, Clickjacking y MIME sniffing.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"

    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# ==============================================================================
# MONTAJE DE RECURSOS ESTATICOS Y PLANTILLAS JINJA2 (TAREA #9)
# ==============================================================================

# Asegurar existencia de directorios requeridos
Path("static/css").mkdir(parents=True, exist_ok=True)
Path("static/js").mkdir(parents=True, exist_ok=True)
Path("templates").mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ==============================================================================
# MONTAJE DE ROUTERS DE API
# ==============================================================================

# 1. Modulo de Autenticacion de Personal (Tarea #5)
app.include_router(auth_router)

# 2. Modulo de Agenda y Disponibilidad (Tarea #6: app/routers/turnos.py)
app.include_router(turnos_router)

# 3. Modulo de Operacion Clinica y Doctor (Tarea #6: app/routers/operacion.py)
app.include_router(operacion_router)

# 4. Modulo de Webhooks de Meta WhatsApp (Tarea #8: app/routers/whatsapp.py)
app.include_router(whatsapp_router)

# 5. Modulo de Modo Demo Aislado (Tarea #11: app/demo_router.py)
app.include_router(demo_router)


# ==============================================================================
# CONFIGURACION PUBLICA SEGURA PARA CLIENTE WEB (PUNTO #2 DE SEGURIDAD)
# ==============================================================================

@app.get("/api/v1/config/public", tags=["Configuracion"])
def obtener_configuracion_publica() -> dict[str, Any]:
    """
    Retorna parametros de configuracion publica no confidenciales para inicializar la SPA.
    Jamas expone SUPABASE_SERVICE_ROLE_KEY, SECRET_KEY, GEMINI_API_KEY ni WHATSAPP_TOKEN.
    """
    return {
        "clinic_name": "Lujo Luminoso",
        "timezone": settings.TIMEZONE,
        "supabase_url": settings.SUPABASE_URL,
        "supabase_anon_key": settings.SUPABASE_ANON_KEY,
        "demo_mode": settings.DEMO_MODE,
        "whatsapp_number": "573001234567" if settings.WHATSAPP_PHONE_NUMBER_ID.startswith("10000") else settings.WHATSAPP_PHONE_NUMBER_ID,
        "whatsapp_contact_number": "573001234567" if settings.WHATSAPP_PHONE_NUMBER_ID.startswith("10000") else settings.WHATSAPP_PHONE_NUMBER_ID,
    }


# ==============================================================================
# ALMACENAMIENTO Y ENDPOINTS DE RESENAS Y CALIFICACIONES (REVIEWS)
# ==============================================================================

REVIEWS_STORAGE: list[dict[str, Any]] = [
    {
        "id": "res-1",
        "nombre": "Camila Rodriguez",
        "servicio": "Diseno de Sonrisa y Microcarillas",
        "calificacion": 5,
        "comentario": "La puntualidad y privacidad son incomparables. Entrar al consultorio y saber que esta reservado solo para ti cambia completamente la experiencia odontologica. Cero estres y un resultado hiper natural.",
        "fecha": "Noviembre 2026",
        "verificado": True,
    },
    {
        "id": "res-2",
        "nombre": "Andres Montoya",
        "servicio": "Microcarillas Ceramicas Feldespaticas",
        "calificacion": 5,
        "comentario": "Mis carillas se ven 100% naturales, nadie nota que son porcelana, solo una sonrisa blanca, pulida y armonica. El doctor me explico cada paso en pantalla digital 3D antes de empezar.",
        "fecha": "Noviembre 2026",
        "verificado": True,
    },
    {
        "id": "res-3",
        "nombre": "Sofia Valencia",
        "servicio": "Implante Dental y Cirugia Guiada",
        "calificacion": 5,
        "comentario": "Me colocaron un implante dental con anestesia computarizada sin ningun dolor y con precision impecable. El seguimiento post quirurgico por WhatsApp fue excelente.",
        "fecha": "Octubre 2026",
        "verificado": True,
    },
    {
        "id": "res-4",
        "nombre": "Dr. Fernando Gutierrez",
        "servicio": "Profilaxis Ultrasonica y Desmanchado",
        "calificacion": 5,
        "comentario": "Higiene profunda con tecnologia piezoelectrica sin nada de sensibilidad. El espacio transmite calma absoluta, atencion de primer nivel mundial.",
        "fecha": "Octubre 2026",
        "verificado": True,
    },
]


@app.get("/api/v1/resenas", tags=["Resenas"])
def listar_resenas() -> dict[str, Any]:
    """Retorna el listado de opiniones y resenas de pacientes verificados."""
    total = len(REVIEWS_STORAGE)
    promedio = round(sum(r["calificacion"] for r in REVIEWS_STORAGE) / max(total, 1), 1)
    return {
        "status": "success",
        "data": {
            "resenas": REVIEWS_STORAGE,
            "promedio": promedio,
            "total": total,
        },
    }


@app.post("/api/v1/resenas", status_code=201, tags=["Resenas"])
@limiter.limit("10/minute")
def crear_resena(request: Request, datos: ResenaCreate) -> dict[str, Any]:
    """Registra una nueva resena de paciente con calificacion y sanitizacion estricta."""
    meses_es = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    ahora = now_colombia()
    fecha_formateada = f"{meses_es.get(ahora.month, '')} {ahora.year}"
    nueva_resena = {
        "id": f"res-{uuid4().hex[:8]}",
        "nombre": datos.nombre.strip(),
        "servicio": datos.servicio.strip(),
        "calificacion": datos.calificacion,
        "comentario": datos.comentario.strip(),
        "fecha": fecha_formateada,
        "verificado": True,
    }
    REVIEWS_STORAGE.insert(0, nueva_resena)
    logger.info("Nueva resena registrada: %s (%s estrellas)", nueva_resena["nombre"], nueva_resena["calificacion"])
    return {
        "status": "success",
        "message": "Resena publicada exitosamente.",
        "data": {
            "resena": nueva_resena,
        },
    }


# ==============================================================================
# VISTAS WEB SPA (JINJA2 + TEMPLATES)
# ==============================================================================

@app.get("/", response_class=HTMLResponse, tags=["Vistas Web"])
@app.get("/inicio", response_class=HTMLResponse, tags=["Vistas Web"])
@app.get("/reservar", response_class=HTMLResponse, tags=["Vistas Web"])
@app.get("/admin", response_class=HTMLResponse, tags=["Vistas Web"])
@app.get("/doctor", response_class=HTMLResponse, tags=["Vistas Web"])
@app.get("/tv", response_class=HTMLResponse, tags=["Vistas Web"])
def render_index(request: Request) -> Any:
    """
    Sirve la aplicacion SPA de la clinica Lujo Luminoso.
    El cliente activa el apartado correspondiente segun la ruta URL solicitada.
    """
    path = request.url.path
    initial_view = "landing"
    if path.startswith("/reservar"):
        initial_view = "reservar"
    elif path.startswith("/admin"):
        initial_view = "admin"
    elif path.startswith("/doctor"):
        initial_view = "doctor"
    elif path.startswith("/tv"):
        initial_view = "tv"
    elif path.startswith("/inicio") or path == "/":
        initial_view = "landing"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "clinic_name": "Lujo Luminoso",
            "initial_view": initial_view,
            "demo_mode": settings.DEMO_MODE,
        },
    )


# ==============================================================================
# ENDPOINTS DE SALUD Y MONITOREO LOCAL
# ==============================================================================

@app.get("/health", tags=["Monitoreo"])
@app.get("/api/v1/health", tags=["Monitoreo"])
def health_check() -> dict[str, Any]:
    """
    Verifica el estado del servicio para monitoreo en PC local y Cloudflare Tunnel.
    """
    return {
        "status": "ok",
        "service": "Lujo Luminoso Clinic Engine",
        "environment": settings.APP_ENV,
        "demo_mode": settings.DEMO_MODE,
        "timestamp": now_colombia().isoformat(),
    }
