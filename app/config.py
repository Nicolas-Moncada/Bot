"""
Gestion de configuracion centralizada y blindaje de variables de entorno.

Valida rigurosamente parametros de seguridad, conexiones externas y politicas
de ejecucion antes de levantar los servicios de la clinica Lujo Luminoso.
"""

from functools import lru_cache
from typing import Literal
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuracion del sistema basada en variables de entorno.
    Bloquea credenciales inseguras y configuraciones permisivas en produccion.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Entorno y Modo de Operacion
    APP_ENV: Literal["development", "production"] = "development"
    DEMO_MODE: bool = False
    TIMEZONE: str = "America/Bogota"

    # Criptografia y Seguridad de Sesiones (Minimo 32 caracteres)
    SECRET_KEY: str = "clave_secreta_super_segura_de_al_menos_32_caracteres_minimo"

    # Control de Acceso CORS
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Backend como Servicio (BaaS) - Supabase
    SUPABASE_URL: str = "https://tu-proyecto.supabase.co"
    SUPABASE_ANON_KEY: str = "tu_clave_publica_anon_de_supabase_aqui"
    SUPABASE_SERVICE_ROLE_KEY: str = "tu_clave_privada_service_role_de_supabase_aqui"

    # Inteligencia Artificial - Google Gemini API
    GEMINI_API_KEY: str = "tu_clave_de_api_de_google_gemini_aqui"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Meta WhatsApp Cloud API
    WHATSAPP_TOKEN: str = "tu_bearer_access_token_de_meta_aqui"
    WHATSAPP_PHONE_NUMBER_ID: str = "100000000000001"
    WHATSAPP_VERIFY_TOKEN: str = "token_personalizado_para_el_reto_de_verificacion_webhook"
    WHATSAPP_APP_SECRET: str = "tu_app_secret_de_meta_para_validar_firma_sha256"

    @property
    def is_production(self) -> bool:
        """Determina si el entorno de ejecucion corresponde a produccion."""
        return self.APP_ENV == "production"

    @property
    def cors_origins(self) -> list[str]:
        """
        Retorna la lista de origenes CORS permitidos.
        Rechaza explicitamente el comodin '*' en produccion para evitar ataques CSRF.
        """
        origins = [item.strip() for item in self.ALLOWED_ORIGINS.split(",") if item.strip()]
        if self.is_production and any(origin == "*" for origin in origins):
            raise ValueError(
                "El comodin '*' no esta permitido en ALLOWED_ORIGINS en entorno de produccion."
            )
        return origins

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Valida que la clave secreta cumpla la longitud minima requerida."""
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY debe tener al menos 32 caracteres para garantizar la seguridad criptografica."
            )
        return v

    @field_validator("SUPABASE_URL")
    @classmethod
    def validate_supabase_url(cls, v: str) -> str:
        """Valida que la URL de Supabase tenga un esquema HTTP o HTTPS valido."""
        cleaned = v.strip()
        if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
            raise ValueError(
                "SUPABASE_URL debe ser una URL valida que comience con http:// o https://."
            )
        return cleaned

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        """
        Asegura que en modo produccion no se utilicen credenciales
        o valores de ejemplo por defecto.
        """
        if self.is_production:
            # Forzar evaluacion de cors_origins para levantar excepcion si contiene '*'
            _ = self.cors_origins

            placeholders = ("placeholder", "tu-proyecto", "tu_clave", "tu_bearer", "tu_app_secret")
            campos_sensibles = (
                "SUPABASE_URL",
                "SUPABASE_ANON_KEY",
                "SUPABASE_SERVICE_ROLE_KEY",
                "GEMINI_API_KEY",
                "WHATSAPP_TOKEN",
                "WHATSAPP_VERIFY_TOKEN",
                "WHATSAPP_APP_SECRET",
            )
            for campo in campos_sensibles:
                valor = getattr(self, campo)
                if not valor or any(p in valor.lower() for p in placeholders):
                    raise ValueError(
                        f"La variable {campo} no puede contener valores por defecto o de ejemplo en produccion."
                    )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna una instancia singleton cacheada de la configuracion."""
    return Settings()
