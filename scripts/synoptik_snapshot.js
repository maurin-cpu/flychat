// Synoptik-Karte aus der laufenden App als PNG — kein Nachbau.
//
// Oeffnet eine Seite mit der Synoptik-Karte (/synoptik/karte?day=N, solange
// die Route nicht deployt ist: /briefing?day=N), wartet bis
// synoptic-embed.js die Karte samt Kacheln gezeichnet hat, und fotografiert
// #bfSynoptic. Aendert sich die Karte in der App, aendert sich das Bild mit.
// Mit <datum> wird die Karte per WCSynopticEmbed.setDate auf den Tag gestellt.
//
// Aufruf (Server, dort liegt Playwright in node_modules):
//   node scripts/synoptik_snapshot.js <url> <png> [breite] [datum]
//   ssh ... "cd /home/deploy/flychat && node - <url> <png>" < synoptik_snapshot.js
// Ausgabe: eine JSON-Zeile {"ok": true, "stand": "<Stand-Text der Karte>"}.
const { chromium } = require("playwright");

const [url, out, width = "960", date = ""] = process.argv.slice(2);
if (!url || !out) {
  console.error("Aufruf: node synoptik_snapshot.js <url> <png> [breite]");
  process.exit(2);
}

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: parseInt(width, 10), height: 900 },
      deviceScaleFactor: 2,
    });
    // Haftungshinweis als bestaetigt markieren (Schluessel aus base.html) —
    // sonst liegt der Dialog samt Abdunklung ueber der Karte.
    await page.addInitScript(() => {
      try { localStorage.setItem("wingcast_disclaimer_v1_accepted", "1"); } catch (e) { /* egal */ }
    });
    await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });

    const card = page.locator("#bfSynoptic:not([hidden])");
    await card.waitFor({ timeout: 30000 });
    // Auf /briefing haengt die Karte am gewaehlten Tag der Seite. Das Datum
    // direkt setzen, statt auf die Tages-Auswahl der Seite zu vertrauen.
    if (date) {
      await page.evaluate((d) => {
        if (window.WCSynopticEmbed && window.WCSynopticEmbed.setDate) {
          window.WCSynopticEmbed.setDate(d);
        }
      }, date);
      await page.waitForTimeout(800);
    }
    // Fronten gezeichnet (synoptic-embed.js setzt data-fronts-ready). Aeltere
    // App-Staende ohne Fronten-Modul setzen das nie — dann nicht blockieren.
    await page.waitForSelector("#bfSynopticMap[data-fronts-ready]", { timeout: 15000 })
      .catch(() => {});
    // Alle Kacheln fertig geladen — sonst fehlen im Bild Teile der Basiskarte.
    await page.waitForFunction(() => {
      const tiles = document.querySelectorAll("#bfSynopticMap img.leaflet-tile");
      return tiles.length > 0 && Array.from(tiles).every((t) => t.complete);
    }, null, { timeout: 30000 });
    await page.waitForTimeout(500);

    await card.screenshot({ path: out });
    const stand = ((await page.textContent("#bfSynopticTs")) || "").replace(/^·\s*/, "").trim();
    console.log(JSON.stringify({ ok: true, stand }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
