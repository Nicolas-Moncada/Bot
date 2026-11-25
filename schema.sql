-- ==============================================================================
-- ESQUEMA MAESTRO DE BASE DE DATOS: CLINICA BOUTIQUE LUJO LUMINOSO
-- ==============================================================================
-- Capacidad clinica: 1 Doctor, 1 Sillon Odontologico
-- Motor: PostgreSQL 15+ en Supabase
-- Politicas: UUID v4 obligatorio, Row Level Security (RLS) estricto,
--            Exclusion GiST sin solapamiento temporal y Cero IDs Secuenciales.
-- Regla transversal: CERO EMOJIS en codigo, comentarios y datos.
-- ==============================================================================


-- ==============================================================================
-- PASO 1: EXTENSIONES Y FUNCIONES AUXILIARES
-- ==============================================================================

-- Habilitar pgcrypto para generacion de identificadores UUID v4 (gen_random_uuid)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Habilitar btree_gist para soportar operadores de exclusion GiST sobre rangos temporales
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Funcion reutilizable para actualizacion automatica de updated_at
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ==============================================================================
-- PASO 2: DEFINICION DE TABLAS (5 TABLAS CON UUID v4)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. Tabla: usuarios_staff
-- Credenciales y roles para administradores, doctor y personal de recepcion.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.usuarios_staff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_usuarios_staff_email_formato CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT chk_usuarios_staff_email_lowercase CHECK (email = lower(email)),
    CONSTRAINT chk_usuarios_staff_nombre_length CHECK (char_length(trim(nombre)) >= 2),
    CONSTRAINT chk_usuarios_staff_rol CHECK (rol IN ('admin', 'doctor', 'recepcion'))
);

-- ------------------------------------------------------------------------------
-- 2. Tabla: pacientes
-- Directorio maestro indexado por numero telefonico E.164 y registro de triage.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pacientes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    email TEXT NULL,
    requiere_atencion_humana BOOLEAN NOT NULL DEFAULT false,
    motivo_urgencia TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_pacientes_telefono_e164 CHECK (telefono ~ '^\+?[1-9]\d{7,14}$'),
    CONSTRAINT chk_pacientes_nombre_length CHECK (char_length(trim(nombre)) >= 2),
    CONSTRAINT chk_pacientes_email_formato CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- ------------------------------------------------------------------------------
-- 3. Tabla: turnos
-- Agenda clinica con duraciones exactas y estados del flujo de atencion.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.turnos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_sala TEXT NOT NULL,
    paciente_id UUID NOT NULL REFERENCES public.pacientes(id) ON DELETE RESTRICT,
    servicio TEXT NOT NULL,
    duracion_min INTEGER NOT NULL,
    fecha_inicio TIMESTAMPTZ NOT NULL,
    fecha_fin TIMESTAMPTZ NOT NULL,
    estado TEXT NOT NULL DEFAULT 'confirmado',
    llamado_at TIMESTAMPTZ NULL,
    origen TEXT NOT NULL,
    notas_internas TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_turnos_codigo_sala CHECK (char_length(trim(codigo_sala)) >= 2),
    CONSTRAINT chk_turnos_servicio CHECK (servicio IN ('profilaxis', 'ortodoncia', 'diseno_sonrisa', 'cirugia_implantes')),
    CONSTRAINT chk_turnos_duracion_min CHECK (duracion_min IN (30, 45, 60, 120)),
    CONSTRAINT chk_turnos_estado CHECK (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion', 'completado', 'cancelado_ausente', 'cancelado_paciente')),
    CONSTRAINT chk_turnos_origen CHECK (origen IN ('whatsapp_ia', 'web_paciente', 'panel_admin', 'demo')),
    CONSTRAINT chk_turnos_rango_valido CHECK (fecha_fin > fecha_inicio),
    CONSTRAINT chk_turnos_servicio_duracion CHECK (
        (servicio = 'profilaxis' AND duracion_min = 30) OR
        (servicio = 'ortodoncia' AND duracion_min = 45) OR
        (servicio = 'diseno_sonrisa' AND duracion_min = 60) OR
        (servicio = 'cirugia_implantes' AND duracion_min = 120)
    ),
    CONSTRAINT chk_turnos_duracion_exacta CHECK (fecha_fin = fecha_inicio + (duracion_min * INTERVAL '1 minute'))
);

-- ------------------------------------------------------------------------------
-- 4. Tabla: sesiones_chat
-- Historial conversacional para el agente de WhatsApp (contexto JSONB).
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sesiones_chat (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono TEXT NOT NULL UNIQUE,
    historial JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_sesiones_chat_telefono CHECK (telefono ~ '^\+?[1-9]\d{7,14}$'),
    CONSTRAINT chk_sesiones_chat_historial_array CHECK (jsonb_typeof(historial) = 'array')
);

