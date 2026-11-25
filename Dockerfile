# ==============================================================================
# Clinica Odontologica Boutique "Lujo Luminoso"
# Dockerfile Endurecido para Despliegue Self-Hosted en PC de Clinica
# Cero Emojis - Usuario no-root (appuser:10001) - Healthcheck nativo
# ==============================================================================

FROM python:3.11-slim

# Variables de entorno de ejecucion
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Bogota

# Instalar dependencias del sistema y configurar zona horaria
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario y grupo sin privilegios (Punto #14 de Seguridad)
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -m -s /bin/bash appuser

WORKDIR /app

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar codigo fuente y activos de la aplicacion
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY schema.sql ./

# Asignar permisos al usuario no privilegiado
RUN chown -R appuser:appuser /app

# Conmutar al usuario de ejecucion segura
USER appuser

# Healthcheck nativo contra el endpoint de estado de FastAPI
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

EXPOSE 8000

# Arranque con proxy-headers para integracion con Cloudflare Tunnel
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
