/**
 * Wingcast - Chat Frontend Logic
 */
(function () {
    'use strict';

    if (typeof marked !== 'undefined' && typeof marked.use === 'function') {
        marked.use({
            gfm: true,
            breaks: true,
        });
    }

    var messagesEl = document.getElementById('chatMessages');
    var inputEl = document.getElementById('chatInput');
    var sendBtn = document.getElementById('chatSendBtn');
    var typingEl = document.getElementById('typingIndicator');
    var quickActions = document.getElementById('quickActions');
    var sessionId = getSessionId();
    var isLoading = false;

    function getSessionId() {
        var id = localStorage.getItem('wingcast_session');
        if (!id) {
            id = 'sess_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
            localStorage.setItem('wingcast_session', id);
        }
        return id;
    }

    function appendMessage(role, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}-message`;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';

        // Markdown Rendering
        var processedText = text;
        var recommendedSpots = [];

        // Extract [RECOMMENDED: SpotName] / [RECOMMENDED: SpotName | status]
        // / [RECOMMENDED: SpotName | safety=green, stars=4]  (RATING_CONCEPT v1.3)
        var regex = /\[RECOMMENDED:\s*([^\]|]+?)(?:\s*\|\s*([^\]]+?))?\]/g;
        var match;
        while ((match = regex.exec(text)) !== null) {
            var rawArg = (match[2] || '').trim().toLowerCase();
            var entry = { name: match[1].trim(), status: 'green', safety: null, stars: null };
            if (rawArg.indexOf('=') >= 0) {
                // Neues Format: safety=..., stars=...
                rawArg.split(',').forEach(function (kv) {
                    var pair = kv.split('=').map(function (s) { return s.trim(); });
                    if (pair.length === 2) {
                        if (pair[0] === 'safety') entry.safety = pair[1];
                        else if (pair[0] === 'stars') {
                            var n = parseInt(pair[1], 10);
                            if (!isNaN(n)) entry.stars = n;
                        }
                    }
                });
                // Legacy-status fuer Backwards-Compat ableiten
                if (entry.safety === 'red') entry.status = 'not_safe';
                else if (entry.safety === 'amber') entry.status = 'amber';
                else if (entry.stars != null && entry.stars >= 4) entry.status = 'violet';
                else entry.status = 'green';
            } else if (rawArg) {
                // Legacy-Format: nur status
                entry.status = rawArg;
            }
            recommendedSpots.push(entry);
        }

        // Remove tags from displayed text (incl. surrounding **bold**, `backtick` markers)
        processedText = text.replace(/`?\*{0,2}\[RECOMMENDED:\s*.*?\]\*{0,2}`?/g, '').trim();
        // Remove empty list items left behind (e.g. "- " or "- ****")
        processedText = processedText.replace(/^[ \t]*[-*]\s*(\*{2,4})?\s*$/gm, '');
        // Remove trailing "Ich empfehle dir:" (or similar) when nothing follows
        processedText = processedText.replace(/\n*Ich empfehle dir:\s*$/i, '').trim();

        // Fix unclosed ```chartjs code blocks before markdown parsing
        processedText = processedText.replace(
            /```chartjs\s*\n([\s\S]*?)(?:\n```|$)/g,
            function (match, inner) {
                if (match.trimEnd().endsWith('```')) return match;   // already closed
                // Split: first line of JSON vs trailing text
                var lines = inner.split('\n');
                var jsonLines = [];
                for (var k = 0; k < lines.length; k++) {
                    var ln = lines[k].trim();
                    if (ln === '' || ln.charAt(0) === '{' || ln.charAt(0) === '"' || ln.charAt(0) === '[' || /^[\d\s,\]\}]/.test(ln)) {
                        jsonLines.push(lines[k]);
                    } else {
                        break;
                    }
                }
                var rest = lines.slice(jsonLines.length).join('\n').trim();
                return '```chartjs\n' + jsonLines.join('\n') + '\n```' + (rest ? '\n' + rest : '');
            }
        );

        if (typeof marked !== 'undefined') {
            contentDiv.innerHTML = marked.parse(processedText);
        } else {
            contentDiv.textContent = processedText;
        }

        // Replace visualization tags in rendered HTML (after marked.parse to avoid wrapping issues)
        // Note: marked.js may wrap tags in <p> or encode special chars, so we match flexibly
        if (role === 'bot') {
            var html = contentDiv.innerHTML;

            // Replace [CHART:type|params] with placeholder divs
            html = html.replace(
                /(?:<p>)?\[CHART:(\w+)\|([^\]]+)\](?:<\/p>)?/g,
                function (match, type, paramStr) {
                    return '<div class="chat-chart-placeholder" data-chart-type="' +
                        type + '" data-chart-params="' + paramStr.replace(/&amp;/g, '&').replace(/"/g, '&quot;') + '"></div>';
                }
            );

            // Replace [METEOGRAM:params] with placeholder divs
            html = html.replace(
                /(?:<p>)?\[METEOGRAM:([^\]]+)\](?:<\/p>)?/g,
                function (match, paramStr) {
                    return '<div class="chat-meteogram" data-meteogram-params="' +
                        paramStr.replace(/&amp;/g, '&').replace(/"/g, '&quot;') + '"></div>';
                }
            );

            // Replace [MAP:params] with placeholder divs
            html = html.replace(
                /(?:<p>)?\[MAP:([^\]]+)\](?:<\/p>)?/g,
                function (match, paramStr) {
                    return '<div class="chat-minimap" data-map-params="' +
                        paramStr.replace(/&amp;/g, '&').replace(/"/g, '&quot;') + '"></div>';
                }
            );

            contentDiv.innerHTML = html;
        }

        // Highlight on map if we have recommendations and it's a bot message
        if (role === 'bot' && recommendedSpots.length > 0 && window.highlightSpots) {
            window.highlightSpots(recommendedSpots);
        }

        msgDiv.appendChild(contentDiv);
        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        // Render visualizations for bot messages
        if (role === 'bot' && window.ChatCharts) {
            ChatCharts.renderTemplateCharts(contentDiv);
            ChatCharts.renderMeteograms(contentDiv);
            ChatCharts.renderMaps(contentDiv);
            ChatCharts.renderChartjsBlocks(contentDiv);
        }
    }

    var skeletonEl = null;

    function showTyping() {
        // Use skeleton shimmer instead of typing dots
        if (!skeletonEl) {
            skeletonEl = document.createElement('div');
            skeletonEl.className = 'skeleton-loading';
            skeletonEl.innerHTML = '<div class="skeleton-line"></div><div class="skeleton-line"></div><div class="skeleton-line"></div>';
        }
        messagesEl.appendChild(skeletonEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function hideTyping() {
        if (skeletonEl && skeletonEl.parentNode) {
            skeletonEl.parentNode.removeChild(skeletonEl);
        }
    }

    function setLoading(loading) {
        isLoading = loading;
        sendBtn.disabled = loading;
        inputEl.disabled = loading;
        if (loading) showTyping();
        else hideTyping();
    }

    function detectFormatHint(message) {
        var msg = message.toLowerCase();
        if (/vergleich|versus|vs\.?|gegenueber|tabelle/.test(msg)) return 'table';
        if (/grafik|graph|diagramm|verlauf|chart|zeitlich|entwicklung|visuali/.test(msg)) return 'chart';
        if (/meteogramm/.test(msg)) return 'meteogram';
        if (/karte|wo liegt|wo ist|zeig.*auf.*karte/.test(msg)) return 'map';
        return null;
    }

    // Phase 1: Map-Action Dispatcher — empfängt Tool-Use Events vom Backend
    // und ruft die window.flymap API auf.
    function handleMapAction(event) {
        if (!event) return;
        var action = event.action;
        var payload = event.payload || {};
        // showNotice ist KEINE Karten-Aktion und darf nicht an window.flymap
        // haengen: Es ist die Rueckmeldung an den Piloten, wenn die
        // Reichweiten-Suche nicht oder nur teilweise liefert. Sie kommt
        // absichtlich aus dem Backend und nicht aus dem Antworttext des
        // Sprachmodells — eine Prompt-Regel wird verletzt, sobald sie
        // unbequem ist, und dann steht der Pilot wieder vor einem
        // "versuch's nochmal", das nie klappt (25.09.2026).
        if (action === 'showNotice') {
            if (payload.text) appendMessage('bot', payload.text);
            return;
        }
        if (!window.flymap) return;
        try {
            switch (action) {
                case 'drawIsochrone':
                    window.flymap.drawIsochrone(payload.geojson, payload.label);
                    break;
                case 'clearIsochrone':
                    window.flymap.clearIsochrone();
                    break;
                case 'setUserLocation':
                    window.flymap.setUserLocation(payload.lat, payload.lon, payload.label);
                    break;
                case 'clearUserLocation':
                    window.flymap.clearUserLocation();
                    break;
                case 'highlightSpots':
                    window.flymap.highlightSpots(payload.spots);
                    break;
                case 'clearAllOverlays':
                    window.flymap.clearAllOverlays();
                    break;
                default:
                    console.warn('Unbekannte Map-Action:', action);
            }
        } catch (err) {
            console.error('Map-Action Fehler:', action, err);
        }
    }

    // Status-Hinweis-Element (während Tool-Use läuft)
    var statusEl = null;
    function showStatus(text) {
        if (!statusEl) {
            statusEl = document.createElement('div');
            statusEl.className = 'message bot-message status-message';
            statusEl.style.opacity = '0.75';
            statusEl.style.fontStyle = 'italic';
            messagesEl.appendChild(statusEl);
        }
        statusEl.textContent = text;
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }
    function clearStatus() {
        if (statusEl && statusEl.parentNode) {
            statusEl.parentNode.removeChild(statusEl);
        }
        statusEl = null;
    }

    function handleStreamingResponse(resp) {
        var reader = resp.body.getReader();
        var decoder = new TextDecoder('utf-8');
        var buffer = '';

        function processBuffer(flush) {
            var lines = buffer.split('\n');
            // letzter Eintrag bleibt im buffer (kann unvollständig sein), ausser wir flushen
            buffer = flush ? '' : lines.pop();
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim();
                if (!line) continue;
                var event;
                try { event = JSON.parse(line); } catch (e) {
                    console.warn('NDJSON parse failed:', line, e);
                    continue;
                }
                dispatchEvent(event);
            }
        }

        function dispatchEvent(event) {
            if (!event || !event.type) return;
            switch (event.type) {
                case 'text':
                    clearStatus();
                    if (event.content) appendMessage('bot', event.content);
                    break;
                case 'map_action':
                    handleMapAction(event);
                    break;
                case 'status':
                    if (event.content) showStatus(event.content);
                    break;
                case 'error':
                    clearStatus();
                    appendMessage('bot', wcT('js.error.prefix', { msg: event.content || wcT('js.chat.unknown_error') }));
                    break;
                case 'done':
                    clearStatus();
                    break;
                default:
                    console.warn('Unbekannter Stream-Event:', event.type);
            }
        }

        function pump() {
            return reader.read().then(function (result) {
                if (result.done) {
                    if (buffer) {
                        buffer += '\n';
                        processBuffer(true);
                    }
                    return;
                }
                buffer += decoder.decode(result.value, { stream: true });
                processBuffer(false);
                return pump();
            });
        }

        return pump();
    }

    function sendMessage(text) {
        if (!text.trim() || isLoading) return;

        if (window.wcTrack) wcTrack('chat_message_sent');

        appendMessage('user', text);

        // Reset highlights on new user message
        if (window.highlightSpots) window.highlightSpots(null);
        // Compact quick actions after first message (keep visible as chips)
        if (quickActions) quickActions.classList.add('compact');

        setLoading(true);

        // Append format hint if detected
        var hint = detectFormatHint(text);
        var msgToSend = text;
        if (hint) msgToSend = text + ' [FORMAT-HINT: ' + hint + ']';

        fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                // Phase 1: opt-in zu Streaming + Tool-Use
                'Accept': 'application/x-ndjson'
            },
            body: JSON.stringify({ message: msgToSend, session_id: sessionId })
        })
            .then(function (resp) {
                // Defense-in-depth: wenn der Server 401 mit login_required liefert,
                // direkt das Login-Modal oeffnen statt generischen Fehler zeigen.
                if (resp.status === 401) {
                    return resp.json().catch(function () { return null; }).then(function (body) {
                        if (body && body.login_required) {
                            var loginBtn = document.getElementById('navLoginBtn');
                            if (loginBtn) loginBtn.click();
                            var msg = body.message || wcT('js.chat.login_required');
                            throw new Error(msg);
                        }
                        throw new Error('Server error: 401');
                    });
                }
                if (!resp.ok) throw new Error('Server error: ' + resp.status);
                var contentType = resp.headers.get('Content-Type') || '';
                if (contentType.indexOf('application/x-ndjson') !== -1) {
                    return handleStreamingResponse(resp);
                }
                // Legacy fallback (Server unterstützt kein Streaming)
                return resp.json().then(function (data) {
                    appendMessage('bot', data.reply || wcT('js.chat.no_reply'));
                });
            })
            .catch(function (err) {
                clearStatus();
                var errorDiv = document.createElement('div');
                errorDiv.className = 'message bot-message';
                var contentDiv = document.createElement('div');
                contentDiv.className = 'message-content';
                var msgP = document.createElement('p');
                msgP.textContent = 'Fehler: ' + (err && err.message ? err.message : 'Unbekannt');
                contentDiv.appendChild(msgP);
                var dismissBtn = document.createElement('button');
                dismissBtn.className = 'btn btn-secondary btn-sm';
                dismissBtn.style.marginTop = '8px';
                dismissBtn.textContent = 'Verwerfen';
                dismissBtn.addEventListener('click', function () { errorDiv.remove(); });
                contentDiv.appendChild(dismissBtn);
                var retryBtn = document.createElement('button');
                retryBtn.className = 'btn btn-primary btn-sm';
                retryBtn.style.marginTop = '8px';
                retryBtn.style.marginLeft = '8px';
                retryBtn.textContent = 'Erneut versuchen';
                retryBtn.addEventListener('click', function () {
                    errorDiv.remove();
                    sendMessage(text);
                });
                contentDiv.appendChild(retryBtn);
                errorDiv.appendChild(contentDiv);
                messagesEl.appendChild(errorDiv);
                messagesEl.scrollTop = messagesEl.scrollHeight;
            })
            .finally(function () {
                clearStatus();
                setLoading(false);
                inputEl.focus();
            });
    }

    // ── Textarea auto-resize ──────────────────────────
    function autoResizeInput() {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
        // Re-enable overflow-y when content exceeds max
        inputEl.style.overflowY = inputEl.scrollHeight > 160 ? 'auto' : 'hidden';
    }

    inputEl.addEventListener('input', autoResizeInput);

    function resetInputHeight() {
        inputEl.style.height = 'auto';
        inputEl.style.overflowY = 'hidden';
    }

    // Event Listeners
    sendBtn.addEventListener('click', function () {
        sendMessage(inputEl.value);
        inputEl.value = '';
        resetInputHeight();
    });

    inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(inputEl.value);
            inputEl.value = '';
            resetInputHeight();
        }
        // Shift+Enter = newline (default behavior for textarea)
    });

    // Reset Chat
    var resetBtn = document.getElementById('resetChatBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function () {
            if (!confirm(wcT('js.chat.reset_confirm'))) return;

            fetch('/api/reset-chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Reset fehlgeschlagen');
                    return resp.json();
                })
                .then(function (data) {
                    if (data.success) {
                        // UI zurücksetzen
                        messagesEl.innerHTML = '';
                        appendMessage('bot', wcT('chat.welcome'));
                        if (quickActions) {
                            quickActions.classList.remove('compact');
                        }
                        if (window.highlightSpots) window.highlightSpots(null);
                        inputEl.value = '';
                        resetInputHeight();
                        inputEl.focus();
                    }
                })
                .catch(function (err) {
                    alert('Fehler: ' + err.message);
                });
        });
    }

    // Quick Action Buttons
    document.querySelectorAll('.quick-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var msg = btn.getAttribute('data-msg');
            if (msg) sendMessage(msg);
        });
    });

    // ── Onboarding Hints (first visit only) ──────────────
    (function () {
        var key = 'wingcast_onboarded';
        if (localStorage.getItem(key)) return;
        localStorage.setItem(key, '1');
        var qa = document.getElementById('quickActions');
        if (!qa) return;

        function showHint(target, text) {
            var hint = document.createElement('div');
            hint.className = 'onboarding-hint';
            hint.textContent = text;
            document.body.appendChild(hint);
            var rect = target.getBoundingClientRect();
            hint.style.left = (rect.left + rect.width / 2 - hint.offsetWidth / 2) + 'px';
            hint.style.top = (rect.top - hint.offsetHeight - 10) + 'px';
            setTimeout(function () { if (hint.parentNode) hint.remove(); }, 4000);
        }

        setTimeout(function () { showHint(qa, 'Klicke hier fuer Schnellfragen'); }, 1500);
    })();

    // Listen for spot analyses to drive quick actions
    var _analysisCheckInterval = setInterval(function () {
        var hasSpots = window.analysisData && Object.keys(window.analysisData).length > 0;
        if (hasSpots) {
            updateQuickActionsFromAnalyses(window.analysisData);
            clearInterval(_analysisCheckInterval);
        }
    }, 500);
    setTimeout(function () { clearInterval(_analysisCheckInterval); }, 30000);

    // ── Context-Aware Quick Actions ──────────────────────────
    // Strategie: Buttons = Werbung fuer die Chat-Tools. Drei Schichten:
    //   1. USP-Anker (immer aktiv): Isochrone + Vergleichstabelle — gibt's im Dashboard nicht.
    //   2. Visualisierungs-Discovery (tageweise Rotation): Meteogramm, Thermik-Heatmap,
    //      Windverlauf, Hoehenwind & Turbulenz — jeder dieser 4 Buttons bekommt einmal
    //      pro 4-Tage-Zyklus einen Score-Boost, damit User ueber mehrere Tage hinweg
    //      alle Haupt-Tools mindestens einmal sieht.
    //   3. Situative Trigger (live aus analysisData): Klassiker-Tag, Foehn-Risiko,
    //      Plan B (>=50% unsafe) — tauchen nur auf, wenn die Wetterlage es hergibt.
    // Labels bleiben neutral, keine konkreten Spotnamen (LLM picked Spot zur Laufzeit).
    function updateQuickActionsFromAnalyses(analysisData) {
        if (!quickActions) return;

        var now = new Date();
        var pad2 = function (n) { return String(n).padStart(2, '0'); };
        var fmtDate = function (d) {
            return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
        };
        var todayStr = fmtDate(now);
        var tomorrowStr = fmtDate(new Date(now.getTime() + 86400000));

        // Live-Aggregation aus den Voranalysen (echte Werte, nichts hartcodiert)
        var xcTodayCount = 0;
        var foehnTodayCount = 0;
        var notSafeCount = 0;
        var flyableTodayCount = 0;
        var totalToday = 0;
        var bestTomorrowRating = 0;

        Object.keys(analysisData).forEach(function (name) {
            var d = analysisData[name][todayStr];
            if (d) {
                totalToday++;
                var er = parseInt(d.experience_rating, 10);
                if (!isFinite(er)) er = 0;
                if (d.safety_status === 'not_safe') {
                    notSafeCount++;
                } else {
                    flyableTodayCount++;
                }
                if (er === 5 && d.safety_status !== 'not_safe') xcTodayCount++;
                var foehnRisk = (d.safety && d.safety.foehn_risk) || d.foehn_risk || 'none';
                if (foehnRisk && foehnRisk !== 'none') foehnTodayCount++;
            }
            var dm = analysisData[name][tomorrowStr];
            if (dm && dm.safety_status !== 'not_safe') {
                var emt = parseInt(dm.experience_rating, 10);
                if (isFinite(emt) && emt > bestTomorrowRating) bestTomorrowRating = emt;
            }
        });

        // 3-Tage-Rotation fuer die rotierenden Visualisierungs-Buttons
        // (Windverlauf ist KEIN Rotations-Slot mehr, sondern always-on)
        var dayOfYear = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86400000);
        var vizSlot = dayOfYear % 3;
        var VIZ_BOOST = 3;
        var VIZ_BASE = 5;

        var candidates = [];

        // === Immer aktiv — USP-Anker ===
        // "Karte: 1h ab Zürich" ist am 27.09.2026 bewusst deaktiviert.
        // Grund: Der Vorschlag führte in eine Sackgasse — der Gratis-Kartendienst
        // deckelt die erreichbare Zone bei 60 Minuten und liefert zu ~60 % der
        // Startplätze keine Fahrzeit; ein Pilot hat am 25.09. dreimal vergeblich
        // "try again" gedrückt und ist nicht wiedergekommen
        // (validation/chat/BEFUNDE.md §7). Einen Chip anzubieten heisst, die
        // Funktion zu bewerben — das machen wir erst wieder, wenn sie sauber
        // läuft. Wiedereinschalten: diesen Block plus die Buttons in
        // templates/index.html und templates/regionen.html. Voraussetzung:
        // docs/pläne/PLAN_routing_eigene_instanz.md, Schritt 2.
        // Die i18n-Schlüssel chat.quick_map_* bleiben absichtlich stehen.

        candidates.push({
            label: wcT('chat.quick_top3_label'),
            msg: wcT('chat.quick_top3_msg'),
            score: 9
        });

        // Windverlauf — always-on (User soll diesen Chart immer sehen koennen)
        if (flyableTodayCount > 0) {
            candidates.push({
                label: wcT('chat.quick_wind_label'),
                msg: wcT('chat.quick_wind_msg'),
                score: 8
            });
        }

        // === Visualisierungs-Discovery (tageweise Rotation, neutral formuliert) ===
        if (flyableTodayCount > 0) {
            candidates.push({
                label: wcT('js.chat.q_meteogram_label'),
                msg: wcT('js.chat.q_meteogram_msg'),
                score: VIZ_BASE + (vizSlot === 0 ? VIZ_BOOST : 0)
            });
            candidates.push({
                label: wcT('js.chat.q_heatmap_label'),
                msg: wcT('js.chat.q_heatmap_msg'),
                score: VIZ_BASE + (vizSlot === 1 ? VIZ_BOOST : 0)
            });
            candidates.push({
                label: wcT('js.chat.q_upperwind_label'),
                msg: wcT('js.chat.q_upperwind_msg'),
                score: VIZ_BASE + (vizSlot === 2 ? VIZ_BOOST : 0)
            });
        }

        // === Situativ — XC / Streckenflug ===
        if (xcTodayCount > 0) {
            candidates.push({
                label: wcT('js.chat.q_xc_today_label'),
                msg: wcT('js.chat.q_xc_today_msg'),
                score: 12
            });
        } else if (bestTomorrowRating >= 4) {
            candidates.push({
                label: wcT('js.chat.q_xc_tomorrow_label'),
                msg: wcT('js.chat.q_xc_tomorrow_msg'),
                score: 11
            });
        } else {
            candidates.push({
                label: wcT('js.chat.q_xc_week_label'),
                msg: wcT('js.chat.q_xc_week_msg'),
                score: 7
            });
        }

        // === Situativ — Foehn ===
        if (foehnTodayCount > 0) {
            candidates.push({
                label: wcT('js.chat.q_foehn_today_label'),
                msg: wcT('js.chat.q_foehn_today_msg'),
                score: 11
            });
        } else {
            candidates.push({
                label: wcT('js.chat.q_foehn_week_label'),
                msg: wcT('js.chat.q_foehn_week_msg'),
                score: 5
            });
        }

        // === Situativ — Plan B (>=50% Spots unsafe) ===
        if (totalToday > 0 && notSafeCount / totalToday >= 0.5) {
            candidates.push({
                label: wcT('js.chat.q_planb_label'),
                msg: wcT('js.chat.q_planb_msg'),
                score: 10
            });
        }

        // === Standard — Wochenuebersicht ===
        candidates.push({
            label: wcT('js.chat.q_bestday_label'),
            msg: wcT('js.chat.q_bestday_msg'),
            score: 6
        });

        // Top 5 nach Score (Tie-Break stabil dank push-Reihenfolge)
        candidates.sort(function (a, b) { return b.score - a.score; });
        var picked = candidates.slice(0, 5);

        quickActions.innerHTML = '';
        picked.forEach(function (a) {
            var btn = document.createElement('button');
            btn.className = 'quick-btn';
            btn.setAttribute('data-msg', a.msg);
            btn.textContent = a.label;
            btn.addEventListener('click', function () { sendMessage(a.msg); });
            quickActions.appendChild(btn);
        });
    }

    // ── Data Freshness Indicator ──────────────────────────
    var freshnessEl = document.getElementById('dataFreshness');
    var _freshnessIso = null;
    function updateFreshness(isoStr) {
        if (!freshnessEl || !isoStr) return;
        _freshnessIso = isoStr;
        _renderFreshness();
    }

    function _renderFreshness() {
        if (!freshnessEl || !_freshnessIso) return;
        var ts = new Date(_freshnessIso);
        var ageMs = Date.now() - ts.getTime();
        var ageMin = ageMs / 60000;
        var hh = String(ts.getHours()).padStart(2, '0');
        var mm = String(ts.getMinutes()).padStart(2, '0');
        var ageLabel;
        var cls;
        if (ageMin < 30) {
            ageLabel = 'Aktuell';
            cls = 'fresh';
        } else if (ageMin < 120) {
            ageLabel = Math.round(ageMin) + ' min';
            cls = 'stale';
        } else {
            ageLabel = Math.round(ageMin / 60) + ' h';
            cls = 'old';
        }
        freshnessEl.textContent = hh + ':' + mm + ' \u00B7 ' + ageLabel;
        freshnessEl.className = 'data-freshness ' + cls;
        freshnessEl.title = 'Wetterdaten von ' + hh + ':' + mm + ' Uhr (' + ageLabel + ' alt)';
    }

    // Refresh age display every 60s
    setInterval(_renderFreshness, 60000);

    // Check weather_state from API
    fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
        if (d.weather_loaded_at) updateFreshness(d.weather_loaded_at);
    }).catch(function () { /* ignore */ });

    // Update after successful weather refresh
    window.updateDataFreshness = updateFreshness;

    // Beim Öffnen den (user-gebundenen) Chat-Verlauf laden und anzeigen.
    function loadHistory() {
        fetch('/api/chat-history', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.messages || !d.messages.length) return;
                var welcome = document.getElementById('chatWelcome');
                if (welcome) welcome.remove();
                d.messages.forEach(function (m) {
                    appendMessage(m.role === 'assistant' ? 'bot' : 'user', m.content || '');
                });
                if (quickActions) quickActions.classList.add('compact');
                messagesEl.scrollTop = messagesEl.scrollHeight;
            })
            .catch(function () { /* ignore */ });
    }
    loadHistory();

    inputEl.focus();
})();