-- Trigger para actualizacion automatica de timestamp en sesiones_chat
DROP TRIGGER IF EXISTS trg_sesiones_chat_updated_at ON public.sesiones_chat;
CREATE TRIGGER trg_sesiones_chat_updated_at
BEFORE UPDATE ON public.sesiones_chat
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- ------------------------------------------------------------------------------
-- 5. Tabla: festivos_bloqueos
-- Registro de festivos oficiales colombianos y bloqueos de agenda extraordinarios.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.festivos_bloqueos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha DATE NOT NULL UNIQUE,
    motivo TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT chk_festivos_bloqueos_motivo CHECK (char_length(trim(motivo)) >= 3)
);


-- ==============================================================================
-- PASO 3: BLINDAJE DE CONCURRENCIA, ANTI-ACAPARAMIENTO E INDICES
-- ==============================================================================

-- 1. Restriccion de Exclusion GiST para el Sillon Odontologico Unico
-- Intervalo semiabierto '[)' para permitir turnos contiguos (ej. 09:00-09:30 y 09:30-10:15)
-- mientras bloquea cualquier solapamiento en estados activos.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'excl_turnos_sin_solapamiento'
    ) THEN
        ALTER TABLE public.turnos
        ADD CONSTRAINT excl_turnos_sin_solapamiento
        EXCLUDE USING gist (
            tstzrange(fecha_inicio, fecha_fin, '[)') WITH &&
        )
        WHERE (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion'));
    END IF;
END $$;

-- 2. Indice Unico Parcial Anti-Acaparamiento
-- Impide fisicamente que un mismo paciente tenga mas de un turno activo simultaneamente.
CREATE UNIQUE INDEX IF NOT EXISTS idx_un_turno_activo_por_paciente
ON public.turnos(paciente_id)
WHERE (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion'));

-- 3. Indices de Rendimiento para Consultas de Agenda y Operacion
CREATE INDEX IF NOT EXISTS idx_turnos_rango ON public.turnos(fecha_inicio, fecha_fin);
CREATE INDEX IF NOT EXISTS idx_turnos_estado ON public.turnos(estado);
CREATE INDEX IF NOT EXISTS idx_turnos_paciente ON public.turnos(paciente_id);
CREATE INDEX IF NOT EXISTS idx_pacientes_telefono ON public.pacientes(telefono);
CREATE INDEX IF NOT EXISTS idx_pacientes_triage ON public.pacientes(requiere_atencion_humana) WHERE requiere_atencion_humana = true;
CREATE INDEX IF NOT EXISTS idx_sesiones_chat_telefono ON public.sesiones_chat(telefono);
CREATE INDEX IF NOT EXISTS idx_festivos_fecha ON public.festivos_bloqueos(fecha);


-- ==============================================================================
-- PASO 4: ROW LEVEL SECURITY (RLS) ESTRICTO
-- ==============================================================================

-- Habilitar y forzar RLS en todas las tablas del sistema
ALTER TABLE public.usuarios_staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usuarios_staff FORCE ROW LEVEL SECURITY;

ALTER TABLE public.pacientes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pacientes FORCE ROW LEVEL SECURITY;

ALTER TABLE public.turnos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.turnos FORCE ROW LEVEL SECURITY;

ALTER TABLE public.sesiones_chat ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sesiones_chat FORCE ROW LEVEL SECURITY;

ALTER TABLE public.festivos_bloqueos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.festivos_bloqueos FORCE ROW LEVEL SECURITY;

-- ------------------------------------------------------------------------------
-- Politicas RLS para usuarios_staff
-- Acceso exclusivo para backend via service_role. Denegacion absoluta a anon y authenticated.
-- ------------------------------------------------------------------------------
DROP POLICY IF EXISTS p_usuarios_staff_deny_all ON public.usuarios_staff;
CREATE POLICY p_usuarios_staff_deny_all
ON public.usuarios_staff
FOR ALL
TO anon, authenticated
USING (false)
WITH CHECK (false);

-- ------------------------------------------------------------------------------
-- Politicas RLS para sesiones_chat
-- Historial conversacional privado gestionado exclusivamente por el backend.
-- ------------------------------------------------------------------------------
DROP POLICY IF EXISTS p_sesiones_chat_deny_all ON public.sesiones_chat;
CREATE POLICY p_sesiones_chat_deny_all
ON public.sesiones_chat
FOR ALL
TO anon, authenticated
USING (false)
WITH CHECK (false);

-- ------------------------------------------------------------------------------
-- Politicas RLS para pacientes
-- Datos sensibles (PII y triage medico). Denegacion total de acceso directo a anon.
-- ------------------------------------------------------------------------------
DROP POLICY IF EXISTS p_pacientes_deny_anon ON public.pacientes;
CREATE POLICY p_pacientes_deny_anon
ON public.pacientes
FOR ALL
TO anon
USING (false)
WITH CHECK (false);

-- ------------------------------------------------------------------------------
-- Politicas RLS para turnos
-- 1. Lectura anonima permitida unicamente para estados activos (pantalla TV en sala de espera).
-- 2. Prohibicion absoluta de escrituras directas (INSERT, UPDATE, DELETE) desde anon o authenticated.
-- ------------------------------------------------------------------------------
DROP POLICY IF EXISTS p_turnos_select_public_tv ON public.turnos;
CREATE POLICY p_turnos_select_public_tv
ON public.turnos
FOR SELECT
TO anon, authenticated
USING (estado IN ('confirmado', 'en_sala', 'llamando', 'en_atencion'));

DROP POLICY IF EXISTS p_turnos_write_deny ON public.turnos;
CREATE POLICY p_turnos_write_deny
ON public.turnos
FOR INSERT
TO anon, authenticated
WITH CHECK (false);

DROP POLICY IF EXISTS p_turnos_update_deny ON public.turnos;
CREATE POLICY p_turnos_update_deny
ON public.turnos
FOR UPDATE
TO anon, authenticated
USING (false)
WITH CHECK (false);

DROP POLICY IF EXISTS p_turnos_delete_deny ON public.turnos;
CREATE POLICY p_turnos_delete_deny
ON public.turnos
FOR DELETE
TO anon, authenticated
USING (false);

-- ------------------------------------------------------------------------------
-- Politicas RLS para festivos_bloqueos
-- Lectura publica autorizada para visualizacion de calendario y validacion de reservas.
-- Escritura bloqueada para anon y authenticated (solo backend service_role).
-- ------------------------------------------------------------------------------
DROP POLICY IF EXISTS p_festivos_select_all ON public.festivos_bloqueos;
CREATE POLICY p_festivos_select_all
ON public.festivos_bloqueos
FOR SELECT
TO anon, authenticated
USING (true);

DROP POLICY IF EXISTS p_festivos_write_deny ON public.festivos_bloqueos;
CREATE POLICY p_festivos_write_deny
ON public.festivos_bloqueos
FOR INSERT
TO anon, authenticated
WITH CHECK (false);

DROP POLICY IF EXISTS p_festivos_update_deny ON public.festivos_bloqueos;
CREATE POLICY p_festivos_update_deny
ON public.festivos_bloqueos
FOR UPDATE
TO anon, authenticated
USING (false)
WITH CHECK (false);

DROP POLICY IF EXISTS p_festivos_delete_deny ON public.festivos_bloqueos;
CREATE POLICY p_festivos_delete_deny
ON public.festivos_bloqueos
FOR DELETE
TO anon, authenticated
USING (false);


-- ==============================================================================
-- PASO 5: CONFIGURACION DE SUPABASE REALTIME
-- ==============================================================================

-- Registro seguro e idempotente de tablas turnos y pacientes en publicacion realtime
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_publication_tables 
            WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'turnos'
        ) THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.turnos;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM pg_publication_tables 
            WHERE pubname = 'supabase_realtime' AND schemaname = 'public' AND tablename = 'pacientes'
        ) THEN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.pacientes;
        END IF;
    END IF;
