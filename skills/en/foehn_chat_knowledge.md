# Foehn — Knowledge for Chat Answers

Always use this **together** with the spot/region field **"Critical Foehn"** and the **numbers in the context** (hours, ΔP, upper wind).

**Important: You don't calculate anything yourself.** All values — ΔP, ridge wind 700/850 hPa, surface wind, gusts, foehn level — are delivered fully prepared. Your job is the **interpretation and assessment**.

---

### Avoid the typical wrong answer

- You judge the **foehn situation** from the **"═══ FOEHN INDICATOR ═══"** block (level, **ΔP**, **ridge wind 700 hPa**) — **not** from the spot shortlist (green/orange/not safe).
- **"All spots not safe"** says **nothing** about foehn: that can be rain, gusts, wind direction — **independent** of whether a foehn weather situation is running.
- **No foehn hazard for one launch site** does **not** automatically mean: "There is no foehn in the Alps." Phrase it as: **situation** vs. **relevant for this site**.
- If there is **no** foehn block in the context: say that **no indicator data** was provided — **don't** freely invent "no foehn anywhere."
- **NEVER** issue a blanket foehn warning for all regions! Always check whether the **foehn direction** matches the **region**.

---

### South vs. North — don't confuse them

**South foehn**
Pressure higher in the south than in the north → **ΔP = Lugano − Zurich > 0**.
Typical: **lee of the northern Alps / northern foothills**, lots going on aloft (**S/SW** at the ridge, 700 hPa).
**Affected regions**: Glarner Alpen, Chur/central Graubünden, Alpstein, Berner Alpen, central Swiss foothills, Berner Oberland. With strong south foehn (≥5 hPa) reaching into the Mittelland.

**North foehn**
**ΔP = Zurich − Lugano > 0**.
Typical: **lee south of the ridge**, aloft often **N/NE** (315°–45°).
**Affected regions**: central Ticino, northern Ticino, southern Graubünden (Misox/Calanca).
**NOT affected by north foehn**: Mittelland, Jura, northern foothills, Freiburger Voralpen, Alpstein — these regions get a **cold northerly flow** (Bise-like), **not** a warm downslope wind.

**North foehn specialty:** Physically often a "masked bora" — cold, heavy air plunges over the ridge. Higher density → enormous kinetic energy → surface gusts over 80 km/h possible. Warn conservatively from as little as **~2 hPa**.

**Main-ridge regions** (Valais, Engadine, Surselva, Uri Alps): can be affected **from both directions** — always check both ΔP values.
**Haslital/Grimsel**: lies **north** of the Grimsel Pass → only **south foehn** is critical (lee with south foehn). With north foehn Haslital is the windward side — no foehn effect, at most a channeled northerly wind.

**Direction detection in the data:**
- **700 hPa wind direction**: S/SW (135°–225°) = south foehn | N/NE (315°–45°) = north foehn
- **Sign of ΔP**: ΔP_South positive = south foehn | ΔP_North positive = north foehn
- A note "not critical for this launch site" → **take it seriously!**

---

### Region-specific deviations

| Region | Specialty |
|--------|-------------|
| **Valais** (Visp/Sion) | Breakthrough possible from ~2 hPa, especially in spring (thermals destabilize the inversion) |
| **Berner Alpen** (Haslital) | Grimsel Pass influence, rotors in the lee, 3–4 hPa |
| **Glarnerland** | Guggifoehn effects, 4–5 hPa |
| **Rhine valley** (Chur/Vaduz) | Complex branching, wind shear near the surface, ~4 hPa |

---

### Hidden foehn (cold-air pool) — the most dangerous scenario

Down in the valley **little wind**, aloft at **850/700 hPa** **strong Alpine wind** → **strong shear**.
Danger: turbulent foehn aloft, deceptively calm below. The pilot feels safe but is sitting in a cold-air pool that can erode at any moment.

**Ratio of upper wind : surface wind:**
- **> 3:1** → strong indication of hidden foehn
- **> 5:1** → very pronounced, high danger

**AND** a matching direction aloft (south foehn 135–225°, north foehn 315–45° at 700 hPa).

When you see this pattern, warn explicitly: *"At the surface it's calm, but at 700 hPa a strong southerly is blowing at XX km/h — that's hidden foehn."*

---

### Three styles

