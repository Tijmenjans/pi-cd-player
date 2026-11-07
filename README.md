# Pi CD Player

Overgenomen bestaande Raspberry Pi-mediaspeler met CD, DVD, Vinyl, Spotify en Plexamp. Flask met gewone HTML/CSS/JavaScript; geen frontendbuild. Deze repository is op 7 november 2026 samengesteld uit het afleverpakket en een alleen-lezen vergelijking met Pi en VPS. Tijdens die eerste overdracht is niets live gedeployd of herstart.

De Pythonmodules, `static/` en `catalogue/` blijven in de projectroot: de bestaande imports en paden zijn daarvan afhankelijk. `archive-server/` bevat de bestaande VPS-software, `tests/` de controles en `deploy/` de installatievoorbeelden. Een extra `player/`-laag zou onnodig werkende paden veranderen.

## Beheer en toegang

Werk voortaan vanuit dit project. Gebruik `./tools/pi-ssh` voor de Pi en `./tools/vps-ssh` voor de VPS. De Pi-sleutel en herstelarchieven staan lokaal afgeschermd en buiten Git; zie [toegang en private backups](docs/access.md). Oude chatwerkruimtes zijn niet meer nodig.

## Ontwikkelen en testen

```sh
make setup
make check
make check-http
./tools/deploy plan --dry-run
```

Tests draaien via gewone unittest-discovery met tijdelijke runtime-state en expliciete optische testadapters. `make check-http` gebruikt uitsluitend synthetische data en lokale HTTP-sockets; echte MPD-/hardwarechecks blijven opt-in. Start `app.py` niet als test: dat activeert achtergrondwerk. Zie [onderhoudsplan](docs/management-plan.md), [deploymenttool](docs/deployment-tool.md), [configuratie](docs/configuration.md), [checks](docs/checks.md), [tests](docs/testing.md) en [private backups](docs/private-backups.md).

DVD gaat uitsluitend rechtstreeks naar `http://192.168.1.232:8080/dvd/live.mkv`. Geen dvd-archivering naar Plex. De bestaande vijf bronnen en UI zijn ongewijzigd overgenomen.

Na de overdracht zijn gerichte betrouwbaarheidsverbeteringen voorbereid: gedeelde drivelease, herstelbare bronwissels, offline lokale buffering, onafhankelijke Plex-refresh en VPS-crashherstel. Zie [uitgevoerde verbeteringen](docs/improvements.md) en [Discogs-import](docs/discogs.md). De Pi-onderdelen draaien inmiddels op commit 01963cf; de VPS-wijzigingen zijn nog niet uitgerold. Zie [actuele uitrol en verificatie](docs/management-deployment-2026-11-07.md) voor controles en resterende hardwarebeperkingen.
