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
            gray: 'Bronze (Abgleiter)',
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
                        if (window.updateDataFreshness) window.updateDataFreshness(new Date().toISOString());
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
                'Analyse'
            ]);

            var phaseMap = {
                'all_safety': 0,
                'all_fly': 0,
                // Combined phases (single call per spot/region)
                'region_combined': 0,
                'spot_combined': 0,
                // Legacy single-type phases (run_spot/region_analyses_stream)
                'region_safety': 0,
                'region_fly': 0,
                'spot_safety': 0,
                'spot_fly': 0
            };

            // Track per-type progress within each phase
            var phaseProgress = {
                0: { region: 0, spot: 0, region_total: 0, spot_total: 0 }
            };

            var regionStats = null;
            var spotStats = null;

            var finished = false;
            var es = new EventSource('/api/run-all-analyses-stream');

            var baseLabels = [
                'Analyse'
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

                // Update button text to show completion time
                var hh = String(new Date().getHours()).padStart(2, '0');
                var mm = String(new Date().getMinutes()).padStart(2, '0');
                var textEl = runAnalysesBtn.querySelector('.btn-text');
                if (textEl) textEl.textContent = 'Analyse aktualisieren (' + hh + ':' + mm + ')';
                runAnalysesBtn.classList.remove('attention-pulse');
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

    // ── Onboarding Hints (first visit only) ──────────────
    (function () {
        var key = 'flychat_onboarded';
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

    // ── Week Briefing Card (region-based) ──────────────────────────
    var briefingEl = document.getElementById('morningBriefing');
    var briefingBuilt = false;

    var WEEKDAYS_SHORT = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
    var WEEKDAYS_FULL = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

    function _dateStr(d) {
        return d.getFullYear() + '-' +
            String(d.getMonth() + 1).padStart(2, '0') + '-' +
            String(d.getDate()).padStart(2, '0');
    }

    function _tierDot(safety, tier) {
        var cls = 'tier-' + (safety === 'not_safe' ? 'not-safe' : (tier || 'gray'));
        var icons = { 'violet': '\u2605', 'green': '\u2713', 'gray': '\u223C' };
        var icon = safety === 'not_safe' ? '\u2717' : (icons[tier] || '\u223C');
        return '<span class="briefing-tier-dot ' + cls + '">' + icon + '</span>';
    }

    /**
     * Summarize a single forecast day from region analyses.
     * Returns { score, safeCount, totalCount, bestRegion, bestTier, bestSafety,
     *           bestClimb, bestWindow, flyableRegions }
     */
    function _summarizeDay(regionData, dateStr) {
        var tierRank = { 'violet': 3, 'green': 2, 'gray': 1 };
        var safeRank = { 'safe': 3, 'conditional': 2, 'not_safe': 1 };

        var regions = [];
        Object.keys(regionData).forEach(function (rid) {
            var d = regionData[rid][dateStr];
            if (d) regions.push({ id: rid, data: d });
        });
        if (regions.length === 0) return null;

        // Rank regions
        regions.sort(function (a, b) {
            var sa = safeRank[a.data.safety_status] || 0;
            var sb = safeRank[b.data.safety_status] || 0;
            if (sa !== sb) return sb - sa;
            var fa = tierRank[a.data.fly_status] || 0;
            var fb = tierRank[b.data.fly_status] || 0;
            if (fa !== fb) return fb - fa;
            var ca = parseFloat(a.data.peak_climb_rate) || 0;
            var cb = parseFloat(b.data.peak_climb_rate) || 0;
            return cb - ca;
        });

        var best = regions[0];
        var bd = best.data;
        var safeCount = regions.filter(function (r) {
            return r.data.safety_status === 'safe' && r.data.fly_status && r.data.fly_status !== 'gray';
        }).length;
        var flyableNames = regions
            .filter(function (r) { return r.data.safety_status === 'safe' && r.data.fly_status && r.data.fly_status !== 'gray'; })
            .slice(0, 3)
            .map(function (r) { return r.data.region_name || r.id; });

        var bSafety = bd.safety_status || 'not_safe';
        var bTier = bd.fly_status || 'gray';
        // Score: higher = better day
        var score = (safeRank[bSafety] || 0) * 100 + (tierRank[bTier] || 0) * 10 + safeCount;

        return {
            score: score,
            safeCount: safeCount,
            totalCount: regions.length,
            bestRegion: bd.region_name || best.id,
            bestTier: bTier,
            bestSafety: bSafety,
            bestClimb: bd.peak_climb_rate,
            bestWindow: bd.best_window || bd.safe_window || '',
            flyableRegions: flyableNames,
            feedback: bd.flyability_feedback || bd.safety_feedback || ''
        };
    }

    function buildWeekBriefing(regionData) {
        if (!briefingEl || briefingBuilt) return;
        if (!regionData || typeof regionData !== 'object' || Object.keys(regionData).length === 0) return;

        var now = new Date();
        var todayStr = _dateStr(now);

        // Collect all dates
        var allDates = {};
        Object.keys(regionData).forEach(function (rid) {
            Object.keys(regionData[rid]).forEach(function (ds) {
                allDates[ds] = true;
            });
        });
        var dates = Object.keys(allDates).sort();
        if (dates.length === 0) return;

        // Summarize each day
        var daySummaries = {};
        var bestDayStr = null;
        var bestScore = -1;
        dates.forEach(function (ds) {
            var s = _summarizeDay(regionData, ds);
            if (s) {
                daySummaries[ds] = s;
                if (s.score > bestScore) {
                    bestScore = s.score;
                    bestDayStr = ds;
                }
            }
        });

        if (!bestDayStr) return;

        // ── Best day highlight ──
        var bestDay = daySummaries[bestDayStr];
        var bestDate = new Date(bestDayStr + 'T12:00:00');
        var isToday = bestDayStr === todayStr;
        var dayName = isToday ? 'Heute' : WEEKDAYS_FULL[bestDate.getDay()] + ' ' + bestDate.getDate() + '.';

        var tierIcons = { 'violet': '\u2605', 'green': '\u2713', 'gray': '\u223C' };
        var tierIcon = bestDay.bestSafety === 'not_safe' ? '\u2717' : (tierIcons[bestDay.bestTier] || '\u223C');
        var tierClass = 'tier-' + (bestDay.bestSafety === 'not_safe' ? 'not-safe' : bestDay.bestTier);

        var summary = bestDay.feedback || '';
        if (summary.length > 120) summary = summary.substring(0, 117) + '...';

        var chips = '';
        if (bestDay.bestWindow && bestDay.bestWindow !== 'keins' && bestDay.bestWindow !== '?') {
            chips += '<span class="briefing-detail-chip"><span class="chip-icon">\u2600</span> ' + bestDay.bestWindow + '</span>';
        }
        if (bestDay.bestClimb && parseFloat(bestDay.bestClimb) > 0) {
            chips += '<span class="briefing-detail-chip"><span class="chip-icon">\u2191</span> ' + bestDay.bestClimb + ' m/s</span>';
        }
        chips += '<span class="briefing-detail-chip">' + bestDay.safeCount + '/' + bestDay.totalCount + ' Regionen fliegbar</span>';

        // Flyable region names as a hint
        var regionHint = '';
        if (bestDay.flyableRegions.length > 0) {
            regionHint = '<div class="briefing-region-hint">' + bestDay.flyableRegions.join(', ') + '</div>';
        }

        var bestHtml =
            '<div class="briefing-best-day-label">' + dayName + ' \u2014 bester Flugtag</div>' +
            '<div class="briefing-spot">' +
            '<div class="briefing-tier-badge ' + tierClass + '">' + tierIcon + '</div>' +
            '<div class="briefing-spot-info">' +
            '<div class="briefing-spot-name">' + bestDay.bestRegion + '</div>' +
            '<div class="briefing-spot-summary">' + summary + '</div>' +
            '</div>' +
            '</div>' +
            regionHint +
            '<div class="briefing-details">' + chips + '</div>' +
            '<div class="briefing-actions">' +
            '<button class="btn btn-primary btn-sm" id="briefingAskBestDay">Details</button>' +
            '<button class="btn btn-secondary btn-sm" id="briefingAskChat">Wo fliegen?</button>' +
            '</div>';

        // ── Other days (compact rows) ──
        var otherDates = dates.filter(function (d) { return d !== bestDayStr; });
        var weekRows = '';
        if (otherDates.length > 0) {
            weekRows = '<div class="briefing-week-divider"></div>';
            otherDates.forEach(function (ds) {
                var s = daySummaries[ds];
                if (!s) return;
                var d = new Date(ds + 'T12:00:00');
                var label = ds === todayStr ? 'Heute' : WEEKDAYS_SHORT[d.getDay()] + ' ' + d.getDate() + '.';

                var metrics = '';
                if (s.bestSafety === 'not_safe' || (s.bestTier === 'gray' && s.safeCount === 0)) {
                    metrics = '<span class="week-row-meta">kaum fliegbar</span>';
                } else {
                    var parts = [];
                    if (s.bestClimb && parseFloat(s.bestClimb) > 0) parts.push('\u2191' + s.bestClimb);
                    parts.push(s.safeCount + '/' + s.totalCount + ' Reg.');
                    metrics = '<span class="week-row-meta">' + parts.join(' \u00b7 ') + '</span>';
                }

                weekRows +=
                    '<div class="briefing-week-row" data-date="' + ds + '">' +
                    '<span class="week-row-day">' + label + '</span>' +
                    _tierDot(s.bestSafety, s.bestTier) +
                    '<span class="week-row-spot">' + s.bestRegion + '</span>' +
                    metrics +
                    '</div>';
            });
        }

        var briefingTime = now.toLocaleDateString('de-CH', { day: 'numeric', month: 'short' }) +
            ', ' + now.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' });

        briefingEl.innerHTML =
            '<div class="morning-briefing">' +
            '<div class="morning-briefing-header">' +
            '<span class="briefing-icon">\u2600\uFE0F</span> Wochenbriefing' +
            '<span class="briefing-timestamp">' + briefingTime + '</span>' +
            '</div>' +
            bestHtml +
            weekRows +
            '</div>';

        briefingEl.style.display = '';
        briefingBuilt = true;

        // Wire up buttons
        var detailBtn = document.getElementById('briefingAskBestDay');
        if (detailBtn) {
            detailBtn.addEventListener('click', function () {
                var q = isToday
                    ? 'Wie sind die Flugbedingungen heute in ' + bestDay.bestRegion + '?'
                    : 'Wie werden die Flugbedingungen am ' + WEEKDAYS_FULL[bestDate.getDay()] + ' in ' + bestDay.bestRegion + '?';
                sendMessage(q);
            });
        }
        var askBtn = document.getElementById('briefingAskChat');
        if (askBtn) {
            askBtn.addEventListener('click', function () {
                sendMessage(isToday
                    ? 'Welche Region ist heute am besten zum Fliegen?'
                    : 'Welche Region ist am ' + WEEKDAYS_FULL[bestDate.getDay()] + ' am besten zum Fliegen?');
            });
        }

        // Wire up week rows — click asks chat about that day
        briefingEl.querySelectorAll('.briefing-week-row').forEach(function (row) {
            row.addEventListener('click', function () {
                var ds = row.getAttribute('data-date');
                var d = new Date(ds + 'T12:00:00');
                var dayN = ds === todayStr ? 'heute' : 'am ' + WEEKDAYS_FULL[d.getDay()];
                sendMessage('Wie sind die Flugbedingungen ' + dayN + '?');
            });
        });
    }

    // Listen for analysis data from the InstantDB subscription (set on window by index.html)
    var _briefingCheckInterval = setInterval(function () {
        // Briefing uses region data; quick actions + map colors use spot data
        var hasRegions = window.regionAnalysisData && Object.keys(window.regionAnalysisData).length > 0;
        var hasSpots = window.analysisData && Object.keys(window.analysisData).length > 0;

        if (hasRegions) {
            buildWeekBriefing(window.regionAnalysisData);
        }
        if (hasSpots) {
            updateQuickActionsFromAnalyses(window.analysisData);
        }
        if (hasRegions || hasSpots) {
            if (runAnalysesBtn) runAnalysesBtn.classList.remove('attention-pulse');
        }
        if (hasRegions && hasSpots) {
            clearInterval(_briefingCheckInterval);
        }
    }, 500);
    // Stop checking after 30s
    setTimeout(function () { clearInterval(_briefingCheckInterval); }, 30000);

    // ── Context-Aware Quick Actions ──────────────────────────
    function updateQuickActionsFromAnalyses(analysisData) {
        if (!quickActions) return;

        var now = new Date();
        var todayStr = now.getFullYear() + '-' +
            String(now.getMonth() + 1).padStart(2, '0') + '-' +
            String(now.getDate()).padStart(2, '0');

        // Find best spot for contextual actions
        var bestSpot = null;
        var bestScore = -1;
        var tierRank = { 'violet': 3, 'green': 2, 'gray': 1 };
        var safeRank = { 'safe': 3, 'conditional': 2, 'not_safe': 1 };

        Object.keys(analysisData).forEach(function (name) {
            var d = analysisData[name][todayStr];
            if (!d) return;
            var score = (safeRank[d.safety_status] || 0) * 10 + (tierRank[d.fly_status] || 0);
            if (score > bestScore) {
                bestScore = score;
                bestSpot = name;
            }
        });

        // Replace quick action buttons with context-aware ones
        var contextActions = [
            { msg: 'Welche Region ist heute am besten zum Fliegen?', label: 'Beste Region?' },
            { msg: 'Wo ist die Thermik am st\u00e4rksten?', label: 'Beste Thermik?' },
            { msg: 'Welcher Tag diese Woche ist am besten?', label: 'Bester Tag?' },
            { msg: 'Wie wird das Wetter morgen?', label: 'Morgen?' },
        ];

        quickActions.innerHTML = '';
        contextActions.forEach(function (a) {
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

    inputEl.focus();
})();
