// ══════════════════════════════════════════════════════════════
// Label-Katalog fuer die Analyse-Uebersicht
//
// Einheitliches System mit 4 Kategorien (priorisiert):
//   NO_GO         → rot,     zeigen wenn safety_status = not_safe
//   CONDITIONAL   → orange,  zeigen wenn safety_status = conditional
//   REDUCER       → bronze,  mindert Fliegbarkeit (kann bei conditional+safe)
//   BOOSTER       → gruen,   foerdert Fliegbarkeit (kann bei conditional+safe)
//
// Anzahl-Regel:
//   not_safe    → 1 Label (nur NO_GO)
//   conditional → bis 3 Labels (CONDITIONAL + optional REDUCER + optional BOOSTER)
//   safe        → bis 2 Labels (REDUCER und/oder BOOSTER)
//
// Exklusionen: Thermik-Achse (schwach ↔ stark), Bewoelkung ↔ XC
// ══════════════════════════════════════════════════════════════

export const LABEL_CATEGORIES = {
    NO_GO: 'no_go',
    CONDITIONAL: 'conditional',
    REDUCER: 'reducer',
    BOOSTER: 'booster'
};

// Jeder Eintrag: { label, icon, category, rank }
// rank = Prioritaet innerhalb der Kategorie (niedriger = wichtiger)
export const LABEL_CATALOG = {
    // ─── NO-GO ────────────────────────────────────────────────
    FOEHN:          { label: 'Föhn',            icon: '⛔', category: 'no_go',       rank: 1 },
    GEWITTER:       { label: 'Gewitter',        icon: '⛈',  category: 'no_go',       rank: 2 },
    STURM:          { label: 'Sturm',           icon: '🌬', category: 'no_go',       rank: 3 },
    ALOFT_DANGER:   { label: 'Höhensturm',      icon: '⚠',  category: 'no_go',       rank: 4 },
    STRONG_WIND:    { label: 'Wind zu stark',   icon: '💨', category: 'no_go',       rank: 5 },
    REGEN:          { label: 'Regen',           icon: '🌧', category: 'no_go',       rank: 6 },
    SCHNEE:         { label: 'Schneefall',      icon: '❄',  category: 'no_go',       rank: 7 },
    OVERCAST:       { label: 'Wolkendecke tief', icon: '☁', category: 'no_go',       rank: 8 },
    SICHT:          { label: 'Sicht',           icon: '🌫', category: 'no_go',       rank: 9 },
    VEREISUNG:      { label: 'Vereisung',       icon: '🧊', category: 'no_go',       rank: 10 },
    EINGEKESSELT:   { label: 'Kein Fenster',    icon: '⏳', category: 'no_go',       rank: 11 },

    // ─── CONDITIONAL ─────────────────────────────────────────
    STARKER_WIND:       { label: 'Starker Wind',   icon: '💨', category: 'conditional', rank: 1 },
    WINDRICHTUNG:       { label: 'Wind falsch',    icon: '🧭', category: 'conditional', rank: 2 },
    TURBULENZ:          { label: 'Turbulenz',      icon: '🌀', category: 'conditional', rank: 3 },
    SHEAR_WIND:         { label: 'Scherung',       icon: '↯',  category: 'conditional', rank: 4 },
    GUST_SPREAD:        { label: 'Böig',           icon: '⚡', category: 'conditional', rank: 5 },
    KURZES_FENSTER:     { label: 'Kurzes Fenster', icon: '⏱', category: 'conditional', rank: 6 },
    TREND_SCHLECHTER:   { label: 'Verschlechterung',icon: '📉',category: 'conditional', rank: 7 },

    // ─── REDUCER (mindert Fliegbarkeit) ──────────────────────
    VIEL_BEWOELKUNG:    { label: 'Viel Bewölkung',  icon: '☁', category: 'reducer', rank: 1 },
    SCHWACHE_THERMIK:   { label: 'Schwache Thermik',icon: '🪫', category: 'reducer', rank: 2 },
    TIEFE_BASIS:        { label: 'Tiefe Basis',     icon: '📏', category: 'reducer', rank: 3 },
    KURZES_FLUGFENSTER: { label: 'Kurzes Thermikfenster', icon: '⏱', category: 'reducer', rank: 4 },
    KALT:               { label: 'Kalt',            icon: '🥶', category: 'reducer', rank: 5 },
    FEUCHT:             { label: 'Feucht',          icon: '💧', category: 'reducer', rank: 6 },
    INVERSION:          { label: 'Inversion',       icon: '🔒', category: 'reducer', rank: 7 },

    // ─── BOOSTER (foerdert Fliegbarkeit) ─────────────────────
    XC_BEDINGUNGEN:     { label: 'XC-Tag',          icon: '🚀', category: 'booster', rank: 1 },
    STARKE_THERMIK:     { label: 'Starke Thermik',  icon: '🔥', category: 'booster', rank: 2 },
    HOHE_BASIS:         { label: 'Hohe Basis',      icon: '⬆',  category: 'booster', rank: 3 },
    GUTE_EINSTRAHLUNG:  { label: 'Gute Sonne',     icon: '☀',  category: 'booster', rank: 4 },
    RUECKENWIND_XC:     { label: 'Streckenwind',    icon: '💨', category: 'booster', rank: 5 },
    STABILE_KALTFRONT:  { label: 'Nach Kaltfront',  icon: '❄',  category: 'booster', rank: 6 },
    LANGES_FENSTER:     { label: 'Langes Fenster',  icon: '⏳', category: 'booster', rank: 7 },
    KONVERGENZ:         { label: 'Konvergenz',      icon: '⚡', category: 'booster', rank: 8 }
};

