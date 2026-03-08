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
    var analyzeBtn = document.getElementById('analyzeBtn');
    var analysisStatus = document.getElementById('analysisStatus');

    if (analyzeBtn) {
        analyzeBtn.addEventListener('click', function () {
            analyzeBtn.disabled = true;
            analyzeBtn.textContent = 'Analysiere...';
            analysisStatus.textContent = 'Wetterdaten werden in KI geladen...';

            fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
                .then(function (resp) {
                    if (!resp.ok) throw new Error('Analyse fehlgeschlagen');
                    return resp.json();
                })
                .then(function (data) {
                    if (data.success) {
                        analyzeBtn.textContent = 'Bereit';
                        analyzeBtn.classList.add('success');
                        analysisStatus.textContent = 'Wetterdaten geladen! KI ist bereit.';
                        // Optional: Kurzes Fazit anzeigen
                        if (data.summary) {
                            appendMessage('bot', 'KI-FAZIT: ' + data.summary);
                        }
                    } else {
                        throw new Error(data.error || 'Unbekannter Fehler');
                    }
                })
                .catch(function (err) {
                    analyzeBtn.disabled = false;
                    analyzeBtn.textContent = 'Hochladen LLM';
                    analysisStatus.textContent = 'Fehler: ' + err.message;
                });
        });
    }

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

        // Extract [RECOMMENDED: SpotName] tags
        var regex = /\[RECOMMENDED:\s*(.*?)\]/g;
        var match;
        while ((match = regex.exec(text)) !== null) {
            recommendedSpots.push(match[1]);
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

    // Quick Action Buttons
    document.querySelectorAll('.quick-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var msg = btn.getAttribute('data-msg');
            if (msg) sendMessage(msg);
        });
    });

    inputEl.focus();
})();
