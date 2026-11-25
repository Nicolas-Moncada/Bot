@echo off
chcp 65001 >nul
title Lujo Luminoso - Servidor Clinico Local

echo ==============================================================================
echo CLINICA ODONTOLOGICA BOUTIQUE LUJO LUMINOSO
echo Plataforma Omnicanal de Agendamiento y Operacion Clinica
echo ==============================================================================
echo.

:: 1. Verificacion de Archivo de Configuracion (.env)
if not exist ".env" (
    echo [AVISO] Archivo de configuracion .env no detectado.
    echo [INFO] Creando archivo .env a partir de .env.example...
    copy ".env.example" ".env" >nul
    echo [IMPORTANTE] Configure sus credenciales reales en .env antes de operar en produccion.
    echo.
)

:: 2. Activacion de Entorno Virtual Python
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activando entorno virtual local (.venv)...
    call .venv\Scripts\activate.bat
) else (
    echo [AVISO] No se detecto la carpeta .venv.
    echo [INFO] Utilizando el interprete Python global del sistema...
)

:: 3. Verificacion de Interprete Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No se encontro Python instalado en el sistema o no esta en el PATH.
    echo Por favor instale Python 3.11 o superior para continuar.
    pause
    exit /b 1
)

:: 4. Verificacion de Dependencias
echo [INFO] Comprobando dependencias del sistema...
python -c "import fastapi, uvicorn, supabase, pydantic, pwdlib, jose, slowapi, holidays" >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] Algunas librerias requeridas no estan instaladas.
    echo [INFO] Instalando dependencias desde requirements.txt...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Fallo la instalacion automatica de dependencias.
        pause
        exit /b 1
    )
)

:: 5. Comprobacion de Tunel Cloudflare (Opcional)
where cloudflared >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Utilidad cloudflared detectada en el sistema.
    echo [INFO] Para conectar con su dominio publico, ejecute en otra consola:
    echo        cloudflared tunnel run --token TU_TOKEN
) else (
    echo [INFO] Modo local activo. Para acceso externo configure Cloudflare Tunnel o Docker.
)
echo.

:: 6. Apertura Automatica del Navegador
echo [INFO] Abriendo las interfaces clinicas en el navegador...
start "" "http://localhost:8000"

:: 7. Inicio del Servidor ASGI FastAPI (Uvicorn)
echo [OK] Iniciando servidor de aplicacion en http://127.0.0.1:8000
echo      - Portal Paciente: http://localhost:8000/
echo      - Panel Recepcion: http://localhost:8000/admin
echo      - Modo Doctor:     http://localhost:8000/doctor
echo      - Pantalla TV:     http://localhost:8000/tv
echo.
echo Presione Ctrl+C para detener el servidor de la clinica.
echo ==============================================================================
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips="*"

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] El servidor se detuvo con codigo de salida %errorlevel%.
    pause
)
