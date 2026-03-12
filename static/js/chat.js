/**
 * Flychat - Chat Frontend Logic
 */
(function () {
    'use strict';

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
            contentDiv.innerHTML = marked.parse(processedText, { breaks: true });
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

    function buildAnalysisSummary(data) {
        var dates = data.dates || [];
        var perDay = data.per_day_counts || {};
        var details = data.results_summary || {};
        var summary = '';
        var statusLabels = {
            green: 'GRÜN',
            orange: 'ORANGE',
            yellow: 'GELB',
            not_safe: 'NICHT SICHER',
            error: 'FEHLER'
        };
        var safetyLabels = {
            safe: 'SICHER',
            conditional: 'BEDINGT',
            not_safe: 'NICHT SICHER',
            error: 'FEHLER'
        };

        summary += '✅ **Wetter aktualisiert und LLM-Analyse abgeschlossen**\n';
        summary += '\n- Spots: **' + data.spots_count + '**';
        summary += '\n- Tage: **' + dates.length + '**';
        summary += '\n- LLM-Aufrufe: **' + data.results_count + '**';
        if (data.safety_count !== undefined) {
            summary += ' (Safety: ' + data.safety_count + ', Flyability: ' + (data.flyability_count || 0) + ')';
        }

        dates.forEach(function (dateStr) {
            var counts = perDay[dateStr] || {};
            var chips = [];
            if (counts.green) chips.push(counts.green + ' grün');
            if (counts.orange) chips.push(counts.orange + ' orange');
            if (counts.yellow) chips.push(counts.yellow + ' gelb');
            if (counts.not_safe) chips.push(counts.not_safe + ' nicht sicher');
            if (counts.error) chips.push(counts.error + ' Fehler');

            summary += '\n\n---\n### ' + dateStr;
            summary += '\n**Tagesbild:** ' + (chips.length ? chips.join(', ') : 'keine Daten');

            Object.keys(details).sort().forEach(function (name) {
                var d = (details[name] || {})[dateStr];
                if (!d) return;
                var flyLabel = statusLabels[d.status] || d.status;
                var safeLabel = safetyLabels[d.safety_status] || d.safety_status || 'unbekannt';
                var line = '- **' + name + '**: Sicherheit **' + safeLabel + '**, Flug **' + flyLabel + '**';
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

    // Kombi-Button: Wetter laden + LLM Analyse
    var refreshAndAnalyseBtn = document.getElementById('refreshAndAnalyseBtn');
    if (refreshAndAnalyseBtn) {
        refreshAndAnalyseBtn.addEventListener('click', function () {
            if (refreshAndAnalyseBtn.disabled) return;

            refreshAndAnalyseBtn.disabled = true;
            refreshAndAnalyseBtn.classList.add('loading');
            appendMessage('bot', '🔄 Starte Aktualisierung: Wetterdaten laden, danach LLM-Analyse...');

            fetch('/api/refresh-weather', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Server error: ' + resp.status);
                    return resp.json();
                })
                .then(function (data) {
                    if (!data.success) {
                        throw new Error('Fehler beim Laden der Wetterdaten: ' + (data.error || 'Unbekannter Fehler'));
                    }
                    appendMessage('bot', '✅ Wetterdaten aktualisiert. Starte jetzt die LLM-Analyse...');
                    return fetch('/api/run-analyses', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' }
                    });
                })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Server error: ' + resp.status);
                    return resp.json();
                })
                .then(function (data) {
                    if (data.success) {
                        appendMessage('bot', buildAnalysisSummary(data));
                    } else {
                        appendMessage('bot', 'Analyse fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'));
                    }
                })
                .catch(function (err) {
                    appendMessage('bot', 'Ablauf fehlgeschlagen: ' + err.message);
                })
                .finally(function () {
                    refreshAndAnalyseBtn.disabled = false;
                    refreshAndAnalyseBtn.classList.remove('loading');
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
