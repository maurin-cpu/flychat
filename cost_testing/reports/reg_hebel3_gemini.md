# Regression-Report — 2026-04-29T14:51:07+00:00

- Cases: 12
- Score: 355/468 (75.9%)
- Kritische Regressionen: 5
- Hohe Regressionen: 6

## Bergstation / 2026-05-01
Score: 6/39

- safety_status(kritisch): gold='safe' got='error'
- flyability_tier(kritisch): gold='green' got=''
- safe_window(hoch): overlap=0% gold=[11, 12, 13, 14, 15, 16, 17] got=[]
- rating(hoch): |delta|=8.10
- streckenflug_tier(mittel): gold='top' got='kein_xc' stufen_diff=3

## Bergstation / 2026-05-02
Score: 36/39

- caution_notes(mittel): jaccard=0.00

## Bietstöckli / 2026-05-02
Score: 36/39

- caution_notes(mittel): jaccard=0.00

## Charenstöckli / 2026-04-30
Score: 33/39

- caution_notes(mittel): jaccard=0.00
- streckenflug_tier(mittel): gold='lokal' got='top' stufen_diff=2

## Hummel / 2026-05-01
Score: 36/39

- caution_notes(mittel): jaccard=0.00

## Tisch / 2026-05-01
Score: 21/39

- safety_status(kritisch): gold='conditional' got='safe'
- safe_window(hoch): overlap=71% gold=[13, 14, 15, 16, 17] got=[11, 12, 13, 14, 15, 16, 17]
- caution_notes(mittel): jaccard=0.00

## Waldrand, oberhalb Kreuz / 2026-04-29
Score: 31/39

- safe_window(hoch): overlap=67% gold=[10, 11, 12, 13, 14, 15] got=[10, 11, 12, 13]
- caution_notes(mittel): jaccard=0.00

## Weissenstein / 2026-05-01
Score: 0/39

- safety_status(kritisch): gold='conditional' got='not_safe'
- flyability_tier(kritisch): gold='green' got=''
- safe_window(hoch): overlap=0% gold=[10, 11, 12, 13] got=[]
- rating(hoch): |delta|=7.10
- no_go_reasons(mittel): jaccard=0.00
- caution_notes(mittel): jaccard=0.00
- streckenflug_tier(mittel): gold='moderat' got='kein_xc' stufen_diff=2

