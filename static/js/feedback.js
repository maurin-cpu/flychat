/* Feedback-Widget (Like/Dislike + Kommentar) fuer Spot- und Region-Analyse-Karten.
 *
 * Mount-Pattern (HTML):
 *   <div data-fb-mount data-fb-type="spot" data-fb-target="Uetliberg" data-fb-date="2026-04-30"></div>
 *
 * Aktivierung im Code:
 *   Feedback.scan(rootElement);   // findet alle data-fb-mount und mountet Widgets
 *
 * Anonymitaet: Client-ID wird im localStorage gehalten (UUID v4-ish).
 */
(function () {
    'use strict';

    var CLIENT_KEY = 'flychat_client_id';
    var ENDPOINT = '/api/feedback';
    var CACHE = {};   // key -> {own, aggregate, ts}
    var CACHE_TTL_MS = 30000;

    function uuid() {
        if (window.crypto && crypto.getRandomValues) {
            var b = new Uint8Array(16);
            crypto.getRandomValues(b);
            b[6] = (b[6] & 0x0f) | 0x40;
            b[8] = (b[8] & 0x3f) | 0x80;
            var hex = Array.from(b).map(function (x) { return x.toString(16).padStart(2, '0'); }).join('');
            return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16)
                 + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
        }
        return 'c' + Date.now().toString(16) + Math.random().toString(16).slice(2, 12);
    }

    function getClientId() {
        try {
            var id = localStorage.getItem(CLIENT_KEY);
            if (!id) {
                id = uuid().replace(/-/g, '').slice(0, 32);
                localStorage.setItem(CLIENT_KEY, id);
            }
            return id;
        } catch (e) {
            // Private mode / disabled storage — fallback in-memory
            if (!window.__fb_memid) window.__fb_memid = uuid().replace(/-/g, '').slice(0, 32);
            return window.__fb_memid;
        }
    }

    function cacheKey(type, target, date) {
        return type + '|' + target + '|' + (date || '');
    }

    function fetchState(type, target, date) {
        var key = cacheKey(type, target, date);
        var hit = CACHE[key];
        if (hit && (Date.now() - hit.ts) < CACHE_TTL_MS) {
            return Promise.resolve(hit);
        }
        var url = ENDPOINT + '/' + encodeURIComponent(type) + '/' + encodeURIComponent(target)
                + '?client_id=' + encodeURIComponent(getClientId())
                + (date ? '&date=' + encodeURIComponent(date) : '');
        return fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { own: null, aggregate: { up: 0, down: 0 } }; })
            .then(function (data) {
                CACHE[key] = { own: data.own, aggregate: data.aggregate, ts: Date.now() };
                return CACHE[key];
            })
            .catch(function () {
                return { own: null, aggregate: { up: 0, down: 0 }, ts: Date.now() };
            });
    }

    function submit(payload) {
        return fetch(ENDPOINT, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function (r) {
            if (!r.ok) {
                return r.json().catch(function () { return null; })
                    .then(function (j) { throw new Error((j && j.error) || ('HTTP ' + r.status)); });
            }
            return r.json();
        });
    }

    function deleteOwn(id) {
        return fetch(ENDPOINT + '/' + id + '?client_id=' + encodeURIComponent(getClientId()), {
            method: 'DELETE', credentials: 'same-origin',
        }).then(function (r) { return r.ok; });
    }

    function el(tag, attrs, kids) {
        var n = document.createElement(tag);
        if (attrs) {
            Object.keys(attrs).forEach(function (k) {
                if (k === 'class') n.className = attrs[k];
                else if (k === 'text') n.textContent = attrs[k];
                else if (k === 'html') n.innerHTML = attrs[k];
                else n.setAttribute(k, attrs[k]);
            });
        }
        if (kids) kids.forEach(function (c) { if (c) n.appendChild(c); });
        return n;
    }

    function render(mountEl) {
        if (mountEl.__fbBound) return;
        mountEl.__fbBound = true;

        var type = mountEl.getAttribute('data-fb-type') || '';
        var target = mountEl.getAttribute('data-fb-target') || '';
        var date = mountEl.getAttribute('data-fb-date') || '';
        if (type !== 'spot' && type !== 'region') return;
        if (!target) return;

        mountEl.classList.add('fb-widget');

        var header = el('div', { class: 'fb-widget__header' });
        header.appendChild(el('span', { class: 'fb-widget__title', text: 'War diese Analyse hilfreich?' }));

        var btnRow = el('div', { class: 'fb-widget__btns' });
        var upBtn = el('button', {
            type: 'button', class: 'fb-btn fb-btn--up',
            'aria-label': 'Hilfreich', title: 'Hilfreich',
        });
        upBtn.innerHTML = '<span class="fb-btn__icon">👍</span><span class="fb-btn__count" data-fb-count="up">0</span>';
        var downBtn = el('button', {
            type: 'button', class: 'fb-btn fb-btn--down',
            'aria-label': 'Nicht hilfreich', title: 'Nicht hilfreich',
        });
        downBtn.innerHTML = '<span class="fb-btn__icon">👎</span><span class="fb-btn__count" data-fb-count="down">0</span>';
        btnRow.appendChild(upBtn);
        btnRow.appendChild(downBtn);

        var commentToggle = el('button', {
            type: 'button', class: 'fb-comment__toggle',
            text: 'Kommentar',
        });
        btnRow.appendChild(commentToggle);

        header.appendChild(btnRow);

        var statusLine = el('div', { class: 'fb-widget__status', 'aria-live': 'polite' });

        var commentBox = el('div', { class: 'fb-comment' });
        var textarea = el('textarea', {
            class: 'fb-comment__textarea',
            placeholder: wcT('js.fb.placeholder'),
            rows: '3', maxlength: '4000',
        });
        var submitBtn = el('button', {
            type: 'button', class: 'fb-comment__submit',
            text: 'Senden',
        });
        var cancelBtn = el('button', {
            type: 'button', class: 'fb-comment__cancel',
            text: 'Abbrechen',
        });
        commentBox.appendChild(textarea);
        var actionRow = el('div', { class: 'fb-comment__actions' });
        actionRow.appendChild(submitBtn);
        actionRow.appendChild(cancelBtn);
        commentBox.appendChild(actionRow);

        // Vorschau des gespeicherten Kommentars (sichtbar wenn Box geschlossen)
        var savedPreview = el('div', { class: 'fb-saved-comment' });
        var savedText = el('span', { class: 'fb-saved-comment__text' });
        var savedEdit = el('button', {
            type: 'button', class: 'fb-saved-comment__edit', text: 'Bearbeiten',
        });
        savedPreview.appendChild(el('span', { class: 'fb-saved-comment__icon', text: '💬' }));
        savedPreview.appendChild(savedText);
        savedPreview.appendChild(savedEdit);

        mountEl.appendChild(header);
        mountEl.appendChild(statusLine);
        mountEl.appendChild(savedPreview);
        mountEl.appendChild(commentBox);

        var state = { own: null, aggregate: { up: 0, down: 0 } };

        function paintCounts() {
            mountEl.querySelector('[data-fb-count="up"]').textContent = state.aggregate.up || 0;
            mountEl.querySelector('[data-fb-count="down"]').textContent = state.aggregate.down || 0;
            upBtn.classList.toggle('fb-btn--active', state.own && state.own.vote === 'up');
            downBtn.classList.toggle('fb-btn--active', state.own && state.own.vote === 'down');
            // Gespeicherten Kommentar als Preview anzeigen (wenn Box nicht offen)
            var hasComment = !!(state.own && state.own.comment);
            var commentingNow = mountEl.classList.contains('fb-widget--commenting');
            mountEl.classList.toggle('fb-widget--has-comment', hasComment);
            savedPreview.style.display = (hasComment && !commentingNow) ? '' : 'none';
            if (hasComment) savedText.textContent = state.own.comment;
            if (hasComment) {
                statusLine.textContent = '';
                statusLine.className = 'fb-widget__status';
            } else if (state.own && state.own.vote) {
                statusLine.textContent = wcT('js.fb.thanks');
                statusLine.className = 'fb-widget__status fb-widget__status--ok';
            } else {
                statusLine.textContent = '';
                statusLine.className = 'fb-widget__status';
            }
        }

        function applyResponse(resp) {
            if (resp && resp.aggregate) state.aggregate = resp.aggregate;
            // Optimistic state.own update happens via caller.
            CACHE[cacheKey(type, target, date)] = {
                own: state.own, aggregate: state.aggregate, ts: Date.now(),
            };
            paintCounts();
        }

        function showError(msg) {
            statusLine.textContent = msg || wcT('js.fb.send_error');
            statusLine.className = 'fb-widget__status fb-widget__status--err';
        }

        function vote(value) {
            var nextVote = (state.own && state.own.vote === value) ? null : value;
            // Wenn Comment-Box gerade offen ist + Text drin → mitsenden.
            // Sonst bestehenden Kommentar erhalten.
            var commentingNow = mountEl.classList.contains('fb-widget--commenting');
            var typedComment = commentingNow ? (textarea.value || '').trim() : '';
            var nextComment = typedComment
                || (state.own && state.own.comment)
                || null;

            // Weder Vote noch Kommentar -> Eintrag entfernen
            if (!nextVote && !nextComment) {
                if (state.own && state.own.id) {
                    deleteOwn(state.own.id).then(function () {
                        state.own = null;
                        fetchState(type, target, date).then(function (s) {
                            state.own = s.own; state.aggregate = s.aggregate; paintCounts();
                        });
                    });
                }
                return;
            }
            submit({
                target_type: type, target_id: target, target_date: date || null,
                vote: nextVote, comment: nextComment, client_id: getClientId(),
            }).then(function (resp) {
                state.own = {
                    id: resp.id, vote: nextVote, comment: nextComment || null,
                };
                // Wenn ein neu getippter Kommentar mitgesendet wurde, Box schließen
                if (typedComment) {
                    mountEl.classList.remove('fb-widget--commenting');
                    textarea.value = '';
                }
                applyResponse(resp);
                // Nach dem Voten Kommentar-Box auto-öffnen damit klar ist, dass
                // man nun zusätzlich kommentieren kann (skip wenn Vote entfernt
                // oder bereits Kommentar vorhanden)
                if (nextVote && !nextComment && !typedComment) {
                    setTimeout(openCommentBox, 80);
                }
            }).catch(function (e) { showError(e.message); });
        }

        upBtn.addEventListener('click', function () { vote('up'); });
        downBtn.addEventListener('click', function () { vote('down'); });

        function openCommentBox() {
            mountEl.classList.add('fb-widget--commenting');
            if (state.own && state.own.comment) textarea.value = state.own.comment;
            paintCounts();
            setTimeout(function () { textarea.focus(); }, 0);
        }
        commentToggle.addEventListener('click', function () {
            if (mountEl.classList.contains('fb-widget--commenting')) {
                mountEl.classList.remove('fb-widget--commenting');
                textarea.value = '';
                paintCounts();
            } else {
                openCommentBox();
            }
        });
        savedEdit.addEventListener('click', openCommentBox);

        cancelBtn.addEventListener('click', function () {
            mountEl.classList.remove('fb-widget--commenting');
            textarea.value = '';
            paintCounts();
        });

        submitBtn.addEventListener('click', function () {
            var msg = (textarea.value || '').trim();
            if (!msg && (!state.own || !state.own.vote)) {
                showError(wcT('js.fb.need_input'));
                return;
            }
            submitBtn.disabled = true;
            submit({
                target_type: type, target_id: target, target_date: date || null,
                vote: state.own ? state.own.vote : null,
                comment: msg || null,
                client_id: getClientId(),
            }).then(function (resp) {
                state.own = {
                    id: resp.id,
                    vote: state.own ? state.own.vote : null,
                    comment: msg || null,
                };
                mountEl.classList.remove('fb-widget--commenting');
                textarea.value = '';
                applyResponse(resp);
            }).catch(function (e) { showError(e.message); })
              .finally(function () { submitBtn.disabled = false; });
        });

        // Hydrate initial state
        fetchState(type, target, date).then(function (s) {
            state.own = s.own; state.aggregate = s.aggregate;
            paintCounts();
        });
    }

    function scan(root) {
        if (!root) root = document;
        var mounts = root.querySelectorAll('[data-fb-mount]');
        for (var i = 0; i < mounts.length; i++) render(mounts[i]);
    }

    window.Feedback = { scan: scan, render: render };
})();
