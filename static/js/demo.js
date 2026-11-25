/*
 * Clinica Odontologica Boutique "Lujo Luminoso"
 * Modulo de Demostracion Aislada y Simulador WhatsApp (static/js/demo.js)
 *
 * Responsabilidades:
 * 1. Activacion condicional segun /api/v1/config/public (demo_mode === true).
 * 2. Barra flotante de control clinico (#demo-toolbar) estilo Linear/Raycast.
 * 3. Alternancia rapida de roles (Doctor, Recepcion, Admin) via HttpOnly cookies (Cero tokens en cliente).
 * 4. Sembrado automatizado de escenarios clinicos coherentes con PostgreSQL/GiST.
 * 5. Adelanto temporal de 16 minutos para probar en vivo la inasistencia (cancelado_ausente).
 * 6. Cajon interactivo del Simulador de WhatsApp IA con chips de escenarios y ejecucion determinista.
 *
 * Normas de Seguridad: Cero emojis, Cero almacenamiento de tokens en cliente, Cero innerHTML con datos dinamicos.
 */

(function () {
    "use strict";

    var DemoModule = {
        config: null,
        drawerOpen: false,

        init: function () {
            var self = this;
            fetch("/api/v1/config/public")
                .then(function (res) {
                    if (!res.ok) throw new Error("Error consultando configuracion");
                    return res.json();
                })
                .then(function (cfg) {
                    self.config = cfg;
                    if (cfg && cfg.demo_mode === true) {
                        self.renderToolbar();
                        self.renderDrawer();
                        self.initLucideIcons();
                    }
                })
                .catch(function (err) {
                    console.warn("Aviso: modo demo no inicializado:", err);
                });
        },

        initLucideIcons: function () {
            if (window.lucide && typeof window.lucide.createIcons === "function") {
                try {
                    window.lucide.createIcons();
                } catch (e) {}
            }
        },

        // ======================================================================
        // 1. BARRA FLOTANTE DE CONTROL DEMO (#demo-toolbar)
        // ======================================================================
        renderToolbar: function () {
            var self = this;
            var container = document.getElementById("demo-toolbar");
            if (!container) return;

            while (container.firstChild) container.removeChild(container.firstChild);
            container.className = "demo-floating-bar";

            // Tag de Modo Demo
            var tagBadge = document.createElement("span");
            tagBadge.className = "px-2 py-0.5 rounded text-2xs font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 uppercase tracking-wider";
            tagBadge.textContent = "MODO DEMO";
            container.appendChild(tagBadge);

            // Boton 1: Sembrar Escenario Clinico
            var btnSeed = document.createElement("button");
            btnSeed.type = "button";
            btnSeed.className = "demo-btn demo-btn-accent";
            btnSeed.title = "Poblar citas del dia con estados en_atencion, llamando, en_sala, triage";
            var iconSeed = document.createElement("i");
            iconSeed.setAttribute("data-lucide", "database");
            iconSeed.className = "w-3.5 h-3.5";
            var textSeed = document.createTextNode("Poblar Dia Demo");
            btnSeed.appendChild(iconSeed);
            btnSeed.appendChild(textSeed);

            btnSeed.addEventListener("click", function () {
                btnSeed.disabled = true;
                textSeed.nodeValue = "Sembrando...";
                fetch("/api/v1/demo/seed-scenario", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ limpiar_dia_antes: true })
                })
                    .then(function (res) {
                        if (!res.ok) throw new Error("Error sembrando escenario");
                        return res.json();
                    })
                    .then(function (data) {
                        alert("Escenario clinico demo cargado con exito para fecha " + (data.data ? data.data.fecha_sembrada : "actual") + ".");
                        if (window.RealtimeManager) {
                            window.RealtimeManager.syncActiveView();
                        }
                    })
                    .catch(function (err) {
                        alert("Error al sembrar escenario: " + err.message);
                    })
                    .finally(function () {
                        btnSeed.disabled = false;
                        textSeed.nodeValue = "Poblar Dia Demo";
                    });
            });
            container.appendChild(btnSeed);

            // Boton 2: Cambio Rapido a Rol Doctor
            var btnDoctor = document.createElement("button");
            btnDoctor.type = "button";
            btnDoctor.className = "demo-btn";
            btnDoctor.title = "Iniciar sesion automatica como Doctor (Dr. Armando Casas)";
            var iconDoc = document.createElement("i");
            iconDoc.setAttribute("data-lucide", "stethoscope");
            iconDoc.className = "w-3.5 h-3.5";
            var textDoc = document.createTextNode("Dr. Armando");
            btnDoctor.appendChild(iconDoc);
            btnDoctor.appendChild(textDoc);

            btnDoctor.addEventListener("click", function () {
                self.quickLogin("doctor");
            });
            container.appendChild(btnDoctor);

            // Boton 3: Cambio Rapido a Rol Recepcion
            var btnRecepcion = document.createElement("button");
            btnRecepcion.type = "button";
            btnRecepcion.className = "demo-btn";
            btnRecepcion.title = "Iniciar sesion automatica como Recepcion Clinica";
            var iconRec = document.createElement("i");
            iconRec.setAttribute("data-lucide", "calendar");
            iconRec.className = "w-3.5 h-3.5";
            var textRec = document.createTextNode("Recepcion");
            btnRecepcion.appendChild(iconRec);
            btnRecepcion.appendChild(textRec);

            btnRecepcion.addEventListener("click", function () {
                self.quickLogin("recepcion");
            });
            container.appendChild(btnRecepcion);

            // Boton 4: Adelantar 15 Minutos de Llamado
            var btnFastForward = document.createElement("button");
            btnFastForward.type = "button";
            btnFastForward.className = "demo-btn";
            btnFastForward.title = "Adelanta el cronometro del llamado a 16 minutos para probar cancelado_ausente";
            var iconFF = document.createElement("i");
            iconFF.setAttribute("data-lucide", "fast-forward");
            iconFF.className = "w-3.5 h-3.5";
            var textFF = document.createTextNode("Adelantar 15m");
            btnFastForward.appendChild(iconFF);
            btnFastForward.appendChild(textFF);

            btnFastForward.addEventListener("click", function () {
                self.fastForwardLlamado();
            });
            container.appendChild(btnFastForward);

            // Boton 5: Abrir Simulador de WhatsApp
            var btnSim = document.createElement("button");
            btnSim.type = "button";
            btnSim.className = "demo-btn demo-btn-primary";
            btnSim.title = "Abrir simulador conversacional de WhatsApp IA";
            var iconSim = document.createElement("i");
            iconSim.setAttribute("data-lucide", "message-square");
            iconSim.className = "w-3.5 h-3.5";
            var textSim = document.createTextNode("Simulador WhatsApp");
            btnSim.appendChild(iconSim);
            btnSim.appendChild(textSim);

            btnSim.addEventListener("click", function () {
                self.toggleDrawer();
            });
            container.appendChild(btnSim);

            container.classList.remove("hidden");
        },

        // ======================================================================
        // 2. INICIO RAPIDO DE SESION CON COOKIES HTTPONLY (CERO STORAGE)
        // ======================================================================
        quickLogin: function (rolName) {
            fetch("/api/v1/demo/quick-login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ rol: rolName })
            })
                .then(function (res) {
                    if (!res.ok) throw new Error("Fallo en autenticacion rapida");
                    return res.json();
                })
                .then(function (staffUser) {
                    // Revelar pestanas segun rol
                    var tabAdmin = document.getElementById("tab-admin");
                    var tabDoctor = document.getElementById("tab-doctor");
                    var userBadge = document.getElementById("user-badge");
                    var userNameDisplay = document.getElementById("user-name-display");
                    var btnLoginOpen = document.getElementById("btn-login-open");

                    if (userBadge && userNameDisplay) {
                        userNameDisplay.textContent = staffUser.nombre + " (" + staffUser.rol.toUpperCase() + ")";
                        userBadge.classList.remove("hidden");
                    }
                    if (btnLoginOpen) btnLoginOpen.classList.add("hidden");

                    if (staffUser.rol === "doctor") {
                        if (tabDoctor) tabDoctor.classList.remove("hidden");
                        if (tabAdmin) tabAdmin.classList.add("hidden");
                        if (window.switchView) window.switchView("view-doctor");
                    } else if (staffUser.rol === "recepcion") {
                        if (tabAdmin) tabAdmin.classList.remove("hidden");
                        if (tabDoctor) tabDoctor.classList.add("hidden");
                        if (window.switchView) window.switchView("view-admin");
                    } else if (staffUser.rol === "admin") {
                        if (tabAdmin) tabAdmin.classList.remove("hidden");
                        if (tabDoctor) tabDoctor.classList.remove("hidden");
                        if (window.switchView) window.switchView("view-admin");
                    }

                    if (window.RealtimeManager) {
                        window.RealtimeManager.syncActiveView();
                    }
                })
                .catch(function (err) {
                    alert("Error en login rapido: " + err.message);
                });
        },

        // ======================================================================
        // 3. ADELANTO TEMPORAL DE TOLERANCIA
        // ======================================================================
        fastForwardLlamado: function () {
            fetch("/api/v1/operacion/actual", { credentials: "same-origin" })
                .then(function (res) {
                    if (!res.ok) throw new Error("No se pudo consultar el estado actual");
                    return res.json();
                })
                .then(function (op) {
                    var targetId = null;
                    if (op.turno_llamando) {
                        targetId = op.turno_llamando.id;
                    } else if (op.siguiente_turno) {
                        targetId = op.siguiente_turno.id;
                    }

                    if (!targetId) {
                        alert("No hay ningun turno en estado de llamado o en sala para adelantar.");
                        return;
                    }

                    return fetch("/api/v1/demo/fast-forward-grace/" + encodeURIComponent(targetId), {
                        method: "POST",
                        credentials: "same-origin"
                    })
                        .then(function (ffRes) {
                            if (!ffRes.ok) throw new Error("Error adelantando cronometro");
                            return ffRes.json();
                        })
                        .then(function () {
                            alert("Cronometro adelantado a 16 minutos. Ahora el boton 'Marcar Inasistencia' esta habilitado en el Panel del Doctor.");
                            if (window.RealtimeManager) {
                                window.RealtimeManager.syncActiveView();
                            }
                        });
                })
                .catch(function (err) {
                    alert("Aviso: " + err.message);
                });
        },

        // ======================================================================
        // 4. CAJON DEL SIMULADOR DE WHATSAPP (#demo-whatsapp-drawer)
        // ======================================================================
        renderDrawer: function () {
            var self = this;
            var drawer = document.getElementById("demo-whatsapp-drawer");
            if (!drawer) return;

            while (drawer.firstChild) drawer.removeChild(drawer.firstChild);
            drawer.className = "demo-drawer-panel closed";

            // Encabezado del Cajon
            var header = document.createElement("div");
            header.className = "p-4 border-b border-slate-200 bg-slate-900 text-white flex items-center justify-between";

            var hInfo = document.createElement("div");
            var hTitle = document.createElement("h3");
            hTitle.className = "text-sm font-bold tracking-tight uppercase";
            hTitle.textContent = "Simulador WhatsApp IA";
            var hSub = document.createElement("p");
            hSub.className = "text-2xs font-mono text-teal-300 mt-0.5";
            hSub.textContent = "Paciente: Laura Demo (+57 300 555 0199)";
            hInfo.appendChild(hTitle);
            hInfo.appendChild(hSub);

            var btnClose = document.createElement("button");
            btnClose.type = "button";
            btnClose.className = "p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors";
            var iconClose = document.createElement("i");
            iconClose.setAttribute("data-lucide", "x");
            iconClose.className = "w-4 h-4";
            btnClose.appendChild(iconClose);
            btnClose.addEventListener("click", function () {
                self.toggleDrawer();
            });

            header.appendChild(hInfo);
            header.appendChild(btnClose);
            drawer.appendChild(header);

            // Contenedor de Chips de Escenarios Rapidos
            var chipsBox = document.createElement("div");
            chipsBox.className = "p-3 border-b border-slate-100 bg-slate-50 space-y-1.5";
            var chipLabel = document.createElement("p");
            chipLabel.className = "text-2xs font-semibold text-slate-500 uppercase tracking-wider";
            chipLabel.textContent = "Pruebas Clinicas con 1 Clic:";
            chipsBox.appendChild(chipLabel);

            var chipsWrapper = document.createElement("div");
            chipsWrapper.className = "flex flex-wrap gap-1.5";

            var scenarios = [
                "Consultar horarios para manana",
                "Agendar Profilaxis a las 08:30",
                "Voy a llegar 10 min tarde",
                "Voy a llegar 25 min tarde",
                "No podre asistir por viaje de trabajo",
                "Tengo dolor agudo y sangrado"
            ];

            for (var i = 0; i < scenarios.length; i++) {
                (function (textoEscenario) {
                    var chip = document.createElement("button");
                    chip.type = "button";
                    chip.className = "wa-scenario-chip";
                    chip.textContent = textoEscenario;
                    chip.addEventListener("click", function () {
                        self.enviarMensajeSimulado(textoEscenario);
                    });
                    chipsWrapper.appendChild(chip);
                })(scenarios[i]);
            }
            chipsBox.appendChild(chipsWrapper);
            drawer.appendChild(chipsBox);

            // Area de Flujo de Mensajes
            var streamArea = document.createElement("div");
            streamArea.id = "wa-chat-stream";
            streamArea.className = "flex-1 p-4 overflow-y-auto space-y-3 bg-[#EFEAE2]/40";
            drawer.appendChild(streamArea);

            // Mensaje de Bienvenida en Chat
            self.appendBotBubble("Hola. Soy el asistente clinico de Lujo Luminoso. En que puedo orientarte hoy?", [], false);

            // Barra Inferior de Entrada
            var footerForm = document.createElement("form");
            footerForm.className = "p-3 border-t border-slate-200 bg-white flex items-center gap-2";

            var inputMsg = document.createElement("input");
            inputMsg.type = "text";
            inputMsg.id = "wa-sim-input";
            inputMsg.required = true;
            inputMsg.maxLength = 500;
            inputMsg.placeholder = "Escribe un mensaje de WhatsApp...";
            inputMsg.className = "flex-1 text-xs border border-slate-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-1 focus:ring-slate-900";

            var btnSend = document.createElement("button");
            btnSend.type = "submit";
            btnSend.className = "px-3 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors flex items-center gap-1";
            var iconSend = document.createElement("i");
            iconSend.setAttribute("data-lucide", "send");
            iconSend.className = "w-3.5 h-3.5";
            btnSend.appendChild(iconSend);

            footerForm.addEventListener("submit", function (e) {
                e.preventDefault();
                var txt = inputMsg.value ? inputMsg.value.trim() : "";
                if (!txt) return;
                inputMsg.value = "";
                self.enviarMensajeSimulado(txt);
            });

            footerForm.appendChild(inputMsg);
            footerForm.appendChild(btnSend);
            drawer.appendChild(footerForm);

            drawer.classList.remove("hidden");
        },

        toggleDrawer: function () {
            var drawer = document.getElementById("demo-whatsapp-drawer");
            if (!drawer) return;
            this.drawerOpen = !this.drawerOpen;
            if (this.drawerOpen) {
                drawer.classList.remove("closed");
                var input = document.getElementById("wa-sim-input");
                if (input) input.focus();
            } else {
                drawer.classList.add("closed");
            }
            this.initLucideIcons();
        },

        enviarMensajeSimulado: function (texto) {
            var self = this;
            self.appendUserBubble(texto);

            // Indicador de procesamiento
            var stream = document.getElementById("wa-chat-stream");
            var indicator = document.createElement("div");
            indicator.className = "text-2xs text-slate-400 italic font-mono self-start py-1";
            indicator.textContent = "Procesando mensaje con el motor clinico...";
            if (stream) {
                stream.appendChild(indicator);
                stream.scrollTop = stream.scrollHeight;
            }

            fetch("/api/v1/demo/whatsapp-sim", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({
                    telefono: "+573005550199",
                    nombre_perfil: "Laura Demo",
                    mensaje: texto
                })
            })
                .then(function (res) {
                    if (!res.ok) throw new Error("Error en simulador de WhatsApp");
                    return res.json();
                })
                .then(function (data) {
                    if (indicator && indicator.parentNode) {
                        indicator.parentNode.removeChild(indicator);
                    }
                    self.appendBotBubble(data.bot_reply, data.tool_calls, data.triage_activado);

                    // Refrescar vistas operativas para ver los cambios de inmediato
                    if (window.RealtimeManager) {
                        window.RealtimeManager.syncActiveView();
                    }
                })
                .catch(function (err) {
                    if (indicator && indicator.parentNode) {
                        indicator.parentNode.removeChild(indicator);
                    }
                    self.appendBotBubble("Error procesando solicitud: " + err.message, [], false);
                });
        },

        appendUserBubble: function (texto) {
            var stream = document.getElementById("wa-chat-stream");
            if (!stream) return;

            var bubble = document.createElement("div");
            bubble.className = "wa-bubble-user";
            bubble.textContent = texto;

            stream.appendChild(bubble);
            stream.scrollTop = stream.scrollHeight;
        },

        appendBotBubble: function (texto, toolCalls, triageActivado) {
            var stream = document.getElementById("wa-chat-stream");
            if (!stream) return;

            var wrapper = document.createElement("div");
            wrapper.className = "space-y-1 self-start max-w-[85%]";

            var bubble = document.createElement("div");
            bubble.className = "wa-bubble-bot";
            bubble.textContent = texto;
            wrapper.appendChild(bubble);

            // Badges tecnicos de herramientas ejecutadas
            if (toolCalls && toolCalls.length > 0) {
                for (var i = 0; i < toolCalls.length; i++) {
                    var toolPill = document.createElement("span");
                    toolPill.className = "inline-block px-2 py-0.5 mr-1 rounded text-2xs font-mono font-medium bg-slate-200 text-slate-700";
                    toolPill.textContent = "Herramienta: " + toolCalls[i];
                    wrapper.appendChild(toolPill);
                }
            }

            // Alerta medica si activo Triage
            if (triageActivado) {
                var triageBadge = document.createElement("div");
                triageBadge.className = "p-1.5 rounded bg-rose-50 border border-rose-200 text-rose-800 text-2xs font-semibold flex items-center gap-1";
                triageBadge.textContent = "ALERTA MEDICA: Caso escalado a Triage Prioritario en el consultorio.";
                wrapper.appendChild(triageBadge);
            }

            stream.appendChild(wrapper);
            stream.scrollTop = stream.scrollHeight;
        }
    };

    // Inicializar al cargar el DOM
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            DemoModule.init();
        });
    } else {
        DemoModule.init();
    }

    window.DemoModule = DemoModule;
})();
