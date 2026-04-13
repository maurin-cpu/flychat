/**
 * Flychat - Chat Frontend Logic
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
        var id = localStorage.getItem('flychat_session');
        if (!id) {
            id = 'sess_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
            localStorage.setItem('flychat_session', id);
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

        // Extract [RECOMMENDED: SpotName | status] tags
        var regex = /\[RECOMMENDED:\s*([^\]|]+?)(?:\s*\|\s*([^\]]+?))?\]/g;
        var match;
        while ((match = regex.exec(text)) !== null) {
            recommendedSpots.push({
                name: match[1].trim(),
                status: (match[2] || 'green').trim().toLowerCase()
            });
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

    function showTyping() {
        typingEl.classList.add('visible');
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function hideTyping() {
        typingEl.classList.remove('visible');
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
        if (!event || !window.flymap) return;
        var action = event.action;
        var payload = event.payload || {};
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
                    appendMessage('bot', 'Fehler: ' + (event.content || 'Unbekannter Fehler'));
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

        appendMessage('user', text);

        // Reset highlights on new user message
        if (window.highlightSpots) window.highlightSpots(null);
        // Hide quick actions after first message
        if (quickActions) quickActions.style.display = 'none';

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
                if (!resp.ok) throw new Error('Server error: ' + resp.status);
                var contentType = resp.headers.get('Content-Type') || '';
                if (contentType.indexOf('application/x-ndjson') !== -1) {
                    return handleStreamingResponse(resp);
                }
                // Legacy fallback (Server unterstützt kein Streaming)
                return resp.json().then(function (data) {
                    appendMessage('bot', data.reply || 'Keine Antwort erhalten.');
                });
            })
            .catch(function (err) {
                clearStatus();
                appendMessage('bot', 'Fehler: ' + err.message);
            })
            .finally(function () {
                clearStatus();
                setLoading(false);
                inputEl.focus();
            });
    }

    // Event Listeners
    sendBtn.addEventListener('click', function () {
        sendMessage(inputEl.value);
        inputEl.value = '';
    });

    inputEl.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(inputEl.value);
            inputEl.value = '';
        }
    });

    // Reset Chat
    var resetBtn = document.getElementById('resetChatBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function () {
            if (!confirm('Gesamte Konversation zurücksetzen?')) return;

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
                        appendMessage('bot', 'Hallo! Ich bin dein Flychat-Berater. Frag mich zu Flugbedingungen, Gebietswahl oder Sicherheit.');
                        if (quickActions) quickActions.style.display = 'flex';
                        if (window.highlightSpots) window.highlightSpots(null);
                        inputEl.value = '';
                        inputEl.focus();
                    }
                })
                .catch(function (err) {
                    alert('Fehler: ' + err.message);
                });
        });
    }

    // ── Progress Card helpers ──────────────────────────

    function formatElapsed(startTime) {
        var sec = Math.floor((Date.now() - startTime) / 1000);
        if (sec < 60) return sec + 's';
        return Math.floor(sec / 60) + 'm ' + String(sec % 60).padStart(2, '0') + 's';
    }

    function createProgressCard(title, steps) {
        var el = document.createElement('div');
        el.className = 'message bot-message progress-card';

        var stepsHtml = steps.map(function (label, i) {
            return '<div class="progress-step step-pending" data-step="' + i + '">' +
                '<span class="step-icon">\u25CB</span>' +
                '<span class="step-label">' + label + '</span>' +
                '</div>';
        }).join('');

        el.innerHTML =
            '<div class="progress-header">' +
                '<span class="progress-title">' + title + '</span>' +
                '<span class="progress-timer">0s</span>' +
            '</div>' +
            '<div class="progress-bar-track">' +
                '<div class="progress-bar-fill indeterminate"></div>' +
            '</div>' +
            '<div class="progress-steps">' + stepsHtml + '</div>';

        messagesEl.appendChild(el);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        var startTime = Date.now();
        var timerEl = el.querySelector('.progress-timer');
        var timerId = setInterval(function () {
            timerEl.textContent = formatElapsed(startTime);
        }, 1000);

        return { el: el, timerId: timerId, startTime: startTime, total: steps.length };
    }

    function setProgressStep(card, stepIndex, state) {
        var stepEls = card.el.querySelectorAll('.progress-step');
        if (stepIndex < 0 || stepIndex >= stepEls.length) return;

        // Fix C: 'unknown' (?) für Fehler an unbekanntem Schritt — Steps sind
        // simulierte Timer und können den echten Fehlerort nicht kennen.
        var icons = { pending: '\u25CB', active: '\u25C9', done: '\u2713', error: '\u2717', unknown: '?' };
        var classes = {
            pending: 'step-pending', active: 'step-active', done: 'step-done',
            error: 'step-error', unknown: 'step-unknown'
        };

        // Mark all previous steps as done when activating a later step
        if (state === 'active') {
            for (var i = 0; i < stepIndex; i++) {
                var prev = stepEls[i];
                prev.className = 'progress-step step-done';
                prev.querySelector('.step-icon').textContent = '\u2713';
            }
        }

        var step = stepEls[stepIndex];
        step.className = 'progress-step ' + (classes[state] || classes.pending);
        step.querySelector('.step-icon').textContent = icons[state] || icons.pending;

        // Update progress bar
        var doneCount = card.el.querySelectorAll('.step-done').length;
        var bar = card.el.querySelector('.progress-bar-fill');
        if (state === 'active') {
            bar.classList.remove('indeterminate', 'bar-done', 'bar-error');
            bar.style.width = Math.round(((doneCount + 0.5) / card.total) * 100) + '%';
        }

        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function finalizeProgress(card, success, extraHtml) {
        clearInterval(card.timerId);
        var timerEl = card.el.querySelector('.progress-timer');
        timerEl.textContent = formatElapsed(card.startTime);

        var bar = card.el.querySelector('.progress-bar-fill');
        bar.classList.remove('indeterminate');
        bar.style.width = '100%';

        var stepEls = card.el.querySelectorAll('.progress-step');
        if (success) {
            bar.classList.add('bar-done');
            stepEls.forEach(function (s) {
                if (!s.classList.contains('step-done')) {
                    s.className = 'progress-step step-done';
                    s.querySelector('.step-icon').textContent = '\u2713';
                }
            });
        } else {
            bar.classList.add('bar-error');
            // Fix C: Wir wissen NICHT, welcher Schritt wirklich fehlgeschlagen ist
            // (die Steps sind timer-basiert, nicht echt). Statt einen falschen
            // Schritt mit ✗ zu markieren, markieren wir den aktiven Schritt als "?".
            stepEls.forEach(function (s) {
                if (s.classList.contains('step-active')) {
                    s.className = 'progress-step step-unknown';
                    s.querySelector('.step-icon').textContent = '?';
                }
            });
        }

        if (extraHtml) {
            var extra = document.createElement('div');
            extra.innerHTML = extraHtml;
            card.el.appendChild(extra);
        }

        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function buildStatsHtml(stats) {
        var items = stats.map(function (s) {
            return '<div class="progress-stat">' +
                '<div class="stat-value">' + s.value + '</div>' +
                '<div class="stat-label">' + s.label + '</div>' +
                '</div>';
        }).join('');
        return '<div class="progress-stats">' + items + '</div>';
    }

    function buildDayChipsHtml(data) {
        var dates = data.dates || [];
        var perDay = data.per_day_counts || {};
        if (!dates.length) return '';

        var rows = dates.map(function (dateStr) {
            var counts = perDay[dateStr] || {};
            var sc = counts.safety || {};
            var chips = '';
            if (sc.safe) chips += '<span class="day-chip chip-safe">' + sc.safe + ' Sicher</span>';
            if (sc.conditional) chips += '<span class="day-chip chip-conditional">' + sc.conditional + ' Bedingt</span>';
            if (sc.not_safe) chips += '<span class="day-chip chip-not-safe">' + sc.not_safe + ' Unsicher</span>';
            if (counts.error) chips += '<span class="day-chip chip-error">' + counts.error + ' Fehler</span>';

            // Format date: "2025-04-01" → "01.04"
            var parts = dateStr.split('-');
            var dayLabel = parts.length === 3 ? parts[2] + '.' + parts[1] : dateStr;

            return '<div class="day-row">' +
                '<span class="day-label">' + dayLabel + '</span>' +
                '<div class="day-chips">' + chips + '</div>' +
                '</div>';
        }).join('');

        return '<div class="progress-days">' + rows + '</div>';
    }

    function buildAnalysisSummary(data) {
        var dates = data.dates || [];
        var perDay = data.per_day_counts || {};
        var details = data.results_summary || {};
        var summary = '';
        var flyTierLabels = {
            gray: 'Grau (Abgleiter)',
            green: 'Gr\u00fcn',
            violet: 'Violett',
            not_safe: '\u2014',
            error: '\u2014'
        };
        var safetyLabels = {
            safe: 'Gr\u00fcn (sicher)',
            conditional: 'Orange (bedingt)',
            not_safe: 'Rot (nicht sicher)',
            error: 'Fehler'
        };

        summary += '\u2705 **LLM-Analyse abgeschlossen**\n';
        summary += '\n- Spots: **' + data.spots_count + '**';
        summary += '\n- Tage: **' + dates.length + '**';
        summary += '\n- LLM-Aufrufe: **' + data.results_count + '**';
        if (data.safety_count !== undefined) {
            summary += ' (Safety: ' + data.safety_count + ', Flyability: ' + (data.flyability_count || 0) + ')';
        }

        dates.forEach(function (dateStr) {
            var counts = perDay[dateStr] || {};
            var sc = counts.safety || {};
            var fc = counts.fly || {};
            var chips = [];
            if (sc.safe) chips.push(sc.safe + ' Sich. Gr\u00fcn');
            if (sc.conditional) chips.push(sc.conditional + ' Sich. Orange');
            if (sc.not_safe) chips.push(sc.not_safe + ' Sich. Rot');
            if (fc.violet) chips.push(fc.violet + ' Flug Violett');
            if (fc.green) chips.push(fc.green + ' Flug Gr\u00fcn');
            if (fc.gray) chips.push(fc.gray + ' Flug Grau');
            if (counts.error) chips.push(counts.error + ' Fehler');

            summary += '\n\n---\n### ' + dateStr;
            summary += '\n**Tagesbild:** ' + (chips.length ? chips.join(', ') : 'keine Daten');

            Object.keys(details).sort().forEach(function (name) {
                var d = (details[name] || {})[dateStr];
                if (!d) return;
                var ft = d.fly_status || '';
                var flyLabel = ft
                    ? (flyTierLabels[ft] || ft)
                    : (d.safety_status === 'not_safe' ? '\u2014 (keine Fliegbarkeit)' : '?');
                var safeLabel = safetyLabels[d.safety_status] || d.safety_status || 'unbekannt';
                var line = '- **' + name + '**: Sicherheit **' + safeLabel + '**, Fliegbarkeit **' + flyLabel + '**';
                if (d.best_window && d.best_window !== 'keins') {
                    line += ' (' + d.best_window + ')';
                }
                if (d.recommendation) {
                    line += '\n  - ' + d.recommendation;
                }
                summary += '\n' + line;
            });
        });

        return summary;
    }

    // ── Button: Wetter laden ──────────────────────────
    var refreshWeatherBtn = document.getElementById('refreshWeatherBtn');
    if (refreshWeatherBtn) {
        refreshWeatherBtn.addEventListener('click', function () {
            if (refreshWeatherBtn.disabled) return;

            var runAnalysesBtn = document.getElementById('runAnalysesBtn');
            refreshWeatherBtn.disabled = true;
            refreshWeatherBtn.classList.add('loading');
            if (runAnalysesBtn) runAnalysesBtn.disabled = true;

            var card = createProgressCard('Wetterdaten laden', [
                'Wettermodelle herunterladen (ICON-D2 / EU / CH1 / CH2)',
                'Spots verarbeiten & Thermik berechnen',
                'F\u00f6hn-Lage & Wind-Stationen auswerten',
                'KI-Kontext aufbauen & speichern'
            ]);

            setProgressStep(card, 0, 'active');

            // Simulated step progression — Timing an reale Phasenlängen angepasst:
            // Phase 1 (Open-Meteo Batch): ~10-13s, dominiert die Gesamtdauer
            // Phase 2 (Per-Spot Processing): läuft parallel im Batch-Loop
            // Phase 3 (Föhn + Stations): ~2s
            // Phase 4 (Kontext + InstantDB): ~1s
            var simTimers = [];
            simTimers.push(setTimeout(function () { setProgressStep(card, 1, 'active'); }, 5000));
            simTimers.push(setTimeout(function () { setProgressStep(card, 2, 'active'); }, 13000));
            simTimers.push(setTimeout(function () { setProgressStep(card, 3, 'active'); }, 15500));

            fetch('/api/refresh-weather', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
                .then(function (resp) {
                    // Fix #1: Auch 503 (stale) hat einen JSON-Body — lesen und weitergeben
                    return resp.json().then(function (data) {
                        return { ok: resp.ok, status: resp.status, data: data };
                    });
                })
                .then(function (result) {
                    var data = result.data || {};
                    simTimers.forEach(clearTimeout);
                    if (data.success) {
                        var elapsed = formatElapsed(card.startTime);
                        var stats = buildStatsHtml([
                            { value: data.spots_count || '?', label: 'Spots' },
                            { value: (data.dates || []).length || data.days_count || '5', label: 'Tage' },
                            { value: elapsed, label: 'Dauer' }
                        ]);
                        finalizeProgress(card, true, stats);
                        if (window.refreshSpotMarkers) window.refreshSpotMarkers();
                    } else {
                        finalizeProgress(card, false);
                        var msg = data.error || ('Server error: ' + result.status);
                        if (data.stale && data.last_updated) {
                            msg += ' (Stand der vorhandenen Daten: ' + data.last_updated.replace('T', ' ').slice(0, 16) + ')';
                        }
                        appendMessage('bot', '⚠ Wetter-Refresh: ' + msg);
                    }
                })
                .catch(function (err) {
                    simTimers.forEach(clearTimeout);
                    finalizeProgress(card, false);
                    appendMessage('bot', 'Wetter laden fehlgeschlagen: ' + err.message);
                })
                .finally(function () {
                    refreshWeatherBtn.disabled = false;
                    refreshWeatherBtn.classList.remove('loading');
                    if (runAnalysesBtn) runAnalysesBtn.disabled = false;
                });
        });
    }

    // ── Button: LLM Analyse (SSE) ──────────────────────────
    var runAnalysesBtn = document.getElementById('runAnalysesBtn');
    if (runAnalysesBtn) {
        runAnalysesBtn.addEventListener('click', function () {
            if (runAnalysesBtn.disabled) return;

            var refreshWeatherBtn = document.getElementById('refreshWeatherBtn');
            runAnalysesBtn.disabled = true;
            runAnalysesBtn.classList.add('loading');
            if (refreshWeatherBtn) refreshWeatherBtn.disabled = true;

            var card = createProgressCard('LLM-Analyse', [
                'Sicherheitscheck',
                'Fliegbarkeit'
            ]);

            var phaseMap = {
                'all_safety': 0,
                'all_fly': 1,
                // Legacy single-type phases (run_spot/region_analyses_stream)
                'region_safety': 0,
                'region_fly': 1,
                'spot_safety': 0,
                'spot_fly': 1
            };

            // Track per-type progress within each phase
            var phaseProgress = {
                0: { region: 0, spot: 0, region_total: 0, spot_total: 0 },
                1: { region: 0, spot: 0, region_total: 0, spot_total: 0 }
            };

            var regionStats = null;
            var spotStats = null;

            var finished = false;
            var es = new EventSource('/api/run-all-analyses-stream');

            var baseLabels = [
                'Sicherheitscheck',
                'Fliegbarkeit'
            ];

            function finish(success, extraHtml, errorMsg) {
                if (finished) return;
                finished = true;
                es.close();
                finalizeProgress(card, success, extraHtml);
                if (errorMsg) appendMessage('bot', errorMsg);
                runAnalysesBtn.disabled = false;
                runAnalysesBtn.classList.remove('loading');
                if (refreshWeatherBtn) refreshWeatherBtn.disabled = false;
            }

            es.addEventListener('init', function () {
                setProgressStep(card, 0, 'active');
            });

            es.addEventListener('phase', function (e) {
                var d = JSON.parse(e.data);
                var idx = phaseMap[d.phase];
                if (idx !== undefined) {
                    setProgressStep(card, idx, 'active');
                    var stepEls = card.el.querySelectorAll('.progress-step');
                    if (stepEls[idx]) {
                        stepEls[idx].querySelector('.step-label').textContent =
                            baseLabels[idx] + ' (0/' + d.total + ')';
                    }
                }
            });

            es.addEventListener('progress', function (e) {
                _lastEventTime = Date.now();
                var d = JSON.parse(e.data);
                var idx = phaseMap[d.phase];
                if (idx !== undefined) {
                    // Track per-type counts
                    var pp = phaseProgress[idx];
                    if (pp && d.type) {
                        pp[d.type] = d.completed;
                        // Derive totals from the highest completed value seen
                        if (d.total) {
                            // total covers both types; split by counting per type
                            pp[d.type + '_total'] = d.total;
                        }
                    }
                    // Build label: "Sicherheitscheck (Regionen: 12, Spots: 45 / 285)"
                    var stepEls = card.el.querySelectorAll('.progress-step');
                    if (stepEls[idx]) {
                        var label = baseLabels[idx] + ' (' + d.completed + '/' + d.total + ')';
                        if (d.type && d.name) {
                            label = baseLabels[idx] + ' (' + d.completed + '/' + d.total + ' \u2013 ' + d.name + ')';
                        }
                        stepEls[idx].querySelector('.step-label').textContent = label;
                    }
                    var bar = card.el.querySelector('.progress-bar-fill');
                    bar.classList.remove('indeterminate');
                    var fraction = (idx + (d.completed / Math.max(d.total, 1))) / card.total;
                    bar.style.width = Math.round(fraction * 100) + '%';
                }
                messagesEl.scrollTop = messagesEl.scrollHeight;
            });

            es.addEventListener('done', function (e) {
                var d = JSON.parse(e.data);
                var rs = d.region_stats || {};
                var ss = d.spot_stats || {};
                var elapsed = formatElapsed(card.startTime);
                var stats = buildStatsHtml([
                    { value: String(rs.regions_count || '?'), label: 'Regionen' },
                    { value: String(ss.spots_count || '?'), label: 'Spots' },
                    { value: String(d.total_calls || 0), label: 'Calls' },
                    { value: elapsed, label: 'Dauer' }
                ]);
                var dayChips = buildDayChipsHtml(ss);
                finish(true, stats + dayChips);
            });

            // Server-sent error event (event: error\ndata: {...})
            es.addEventListener('error', function (e) {
                if (finished) return;
                // Nur server-gesendete Error-Events haben e.data
                if (e.data) {
                    try {
                        var d = JSON.parse(e.data);
                        finish(false, null, 'LLM-Analyse fehlgeschlagen: ' + (d.message || 'Unbekannter Fehler'));
                    } catch (_) {
                        finish(false, null, 'LLM-Analyse fehlgeschlagen: ' + e.data);
                    }
                }
                // Transport-Fehler (kein e.data) werden von onerror behandelt
            });

            var _lastEventTime = Date.now();

            // Heartbeats tracken — hält _lastEventTime aktuell
            es.addEventListener('heartbeat', function () {
                _lastEventTime = Date.now();
            });

            es.onerror = function () {
                if (finished) return;
                // Sofort schliessen (kein Reconnect, das würde eine zweite Analyse starten)
                // Aber: wenn wir in den letzten 30s Events bekommen haben, ist der Server
                // wahrscheinlich noch am Arbeiten — wechsle auf Polling-Fallback.
                es.close();
                var timeSinceData = Date.now() - _lastEventTime;
                if (timeSinceData < 30000) {
                    console.log('[SSE] Verbindung verloren, Server vermutlich noch aktiv. Starte Polling-Fallback...');
                    _pollForCompletion(card);
                } else {
                    finish(false, null, 'LLM-Analyse: Verbindung zum Server verloren.');
                }
            };

            function _pollForCompletion(card) {
                // Polling: Server liefert cached Ergebnis über bestehende Endpoints
                var pollCount = 0;
                var maxPolls = 120; // max 10 Minuten (alle 5s)
                var pollTimer = setInterval(function () {
                    pollCount++;
                    if (finished || pollCount > maxPolls) {
                        clearInterval(pollTimer);
                        if (!finished) {
                            finish(false, null, 'LLM-Analyse: Timeout beim Warten auf Ergebnis.');
                        }
                        return;
                    }
                    fetch('/api/analyses-status')
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            if (d.running) return; // noch nicht fertig
                            clearInterval(pollTimer);
                            if (d.completed) {
                                var elapsed = formatElapsed(card.startTime);
                                var stats = buildStatsHtml([
                                    { value: String(d.regions_count || '?'), label: 'Regionen' },
                                    { value: String(d.spots_count || '?'), label: 'Spots' },
                                    { value: String(d.total_calls || 0), label: 'Calls' },
                                    { value: elapsed, label: 'Dauer' }
                                ]);
                                finish(true, stats);
                            } else {
                                finish(false, null, 'LLM-Analyse fehlgeschlagen (Polling-Fallback).');
                            }
                        })
                        .catch(function () { /* retry next poll */ });
                }, 5000);
            }
        });
    }

    // Quick Action Buttons
    document.querySelectorAll('.quick-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var msg = btn.getAttribute('data-msg');
            if (msg) sendMessage(msg);
        });
    });

    inputEl.focus();
})();
