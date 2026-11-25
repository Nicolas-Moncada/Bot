/**
 * Logica de Cliente Web Segura: Clinica Odontologica Lujo Luminoso
 *
 * Directrices estrictas de blindaje:
 *   1. CERO EMOJIS en variables, strings, comentarios o logs.
 *   2. Prohibido usar innerHTML con datos de usuario o respuestas del servidor (Punto #8).
 *   3. Prohibido almacenar tokens en almacenamiento local; uso exclusivo de cookies HttpOnly (Punto #10).
 *   4. Peticiones de red siempre con credentials: "same-origin".
 *   5. Iconografia vectorial delegada exclusivamente a Lucide Icons y SVGs estandar.
 */

// Blindaje global preventivo para evitar errores de tipo 'is not a function'
window.RealtimeManager = window.RealtimeManager || {
    init: function () {},
    syncActiveView: function () {},
    refreshActiveView: function () {},
    refreshAll: function () {},
    loadAdminDashboard: function () {},
    loadDoctorDashboard: function () {},
    loadTvDashboard: function () {},
    onViewChanged: function () {},
    aplicarRetraso: function () {},
    cambiarEstadoDesdeModal: function () {},
    closeTurnoDetailModal: function () {},
    toggleAudio: function () {}
};

(function () {
    'use strict';

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // =========================================================================
    // ESTADO DE LA APLICACION EN MEMORIA DE EJECUCION
    // =========================================================================
    const state = {
        currentUser: null,
        currentView: 'landing',
        currentAdminTab: 'agenda',
        pendingView: null,
        publicConfig: null,
        selectedService: 'profilaxis',
        selectedDate: '',
        selectedSlot: null,
        captchaToken: null,
        captchaVerifiedToken: null,
        captchaMode: 'code',
        captchaSelectedIndices: [],
        captchaData: null,
        servicesCatalog: {
            profilaxis: { name: 'Profilaxis / Limpieza Profunda', duration: 30 },
            ortodoncia: { name: 'Control de Ortodoncia Invisible', duration: 45 },
            diseno_sonrisa: { name: 'Diseno de Sonrisa Digital', duration: 60 },
            cirugia_implantes: { name: 'Cirugia / Implantes Dentales', duration: 120 }
        }
    };

    // =========================================================================
    // AYUDANTE SEGURO DE CONSTRUCCION DOM (ANTI-XSS)
    // =========================================================================
    function createSafeElement(tag, attrs = {}, children = []) {
        const element = document.createElement(tag);

        for (const [key, val] of Object.entries(attrs)) {
            if (key === 'className' || key === 'class') {
                element.className = val;
            } else if (key.startsWith('on') && typeof val === 'function') {
                element.addEventListener(key.slice(2).toLowerCase(), val);
            } else if (key === 'dataset' && typeof val === 'object') {
                for (const [dKey, dVal] of Object.entries(val)) {
                    element.dataset[dKey] = dVal;
                }
            } else {
                element.setAttribute(key, val);
            }
        }

        const childList = Array.isArray(children) ? children : [children];
        for (const child of childList) {
            if (typeof child === 'string' || typeof child === 'number') {
                element.appendChild(document.createTextNode(String(child)));
            } else if (child instanceof Node) {
                element.appendChild(child);
            }
        }

        return element;
    }

    // =========================================================================
    // CLIENTE HTTP WRAPPER (HTTPONLY COOKIES SAME-ORIGIN)
    // =========================================================================
    async function apiFetch(url, options = {}) {
        const defaultHeaders = {
            'Accept': 'application/json'
        };

        if (options.body && typeof options.body === 'string') {
            defaultHeaders['Content-Type'] = 'application/json';
        }

        const mergedOptions = {
            credentials: 'same-origin',
            ...options,
            headers: {
                ...defaultHeaders,
                ...(options.headers || {})
            }
        };

        try {
            const response = await fetch(url, mergedOptions);
            let data = null;
            const contentType = response.headers.get('content-type') || '';
            if (contentType.includes('application/json')) {
                data = await response.json();
            }
            return {
                ok: response.ok,
                status: response.status,
                data: data
            };
        } catch (error) {
            return {
                ok: false,
                status: 0,
                data: {
                    status: 'error',
                    code: 'network_error',
                    message: 'Fallo de comunicacion con el servidor clinico.'
                }
            };
        }
    }

    // =========================================================================
    // GESTION DE APARTADOS Y VISTAS (SPA MULTI-PANEL)
    // =========================================================================
    function switchView(viewName) {
        let targetView = viewName || 'landing';
        if (targetView === 'paciente') targetView = 'reservar';

        // Vistas restringidas requieren sesion de personal autenticado
        if ((targetView === 'admin' || targetView === 'doctor' || targetView === 'tv') && !state.currentUser) {
            state.pendingView = targetView;
            openAuthModal('login');
            return;
        }

        const views = {
            landing: document.getElementById('view-landing'),
            reservar: document.getElementById('view-reservar'),
            admin: document.getElementById('view-admin'),
            doctor: document.getElementById('view-doctor'),
            tv: document.getElementById('view-tv')
        };

        for (const [, section] of Object.entries(views)) {
            if (section) section.classList.add('hidden');
        }

        const activeSection = views[targetView] || views.landing;
        if (activeSection) {
            activeSection.classList.remove('hidden');
        }

        // Barra superior privada de personal
        const staffBar = document.getElementById('staff-operational-bar');
        if (staffBar) {
            if (state.currentUser && (state.currentUser.rol === 'admin' || state.currentUser.rol === 'doctor' || state.currentUser.rol === 'recepcion')) {
                staffBar.classList.remove('hidden');
                const badge = document.getElementById('staff-bar-user-badge');
                if (badge) {
                    badge.textContent = state.currentUser.nombre + ' (' + state.currentUser.rol + ')';
                }
            } else {
                staffBar.classList.add('hidden');
            }
        }

        // Navegacion publica
        if (targetView === 'landing') {
            updateNavActive('inicio');
        } else {
            updateNavActive(null);
        }

        // Ajustes para Pantalla TV
        const header = document.getElementById('main-header');
        const footer = document.querySelector('footer');
        if (targetView === 'tv') {
            document.body.classList.add('bg-[#0A192F]');
            if (header) header.classList.add('hidden');
            if (footer) footer.classList.add('hidden');
        } else {
            document.body.classList.remove('bg-[#0A192F]');
            if (header) header.classList.remove('hidden');
            if (footer) footer.classList.remove('hidden');
        }

        state.currentView = targetView;
        refreshIcons();

        if (window.RealtimeManager && typeof window.RealtimeManager.onViewChanged === 'function') {
            window.RealtimeManager.onViewChanged(targetView);
        }

        if (targetView === 'admin') {
            switchAdminTab(state.currentAdminTab || 'agenda');
        }

        if (targetView === 'reservar') {
            if (!state.captchaVerifiedToken) {
                loadCaptchaChallenge();
            }
            syncDurationIndicator(state.selectedService || 'profilaxis');
            if (typeof renderCustomCalendar === 'function') {
                renderCustomCalendar();
            }
            loadAvailability();
            refreshIcons();
        }

        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    window.switchView = switchView;

    function updateNavActive(activeId) {
        const navItems = ['inicio', 'tratamientos', 'experiencia', 'contacto'];
        navItems.forEach(id => {
            const btn = document.getElementById(`nav-${id}`);
            if (!btn) return;
            if (id === activeId) {
                btn.className = 'text-sm font-semibold text-[#0A192F] border-b-2 border-[#0D9488] pb-1 transition-colors';
            } else {
                btn.className = 'text-sm font-medium text-slate-600 hover:text-[#0A192F] pb-1 border-b-2 border-transparent hover:border-slate-300 transition-colors';
            }
        });
    }
    window.updateNavActive = updateNavActive;

    function scrollToSection(sectionId) {
        if (state.currentView !== 'landing') {
            switchView('landing');
        }
        setTimeout(() => {
            if (sectionId === 'inicio') {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
                const el = document.getElementById(sectionId);
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }
            updateNavActive(sectionId);
        }, 80);
    }
    window.scrollToSection = scrollToSection;

    function selectServiceAndGo(serviceKey) {
        state.selectedService = serviceKey;
        const select = document.getElementById('select-service');
        if (select) {
            select.value = serviceKey;
        }
        syncDurationIndicator(serviceKey);
        switchView('reservar');
        loadAvailability();
    }
    window.selectServiceAndGo = selectServiceAndGo;

    function syncDurationIndicator(serviceKey) {
        const indicator = document.getElementById('selected-service-duration');
        const s = state.servicesCatalog[serviceKey];
        if (indicator && s) {
            indicator.textContent = 'Duracion: ' + s.duration + ' min';
        }
        // Sincronizar tarjetas visuales de procedimiento
        document.querySelectorAll('.booking-service-card').forEach(card => {
            const key = card.getAttribute('data-service-key');
            if (key === serviceKey) {
                card.classList.add('card-selected');
            } else {
                card.classList.remove('card-selected');
            }
        });
    }

    // =========================================================================
    // WIDGET INTERACTIVO DE SEGURIDAD "NO SOY UN ROBOT" (CAPTCHA)
    // =========================================================================
    async function loadCaptchaChallenge() {
        const res = await apiFetch('/api/v1/auth/captcha/new');
        if (!res.ok || !res.data || !res.data.data) {
            return;
        }
        state.captchaData = res.data.data;
        state.captchaToken = state.captchaData.captcha_token;
        state.captchaSelectedIndices = [];
        state.captchaVerifiedToken = null;

        renderCaptchaCanvas(state.captchaData.code);
        renderCaptchaGrid(state.captchaData.grid_items, state.captchaData.grid_instruction);
        updateCaptchaBadge(false);
    }
    window.loadCaptchaChallenge = loadCaptchaChallenge;

    function renderCaptchaCanvas(code) {
        const canvas = document.getElementById('captcha-canvas-res');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Fondo con textura ligera
        const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
        grad.addColorStop(0, '#F1F5F9');
        grad.addColorStop(1, '#E2E8F0');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Lineas de ruido
        for (let i = 0; i < 4; i++) {
            ctx.strokeStyle = (i % 2 === 0) ? 'rgba(13, 148, 136, 0.25)' : 'rgba(2, 132, 199, 0.25)';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(Math.random() * canvas.width, Math.random() * canvas.height);
            ctx.bezierCurveTo(
                Math.random() * canvas.width, Math.random() * canvas.height,
                Math.random() * canvas.width, Math.random() * canvas.height,
                Math.random() * canvas.width, Math.random() * canvas.height
            );
            ctx.stroke();
        }

        // Puntos de dispersion
        for (let i = 0; i < 30; i++) {
            ctx.fillStyle = 'rgba(100, 116, 139, 0.3)';
            ctx.fillRect(Math.random() * canvas.width, Math.random() * canvas.height, 2, 2);
        }

        // Dibujar caracteres rotados
        const colors = ['#0A192F', '#0D9488', '#0284C7', '#0F766E'];
        ctx.textBaseline = 'middle';

        for (let i = 0; i < code.length; i++) {
            const char = code[i];
            const x = 24 + i * 28;
            const y = canvas.height / 2;
            const angle = (Math.random() - 0.5) * 0.4;

            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(angle);
            ctx.font = 'bold 24px monospace';
            ctx.fillStyle = colors[i % colors.length];
            ctx.fillText(char, -8, 0);
            ctx.restore();
        }
    }

    function renderCaptchaGrid(items, instruction) {
        const container = document.getElementById('captcha-grid-tiles-res');
        const instrEl = document.getElementById('captcha-grid-instruction-res');
        if (instrEl && instruction) {
            instrEl.textContent = instruction;
        }
        if (!container || !Array.isArray(items)) return;

        container.replaceChildren();

        items.forEach((item, idx) => {
            const tile = createSafeElement('div', {
                class: 'captcha-tile',
                dataset: { index: String(idx) },
                onclick: () => toggleGridTile(idx)
            });

            const img = createSafeElement('img', {
                src: item.image,
                alt: item.label,
                class: 'captcha-tile-img',
                loading: 'lazy'
            });

            tile.appendChild(img);
            container.appendChild(tile);
        });
    }

    function toggleGridTile(index) {
        const container = document.getElementById('captcha-grid-tiles-res');
        if (!container) return;
        const tiles = container.querySelectorAll('.captcha-tile');
        const tile = tiles[index];
        if (!tile) return;

        const pos = state.captchaSelectedIndices.indexOf(index);
        if (pos > -1) {
            state.captchaSelectedIndices.splice(pos, 1);
            tile.classList.remove('selected');
            const badge = tile.querySelector('.captcha-badge-selected');
            if (badge) badge.remove();
        } else {
            if (state.captchaSelectedIndices.length >= 3) {
                // Limitar a maximo 3 seleccionados
                const first = state.captchaSelectedIndices.shift();
                const firstTile = tiles[first];
                if (firstTile) {
                    firstTile.classList.remove('selected');
                    const b = firstTile.querySelector('.captcha-badge-selected');
                    if (b) b.remove();
                }
            }
            state.captchaSelectedIndices.push(index);
            tile.classList.add('selected');
            const badge = createSafeElement('div', { class: 'captcha-badge-selected' });
            badge.appendChild(createSafeElement('i', { 'data-lucide': 'check', class: 'w-3 h-3 text-white' }));
            tile.appendChild(badge);
            refreshIcons();
        }
    }

    async function verifyCaptcha(mode) {
        if (!state.captchaToken) {
            await loadCaptchaChallenge();
            return;
        }

        let payload = {
            captcha_token: state.captchaToken,
            mode: mode
        };

        if (mode === 'code') {
            const input = document.getElementById('input-captcha-code-res');
            const codeVal = input ? input.value.trim().toUpperCase() : '';
            if (!codeVal) {
                alert('Por favor escriba el codigo de 6 caracteres.');
                return;
            }
            payload.answer_code = codeVal;
        } else if (mode === 'image_grid') {
            if (state.captchaSelectedIndices.length !== 3) {
                alert('Debe seleccionar exactamente 3 imagenes para validar el reto.');
                return;
            }
            payload.selected_indices = state.captchaSelectedIndices;
        }

        const res = await apiFetch('/api/v1/auth/captcha/verify', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        if (res.ok && res.data && res.data.data && res.data.data.captcha_verified_token) {
            state.captchaVerifiedToken = res.data.data.captcha_verified_token;
            updateCaptchaBadge(true);
        } else {
            const errMsg = (res.data && res.data.message) ? res.data.message : 'Verificacion fallida.';
            alert(errMsg);
            loadCaptchaChallenge();
        }
    }

    function updateCaptchaBadge(verified) {
        const badge = document.getElementById('captcha-badge-res');
        const box = document.getElementById('captcha-box-res');
        if (!badge) return;

        if (verified) {
            badge.className = 'text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200';
            badge.textContent = 'Verificado (No soy un robot)';
            if (box) {
                box.style.borderColor = '#0D9488';
            }
        } else {
            badge.className = 'text-[11px] text-slate-500';
            badge.textContent = 'Pendiente de verificacion';
            if (box) {
                box.style.borderColor = '#E2E8F0';
            }
        }
    }

    // =========================================================================
    // MODAL DE AUTENTICACION Y REGISTRO (#modal-auth)
    // =========================================================================
    function openAuthModal(initialTab) {
        const modal = document.getElementById('modal-auth');
        if (!modal) return;
        modal.classList.remove('hidden');
        switchAuthTab(initialTab || 'login');
    }
    window.openAuthModal = openAuthModal;

    function closeAuthModal() {
        const modal = document.getElementById('modal-auth');
        if (modal) modal.classList.add('hidden');
    }
    window.closeAuthModal = closeAuthModal;

    function switchAuthTab(tab) {
        const btnLogin = document.getElementById('tab-auth-login');
        const btnReg = document.getElementById('tab-auth-register');
        const formLogin = document.getElementById('login-form');
        const formReg = document.getElementById('register-form');

        if (tab === 'register') {
            if (btnLogin) btnLogin.classList.remove('active');
            if (btnReg) btnReg.classList.add('active');
            if (formLogin) formLogin.classList.add('hidden');
            if (formReg) formReg.classList.remove('hidden');
        } else {
            if (btnLogin) btnLogin.classList.add('active');
            if (btnReg) btnReg.classList.remove('active');
            if (formLogin) formLogin.classList.remove('hidden');
            if (formReg) formReg.classList.add('hidden');
        }
    }

    async function handleLoginSubmit(event) {
        event.preventDefault();
        const errDiv = document.getElementById('login-error');
        if (errDiv) errDiv.classList.add('hidden');

        const emailInput = document.getElementById('login-email');
        const passInput = document.getElementById('login-password');

        const payload = {
            email: emailInput ? emailInput.value.trim() : '',
            password: passInput ? passInput.value : ''
        };

        const res = await apiFetch('/api/v1/auth/login', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        if (res.ok && res.data && res.data.data) {
            state.currentUser = res.data.data.usuario;
            updateSessionUI();
            closeAuthModal();

            if (state.pendingView) {
                const pv = state.pendingView;
                state.pendingView = null;
                switchView(pv);
            } else if (state.currentUser.rol === 'doctor') {
                switchView('doctor');
            } else {
                switchView('admin');
            }
        } else {
            if (errDiv) {
                errDiv.textContent = (res.data && res.data.message) ? res.data.message : 'Credenciales invalidas.';
                errDiv.classList.remove('hidden');
            }
        }
    }

    async function handleRegisterSubmit(event) {
        event.preventDefault();
        const errDiv = document.getElementById('register-error');
        if (errDiv) errDiv.classList.add('hidden');

        const nombre = document.getElementById('reg-nombre')?.value.trim() || '';
        const telefono = document.getElementById('reg-telefono')?.value.trim() || '';
        const email = document.getElementById('reg-email')?.value.trim() || '';
        const password = document.getElementById('reg-password')?.value || '';

        const payload = {
            nombre: nombre,
            telefono: telefono,
            email: email,
            password: password,
            rol: 'recepcion'
        };

        const res = await apiFetch('/api/v1/auth/register', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        if (res.ok && res.data && res.data.data) {
            state.currentUser = res.data.data.usuario;
            updateSessionUI();
            closeAuthModal();
            alert('Cuenta creada exitosamente. Sesion iniciada.');
        } else {
            if (errDiv) {
                errDiv.textContent = (res.data && res.data.message) ? res.data.message : 'No se pudo crear la cuenta.';
                errDiv.classList.remove('hidden');
            }
        }
    }

    async function handleLogout() {
        await apiFetch('/api/v1/auth/logout', { method: 'POST' });
        state.currentUser = null;
        updateSessionUI();
        switchView('landing');
    }
    window.handleLogout = handleLogout;

    // =========================================================================
    // MODAL DE GOOGLE AUTH (#modal-google-accounts)
    // =========================================================================
    function openGoogleSelector() {
        const modal = document.getElementById('modal-google-accounts');
        if (modal) modal.classList.remove('hidden');
    }
    window.openGoogleSelector = openGoogleSelector;

    function closeGoogleSelector() {
        const modal = document.getElementById('modal-google-accounts');
        if (modal) modal.classList.add('hidden');
    }
    window.closeGoogleSelector = closeGoogleSelector;

    async function loginWithPresetGoogle(email, name) {
        const res = await apiFetch('/api/v1/auth/google', {
            method: 'POST',
            body: JSON.stringify({ email: email, nombre: name })
        });

        if (res.ok && res.data && res.data.data) {
            state.currentUser = res.data.data.usuario;
            updateSessionUI();
            closeGoogleSelector();
            closeAuthModal();

            // Si esta en vista reservar, autocompletar campos
            const inputNom = document.getElementById('input-nombre');
            const inputEml = document.getElementById('input-email');
            if (inputNom && !inputNom.value) inputNom.value = name;
            if (inputEml && !inputEml.value) inputEml.value = email;

            const checkGcal = document.getElementById('checkbox-save-gcal');
            if (checkGcal) checkGcal.checked = true;

            alert('Sesion iniciada con Google como: ' + name);
        } else {
            alert('No se pudo autenticar con Google.');
        }
    }
    window.loginWithPresetGoogle = loginWithPresetGoogle;

    // =========================================================================
    // ADMINISTRACION DE PERSONAL STAFF (SUB-PESTANA STAFF)
    // =========================================================================
    function switchAdminTab(tabName) {
        state.currentAdminTab = tabName;
        const tabs = {
            agenda: document.getElementById('admin-tab-agenda'),
            retraso: document.getElementById('admin-tab-retraso'),
            staff: document.getElementById('admin-tab-staff')
        };
        const btns = {
            agenda: document.getElementById('tab-btn-agenda'),
            retraso: document.getElementById('tab-btn-retraso'),
            staff: document.getElementById('tab-btn-staff')
        };

        for (const [key, tab] of Object.entries(tabs)) {
            if (tab) tab.classList.add('hidden');
        }
        for (const [key, btn] of Object.entries(btns)) {
            if (btn) {
                btn.className = 'text-xs font-semibold px-3 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 transition-colors';
            }
        }

        if (tabs[tabName]) tabs[tabName].classList.remove('hidden');
        if (btns[tabName]) {
            btns[tabName].className = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-[#0D9488] text-white transition-colors';
        }

        if (tabName === 'staff') {
            cargarListaPersonal();
        }
    }
    window.switchAdminTab = switchAdminTab;

    async function cargarListaPersonal() {
        const tbody = document.getElementById('table-staff-body');
        if (!tbody) return;

        const res = await apiFetch('/api/v1/auth/staff');
        if (!res.ok || !res.data || !res.data.data) {
            tbody.replaceChildren(createSafeElement('tr', {}, [
                createSafeElement('td', { colspan: '4', class: 'p-4 text-center text-rose-500' }, 'Se requiere rol Administrador para gestionar personal.')
            ]));
            return;
        }

        const staffList = res.data.data.staff || [];
        tbody.replaceChildren();

        if (staffList.length === 0) {
            tbody.appendChild(createSafeElement('tr', {}, [
                createSafeElement('td', { colspan: '4', class: 'p-4 text-center text-slate-400' }, 'Cero colaboradores registrados.')
            ]));
            return;
        }

        staffList.forEach(u => {
            const tr = createSafeElement('tr', { class: 'hover:bg-slate-50' });

            // Nombre y correo
            const tdNom = createSafeElement('td', { class: 'p-2.5' }, [
                createSafeElement('span', { class: 'font-semibold text-slate-900 block' }, u.nombre),
                createSafeElement('span', { class: 'text-[11px] text-slate-500 block' }, u.email)
            ]);

            // Rol
            const tdRol = createSafeElement('td', { class: 'p-2.5' }, [
                createSafeElement('span', { class: 'uppercase font-mono text-[10px] px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-bold' }, u.rol)
            ]);

            // Estado
            const tdEstado = createSafeElement('td', { class: 'p-2.5' }, [
                createSafeElement('span', {
                    class: u.activo ? 'text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full text-[10px] font-semibold' : 'text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full text-[10px]'
                }, u.activo ? 'Activo' : 'Inactivo')
            ]);

            // Accion Toggle
            const btnToggle = createSafeElement('button', {
                type: 'button',
                class: 'btn-compact btn-secondary text-[11px] py-1 px-2.5',
                onclick: () => alternarEstadoPersonal(u.id, !u.activo)
            }, u.activo ? 'Desactivar' : 'Activar');

            const tdAcc = createSafeElement('td', { class: 'p-2.5 text-right' }, [btnToggle]);

            tr.appendChild(tdNom);
            tr.appendChild(tdRol);
            tr.appendChild(tdEstado);
            tr.appendChild(tdAcc);
            tbody.appendChild(tr);
        });
    }
    window.cargarListaPersonal = cargarListaPersonal;

    async function alternarEstadoPersonal(staffId, nuevoEstado) {
        const res = await apiFetch(`/api/v1/auth/staff/${staffId}/toggle`, {
            method: 'PATCH',
            body: JSON.stringify({ activo: nuevoEstado })
        });
        if (res.ok) {
            cargarListaPersonal();
        } else {
            alert((res.data && res.data.message) ? res.data.message : 'Error al cambiar estado.');
        }
    }

    async function handleCrearStaffSubmit(event) {
        event.preventDefault();
        const errDiv = document.getElementById('staff-create-error');
        const sucDiv = document.getElementById('staff-create-success');
        if (errDiv) errDiv.classList.add('hidden');
        if (sucDiv) sucDiv.classList.add('hidden');

        const nombre = document.getElementById('staff-input-nombre')?.value.trim() || '';
        const email = document.getElementById('staff-input-email')?.value.trim() || '';
        const password = document.getElementById('staff-input-password')?.value || '';
        const rol = document.getElementById('staff-select-rol')?.value || 'recepcion';

        const res = await apiFetch('/api/v1/auth/staff', {
            method: 'POST',
            body: JSON.stringify({ nombre: nombre, email: email, password: password, rol: rol })
        });

        if (res.ok && res.data) {
            if (sucDiv) {
                sucDiv.textContent = 'Colaborador creado exitosamente.';
                sucDiv.classList.remove('hidden');
            }
            document.getElementById('form-crear-staff')?.reset();
            cargarListaPersonal();
        } else {
            if (errDiv) {
                errDiv.textContent = (res.data && res.data.message) ? res.data.message : 'Error al registrar colaborador.';
                errDiv.classList.remove('hidden');
            }
        }
    }

    // =========================================================================
    // CALENDARIO BOUTIQUE Y GESTION DE DISPONIBILIDAD (#view-reservar)
    // =========================================================================

    // Cache en memoria para busquedas instantaneas (0ms de latencia tras consulta)
    const availabilityCache = new Map();

    const MESES_ES = [
        'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
    ];
    const DIAS_SEMANA_ES = [
        'Domingo', 'Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado'
    ];

    let calCurrentYear = new Date().getFullYear();
    let calCurrentMonth = new Date().getMonth(); // 0 a 11

    function formatDateIso(dateObj) {
        const y = dateObj.getFullYear();
        const m = String(dateObj.getMonth() + 1).padStart(2, '0');
        const d = String(dateObj.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }

    function initCustomCalendar() {
        const calGrid = document.getElementById('custom-cal-grid');
        const calHeader = document.getElementById('custom-cal-month-year');
        const btnPrev = document.getElementById('btn-cal-prev-month');
        const btnNext = document.getElementById('btn-cal-next-month');
        const hiddenDate = document.getElementById('input-date');

        if (!calGrid || !calHeader) return;

        // Establecer fecha inicial por defecto (si hoy es fin de semana, sugerir proximo dia habil)
        const hoy = new Date();
        const fechaInicial = new Date();
        if (fechaInicial.getDay() === 6) { // Sabado
            fechaInicial.setDate(fechaInicial.getDate() + 2);
        } else if (fechaInicial.getDay() === 0) { // Domingo
            fechaInicial.setDate(fechaInicial.getDate() + 1);
        }

        calCurrentYear = fechaInicial.getFullYear();
        calCurrentMonth = fechaInicial.getMonth();

        const fechaInicialStr = formatDateIso(fechaInicial);
        if (hiddenDate && !hiddenDate.value) {
            hiddenDate.value = fechaInicialStr;
            state.selectedDate = fechaInicialStr;
        }

        btnPrev?.addEventListener('click', () => {
            calCurrentMonth--;
            if (calCurrentMonth < 0) {
                calCurrentMonth = 11;
                calCurrentYear--;
            }
            renderCustomCalendar();
        });

        btnNext?.addEventListener('click', () => {
            calCurrentMonth++;
            if (calCurrentMonth > 11) {
                calCurrentMonth = 0;
                calCurrentYear++;
            }
            renderCustomCalendar();
        });

        // Atajos de seleccion rapida (Hoy, Mañana, Lunes)
        document.querySelectorAll('.btn-quick-date').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.getAttribute('data-quick');
                const target = new Date();
                if (action === 'today') {
                    if (target.getDay() === 6) target.setDate(target.getDate() + 2);
                    else if (target.getDay() === 0) target.setDate(target.getDate() + 1);
                } else if (action === 'tomorrow') {
                    target.setDate(target.getDate() + 1);
                    if (target.getDay() === 6) target.setDate(target.getDate() + 2);
                    else if (target.getDay() === 0) target.setDate(target.getDate() + 1);
                } else if (action === 'monday') {
                    const daysUntilMonday = ((1 - target.getDay() + 7) % 7) || 7;
                    target.setDate(target.getDate() + daysUntilMonday);
                }
                calCurrentYear = target.getFullYear();
                calCurrentMonth = target.getMonth();
                const targetIso = formatDateIso(target);
                selectDate(targetIso);
                renderCustomCalendar();
            });
        });

        renderCustomCalendar();
        if (state.selectedDate) {
            updateSelectedLabel(state.selectedDate);
            loadAvailability();
        }
    }
    window.initCustomCalendar = initCustomCalendar;

    function renderCustomCalendar() {
        const calGrid = document.getElementById('custom-cal-grid');
        const calHeader = document.getElementById('custom-cal-month-year');
        if (!calGrid || !calHeader) return;

        calHeader.textContent = `${MESES_ES[calCurrentMonth]} ${calCurrentYear}`;
        calGrid.innerHTML = '';

        const hoy = new Date();
        const hoyIso = formatDateIso(hoy);

        const primerDia = new Date(calCurrentYear, calCurrentMonth, 1);
        const diasEnMes = new Date(calCurrentYear, calCurrentMonth + 1, 0).getDate();

        // Offset de inicio con Lunes como primer dia de la semana (Lunes=0 ... Domingo=6)
        let offsetInicio = primerDia.getDay() - 1;
        if (offsetInicio === -1) offsetInicio = 6;

        // Celdas vacias para alinear el primer dia
        for (let i = 0; i < offsetInicio; i++) {
            const emptyCell = document.createElement('div');
            emptyCell.className = 'cal-day-cell cal-past';
            calGrid.appendChild(emptyCell);
        }

        const serviceSelect = document.getElementById('select-service');
        const currentService = serviceSelect ? serviceSelect.value : (state.selectedService || 'profilaxis');

        for (let dia = 1; dia <= diasEnMes; dia++) {
            const dateObj = new Date(calCurrentYear, calCurrentMonth, dia);
            const dateIso = formatDateIso(dateObj);
            const dayOfWeek = dateObj.getDay(); // 0: Dom, 6: Sab
            const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
            const isPast = dateIso < hoyIso;
            const isToday = (dateIso === hoyIso);
            const isSelected = (state.selectedDate === dateIso);

            const cell = document.createElement('button');
            cell.type = 'button';
            cell.setAttribute('data-date', dateIso);

            if (isPast) {
                cell.className = 'cal-day-cell cal-past';
                cell.disabled = true;
                cell.innerHTML = `<span>${dia}</span>`;
            } else if (isWeekend) {
                cell.className = 'cal-day-cell cal-weekend';
                cell.disabled = true;
                cell.title = 'Fines de semana cerrado';
                cell.innerHTML = `<span>${dia}</span><span class="text-[9px] text-slate-300">Cerrado</span>`;
            } else {
                // Dia habil activo
                cell.className = 'cal-day-cell cal-active' + (isToday ? ' cal-today' : '') + (isSelected ? ' cal-selected' : '');
                cell.innerHTML = `<span>${dia}</span><span class="cal-dot-avail" title="Con disponibilidad"></span>`;

                cell.addEventListener('click', () => {
                    selectDate(dateIso);
                });

                // Pre-fetch en segundo plano para respuesta instantanea (0ms)
                cell.addEventListener('mouseenter', () => {
                    prefetchAvailability(dateIso, currentService);
                });
            }

            calGrid.appendChild(cell);
        }

        // Pre-cargar en cache los primeros dias habiles
        prefetchUpcomingDays(currentService);
    }
    window.renderCustomCalendar = renderCustomCalendar;

    function selectDate(dateIso) {
        state.selectedDate = dateIso;
        const hiddenDate = document.getElementById('input-date');
        if (hiddenDate) {
            hiddenDate.value = dateIso;
        }

        document.querySelectorAll('.cal-day-cell').forEach(c => {
            if (c.getAttribute('data-date') === dateIso) {
                c.classList.add('cal-selected');
            } else {
                c.classList.remove('cal-selected');
            }
        });

        updateSelectedLabel(dateIso);
        loadAvailability();
    }
    window.selectDate = selectDate;

    function updateSelectedLabel(dateIso) {
        const lbl = document.getElementById('custom-cal-selected-label');
        if (!lbl || !dateIso) return;
        const [y, m, d] = dateIso.split('-').map(Number);
        const obj = new Date(y, m - 1, d);
        const nombreDia = DIAS_SEMANA_ES[obj.getDay()];
        const nombreMes = MESES_ES[obj.getMonth()];
        lbl.textContent = `Cita seleccionada: ${nombreDia}, ${d} de ${nombreMes} de ${y}`;
    }

    async function prefetchAvailability(fecha, servicio) {
        const key = `${fecha}_${servicio}`;
        if (availabilityCache.has(key)) return;
        try {
            const res = await apiFetch(`/api/v1/disponibilidad?fecha=${fecha}&servicio=${servicio}`);
            if (res.ok) {
                availabilityCache.set(key, res);
            }
        } catch (e) {
            // Silencioso
        }
    }

    function prefetchUpcomingDays(servicio) {
        const activeCells = document.querySelectorAll('.cal-day-cell.cal-active');
        let count = 0;
        activeCells.forEach(cell => {
            if (count >= 5) return;
            const dateIso = cell.getAttribute('data-date');
            if (dateIso) {
                prefetchAvailability(dateIso, servicio);
                count++;
            }
        });
    }

    async function loadAvailability(forceRefresh = false) {
        const dateInput = document.getElementById('input-date');
        const serviceSelect = document.getElementById('select-service');
        if (!dateInput || !serviceSelect) return;

        const fecha = dateInput.value;
        const servicio = serviceSelect.value;
        if (!fecha) return;

        const cacheKey = `${fecha}_${servicio}`;
        const loading = document.getElementById('availability-loading');
        const holidayBanner = document.getElementById('holiday-banner');
        const noSlotsBanner = document.getElementById('no-slots-banner');
        const morningGrid = document.getElementById('slots-morning');
        const afternoonGrid = document.getElementById('slots-afternoon');

        if (holidayBanner) holidayBanner.classList.add('hidden');
        if (noSlotsBanner) noSlotsBanner.classList.add('hidden');

        // BUSQUEDA ULTRA RAPIDA: Si ya esta en cache, renderizar en 0ms
        if (!forceRefresh && availabilityCache.has(cacheKey)) {
            const cachedRes = availabilityCache.get(cacheKey);
            renderAvailabilityResponse(cachedRes, morningGrid, afternoonGrid, holidayBanner, noSlotsBanner);
            return;
        }

        if (loading) loading.classList.remove('hidden');
        if (morningGrid) morningGrid.replaceChildren();
        if (afternoonGrid) afternoonGrid.replaceChildren();

        const res = await apiFetch(`/api/v1/disponibilidad?fecha=${fecha}&servicio=${servicio}`);
        if (loading) loading.classList.add('hidden');

        if (res.ok) {
            availabilityCache.set(cacheKey, res);
        }

        renderAvailabilityResponse(res, morningGrid, afternoonGrid, holidayBanner, noSlotsBanner);
    }
    window.loadAvailability = loadAvailability;

    function renderAvailabilityResponse(res, morningGrid, afternoonGrid, holidayBanner, noSlotsBanner) {
        if (!res || !res.ok) {
            if (res && res.data && res.data.code === 'holiday_or_weekend') {
                if (holidayBanner) {
                    const txt = document.getElementById('holiday-banner-text');
                    if (txt) txt.textContent = res.data.message;
                    holidayBanner.classList.remove('hidden');
                }
            } else if (noSlotsBanner) {
                noSlotsBanner.classList.remove('hidden');
            }
            return;
        }

        const data = res.data;
        const bloques = data.bloques_disponibles || [];

        if (bloques.length === 0) {
            if (noSlotsBanner) noSlotsBanner.classList.remove('hidden');
            return;
        }

        const morningSlots = [];
        const afternoonSlots = [];
        const seen = new Set();

        bloques.forEach(b => {
            if (seen.has(b.hora_inicio)) return;
            seen.add(b.hora_inicio);

            const horaNum = parseInt(b.hora_inicio.split(':')[0], 10);
            if (horaNum < 12) {
                morningSlots.push(b);
            } else if (horaNum >= 13) {
                afternoonSlots.push(b);
            }
        });

        renderSlotChips(morningGrid, morningSlots, 'morning');
        renderSlotChips(afternoonGrid, afternoonSlots, 'afternoon');
    }

    function renderSlotChips(container, slots, type) {
        if (!container) return;
        container.replaceChildren();

        if (slots.length === 0) {
            const emptyWrap = document.createElement('div');
            emptyWrap.className = 'col-span-full py-4 px-3 text-center rounded-xl bg-white/70 border border-slate-200 text-slate-400 text-xs italic';
            emptyWrap.textContent = type === 'morning'
                ? 'Sin turnos matutinos disponibles para este procedimiento.'
                : 'Sin turnos vespertinos disponibles para este procedimiento.';
            container.appendChild(emptyWrap);
            return;
        }

        const typeClass = type === 'morning' ? 'slot-chip-morning' : 'slot-chip-afternoon';
        const iconSvg = type === 'morning'
            ? '<svg class="w-4 h-4 text-amber-500 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><path d="M12 1v2"/><path d="M12 21v2"/><path d="M4.22 4.22l1.42 1.42"/><path d="M18.36 18.36l1.42 1.42"/><path d="M1 12h2"/><path d="M21 12h2"/><path d="M4.22 19.78l1.42-1.42"/><path d="M18.36 5.64l1.42-1.42"/></svg>'
            : '<svg class="w-4 h-4 text-teal-600 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';

        slots.forEach((slot) => {
            const isSelected = state.selectedSlot && state.selectedSlot.hora_inicio === slot.hora_inicio;
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = `slot-chip ${typeClass}` + (isSelected ? ' slot-selected' : '');
            chip.innerHTML = `
                <div class="flex items-center gap-1.5">
                    ${iconSvg}
                    <span class="text-xs font-bold text-slate-800">${escapeHtml(slot.hora_inicio)}</span>
                </div>
                <span class="text-[10px] font-bold ${type === 'morning' ? 'text-amber-800 bg-amber-100' : 'text-teal-800 bg-teal-100'} px-1.5 py-0.5 rounded-md">${escapeHtml(slot.hora_fin)}</span>
            `;
            chip.onclick = () => selectSlot(slot, chip);
            container.appendChild(chip);
        });
    }

    function selectSlot(slot, chipElement) {
        state.selectedSlot = slot;
        document.querySelectorAll('.slot-chip').forEach(c => c.classList.remove('slot-selected'));
        if (chipElement) chipElement.classList.add('slot-selected');

        // Actualizar banner interactivo de resumen de cita
        const summaryBox = document.getElementById('selected-slot-summary');
        const badgeService = document.getElementById('summary-badge-service');
        const badgeDate = document.getElementById('summary-badge-date');
        const badgeTime = document.getElementById('summary-badge-time');

        if (summaryBox && badgeService && badgeDate && badgeTime) {
            summaryBox.classList.remove('hidden');
            const sName = state.servicesCatalog[state.selectedService]?.name || 'Tratamiento Clínico';
            badgeService.textContent = sName;
            badgeDate.textContent = state.selectedDate || 'Fecha seleccionada';
            badgeTime.textContent = `${slot.hora_inicio} a ${slot.hora_fin}`;
        }

        // Marcar progreso en el wizard
        document.getElementById('step-nav-3')?.classList.add('step-active');

        // Desplazamiento suave al contenedor de captcha y datos
        const captchaSec = document.getElementById('captcha-box-res');
        if (captchaSec) {
            captchaSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    async function handleBookingSubmit(event) {
        event.preventDefault();
        const errDiv = document.getElementById('booking-error');
        if (errDiv) errDiv.classList.add('hidden');

        if (!state.selectedSlot) {
            alert('Por favor seleccione un horario libre disponible en la grilla.');
            return;
        }

        const dateInput = document.getElementById('input-date');
        const serviceSelect = document.getElementById('select-service');
        const nombreInput = document.getElementById('input-nombre');
        const telInput = document.getElementById('input-telefono');
        const emailInput = document.getElementById('input-email');
        const notasInput = document.getElementById('input-notas');
        const checkGcal = document.getElementById('checkbox-save-gcal');

        const payload = {
            telefono: telInput ? telInput.value.trim() : '',
            nombre_paciente: nombreInput ? nombreInput.value.trim() : '',
            email_paciente: emailInput && emailInput.value.trim() ? emailInput.value.trim() : null,
            servicio: serviceSelect ? serviceSelect.value : state.selectedService,
            fecha: dateInput ? dateInput.value : state.selectedDate,
            hora_inicio: state.selectedSlot.hora_inicio,
            origen: 'web_paciente',
            notas_internas: notasInput && notasInput.value.trim() ? notasInput.value.trim() : null,
            captcha_verified_token: state.captchaVerifiedToken || null,
            guardar_en_google_calendar: checkGcal ? checkGcal.checked : false
        };

        const res = await apiFetch('/api/v1/turnos', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        if (res.ok && res.data) {
            showBookingSuccess(res.data, checkGcal ? checkGcal.checked : false);
        } else {
            if (res.status === 409 && res.data && res.data.code === 'slot_taken') {
                handleSlotTakenCollision(res.data);
            } else {
                if (errDiv) {
                    errDiv.textContent = (res.data && res.data.message) ? res.data.message : 'Error al procesar reserva.';
                    errDiv.classList.remove('hidden');
                }
            }
        }
    }

    function handleSlotTakenCollision(data) {
        const banner = document.getElementById('slot-taken-banner');
        const altContainer = document.getElementById('slot-taken-alternatives');
        if (banner) banner.classList.remove('hidden');
        if (altContainer && Array.isArray(data.detalles && data.detalles.alternativas)) {
            altContainer.replaceChildren();
            data.detalles.alternativas.forEach(alt => {
                const btn = createSafeElement('button', {
                    type: 'button',
                    class: 'slot-chip slot-alternative',
                    onclick: () => {
                        state.selectedSlot = { hora_inicio: alt };
                        loadAvailability();
                    }
                }, alt);
                altContainer.appendChild(btn);
            });
        }
    }

    function showBookingSuccess(turno, saveToGcal) {
        const containerCard = document.getElementById('booking-container-card');
        const successCard = document.getElementById('booking-success-card');
        if (containerCard) containerCard.classList.add('hidden');
        if (successCard) successCard.classList.remove('hidden');

        document.getElementById('success-codigo').textContent = turno.codigo_sala || 'T-XX';
        document.getElementById('success-servicio').textContent = turno.servicio || '-';
        document.getElementById('success-fechahora').textContent = `${turno.fecha_inicio.substring(0, 10)} a las ${turno.fecha_inicio.substring(11, 16)}`;

        // Generar enlace web intent de Google Calendar
        const dtStartIso = turno.fecha_inicio.replace(/-|:|\.\d\d\d/g, '').replace('T', 'T');
        const dtEndIso = turno.fecha_fin.replace(/-|:|\.\d\d\d/g, '').replace('T', 'T');
        const title = encodeURIComponent(`Cita Odontologica: ${turno.servicio} - Lujo Luminoso (${turno.codigo_sala})`);
        const details = encodeURIComponent(`Cita confirmada en Clinica Odontologica Boutique Lujo Luminoso.\nCodigo de Sala: ${turno.codigo_sala}\nDireccion: Carrera 15 # 85-30, Consultorio 402, Bogota.`);
        const location = encodeURIComponent('Carrera 15 # 85-30, Consultorio 402, Chico, Bogota');

        const gcalUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}&dates=${dtStartIso}/${dtEndIso}&details=${details}&location=${location}&ctz=America/Bogota`;

        const btnGcal = document.getElementById('btn-add-gcal');
        if (btnGcal) {
            btnGcal.href = gcalUrl;
        }

        const btnIcs = document.getElementById('btn-download-ics');
        if (btnIcs) {
            btnIcs.href = `/api/v1/turnos/${turno.id}/ics`;
        }

        // Si la casilla de guardar en Google Calendar estaba activa, abrir inmediatamente en pestaña
        if (saveToGcal) {
            window.open(gcalUrl, '_blank');
        }

        successCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // =========================================================================
    // SINCRONIZACION DEL ESTADO VISUAL DE SESION
    // =========================================================================
    function updateSessionUI() {
        const loggedOut = document.getElementById('auth-logged-out');
        const loggedIn = document.getElementById('auth-logged-in');
        const staffBar = document.getElementById('staff-operational-bar');
        const nameBadge = document.getElementById('user-badge-name');
        const roleBadge = document.getElementById('user-badge-role');

        if (state.currentUser) {
            if (loggedOut) loggedOut.classList.add('hidden');
            if (loggedIn) loggedIn.classList.remove('hidden');
            if (nameBadge) nameBadge.textContent = state.currentUser.nombre;
            if (roleBadge) roleBadge.textContent = state.currentUser.rol;

            if (staffBar && (state.currentUser.rol === 'admin' || state.currentUser.rol === 'doctor' || state.currentUser.rol === 'recepcion')) {
                staffBar.classList.remove('hidden');
            }
        } else {
            if (loggedOut) loggedOut.classList.remove('hidden');
            if (loggedIn) loggedIn.classList.add('hidden');
            if (staffBar) staffBar.classList.add('hidden');
        }
    }

    async function checkCurrentSession() {
        const res = await apiFetch('/api/v1/auth/me');
        if (res.ok && res.data && res.data.data) {
            state.currentUser = res.data.data.usuario;
        } else {
            state.currentUser = null;
        }
        updateSessionUI();
    }

    // =========================================================================
    // INICIALIZACION Y EVENT LISTENERS
    // =========================================================================
    function refreshIcons() {
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons();
        }
    }

    function initEventListeners() {
        // Navbar
        document.getElementById('nav-inicio')?.addEventListener('click', () => scrollToSection('inicio'));
        document.getElementById('nav-tratamientos')?.addEventListener('click', () => scrollToSection('tratamientos'));
        document.getElementById('nav-experiencia')?.addEventListener('click', () => scrollToSection('experiencia'));
        document.getElementById('nav-contacto')?.addEventListener('click', () => scrollToSection('contacto'));

        // Modales
        document.getElementById('btn-open-login')?.addEventListener('click', () => openAuthModal('login'));
        document.getElementById('btn-footer-login')?.addEventListener('click', () => openAuthModal('login'));
        document.getElementById('btn-mobile-login')?.addEventListener('click', () => openAuthModal('login'));
        document.getElementById('btn-close-auth')?.addEventListener('click', closeAuthModal);

        document.getElementById('tab-auth-login')?.addEventListener('click', () => switchAuthTab('login'));
        document.getElementById('tab-auth-register')?.addEventListener('click', () => switchAuthTab('register'));

        document.getElementById('login-form')?.addEventListener('submit', handleLoginSubmit);
        document.getElementById('register-form')?.addEventListener('submit', handleRegisterSubmit);
        document.getElementById('btn-logout')?.addEventListener('click', handleLogout);

        // Google Auth
        document.getElementById('btn-google-auth-trigger')?.addEventListener('click', openGoogleSelector);
        document.getElementById('btn-close-google-accounts')?.addEventListener('click', closeGoogleSelector);
        document.getElementById('btn-autofill-google-res')?.addEventListener('click', openGoogleSelector);

        document.getElementById('google-custom-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            const nom = document.getElementById('google-custom-name')?.value.trim();
            const eml = document.getElementById('google-custom-email')?.value.trim();
            if (nom && eml) loginWithPresetGoogle(eml, nom);
        });

        // Captcha
        document.getElementById('tab-captcha-code-res')?.addEventListener('click', () => {
            state.captchaMode = 'code';
            document.getElementById('panel-captcha-code-res')?.classList.remove('hidden');
            document.getElementById('panel-captcha-grid-res')?.classList.add('hidden');
            document.getElementById('tab-captcha-code-res').className = 'text-xs font-bold text-[#0D9488] border-b-2 border-[#0D9488] pb-1';
            document.getElementById('tab-captcha-grid-res').className = 'text-xs font-medium text-slate-500 hover:text-slate-800 pb-1';
        });

        document.getElementById('tab-captcha-grid-res')?.addEventListener('click', () => {
            state.captchaMode = 'image_grid';
            document.getElementById('panel-captcha-code-res')?.classList.add('hidden');
            document.getElementById('panel-captcha-grid-res')?.classList.remove('hidden');
            document.getElementById('tab-captcha-grid-res').className = 'text-xs font-bold text-[#0D9488] border-b-2 border-[#0D9488] pb-1';
            document.getElementById('tab-captcha-code-res').className = 'text-xs font-medium text-slate-500 hover:text-slate-800 pb-1';
        });

        document.getElementById('btn-reload-captcha-res')?.addEventListener('click', loadCaptchaChallenge);
        document.getElementById('btn-verify-captcha-code-res')?.addEventListener('click', () => verifyCaptcha('code'));
        document.getElementById('btn-verify-captcha-grid-res')?.addEventListener('click', () => verifyCaptcha('image_grid'));

        // Formulario de Reserva
        document.querySelectorAll('.booking-service-card').forEach(card => {
            card.addEventListener('click', () => {
                const serviceKey = card.getAttribute('data-service-key');
                if (!serviceKey) return;
                state.selectedService = serviceKey;
                const select = document.getElementById('select-service');
                if (select) {
                    select.value = serviceKey;
                }
                syncDurationIndicator(serviceKey);
                renderCustomCalendar();
                loadAvailability();
            });
        });

        document.getElementById('select-service')?.addEventListener('change', (e) => {
            state.selectedService = e.target.value;
            syncDurationIndicator(state.selectedService);
            loadAvailability();
        });

        document.getElementById('input-date')?.addEventListener('change', (e) => {
            state.selectedDate = e.target.value;
            loadAvailability();
        });

        document.getElementById('booking-form')?.addEventListener('submit', handleBookingSubmit);

        // Formularios Administrativos
        document.getElementById('form-crear-staff')?.addEventListener('submit', handleCrearStaffSubmit);

        // FAQ Acordeon
        const faqHeaders = document.querySelectorAll('.faq-accordion-header');
        faqHeaders.forEach(header => {
            header.addEventListener('click', () => {
                const item = header.closest('.faq-accordion-item');
                if (!item) return;
                const isCurrentlyOpen = item.classList.contains('faq-open');
                document.querySelectorAll('.faq-accordion-item').forEach(otherItem => {
                    otherItem.classList.remove('faq-open');
                    otherItem.querySelector('.faq-accordion-header')?.setAttribute('aria-expanded', 'false');
                });
                if (!isCurrentlyOpen) {
                    item.classList.add('faq-open');
                    header.setAttribute('aria-expanded', 'true');
                }
            });
        });

        // Configurar fecha minima por defecto en datepicker (hoy)
        const dateInput = document.getElementById('input-date');
        if (dateInput) {
            const todayStr = new Date().toISOString().split('T')[0];
            dateInput.min = todayStr;
            // Si es sabado o domingo, sugerir lunes
            const d = new Date();
            if (d.getDay() === 6) d.setDate(d.getDate() + 2);
            else if (d.getDay() === 0) d.setDate(d.getDate() + 1);
            dateInput.value = d.toISOString().split('T')[0];
            state.selectedDate = dateInput.value;
        }

        // Modulos Interactivos Nuevos
        initBeforeAfterSlider();
        initFacilityTour();
        initProcedureEstimator();
        initTreatmentFilters();
        initScrollReveal();
        initReviewsSystem();
        initCustomCalendar();
    }

    // =========================================================================
    // MODULOS INTERACTIVOS: COMPARADOR, TOUR VIRTUAL Y COTIZADOR
    // =========================================================================

    function initBeforeAfterSlider() {
        const range = document.getElementById('smile-before-after-range');
        const box = document.getElementById('smile-before-after-box');
        if (!range || !box) return;

        function updatePos(val) {
            box.style.setProperty('--slider-pos', val + '%');
        }

        range.addEventListener('input', (e) => updatePos(e.target.value));
        range.addEventListener('change', (e) => updatePos(e.target.value));
        updatePos(50);
    }

    function initFacilityTour() {
        const tabs = document.querySelectorAll('.facility-tab-btn');
        const img = document.getElementById('facility-tour-img');
        const title = document.getElementById('facility-tour-title');
        const desc = document.getElementById('facility-tour-desc');
        const badge = document.getElementById('facility-tour-badge');
        const featuresList = document.getElementById('facility-tour-features');

        const facilitiesData = {
            'sillon': {
                img: 'https://images.unsplash.com/photo-1629909613654-28e377c37b09?auto=format&fit=crop&w=1200&q=85',
                badge: 'Suite Clinica Privada',
                title: 'Atencion Dedicada 1 a 1 Sin Prisas',
                desc: 'Un espacio exclusivo reservado unicamente para usted durante su procedimiento. Cero salas de espera compartidas, atencion pausada y anestesia digital indolora para una experiencia completamente comoda y libre de estres.',
                features: [
                    'Consultorio cerrado exclusivamente para 1 paciente',
                    'Anestesia computarizada indolora sin molestias',
                    'Acompanamiento directo y continuo del especialista'
                ]
            },
            'lounge': {
                img: '/static/img/lounge_vip_interior.jpg',
                badge: 'Lounge Privado VIP',
                title: 'Recepcion Sin Filas ni Salas de Espera Concurridas',
                desc: 'Un espacio disenado con la calidez de un hotel boutique de 5 estrellas. Acceso privado directo, musica acustica relajante y bebidas de cortesia para que disfrute de total serenidad antes de su consulta.',
                features: [
                    'Sin cruzarse con otros pacientes en salas llenas',
                    'Ambiente sereno, insonorizado y confortable',
                    'Puntualidad absoluta: Ingreso directo a su cita'
                ]
            },
            'lab': {
                img: '/static/img/scanner_digital_3d.jpg',
                badge: 'Escaner Intraoral 3D',
                title: 'Diagnostico Digital en 60 Segundos Sin Pastas',
                desc: 'Escaner optico tridimensional de ultima generacion que captura la anatomia de su sonrisa con precision micrometrica, eliminando por completo las molestas pastas tradicionales y cualquier sensacion de nausea.',
                features: [
                    'Escaneo comodo y rapido en menos de un minuto',
                    'Visualizacion en pantalla de su futura sonrisa',
                    'Ajuste perfecto para carillas, coronas e implantes'
                ]
            },
            'esterilizacion': {
                img: 'https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=1200&q=85',
                badge: 'Bioseguridad Grado Hospitalario',
                title: 'Esterilizacion Certificada y Aire Puro HEPA',
                desc: 'Maximo rigor sanitario con autoclave hospitalario Clase B y purificacion de aire continua con filtros HEPA. Instrumental esteril sellado que se abre unicamente frente a usted para su total tranquilidad.',
                features: [
                    'Instrumental quirurgico sellado individualmente',
                    'Filtrado y renovacion continua de aire HEPA',
                    'Protocolo de desinfeccion de grado hospitalario'
                ]
            }
        };

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const key = tab.getAttribute('data-facility');
                const data = facilitiesData[key];
                if (!data) return;

                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                if (img) {
                    img.style.opacity = '0.3';
                    setTimeout(() => {
                        img.src = data.img;
                        img.alt = data.title;
                        img.style.opacity = '1';
                    }, 150);
                }
                if (badge) badge.textContent = data.badge;
                if (title) title.textContent = data.title;
                if (desc) desc.textContent = data.desc;

                if (featuresList) {
                    featuresList.innerHTML = '';
                    data.features.forEach(feat => {
                        const li = document.createElement('li');
                        li.className = 'flex items-center gap-2 text-xs text-slate-600';
                        li.innerHTML = '<svg class="w-4 h-4 text-[#0D9488] shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg><span>' + feat + '</span>';
                        featuresList.appendChild(li);
                    });
                }
            });
        });
    }

    function initProcedureEstimator() {
        const cards = document.querySelectorAll('.procedure-card-select');
        const badge = document.getElementById('estimator-badge');
        const title = document.getElementById('estimator-title');
        const time = document.getElementById('estimator-time');
        const desc = document.getElementById('estimator-desc');
        const btnBook = document.getElementById('estimator-btn-book');

        const proceduresData = {
            'cirugia_implantes': {
                badge: 'Quirurgico de Alta Complejidad',
                title: 'Implantes Dentales y Cirugia Oral Guiada',
                time: '120 Minutos (Bloque Completo)',
                desc: 'Procedimiento de sustitucion definitiva con titanio grado medico suizo. Guiado tomografico 3D y anestesia indolora computarizada.',
                key: 'cirugia_implantes'
            },
            'diseno_sonrisa': {
                badge: 'Estetica Dental de Vanguardia',
                title: 'Diseno de Sonrisa y Microcarillas',
                time: '60 Minutos (Atencion Minuciosa)',
                desc: 'Analisis fotografico y adaptacion de laminas de ceramica feldespatica sin desgaste agresivo, logrando translucidez y armonia perfecta.',
                key: 'diseno_sonrisa'
            },
            'ortodoncia': {
                badge: 'Alineacion y Oclusion',
                title: 'Ortodoncia Invisible y Brackets Zafiro',
                time: '45 Minutos (Calibracion de Alta Precision)',
                desc: 'Planificacion cinematica tridimensional para alineadores invisibles removibles de baja friccion y correccion estetica rapida.',
                key: 'ortodoncia'
            },
            'profilaxis': {
                badge: 'Mantenimiento y Prevencion',
                title: 'Profilaxis Ultrasonica y Desmanchado',
                time: '30 Minutos (Higiene Profunda)',
                desc: 'Remocion de calculo y pulido con aeropulidor de microparticulas, devolviendo la sensacion de frescura y blancura natural al instante.',
                key: 'profilaxis'
            }
        };

        cards.forEach(card => {
            card.addEventListener('click', () => {
                const key = card.getAttribute('data-service');
                const data = proceduresData[key];
                if (!data) return;

                cards.forEach(c => c.classList.remove('selected'));
                card.classList.add('selected');

                if (badge) badge.textContent = data.badge;
                if (title) title.textContent = data.title;
                if (time) time.textContent = data.time;
                if (desc) desc.textContent = data.desc;

                if (btnBook) {
                    btnBook.onclick = () => {
                        selectServiceAndGo(data.key);
                    };
                }
            });
        });
    }

    function initTreatmentFilters() {
        const filterBtns = document.querySelectorAll('.treatment-filter-chip');
        const cards = document.querySelectorAll('.treatment-card-item');

        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const cat = btn.getAttribute('data-category');

                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                cards.forEach(card => {
                    const cardCat = card.getAttribute('data-category');
                    if (cat === 'all' || cardCat === cat) {
                        card.style.display = '';
                        card.classList.add('animate-fade-in');
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        });
    }

    function initScrollReveal() {
        if (!('IntersectionObserver' in window)) return;
        document.documentElement.classList.add('js-reveal-active');
        const reveals = document.querySelectorAll('.reveal-on-scroll');
        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-revealed');
                    obs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1 });

        reveals.forEach(el => observer.observe(el));
    }

    // =========================================================================
    // MODULO DE RESENAS Y CALIFICACIONES (REVIEWS)
    // =========================================================================

    let currentReviewRating = 5;

    function initReviewsSystem() {
        const btnOpenModal = document.getElementById('btn-open-review-modal');
        const btnCloseModal = document.getElementById('btn-close-review-modal');
        const modalReview = document.getElementById('modal-review');
        const formReview = document.getElementById('form-nueva-resena');

        btnOpenModal?.addEventListener('click', () => {
            if (modalReview) modalReview.classList.remove('hidden');
        });

        if (window.location.hash === '#escribir-resena' || window.location.search.includes('modal=review')) {
            modalReview?.classList.remove('hidden');
        }

        btnCloseModal?.addEventListener('click', () => {
            if (modalReview) modalReview.classList.add('hidden');
        });

        // Selector de Estrellas
        const starBtns = document.querySelectorAll('.star-picker-btn');
        function updateStarUI(rating) {
            currentReviewRating = rating;
            const valInput = document.getElementById('review-rating-value');
            if (valInput) valInput.value = rating;
            starBtns.forEach(btn => {
                const starNum = parseInt(btn.getAttribute('data-star') || '1', 10);
                if (starNum <= rating) {
                    btn.classList.add('star-active');
                    btn.classList.remove('star-inactive');
                } else {
                    btn.classList.remove('star-active');
                    btn.classList.add('star-inactive');
                }
            });
        }

        starBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const val = parseInt(btn.getAttribute('data-star') || '5', 10);
                updateStarUI(val);
            });
        });

        updateStarUI(5);

        // Envio de la resena
        formReview?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const errDiv = document.getElementById('review-form-error');
            if (errDiv) errDiv.classList.add('hidden');

            const nombre = document.getElementById('review-nombre')?.value.trim();
            const servicio = document.getElementById('review-servicio')?.value;
            const comentario = document.getElementById('review-comentario')?.value.trim();

            if (!nombre || !comentario) {
                if (errDiv) {
                    errDiv.textContent = 'Por favor complete su nombre y comentario.';
                    errDiv.classList.remove('hidden');
                }
                return;
            }

            const payload = {
                nombre: nombre,
                servicio: servicio,
                calificacion: currentReviewRating,
                comentario: comentario
            };

            const res = await apiFetch('/api/v1/resenas', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                if (modalReview) modalReview.classList.add('hidden');
                formReview.reset();
                updateStarUI(5);
                alert('Gracias por su resena! Ha sido publicada exitosamente.');
                loadReviews();
            } else {
                if (errDiv) {
                    errDiv.textContent = (res.data && res.data.message) ? res.data.message : 'Error al publicar la resena.';
                    errDiv.classList.remove('hidden');
                }
            }
        });

        loadReviews();
    }

    async function loadReviews() {
        const res = await apiFetch('/api/v1/resenas');
        if (!res.ok || !res.data || !res.data.data) return;

        const data = res.data.data;
        const resenas = data.resenas || [];
        const promedio = data.promedio || 5.0;
        const total = data.total || resenas.length;

        const avgEl = document.getElementById('reviews-average-rating');
        const totalEl = document.getElementById('reviews-total-count');
        if (avgEl) avgEl.textContent = promedio.toFixed(1);
        if (totalEl) totalEl.textContent = total;

        const container = document.getElementById('reviews-container');
        if (!container) return;

        container.innerHTML = '';
        resenas.forEach(r => {
            const card = document.createElement('div');
            card.className = 'clinic-card p-6 space-y-4 shadow-sm hover-lift animate-fade-in flex flex-col justify-between';

            let starsSvg = '';
            for (let i = 1; i <= 5; i++) {
                const fillClass = i <= r.calificacion ? 'fill-current text-amber-400' : 'text-slate-300';
                starsSvg += '<svg class="w-4 h-4 ' + fillClass + '" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
            }

            const initial = (r.nombre && r.nombre.length > 0) ? r.nombre[0].toUpperCase() : 'P';

            card.innerHTML = `
                <div class="space-y-3">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-1">
                            ${starsSvg}
                        </div>
                        <span class="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200/60">
                            <svg class="w-3 h-3 text-[#0D9488]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                            <span>Verificado</span>
                        </span>
                    </div>
                    <p class="text-xs sm:text-sm text-slate-600 leading-relaxed italic">
                        "${escapeHtml(r.comentario)}"
                    </p>
                </div>
                <div class="pt-4 border-t border-slate-100 flex items-center gap-3">
                    <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-[#0A192F] to-[#0D9488] text-white flex items-center justify-center font-bold text-xs shrink-0 shadow-xs">
                        ${initial}
                    </div>
                    <div class="flex-1 min-w-0">
                        <span class="text-xs font-bold text-slate-900 block truncate">${escapeHtml(r.nombre)}</span>
                        <span class="text-[11px] text-slate-500 block truncate">${escapeHtml(r.servicio)} &bull; ${escapeHtml(r.fecha)}</span>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }

    async function initApp() {
        initEventListeners();
        await checkCurrentSession();

        // Determinar vista inicial segun URL del navegador o atributo del body
        let initialView = document.body.dataset.initialView || 'landing';
        const currentPath = window.location.pathname || '';
        if (currentPath.startsWith('/reservar')) {
            initialView = 'reservar';
        } else if (currentPath.startsWith('/admin')) {
            initialView = 'admin';
        } else if (currentPath.startsWith('/doctor')) {
            initialView = 'doctor';
        } else if (currentPath.startsWith('/tv')) {
            initialView = 'tv';
        }
        switchView(initialView);
        refreshIcons();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initApp);
    } else {
        initApp();
    }

})();
