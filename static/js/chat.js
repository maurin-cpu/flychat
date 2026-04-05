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

        // Remove tags from displayed text
        processedText = text.replace(/\[RECOMMENDED:\s*.*?\]/g, '').trim();

        if (typeof marked !== 'undefined') {
            contentDiv.innerHTML = marked.parse(processedText);
        } else {
            contentDiv.textContent = processedText;
        }

        // Highlight on map if we have recommendations and it's a bot message
        if (role === 'bot' && recommendedSpots.length > 0 && window.highlightSpots) {
            window.highlightSpots(recommendedSpots);
        }

        msgDiv.appendChild(contentDiv);
        messagesEl.appendChild(msgDiv);
        messagesEl.scrollTop = messagesEl.scrollHeight;
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

    function sendMessage(text) {
        if (!text.trim() || isLoading) return;

        appendMessage('user', text);

        // Reset highlights on new user message
        if (window.highlightSpots) window.highlightSpots(null);
        // Hide quick actions after first message
        if (quickActions) quickActions.style.display = 'none';

        setLoading(true);

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: sessionId })
        })
            .then(function (resp) {
                if (!resp.ok) throw new Error('Server error: ' + resp.status);
                return resp.json();
            })
            .then(function (data) {
                appendMessage('bot', data.reply || 'Keine Antwort erhalten.');
            })
            .catch(function (err) {
                appendMessage('bot', 'Fehler: ' + err.message);
            })
            .finally(function () {
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

        var icons = { pending: '\u25CB', active: '\u25C9', done: '\u2713', error: '\u2717' };
        var classes = { pending: 'step-pending', active: 'step-active', done: 'step-done', error: 'step-error' };

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
            // Mark the active step as error, leave rest pending
            stepEls.forEach(function (s) {
                if (s.classList.contains('step-active')) {
                    s.className = 'progress-step step-error';
                    s.querySelector('.step-icon').textContent = '\u2717';
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
                'API-Verbindung herstellen',
                'Batch-Download (28 Spots, 4 Modelle)',
                'Thermik berechnen',
                'F\u00f6hn-Daten & Kontext aufbauen'
            ]);

            setProgressStep(card, 0, 'active');

            // Simulated step progression
            var simTimers = [];
            simTimers.push(setTimeout(function () { setProgressStep(card, 1, 'active'); }, 2000));
            simTimers.push(setTimeout(function () { setProgressStep(card, 2, 'active'); }, 6000));
            simTimers.push(setTimeout(function () { setProgressStep(card, 3, 'active'); }, 10000));

            fetch('/api/refresh-weather', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Server error: ' + resp.status);
                    return resp.json();
                })
                .then(function (data) {
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
                        simTimers.forEach(clearTimeout);
                        finalizeProgress(card, false);
                        appendMessage('bot', 'Fehler: ' + (data.error || 'Unbekannter Fehler'));
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

    // ── Button: LLM Analyse ──────────────────────────
    var runAnalysesBtn = document.getElementById('runAnalysesBtn');
    if (runAnalysesBtn) {
        runAnalysesBtn.addEventListener('click', function () {
            if (runAnalysesBtn.disabled) return;

            var refreshWeatherBtn = document.getElementById('refreshWeatherBtn');
            runAnalysesBtn.disabled = true;
            runAnalysesBtn.classList.add('loading');
            if (refreshWeatherBtn) refreshWeatherBtn.disabled = true;

            var card = createProgressCard('LLM-Analyse', [
                'Wetterdaten vorbereiten',
                'Regionen: Sicherheitscheck',
                'Regionen: Fliegbarkeit',
                'Startplätze: Sicherheitscheck',
                'Startplätze: Fliegbarkeit',
                'Ergebnisse zusammenfassen'
            ]);

            setProgressStep(card, 0, 'active');

            var regionData = null;
            var spotData = null;
            var simTimer = null;

            // Step 1: Regionen Sicherheitscheck
            setTimeout(function () { setProgressStep(card, 1, 'active'); }, 1500);
            // Simulated switch to Fliegbarkeit midway through region call
            simTimer = setTimeout(function () { setProgressStep(card, 2, 'active'); }, 25000);

            fetch('/api/run-region-analyses', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Server error (Regionen): ' + resp.status);
                    return resp.json();
                })
                .then(function (data) {
                    if (!data.success) throw new Error('Regionen-Analyse fehlgeschlagen: ' + (data.error || 'Unbekannt'));
                    regionData = data;
                    clearTimeout(simTimer);
                    // Step 3: Startplätze Sicherheitscheck
                    setProgressStep(card, 3, 'active');
                    // Simulated switch to Fliegbarkeit midway through spot call
                    simTimer = setTimeout(function () { setProgressStep(card, 4, 'active'); }, 25000);
                    return fetch('/api/run-analyses', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' }
                    });
                })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Server error (Startplätze): ' + resp.status);
                    return resp.json();
                })
                .then(function (data) {
                    if (!data.success) throw new Error('Spot-Analyse fehlgeschlagen: ' + (data.error || 'Unbekannt'));
                    spotData = data;
                    clearTimeout(simTimer);
                    // Step 5: Ergebnisse zusammenfassen
                    setProgressStep(card, 5, 'active');

                    var elapsed = formatElapsed(card.startTime);
                    var safeCount = 0;
                    var perDay = spotData.per_day_counts || {};
                    Object.keys(perDay).forEach(function (d) {
                        var sc = (perDay[d].safety || {});
                        safeCount += (sc.safe || 0);
                    });
                    var totalCalls = (regionData.results_count || 0) + (spotData.results_count || 0);
                    var stats = buildStatsHtml([
                        { value: String(regionData.regions_count || '?'), label: 'Regionen' },
                        { value: String(spotData.spots_count || '?'), label: 'Spots' },
                        { value: String(totalCalls), label: 'Calls' },
                        { value: elapsed, label: 'Dauer' }
                    ]);
                    var dayChips = buildDayChipsHtml(spotData);
                    finalizeProgress(card, true, stats + dayChips);
                })
                .catch(function (err) {
                    clearTimeout(simTimer);
                    finalizeProgress(card, false);
                    appendMessage('bot', 'LLM-Analyse fehlgeschlagen: ' + err.message);
                })
                .finally(function () {
                    runAnalysesBtn.disabled = false;
                    runAnalysesBtn.classList.remove('loading');
                    if (refreshWeatherBtn) refreshWeatherBtn.disabled = false;
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

    inputEl.focus();
})();