| Type | Keyword | Detection |
|-----|-----------|-----------|
| **Deep** | 700 hPa **> ~18 km/h** from the south (135–225°) | Classic, ΔP and upper wind correlate |
| **Shallow** | Already at a **small ΔP (~2 hPa)** | The **vertical profile** (850/700) is more telling than ΔP alone |
| **Counterflow** | 700 hPa from **W/NW (~240–360°)** | Rarer, but real. Not detectable from ΔP alone |

---

### Thresholds — always take the numbers from the context

**ΔP (Lugano − Zurich), south foehn:**
~**3 hPa** → tendency · **≥ ~4 hPa** → more likely valley foehn · **≥ ~8 hPa** → very strong / reaching the foreland.

**Upper wind:**

| Pressure level | Corresponds to approx. | Critical | Signal |
|---|---|---|---|
| **700 hPa** | ~3000 m (ridge height) | > ~54 km/h from a matching direction | Massive overflow |
| **850 hPa** | ~1500 m (summit level) | > {{cfg.WIND_DANGER_KMH}} km/h from a matching direction | Caution, turbulence |
| **10 m** (surface) | Valley floor/launch site | > 15 km/h from the foehn direction | Borderline for launching |

**Important:** **ΔP alone is not enough.** At **2–4 hPa** a **shallow foehn** can sit there — then **850/700** and **surface vs. aloft** weigh more heavily.

---

### Early warning signals in the hourly data

- **700 hPa veers to S/SW and strengthens** → south foehn is building up
- **700 hPa veers to N/NE and strengthens** → north foehn is building up
- **ΔP rises steadily** → foehn building. **A rate > 0.5 hPa/h is critical**
- **ΔP plateaus at a high value** → foehn is established. Grounding.
- **ΔP falls after a peak** → foehn is collapsing. Caution: the collapse itself can be turbulent
- **Gusts ≫ mean wind** + tags [ALOFT-...] → read together with the foehn indicator
- **Surface wind suddenly drops or veers to the foehn direction** → point of no return

---

### Synergies with other weather phenomena

- **Foehn + cold front:** The most dangerous combination. Pre-frontal instability + foehn = uncontrollable mixing with rotors down to the surface.
- **Foehn + thermals (summer):** Thermals can temporarily slow the upper wind, but in foehn situations they often lead to uncontrollable mixing — thermals act as a "trigger" for a foehn breakthrough.
- **Foehn + inversion (winter/spring):** Stable inversions protect the valleys but are weakened over the course of the day by solar radiation. Safe morning conditions can flip in the afternoon.

---

### Confirmation-bias breaker

When foehn warning signals are present and the pilot still wants to fly:

- **Landing-site focus:** *"How does it look at the landing site? Foehn often shows up there first — has the valley wind stopped?"*
- **Trend instead of snapshot:** *"Yes, it's calm right now. But ΔP is rising. In an hour the situation can look completely different."*
- **Worst case:** *"What happens if the breakthrough comes while you're in the air?"*

---

### Foehn physics (background knowledge for explanations)

Use this knowledge to explain to the pilot *why* a situation is dangerous:

- **Thermodynamic foehn:** Moist-adiabatic ascent on the windward side, dry-adiabatic descent in the lee. Recognizable by: temperature rise, humidity drop.
- **Hydraulic foehn:** Overflow like water over a weir. Produces rotors with vertical wind speeds over 90 km/h — a deadly hazard.
- **Isentropic drawdown:** Warm air aloft sinks down. Treacherous: temperature rise in the valley with calm winds (pre-frontal) — the danger is there before the wind arrives.
- **Turbulent erosion:** Mechanical mixing destroys the cold-air pool. Signal: BLH rises over the course of the day up to the foehn level.

---

### Meteogram / hourly list — what you connect

Per hour there is, among others: **wind 10 m**, **gusts**, **850 & 700 hPa** (direction °, km/h).

**Typical patterns:**
- Surface **weak**, aloft **strong + S/SW** → **hidden south foehn** possible
- Surface **weak**, aloft **strong + N/NE** → **hidden north foehn** possible (only south of the ridge!)
- **Gusts ≫ wind**, tags [ALOFT-...], "FOEHN INDICATOR" block → read together, don't dismiss individually

---

### Explain it to fit the app

The context contains, among other things, **Zurich + Lugano** and **700 hPa** at the north point.
State **ΔP** and **ridge wind** so that they fit **these numbers** — don't put freely invented thresholds alongside them.
