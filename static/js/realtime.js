/**
 * Modulo de Sincronizacion en Tiempo Real y Operacion Clinica: Lujo Luminoso
 *
 * Implementa:
 *   1. Sincronizacion hibrida: Supabase Realtime (postgres_changes) + Polling LAN de respaldo.
 *   2. Sintetizador acustico sin archivos externos con AudioContext (Web Audio API nativa).
 *   3. Integracion de FullCalendar v6 para el Panel de Administracion y Recepcion.
 *   4. Modo Enfoque del Doctor con cronometro regresivo de gracia de 15 minutos (NO_SHOW_GRACE_MINUTES).
 *   5. Pantalla TV de Sala de Espera con anonimizacion PII y foco visual en paciente llamado.
 *   6. Regla Cero: CERO EMOJIS, cero innerHTML con datos de usuario y cero tokens en almacenamiento local.
 */

(function () {
    'use strict';

    // =========================================================================
    // ESTADO LOCAL DE OPERACION Y TIEMPO REAL
    // =========================================================================
    const rtState = {
        supabaseClient: null,
        calendarInstance: null,
        pollingTimer: null,
        graceTimerInterval: null,
        currentOperacionData: null,
        currentTVData: null,
        lastCallingKey: null,
        audioContext: null,
        audioEnabled: false,
        debounceTimer: null,
        selectedTurnoForDetail: null,
        instrumentalGuards: {
            profilaxis: 'Bandeja de profilaxis: pieza de mano de baja velocidad, pasta profilactica, copa de caucho, curetas universales y succion esteril.',
            ortodoncia: 'Bandeja de ortodoncia: alicates de corte distal, pinza Weingart, explorador de arcos, ligaduras esteticas y modulo elastico.',
            diseno_sonrisa: 'Bandeja de estetica: juego de carillas, resinas microhibridas, guia de color Vita, lampara de fotocurado calibrada y tira de pulir.',
            cirugia_implantes: 'Campo quirurgico esteril completo: motor de implantes, kit quirurgico oseointegradable, sutura 4-0, bisturi Bard-Parker #15 y anestesia con vasoconstrictor.'
        }
    };

    // =========================================================================
    // AYUDANTE DOM SEGURO (ANTI-XSS)
    // =========================================================================
    function domSafe(tag, attrs = {}, children = []) {
        const el = document.createElement(tag);
        for (const [key, val] of Object.entries(attrs)) {
            if (key === 'className' || key === 'class') {
                el.className = val;
            } else if (key.startsWith('on') && typeof val === 'function') {
                el.addEventListener(key.slice(2).toLowerCase(), val);
            } else if (key === 'dataset' && typeof val === 'object') {
                for (const [dKey, dVal] of Object.entries(val)) {
                    el.dataset[dKey] = dVal;
                }
            } else {
                el.setAttribute(key, val);
            }
        }
        const childList = Array.isArray(children) ? children : [children];
        for (const child of childList) {
            if (typeof child === 'string' || typeof child === 'number') {
                el.appendChild(document.createTextNode(String(child)));
            } else if (child instanceof Node) {
                el.appendChild(child);
            }
        }
        return el;
    }

    // =========================================================================
    // SINTETIZADOR ACUSTICO WEB AUDIO API (SIN ARCHIVOS EXTERNOS)
    // =========================================================================
    function getAudioContext() {
        if (!rtState.audioContext) {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (AudioContextClass) {
                rtState.audioContext = new AudioContextClass();
            }
        }
        return rtState.audioContext;
    }

    function playClinicChime() {
        try {
            const ctx = getAudioContext();
            if (!ctx) return;

            if (ctx.state === 'suspended') {
                ctx.resume();
            }

            const now = ctx.currentTime;
            // Acorde melodico armonico suave: Do5 (523.25 Hz) -> Mi5 (659.25 Hz) -> Sol5 (783.99 Hz)
            const sequence = [
                { freq: 523.25, start: 0.0, dur: 0.5 },
                { freq: 659.25, start: 0.22, dur: 0.5 },
                { freq: 783.99, start: 0.44, dur: 0.9 }
            ];

            for (const item of sequence) {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();

                osc.type = 'sine';
                osc.frequency.setValueAtTime(item.freq, now + item.start);

                gain.gain.setValueAtTime(0.0001, now + item.start);
                gain.gain.exponentialRampToValueAtTime(0.2, now + item.start + 0.04);
                gain.gain.exponentialRampToValueAtTime(0.0001, now + item.start + item.dur);

                osc.connect(gain);
                gain.connect(ctx.destination);

                osc.start(now + item.start);
                osc.stop(now + item.start + item.dur);
            }
        } catch (e) {
            // Falla silenciosa si las politicas del navegador impiden audio
        }
    }

    function toggleAudio() {
        const ctx = getAudioContext();
        if (ctx) {
            if (ctx.state === 'suspended') {
                ctx.resume();
            }
            rtState.audioEnabled = true;
            playClinicChime();
            updateAudioButtonUI(true);
        }
    }

    function updateAudioButtonUI(enabled) {
        const btn = document.getElementById('btn-tv-audio-toggle');
        if (btn) {
            btn.replaceChildren();
            const icon = domSafe('i', {
                'data-lucide': enabled ? 'volume-2' : 'volume-x',
                class: 'w-4 h-4 mr-1.5'
            });
            const text = domSafe('span', {}, enabled ? 'Audio de Sala Activo' : 'Activar Sonido de Sala');
            btn.appendChild(icon);
            btn.appendChild(text);
            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
        }
    }

    // =========================================================================
    // CLIENTE HTTP WRAPPER LOCAL CON MANEJO DE 401
    // =========================================================================
    async function apiCall(url, options = {}) {
        const defaultHeaders = { 'Accept': 'application/json' };
        if (options.body && typeof options.body === 'string') {
            defaultHeaders['Content-Type'] = 'application/json';
        }

        const merged = {
            credentials: 'same-origin',
            ...options,
            headers: { ...defaultHeaders, ...(options.headers || {}) }
        };

        try {
            const resp = await fetch(url, merged);
            if (resp.status === 401) {
                // Manejo estricto de sesion expirada (Punto #11 de Seguridad)
                handleSessionExpired();
                return { ok: false, status: 401, data: null };
            }

            let data = null;
            const ct = resp.headers.get('content-type') || '';
            if (ct.includes('application/json')) {
                data = await resp.json();
            }
            return { ok: resp.ok, status: resp.status, data };
        } catch (err) {
            return { ok: false, status: 0, data: null };
        }
    }

    function handleSessionExpired() {
        if (window.ClinicApp && typeof window.ClinicApp.onSessionExpired === 'function') {
            window.ClinicApp.onSessionExpired();
        } else {
            const modal = document.getElementById('modal-login');
            const err = document.getElementById('login-error');
            if (modal) modal.classList.remove('hidden');
            if (err) {
                err.textContent = 'Su sesion clinica ha expirado. Por favor ingrese sus credenciales nuevamente.';
                err.classList.remove('hidden');
            }
        }
    }

    // =========================================================================
    // SINCRONIZACION HIBRIDA: SUPABASE REALTIME + LAN POLLING
    // =========================================================================
    async function initRealtimeEngine() {
        // Consultar configuracion publica
        const cfgResp = await apiCall('/api/v1/config/public');
        if (cfgResp.ok && cfgResp.data) {
            const { supabase_url, supabase_anon_key } = cfgResp.data;

            if (
                window.supabase
                && supabase_url
                && supabase_anon_key
                && !supabase_anon_key.startsWith('tu_')
            ) {
                try {
                    rtState.supabaseClient = window.supabase.createClient(supabase_url, supabase_anon_key);
                    const channel = rtState.supabaseClient.channel('lujo-luminoso-operacion');

                    channel
                        .on('postgres_changes', { event: '*', schema: 'public', table: 'turnos' }, onDatabaseChange)
                        .on('postgres_changes', { event: '*', schema: 'public', table: 'pacientes' }, onDatabaseChange)
                        .subscribe((status) => {
                            const indicator = document.getElementById('realtime-status-indicator');
                            if (indicator) {
                                indicator.className = status === 'SUBSCRIBED'
                                    ? 'inline-flex items-center gap-1.5 text-xs text-emerald-800 bg-emerald-50 px-2.5 py-1 rounded-lg border border-emerald-200'
                                    : 'inline-flex items-center gap-1.5 text-xs text-slate-600 bg-slate-100 px-2.5 py-1 rounded-lg border border-slate-200';
                            }
                        });
                } catch (e) {
                    // Si falla el socket externo, el polling LAN entra como respaldo 100%
                }
            }
        }

        // Iniciar Polling LAN continuo cada 8 segundos (resiliente para PC de consultorio)
        if (!rtState.pollingTimer) {
            rtState.pollingTimer = setInterval(() => {
                if (document.visibilityState === 'visible') {
                    refreshActiveOperationalView();
                }
            }, 8000);
        }

        // Cargar vista operativa inicial
        refreshActiveOperationalView();
    }

    function onDatabaseChange() {
        if (rtState.debounceTimer) clearTimeout(rtState.debounceTimer);
        rtState.debounceTimer = setTimeout(() => {
            refreshActiveOperationalView();
        }, 300);
    }

    function refreshActiveOperationalView() {
        const activeView = (window.ClinicApp && window.ClinicApp.getCurrentView)
            ? window.ClinicApp.getCurrentView()
            : 'paciente';

        if (activeView === 'admin') {
            loadAdminData();
            if (rtState.calendarInstance) {
                rtState.calendarInstance.refetchEvents();
            }
        } else if (activeView === 'doctor') {
            loadDoctorData();
        } else if (activeView === 'tv') {
            loadTVData();
        }
    }

    // =========================================================================
    // VISTA 2: PANEL DE ADMINISTRACION, FULLCALENDAR, RETRASOS Y FESTIVOS
    // =========================================================================
    function initAdminCalendar() {
        const calendarEl = document.getElementById('admin-fullcalendar') || document.getElementById('fullcalendar-container');
        if (!calendarEl || typeof FullCalendar === 'undefined') return;

        if (rtState.calendarInstance) {
            rtState.calendarInstance.destroy();
        }

        calendarEl.replaceChildren();

        rtState.calendarInstance = new FullCalendar.Calendar(calendarEl, {
            initialView: 'timeGridWeek',
            locale: 'es',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'timeGridWeek,timeGridDay'
            },
            buttonText: {
                today: 'Hoy',
                week: 'Semana',
                day: 'Dia'
            },
            slotMinTime: '07:00:00',
            slotMaxTime: '17:30:00',
            slotDuration: '00:15:00',
            allDaySlot: false,
            nowIndicator: true,
            hiddenDays: [0, 6], // Oculta sabados y domingos
            businessHours: [
                { daysOfWeek: [1, 2, 3, 4, 5], startTime: '07:00', endTime: '12:00' },
                { daysOfWeek: [1, 2, 3, 4, 5], startTime: '13:00', endTime: '17:00' }
            ],
            events: async function (fetchInfo, successCallback, failureCallback) {
                const startDate = String(fetchInfo.startStr || '').split('T')[0];
                const endDate = String(fetchInfo.endStr || '').split('T')[0];
                const url = '/api/v1/turnos?fecha_inicio=' + encodeURIComponent(startDate) +
                            '&fecha_fin=' + encodeURIComponent(endDate);
                const resp = await apiCall(url);
                if (resp.ok && Array.isArray(resp.data)) {
                    const mappedEvents = resp.data.map(turno => {
                        const colorMap = {
                            confirmado: '#3B6E8C',
                            en_sala: '#4A6B5D',
                            llamando: '#D97706',
                            en_atencion: '#0F766E',
                            completado: '#64748B',
                            cancelado_paciente: '#94A3B8',
                            cancelado_ausente: '#94A3B8'
                        };
                        const pacienteNombre = turno.paciente ? turno.paciente.nombre : 'Paciente';
                        return {
                            id: turno.id,
                            title: (turno.codigo_sala || 'T-XX') + ' ' + pacienteNombre,
                            start: turno.fecha_inicio,
                            end: turno.fecha_fin,
                            backgroundColor: colorMap[turno.estado] || '#64748B',
                            borderColor: colorMap[turno.estado] || '#64748B',
                            extendedProps: turno
                        };
                    });
                    successCallback(mappedEvents);
                } else {
                    failureCallback();
                }
            },
            eventClick: function (info) {
                openTurnoDetailModal(info.event.extendedProps);
            }
        });

        rtState.calendarInstance.render();
    }

    async function loadAdminData() {
        const resp = await apiCall('/api/v1/operacion/estado-actual');
        if (resp.ok && resp.data) {
            rtState.currentOperacionData = resp.data;
            renderTriageAlerts(resp.data.alertas_triage || []);
            loadFestivosList();
        }
    }

    function renderTriageAlerts(alertas) {
        const container = document.getElementById('triage-alerts-container');
        if (!container) return;

        container.replaceChildren();

        if (alertas.length === 0) {
            return;
        }

        for (const paciente of alertas) {
            const card = domSafe('div', {
                class: 'p-4 rounded-xl bg-rose-50/90 border border-rose-200 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs'
            }, [
                domSafe('div', { class: 'flex items-start gap-3' }, [
                    domSafe('div', { class: 'w-8 h-8 rounded-lg bg-rose-600 text-white flex items-center justify-center shrink-0 mt-0.5' }, [
                        domSafe('i', { 'data-lucide': 'alert-octagon', class: 'w-4 h-4' })
                    ]),
                    domSafe('div', {}, [
                        domSafe('div', { class: 'flex items-center gap-2' }, [
                            domSafe('span', { class: 'font-bold text-rose-950 text-sm' }, paciente.nombre || 'Paciente Sin Nombre'),
                            domSafe('span', { class: 'font-mono text-slate-500 text-[11px]' }, paciente.telefono)
                        ]),
                        domSafe('p', { class: 'text-rose-900 mt-1' }, [
                            domSafe('span', { class: 'font-semibold' }, 'Motivo de Urgencia Clinica: '),
                            domSafe('span', {}, paciente.motivo_urgencia || 'Sin descripcion de sintomas')
                        ])
                    ])
                ]),
                domSafe('button', {
                    type: 'button',
                    class: 'btn-compact btn-primary bg-rose-700 hover:bg-rose-800 text-xs shrink-0 self-start sm:self-auto',
                    onclick: () => resolverTriagePrompt(paciente.id, paciente.nombre)
                }, [
                    domSafe('i', { 'data-lucide': 'check-circle-2', class: 'w-3.5 h-3.5' }),
                    domSafe('span', {}, 'Marcar Urgencia Atendida')
                ])
            ]);

            container.appendChild(card);
        }

        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    async function resolverTriagePrompt(pacienteId, pacienteNombre) {
        const nota = prompt('Ingrese la nota de evolucion clinica para registrar la resolucion del triage de ' + pacienteNombre + ':');
        if (!nota || nota.trim().length < 5) {
            alert('La nota de evolucion medica debe tener al menos 5 caracteres.');
            return;
        }

        const payload = JSON.stringify({ nota_evolucion: nota.trim() });
        const resp = await apiCall('/api/v1/operacion/triage/' + encodeURIComponent(pacienteId) + '/resolver', {
            method: 'POST',
            body: payload
        });

        if (resp.ok) {
            alert('Alerta de triage resuelta exitosamente.');
            loadAdminData();
        } else {
            alert('No fue posible resolver el triage: ' + (resp.data && resp.data.message ? resp.data.message : 'Error de permisos o servidor'));
        }
    }

    // Modal de Detalle de Turno y Acciones Rapidas de Recepcion
    function openTurnoDetailModal(turno) {
        rtState.selectedTurnoForDetail = turno;
        const modal = document.getElementById('modal-turno-detail');
        if (!modal) return;

        const codEl = document.getElementById('detail-turno-codigo');
        const pacEl = document.getElementById('detail-turno-paciente');
        const telEl = document.getElementById('detail-turno-telefono');
        const srvEl = document.getElementById('detail-turno-servicio');
        const estEl = document.getElementById('detail-turno-estado');
        const fchEl = document.getElementById('detail-turno-horario');
        const notEl = document.getElementById('detail-turno-notas');

        if (codEl) codEl.textContent = turno.codigo_sala || 'T-XX';
        if (pacEl) pacEl.textContent = turno.paciente ? turno.paciente.nombre : 'Paciente';
        if (telEl) telEl.textContent = turno.paciente ? turno.paciente.telefono : '-';
        if (srvEl) srvEl.textContent = turno.servicio || '-';
        if (estEl) estEl.textContent = turno.estado || '-';

        const horaInicio = turno.fecha_inicio ? new Date(turno.fecha_inicio).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
        const horaFin = turno.fecha_fin ? new Date(turno.fecha_fin).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
        if (fchEl) fchEl.textContent = horaInicio + ' - ' + horaFin;

        if (notEl) {
            notEl.textContent = turno.notas_internas || 'Sin notas clinicas registradas.';
        }

        // Habilitar o deshabilitar botones segun el estado actual
        const btnEnSala = document.getElementById('btn-action-en-sala');
        const btnLlamar = document.getElementById('btn-action-llamar');
        const btnCancelar = document.getElementById('btn-action-cancelar-paciente');

        if (btnEnSala) btnEnSala.disabled = (turno.estado !== 'confirmado');
        if (btnLlamar) btnLlamar.disabled = (turno.estado !== 'confirmado' && turno.estado !== 'en_sala');
        if (btnCancelar) btnCancelar.disabled = (turno.estado === 'completado' || turno.estado.startsWith('cancelado'));

        modal.classList.remove('hidden');
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    function closeTurnoDetailModal() {
        const modal = document.getElementById('modal-turno-detail');
        if (modal) modal.classList.add('hidden');
        rtState.selectedTurnoForDetail = null;
    }

    async function cambiarEstadoDesdeModal(nuevoEstado) {
        if (!rtState.selectedTurnoForDetail) return;
        const turnoId = rtState.selectedTurnoForDetail.id;

        let motivo = null;
        if (nuevoEstado === 'cancelado_paciente') {
            motivo = prompt('Ingrese el motivo de cancelacion solicitado por el paciente:');
            if (!motivo) return;
        }

        const payload = JSON.stringify({
            nuevo_estado: nuevoEstado,
            motivo_cancelacion: motivo
        });

        const resp = await apiCall('/api/v1/operacion/turnos/' + encodeURIComponent(turnoId) + '/estado', {
            method: 'PATCH',
            body: payload
        });

        if (resp.ok) {
            closeTurnoDetailModal();
            refreshActiveOperationalView();
        } else {
            alert('Error al actualizar estado: ' + (resp.data && resp.data.message ? resp.data.message : 'Accion rechazada'));
        }
    }

    // Control de Retraso Masivo
    async function aplicarRetrasoMasivo(minutos) {
        const confirmado = confirm('Desea aplicar un retraso masivo de +' + minutos + ' minutos a todas las citas posteriores del dia?');
        if (!confirmado) return;

        const payload = JSON.stringify({
            minutos_retraso: Number(minutos),
            motivo: 'Retraso clinico reportado desde el panel'
        });

        const resp = await apiCall('/api/v1/operacion/retraso', {
            method: 'POST',
            body: payload
        });

        const feedback = document.getElementById('retraso-feedback');
        if (resp.ok && resp.data) {
            const data = resp.data;
            if (feedback) {
                feedback.replaceChildren();
                feedback.className = 'mt-3 p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs text-emerald-900 block';
                feedback.appendChild(domSafe('p', { class: 'font-semibold' }, data.mensaje || 'Retraso aplicado exitosamente.'));
                feedback.appendChild(domSafe('p', { class: 'text-[11px] mt-0.5 text-emerald-800' },
                    'Turnos desplazados en orden inverso: ' + data.turnos_afectados.length + '. Nueva hora de cierre estimada: ' + data.hora_cierre_estimada
                ));
            }
            refreshActiveOperationalView();
        } else {
            if (feedback) {
                feedback.replaceChildren();
                feedback.className = 'mt-3 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-900 block';
                feedback.appendChild(domSafe('p', { class: 'font-semibold' }, 'Fallo al aplicar retraso: ' + (resp.data && resp.data.message ? resp.data.message : 'Error')));
            }
        }
    }

    // Gestion de Festivos y Bloqueos
    async function loadFestivosList() {
        const listContainer = document.getElementById('festivos-list');
        if (!listContainer) return;

        const currentYear = new Date().getFullYear();
        const resp = await apiCall('/api/v1/operacion/festivos?anio=' + currentYear);
        if (resp.ok && Array.isArray(resp.data)) {
            listContainer.replaceChildren();
            if (resp.data.length === 0) {
                listContainer.appendChild(domSafe('p', { class: 'text-xs text-slate-400 italic' }, 'Sin bloqueos extraordinarios registrados.'));
                return;
            }

            for (const f of resp.data) {
                const item = domSafe('div', { class: 'flex items-center justify-between p-2 rounded-lg bg-slate-50 border border-slate-200 text-xs' }, [
                    domSafe('span', { class: 'font-medium text-slate-800' }, f.fecha),
                    domSafe('span', { class: 'text-slate-500' }, f.descripcion),
                    domSafe('span', { class: 'text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-700' }, f.es_oficial_pais ? 'Oficial' : 'Clinico')
                ]);
                listContainer.appendChild(item);
            }
        }
    }

    async function handleCrearBloqueoSubmit(event) {
        event.preventDefault();
        const dateInput = document.getElementById('bloqueo-fecha');
        const descInput = document.getElementById('bloqueo-descripcion');

        if (!dateInput || !descInput) return;
        const fecha = dateInput.value;
        const descripcion = descInput.value.trim();

        if (!fecha || descripcion.length < 3) {
            alert('Seleccione fecha e ingrese una descripcion de al menos 3 caracteres.');
            return;
        }

        const payload = JSON.stringify({ fecha, descripcion });
        const resp = await apiCall('/api/v1/operacion/festivos', {
            method: 'POST',
            body: payload
        });

        if (resp.ok) {
            descInput.value = '';
            alert('Bloqueo clinico registrado exitosamente.');
            loadFestivosList();
        } else {
            alert('No fue posible crear el bloqueo: ' + (resp.data && resp.data.message ? resp.data.message : 'Error'));
        }
    }

    // =========================================================================
    // VISTA 3: MODO ENFOQUE DEL DOCTOR, CRONOMETRO 15 MIN Y AVISOS WHATSAPP
    // =========================================================================
    async function loadDoctorData() {
        const resp = await apiCall('/api/v1/operacion/estado-actual');
        if (!resp.ok || !resp.data) return;

        const data = resp.data;
        rtState.currentOperacionData = data;

        renderCurrentPatientCard(data.turno_en_atencion, data.turno_llamando, data.siguiente_turno);
        renderNextProcedureCard(data.siguiente_turno);
        renderWaitingQueueAndIncidencias(data.cola_espera || [], data.turnos_del_dia || []);
    }

    function renderCurrentPatientCard(enAtencion, llamando, siguienteTurno) {
        const card = document.getElementById('current-patient-card');
        const timerCard = document.getElementById('grace-timer-display');

        // Sincronizar elementos de #view-doctor en index.html
        const docCodigo = document.getElementById('doctor-paciente-codigo');
        const docNombre = document.getElementById('doctor-paciente-nombre');
        const docServicio = document.getElementById('doctor-paciente-servicio');
        const docTimerVal = document.getElementById('doctor-timer-val');
        const docTimerState = document.getElementById('doctor-timer-state');

        const activo = enAtencion || llamando || siguienteTurno || null;
        if (activo) {
            rtState.selectedTurnoForDetail = activo;
        }

        if (docCodigo && docNombre && docServicio) {
            if (enAtencion) {
                docCodigo.textContent = enAtencion.codigo_sala || 'T-XX';
                docNombre.textContent = enAtencion.paciente ? enAtencion.paciente.nombre : 'Paciente en Atencion';
                docServicio.textContent = 'En Sillon Clinico • ' + (enAtencion.servicio || 'Procedimiento');
                if (docTimerVal) docTimerVal.textContent = 'ACTIVO';
                if (docTimerState) docTimerState.textContent = 'En atencion odontologica';
            } else if (llamando) {
                docCodigo.textContent = llamando.codigo_sala || 'T-XX';
                docNombre.textContent = llamando.paciente ? llamando.paciente.nombre : 'Paciente Llamado';
                docServicio.textContent = 'Llamando a Sala • ' + (llamando.servicio || 'Procedimiento');
                if (docTimerState) docTimerState.textContent = 'Ventana de gracia (15 min)';
            } else if (siguienteTurno) {
                docCodigo.textContent = siguienteTurno.codigo_sala || 'T-XX';
                docNombre.textContent = siguienteTurno.paciente ? siguienteTurno.paciente.nombre : 'Siguiente Paciente';
                docServicio.textContent = 'En Espera • ' + (siguienteTurno.servicio || 'Procedimiento');
                if (docTimerVal) docTimerVal.textContent = '15:00';
                if (docTimerState) docTimerState.textContent = 'Listo para llamar';
            } else {
                docCodigo.textContent = 'T-XX';
                docNombre.textContent = 'Sin paciente activo';
                docServicio.textContent = 'Seleccione un turno desde el calendario para iniciar procedimiento.';
                if (docTimerVal) docTimerVal.textContent = '15:00';
                if (docTimerState) docTimerState.textContent = 'Ventana de gracia';
            }
        }

        // Limpiar cronometro previo si existia
        if (rtState.graceTimerInterval) {
            clearInterval(rtState.graceTimerInterval);
            rtState.graceTimerInterval = null;
        }

        if (llamando && llamando.llamado_at) {
            iniciarCronometroGracia(llamando.llamado_at);
        }

        if (!card) return;

        card.replaceChildren();

        // Caso 1: Paciente actualmente en atencion en sillon
        if (enAtencion) {
            if (timerCard) timerCard.classList.add('hidden');

            const pacienteNombre = enAtencion.paciente ? enAtencion.paciente.nombre : 'Paciente';
            const horaInicio = enAtencion.fecha_inicio ? new Date(enAtencion.fecha_inicio).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
            const horaFin = enAtencion.fecha_fin ? new Date(enAtencion.fecha_fin).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';

            const content = domSafe('div', { class: 'space-y-4' }, [
                domSafe('div', { class: 'flex items-center justify-between' }, [
                    domSafe('span', { class: 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold' }, [
                        domSafe('span', { class: 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse' }),
                        domSafe('span', {}, 'En Sillon Clinico')
                    ]),
                    domSafe('span', { class: 'font-mono text-xs text-slate-500' }, horaInicio + ' - ' + horaFin)
                ]),
                domSafe('div', {}, [
                    domSafe('span', { class: 'text-3xl font-bold text-slate-900 block' }, enAtencion.codigo_sala || 'T-XX'),
                    domSafe('h2', { class: 'text-xl font-semibold text-slate-800 mt-1' }, pacienteNombre),
                    domSafe('p', { class: 'text-sm font-medium text-[#4A6B5D] mt-0.5' }, enAtencion.servicio || 'Procedimiento')
                ]),
                domSafe('div', { class: 'p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs text-slate-600' }, [
                    domSafe('span', { class: 'font-semibold block text-slate-700' }, 'Notas Internas / Incidencias:'),
                    domSafe('p', { class: 'mt-0.5' }, enAtencion.notas_internas || 'Sin notas especiales para este turno.')
                ]),
                domSafe('div', { class: 'pt-2' }, [
                    domSafe('button', {
                        type: 'button',
                        class: 'w-full btn-compact btn-primary bg-emerald-700 hover:bg-emerald-800 py-3 text-sm font-semibold shadow-sm',
                        onclick: () => cambiarEstadoTurnoDoctor(enAtencion.id, 'completado')
                    }, [
                        domSafe('i', { 'data-lucide': 'check-circle', class: 'w-4 h-4' }),
                        domSafe('span', {}, 'Finalizar Procedimiento (completado)')
                    ])
                ])
            ]);

            card.appendChild(content);
            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
            return;
        }

        // Caso 2: Turno actualmente en estado llamando (Activacion de Cronometro de Gracia de 15 Minutos)
        if (llamando) {
            if (timerCard) timerCard.classList.remove('hidden');

            const pacienteNombre = llamando.paciente ? llamando.paciente.nombre : 'Paciente';

            const content = domSafe('div', { class: 'space-y-4' }, [
                domSafe('div', { class: 'flex items-center justify-between' }, [
                    domSafe('span', { class: 'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-100 text-amber-800 text-xs font-semibold' }, [
                        domSafe('span', { class: 'w-2 h-2 rounded-full bg-amber-500 animate-ping' }),
                        domSafe('span', {}, 'Llamado Activo en Pantalla TV')
                    ]),
                    domSafe('span', { class: 'font-mono text-xs text-slate-500' }, llamando.codigo_sala || 'T-XX')
                ]),
                domSafe('div', {}, [
                    domSafe('span', { class: 'text-3xl font-bold text-amber-900 block' }, llamando.codigo_sala || 'T-XX'),
                    domSafe('h2', { class: 'text-xl font-semibold text-slate-800 mt-1' }, pacienteNombre),
                    domSafe('p', { class: 'text-sm font-medium text-slate-600 mt-0.5' }, llamando.servicio || 'Procedimiento')
                ]),
                domSafe('div', { class: 'grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2' }, [
                    domSafe('button', {
                        type: 'button',
                        class: 'btn-compact btn-primary bg-[#4A6B5D] hover:bg-[#3D594D] py-2.5 text-xs font-semibold',
                        onclick: () => cambiarEstadoTurnoDoctor(llamando.id, 'en_atencion')
                    }, [
                        domSafe('i', { 'data-lucide': 'play', class: 'w-3.5 h-3.5' }),
                        domSafe('span', {}, 'Paciente Ingreso - Iniciar Atencion')
                    ]),
                    domSafe('button', {
                        type: 'button',
                        id: 'btn-doctor-declarar-ausente',
                        class: 'btn-compact btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50 disabled:opacity-40 disabled:cursor-not-allowed',
                        disabled: true,
                        onclick: () => declararAusenteDoctor(llamando.id)
                    }, [
                        domSafe('i', { 'data-lucide': 'user-x', class: 'w-3.5 h-3.5' }),
                        domSafe('span', {}, 'Declarar Ausente (No-Show)')
                    ])
                ])
            ]);

            card.appendChild(content);

            // Iniciar cuenta regresiva en vivo de 15 minutos (900 segundos)
            iniciarCronometroGracia(llamando.llamado_at);

            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
            return;
        }

        // Caso 3: Sillon libre y sin llamado activo
        if (timerCard) timerCard.classList.add('hidden');

        const content = domSafe('div', { class: 'py-8 text-center space-y-4' }, [
            domSafe('div', { class: 'w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto' }, [
                domSafe('i', { 'data-lucide': 'armchair', class: 'w-6 h-6' })
            ]),
            domSafe('div', {}, [
                domSafe('h3', { class: 'text-base font-semibold text-slate-800' }, 'Sillon Clinico Libre'),
                domSafe('p', { class: 'text-xs text-slate-500 mt-0.5' },
                    siguienteTurno
                        ? 'Siguiente cita programada: ' + (siguienteTurno.codigo_sala || 'T-XX') + ' (' + (siguienteTurno.paciente ? siguienteTurno.paciente.nombre : 'Paciente') + ').'
                        : 'No hay mas pacientes programados para el dia.'
                )
            ]),
            siguienteTurno ? domSafe('div', { class: 'pt-2' }, [
                domSafe('button', {
                    type: 'button',
                    class: 'btn-compact btn-primary bg-[#4A6B5D] hover:bg-[#3D594D] px-5 py-2.5 text-sm font-semibold shadow-sm',
                    onclick: () => llamarSiguienteTurnoDoctor(siguienteTurno.id)
                }, [
                    domSafe('i', { 'data-lucide': 'bell-ring', class: 'w-4 h-4' }),
                    domSafe('span', {}, 'Llamar Paciente a Consultorio (' + (siguienteTurno.codigo_sala || 'T-XX') + ')')
                ])
            ]) : domSafe('span', { class: 'text-xs text-slate-400 italic' }, 'Jornada completada')
        ]);

        card.appendChild(content);
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    function iniciarCronometroGracia(llamadoAtStr) {
        const timerCard = document.getElementById('grace-timer-display');
        const docTimerVal = document.getElementById('doctor-timer-val');
        const docTimerState = document.getElementById('doctor-timer-state');
        const btnAusente = document.getElementById('btn-doctor-declarar-ausente') || document.getElementById('btn-doctor-ausente');
        if ((!timerCard && !docTimerVal) || !llamadoAtStr) return;

        const llamadoDate = new Date(llamadoAtStr).getTime();
        const graceSeconds = 900; // 15 minutos exactos

        function tick() {
            const now = Date.now();
            const elapsed = Math.floor((now - llamadoDate) / 1000);
            const remaining = Math.max(0, graceSeconds - elapsed);

            const mins = Math.floor(remaining / 60);
            const secs = remaining % 60;
            const timeFormatted = String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');

            if (docTimerVal) {
                docTimerVal.textContent = timeFormatted;
            }
            if (docTimerState) {
                docTimerState.textContent = remaining > 0 ? 'Ventana de gracia en curso' : 'No-Show Habilitado';
            }

            if (timerCard) {
                timerCard.replaceChildren();
                if (remaining > 0) {
                    timerCard.appendChild(domSafe('div', { class: 'flex items-center justify-between text-xs' }, [
                        domSafe('div', { class: 'flex items-center gap-2 text-slate-700' }, [
                            domSafe('i', { 'data-lucide': 'timer', class: 'w-4 h-4 text-amber-600' }),
                            domSafe('span', { class: 'font-semibold' }, 'Ventana de Gracia Legal en Curso:')
                        ]),
                        domSafe('span', { class: 'font-mono text-sm font-bold text-amber-700' }, timeFormatted + ' restantes')
                    ]));
                } else {
                    timerCard.appendChild(domSafe('div', { class: 'flex items-center justify-between text-xs' }, [
                        domSafe('div', { class: 'flex items-center gap-2 text-rose-800' }, [
                            domSafe('i', { 'data-lucide': 'alert-circle', class: 'w-4 h-4 text-rose-600' }),
                            domSafe('span', { class: 'font-bold' }, 'Ventana de 15 Minutos Expirada:')
                        ]),
                        domSafe('span', { class: 'font-mono text-sm font-bold text-rose-600' }, '00:00 (No-Show Habilitado)')
                    ]));
                }
            }

            if (btnAusente) {
                btnAusente.disabled = remaining > 0;
                if (remaining <= 0) {
                    btnAusente.classList.add('bg-rose-50', 'border-rose-300');
                }
            }

            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons();
            }
        }

        tick();
        rtState.graceTimerInterval = setInterval(tick, 1000);
    }

    async function cambiarEstadoTurnoDoctor(turnoId, nuevoEstado) {
        const payload = JSON.stringify({ nuevo_estado: nuevoEstado });
        const resp = await apiCall('/api/v1/operacion/turnos/' + encodeURIComponent(turnoId) + '/estado', {
            method: 'PATCH',
            body: payload
        });

        if (resp.ok) {
            loadDoctorData();
        } else {
            alert('Accion rechazada: ' + (resp.data && resp.data.message ? resp.data.message : 'Error'));
        }
    }

    async function declararAusenteDoctor(turnoId) {
        const confirmado = confirm('Desea declarar formalmente la inasistencia (cancelado_ausente) de este paciente? Se enviara un mensaje de WhatsApp para que reagende.');
        if (!confirmado) return;

        const payload = JSON.stringify({
            nuevo_estado: 'cancelado_ausente',
            motivo_cancelacion: 'Inasistencia tras expirar la ventana de gracia de 15 minutos post llamado.'
        });

        const resp = await apiCall('/api/v1/operacion/turnos/' + encodeURIComponent(turnoId) + '/estado', {
            method: 'PATCH',
            body: payload
        });

        if (resp.ok) {
            loadDoctorData();
        } else {
            alert('No se pudo declarar ausente: ' + (resp.data && resp.data.message ? resp.data.message : 'Error'));
        }
    }

    async function llamarSiguienteTurnoDoctor(turnoId) {
        const payload = JSON.stringify({ nuevo_estado: 'llamando' });
        const resp = await apiCall('/api/v1/operacion/turnos/' + encodeURIComponent(turnoId) + '/estado', {
            method: 'PATCH',
            body: payload
        });

        if (resp.ok) {
            loadDoctorData();
        } else {
            alert('Error al llamar al paciente: ' + (resp.data && resp.data.message ? resp.data.message : 'Error'));
        }
    }

    function renderNextProcedureCard(siguienteTurno) {
        const card = document.getElementById('next-procedure-prep-card');
        if (!card) return;

        card.replaceChildren();

        if (!siguienteTurno) {
            card.appendChild(domSafe('div', { class: 'py-6 text-center text-xs text-slate-400' }, 'No hay turnos siguientes pendientes en la agenda de hoy.'));
            return;
        }

        const srvKey = siguienteTurno.servicio || 'profilaxis';
        const instrumentalDesc = rtState.instrumentalGuards[srvKey] || 'Bandeja de exploracion e instrumental basico esteril.';
        const horaInicio = siguienteTurno.fecha_inicio ? new Date(siguienteTurno.fecha_inicio).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
        const pacNombre = siguienteTurno.paciente ? siguienteTurno.paciente.nombre : 'Paciente';

        const content = domSafe('div', { class: 'space-y-3 text-xs' }, [
            domSafe('div', { class: 'flex items-center justify-between' }, [
                domSafe('span', { class: 'font-semibold text-slate-900 text-sm' }, (siguienteTurno.codigo_sala || 'T-XX') + ' - ' + pacNombre),
                domSafe('span', { class: 'font-mono text-slate-500' }, horaInicio)
            ]),
            domSafe('div', { class: 'flex items-center gap-2' }, [
                domSafe('span', { class: 'font-medium text-[#4A6B5D]' }, srvKey.toUpperCase()),
                domSafe('span', { class: 'text-slate-400' }, '&bull;'),
                domSafe('span', { class: 'px-1.5 py-0.5 rounded bg-slate-100 text-slate-700' }, siguienteTurno.estado)
            ]),
            domSafe('div', { class: 'p-3 rounded-xl bg-slate-50 border border-slate-200' }, [
                domSafe('span', { class: 'font-semibold text-slate-800 block mb-1' }, 'Preparacion de Instrumental Quirurgico:'),
                domSafe('p', { class: 'text-slate-600 leading-relaxed' }, instrumentalDesc)
            ])
        ]);

        card.appendChild(content);
    }

    function renderWaitingQueueAndIncidencias(colaEspera, turnosDelDia) {
        const queueContainer = document.getElementById('waiting-queue-list');
        if (!queueContainer) return;

        queueContainer.replaceChildren();

        // 1. Cola de espera en sala
        const queueHeader = domSafe('h4', { class: 'text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2' }, 'Pacientes en Sala de Espera');
        queueContainer.appendChild(queueHeader);

        if (colaEspera.length === 0) {
            queueContainer.appendChild(domSafe('p', { class: 'text-xs text-slate-400 italic mb-4' }, 'Sin pacientes esperando en sala.'));
        } else {
            const listDiv = domSafe('div', { class: 'space-y-2 mb-4' });
            for (const turno of colaEspera) {
                const hora = turno.fecha_inicio ? new Date(turno.fecha_inicio).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
                const item = domSafe('div', { class: 'p-2.5 rounded-lg bg-slate-50 border border-slate-200 flex items-center justify-between text-xs' }, [
                    domSafe('div', {}, [
                        domSafe('span', { class: 'font-bold text-slate-900 mr-2' }, turno.codigo_sala || 'T-XX'),
                        domSafe('span', { class: 'text-slate-800' }, turno.paciente ? turno.paciente.nombre : 'Paciente')
                    ]),
                    domSafe('span', { class: 'font-mono text-slate-500' }, hora)
                ]);
                listDiv.appendChild(item);
            }
            queueContainer.appendChild(listDiv);
        }

        // 2. Feed de Incidencias y Cancelaciones de WhatsApp
        const incidenciasHeader = domSafe('h4', { class: 'text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 pt-2 border-t border-slate-200' }, 'Avisos y Cancelaciones Recientes (WhatsApp)');
        queueContainer.appendChild(incidenciasHeader);

        const incidencias = turnosDelDia.filter(t => {
            const notas = t.notas_internas || '';
            return t.estado === 'cancelado_paciente' || notas.includes('[AVISO PACIENTE]') || notas.includes('[CANCELADO POR PACIENTE]');
        });

        if (incidencias.length === 0) {
            queueContainer.appendChild(domSafe('p', { class: 'text-xs text-slate-400 italic' }, 'Cero incidencias o cancelaciones reportadas hoy.'));
        } else {
            const feedDiv = domSafe('div', { class: 'space-y-2' });
            for (const t of incidencias) {
                const pacNombre = t.paciente ? t.paciente.nombre : 'Paciente';
                const isCancelado = t.estado === 'cancelado_paciente';
                const item = domSafe('div', {
                    class: isCancelado
                        ? 'p-2.5 rounded-lg bg-rose-50/80 border border-rose-200 text-xs text-rose-900'
                        : 'p-2.5 rounded-lg bg-amber-50/80 border border-amber-200 text-xs text-amber-900'
                }, [
                    domSafe('div', { class: 'flex items-center justify-between font-semibold' }, [
                        domSafe('span', {}, (t.codigo_sala || 'T-XX') + ' ' + pacNombre),
                        domSafe('span', { class: 'text-[10px] uppercase font-bold' }, isCancelado ? 'Cancelado' : 'Aviso Retraso')
                    ]),
                    domSafe('p', { class: 'mt-1 text-[11px] opacity-90' }, t.notas_internas || 'Sin detalle')
                ]);
                feedDiv.appendChild(item);
            }
            queueContainer.appendChild(feedDiv);
        }
    }

    // =========================================================================
    // VISTA 4: PANTALLA TV DE SALA DE ESPERA CON SINTETIZADOR WEB AUDIO API
    // =========================================================================
    async function loadTVData() {
        const resp = await apiCall('/api/v1/turnos/pantalla-tv');
        if (!resp.ok || !resp.data) return;

        const data = resp.data;
        rtState.currentTVData = data;

        const turnos = Array.isArray(data) ? data : (data.turnos_espera || []);
        const turnoLlamado = Array.isArray(data)
            ? (turnos.find(t => t.estado === 'llamando') || turnos.find(t => t.estado === 'en_atencion') || null)
            : (data.turno_llamado || null);
        const turnosEspera = Array.isArray(data)
            ? turnos.filter(t => !turnoLlamado || t.id !== turnoLlamado.id)
            : (data.turnos_espera || []);

        renderTVCallingSpotlight(turnoLlamado);
        renderTVUpcomingGrid(turnosEspera);
    }

    function renderTVCallingSpotlight(turnoLlamado) {
        const tvCodigo = document.getElementById('tv-current-codigo');
        const tvNombre = document.getElementById('tv-current-nombre');
        const tvServicio = document.getElementById('tv-current-servicio');

        if (tvCodigo && tvNombre && tvServicio) {
            if (turnoLlamado) {
                const currentKey = turnoLlamado.id + '_' + (turnoLlamado.llamado_at || '');
                if (currentKey !== rtState.lastCallingKey) {
                    rtState.lastCallingKey = currentKey;
                    playClinicChime();
                }
                tvCodigo.textContent = turnoLlamado.codigo_sala || 'T-01';
                tvNombre.textContent = turnoLlamado.nombre_mostrar || 'Paciente';
                tvServicio.textContent = turnoLlamado.estado === 'en_atencion'
                    ? 'En Atencion Odontologica • Consultorio Principal'
                    : 'Consultorio Principal - Favor Ingresar';
            } else {
                tvCodigo.textContent = 'T-XX';
                tvNombre.textContent = 'Esperando Proximo Llamado';
                tvServicio.textContent = 'Por favor pase al consultorio principal cuando sea anunciado';
            }
        }

        const spotlight = document.getElementById('tv-calling-spotlight');
        if (!spotlight) return;

        spotlight.replaceChildren();

        if (turnoLlamado) {
            const currentKey = turnoLlamado.id + '_' + (turnoLlamado.llamado_at || '');

            // Si es un nuevo llamado en sala, reproducir el acorde sintetizado con Web Audio API
            if (currentKey !== rtState.lastCallingKey) {
                rtState.lastCallingKey = currentKey;
                playClinicChime();
            }

            spotlight.className = 'tv-glow-card tv-calling-active p-8 rounded-2xl text-center space-y-4';

            const content = [
                domSafe('span', { class: 'text-sm font-semibold uppercase tracking-widest text-[#4A6B5D] block' }, 'Turno Llamado a Consulta'),
                domSafe('div', { class: 'py-6' }, [
                    domSafe('span', { class: 'text-8xl font-black text-white tracking-tight block drop-shadow-lg' }, turnoLlamado.codigo_sala || 'T-01'),
                    domSafe('span', { class: 'text-3xl font-medium text-slate-200 mt-3 block' }, turnoLlamado.nombre_mostrar || 'Paciente'),
                    domSafe('span', { class: 'text-xs uppercase tracking-widest text-emerald-400 font-semibold mt-2 block' }, turnoLlamado.servicio || '')
                ]),
                domSafe('p', { class: 'text-sm font-medium text-emerald-300 bg-emerald-950/60 py-2 px-4 rounded-xl border border-emerald-800/80 inline-block' },
                    'Consultorio Principal - Favor Ingresar'
                )
            ];

            for (const c of content) spotlight.appendChild(c);
        } else {
            spotlight.className = 'tv-glow-card p-8 rounded-2xl text-center space-y-4';
            const content = [
                domSafe('span', { class: 'text-sm font-semibold uppercase tracking-widest text-slate-400 block' }, 'Sala de Espera'),
                domSafe('div', { class: 'py-8' }, [
                    domSafe('span', { class: 'text-6xl font-bold text-slate-600 tracking-tight block' }, '--'),
                    domSafe('span', { class: 'text-xl font-medium text-slate-400 mt-2 block' }, 'Esperando llamado del doctor...')
                ]),
                domSafe('p', { class: 'text-xs text-slate-500' }, 'Por favor tome asiento; su codigo sera anunciado en esta pantalla.')
            ];
            for (const c of content) spotlight.appendChild(c);
        }
    }

    function renderTVUpcomingGrid(turnosEspera) {
        const grid = document.getElementById('tv-upcoming-grid');
        if (!grid) return;

        grid.replaceChildren();

        const title = domSafe('span', { class: 'text-xs font-semibold uppercase tracking-widest text-slate-400 block mb-3' }, 'Proximos Turnos');
        grid.appendChild(title);

        if (turnosEspera.length === 0) {
            grid.appendChild(domSafe('div', { class: 'py-8 text-center text-xs text-slate-500 italic' }, 'Cero pacientes adicionales en turno en este momento.'));
            return;
        }

        const list = domSafe('div', { class: 'space-y-2.5' });
        for (const t of turnosEspera) {
            const item = domSafe('div', { class: 'p-3 rounded-xl bg-slate-800/70 border border-slate-700/60 flex items-center justify-between text-sm' }, [
                domSafe('div', { class: 'flex items-center gap-3' }, [
                    domSafe('span', { class: 'font-mono font-bold text-emerald-400 text-base' }, t.codigo_sala || 'T-XX'),
                    domSafe('span', { class: 'text-slate-200' }, t.nombre_mostrar || 'Paciente')
                ]),
                domSafe('span', { class: 'text-xs px-2 py-0.5 rounded bg-slate-700/80 text-slate-300 font-medium' }, t.estado)
            ]);
            list.appendChild(item);
        }
        grid.appendChild(list);
    }

    // =========================================================================
    // EXPOSICION DE INTERFAZ GLOBAL Y EVENTOS
    // =========================================================================
    window.RealtimeManager = Object.assign(window.RealtimeManager || {}, {
        init: initRealtimeEngine,
        syncActiveView: function (viewName) {
            refreshActiveOperationalView();
            if (viewName && typeof window.RealtimeManager.onViewChanged === 'function') {
                window.RealtimeManager.onViewChanged(viewName);
            }
        },
        refreshActiveView: refreshActiveOperationalView,
        refreshAll: function () {
            loadAdminData();
            loadDoctorData();
            loadTVData();
        },
        loadAdminDashboard: loadAdminData,
        loadDoctorDashboard: loadDoctorData,
        loadTvDashboard: loadTVData,
        onViewChanged: function (viewName) {
            if (viewName === 'admin') {
                initAdminCalendar();
                loadAdminData();
            } else if (viewName === 'doctor') {
                loadDoctorData();
            } else if (viewName === 'tv') {
                loadTVData();
            }
        },
        aplicarRetraso: aplicarRetrasoMasivo,
        cambiarEstadoDesdeModal: cambiarEstadoDesdeModal,
        closeTurnoDetailModal: closeTurnoDetailModal,
        toggleAudio: toggleAudio
    });

    // Auto-inicializar cuando el DOM este listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRealtimeEngine);
    } else {
        initRealtimeEngine();
    }
})();