EXCEPTION
    WHEN undefined_object THEN
        NULL;
END $$;

-- Replica Identity Full para asegurar que los eventos Realtime transmitan el registro integro
ALTER TABLE public.turnos REPLICA IDENTITY FULL;
ALTER TABLE public.pacientes REPLICA IDENTITY FULL;


-- ==============================================================================
-- PASO 6: BLOQUE DE REVERSION (ROLLBACK) DOCUMENTADO
-- ==============================================================================
/* === ROLLBACK SCRIPT ===
-- Para revertir completamente los cambios introducidos por este esquema en orden inverso:

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        ALTER PUBLICATION supabase_realtime DROP TABLE IF EXISTS public.turnos;
        ALTER PUBLICATION supabase_realtime DROP TABLE IF EXISTS public.pacientes;
    END IF;
EXCEPTION
    WHEN undefined_object THEN NULL;
END $$;

DROP TABLE IF EXISTS public.festivos_bloqueos CASCADE;
DROP TABLE IF EXISTS public.sesiones_chat CASCADE;
DROP TABLE IF EXISTS public.turnos CASCADE;
DROP TABLE IF EXISTS public.pacientes CASCADE;
DROP TABLE IF EXISTS public.usuarios_staff CASCADE;

DROP FUNCTION IF EXISTS public.set_updated_at() CASCADE;

-- NOTA: Descomentar las siguientes lineas unicamente si se desea remover las extensiones
-- y ninguna otra aplicacion en la base de datos las esta utilizando:
-- DROP EXTENSION IF EXISTS "btree_gist" CASCADE;
-- DROP EXTENSION IF EXISTS "pgcrypto" CASCADE;
=== END ROLLBACK SCRIPT === */
