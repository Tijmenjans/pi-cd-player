# Pi CD Player

Overgenomen bestaande Raspberry Pi-mediaspeler met CD, DVD, Vinyl, Spotify en Plexamp. Flask met gewone HTML/CSS/JavaScript; geen frontendbuild. Deze repository is op 7 november 2026 samengesteld uit het afleverpakket en een alleen-lezen vergelijking met Pi en VPS. Tijdens die eerste overdracht is niets live gedeployd of herstart.

De Pythonmodules, `static/` en `catalogue/` blijven in de projectroot: de bestaande imports en paden zijn daarvan afhankelijk. `archive-server/` bevat de bestaande VPS-software, `tests/` de controles en `deploy/` de installatievoorbeelden. Een extra `player/`-laag zou onnodig werkende paden veranderen.

## Ontwikkelen en testen

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python tools/run_tests.py
node tests/test_frontend.cjs
```

De offline runner kopieert code en fixtures naar een tijdelijke map en vervangt libdiscid expliciet door een drive-simulatie. Start `app.py` niet als test: dat activeert achtergrondwerk. Voor productie zijn ook native Linux-pakketten en privéconfiguratie nodig. Zie [tests](docs/testing.md), [architectuur](docs/architecture.md), [deployment](docs/deployment.md), [herstel](docs/recovery.md) en [overdracht](docs/migration.md).

DVD gaat uitsluitend rechtstreeks naar `http://192.168.1.232:8080/dvd/live.mkv`. Geen dvd-archivering naar Plex. De bestaande vijf bronnen en UI zijn ongewijzigd overgenomen.

Na de overdracht zijn gerichte betrouwbaarheidsverbeteringen voorbereid: gedeelde drivelease, herstelbare bronwissels, offline lokale buffering, onafhankelijke Plex-refresh en VPS-crashherstel. Zie [uitgevoerde verbeteringen](docs/improvements.md) en [Discogs-import](docs/discogs.md). De Pi-onderdelen draaien inmiddels op commit 70eb61f; de VPS-wijzigingen zijn nog niet uitgerold. Zie [uitrol en verificatie](docs/pi-deployment-2026-11-07.md) voor controles en resterende hardwarebeperkingen.