// Exklusions-Gruppen: Wenn LLM sowohl einen Reducer als auch einen
// widerspruechlichen Booster liefert, wird nur der hoehere Rank beider
// Kategorien angezeigt (im Zweifel: das gefahrenrelevantere, also Reducer).
export const EXCLUSION_GROUPS = [
    ['SCHWACHE_THERMIK', 'STARKE_THERMIK'],
    ['VIEL_BEWOELKUNG', 'XC_BEDINGUNGEN'],
    ['VIEL_BEWOELKUNG', 'GUTE_EINSTRAHLUNG'],
    ['TIEFE_BASIS', 'HOHE_BASIS'],
    ['KURZES_FLUGFENSTER', 'LANGES_FENSTER']
];

/**
 * Waehlt die anzuzeigenden Labels gemaess Regelwerk.
 * @param {object} analysis — JSON-Doc aus InstantDB mit primary_* Feldern
 * @returns {Array<{key:string, label:string, icon:string, category:string}>}
 */
export function pickDisplayLabels(analysis) {
    if (!analysis) return [];
    var safety = analysis.safety_status || 'error';

    var keyNoGo = sanitizeKey(analysis.primary_no_go);
    var keyCaution = sanitizeKey(analysis.primary_caution);
    var keyReducer = sanitizeKey(analysis.primary_reducer);
    var keyBooster = sanitizeKey(analysis.primary_booster);

    // Konflikt-Aufloesung (Reducer vs. Booster)
    if (keyReducer && keyBooster) {
        for (var i = 0; i < EXCLUSION_GROUPS.length; i++) {
            var grp = EXCLUSION_GROUPS[i];
            if (grp.indexOf(keyReducer) !== -1 && grp.indexOf(keyBooster) !== -1) {
                // Im Zweifel Reducer behalten (sicherheitsrelevant).
                keyBooster = null;
                break;
            }
        }
    }

    var out = [];
    if (safety === 'not_safe') {
        // Nur das NO-GO Label
        if (keyNoGo && LABEL_CATALOG[keyNoGo]) {
            out.push(buildEntry(keyNoGo));
        }
        return out;
    }

    if (safety === 'conditional') {
        if (keyCaution && LABEL_CATALOG[keyCaution]) {
            out.push(buildEntry(keyCaution));
        }
        if (keyReducer && LABEL_CATALOG[keyReducer]) {
            out.push(buildEntry(keyReducer));
        }
        if (keyBooster && LABEL_CATALOG[keyBooster]) {
            out.push(buildEntry(keyBooster));
        }
        return out;
    }

    if (safety === 'safe') {
        if (keyReducer && LABEL_CATALOG[keyReducer]) {
            out.push(buildEntry(keyReducer));
        }
        if (keyBooster && LABEL_CATALOG[keyBooster]) {
            out.push(buildEntry(keyBooster));
        }
        return out;
    }

    // no_data / error: keine Labels
    return out;
}

function sanitizeKey(raw) {
    if (!raw) return null;
    var k = String(raw).trim().toUpperCase();
    if (!k || k === 'NULL' || k === 'NONE' || k === '-') return null;
    return LABEL_CATALOG[k] ? k : null;
}

function buildEntry(key) {
    var c = LABEL_CATALOG[key];
    return {
        key: key,
        label: c.label,
        icon: c.icon,
        category: c.category
    };
}
