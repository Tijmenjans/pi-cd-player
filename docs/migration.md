# Overdracht — 7 november 2026

Werkmap begon leeg met bestaande .git, zonder commits/remote. Vertrekpunt: vinyl-current-delivery onder Documents/Codex/2026-10-30/die-je-de-ufo202-aangesloten-op/work; het opgegeven tar.gz is als secundair archief geïnventariseerd, niet blind uitgepakt. Geen toepasselijke AGENTS.md in die bron gevonden. README is bewaard als historical-delivery.md.

Pi /home/tijmen/cdspeler is alleen-lezen geïnventariseerd. Runtime-Pythonmodules uit het pakket waren gelijk aan de Pi. Ontbrekende modules (catalogue, music_metadata, queueing, Spotify en Plexamp), aanvullende tests, service-/audiovoorbeelden en de tweede gecontroleerde catalogusentry zijn gericht overgenomen. Alle vijf static-bestanden en beide catalogusentries hebben dezelfde SHA-256 als de Pi. docs/source-inventory.json legt de vergelijking vóór reorganisatie vast; paden daarin zijn oorspronkelijke runtimepaden. Deploymentbestanden zijn daarna onder deploy/ geplaatst.

VPS /opt/cd-archive: server.py, silence.py, Dockerfile en compose.yaml gelijk aan pakket; artwork.py en bijbehorende systemd-service toegevoegd. .env, media, databases, logs, backups en /opt/plex/plex_api.py niet gekopieerd. Pi-data, Caldera-configuratie, SSH-sleutel, vendor-binaries en venvs eveneens uitgesloten.

Oudere Pi-testkopieën van handoff en pipeline zijn niet leidend gemaakt: het pakket heeft de recentere blocked-track-, skip-herstel- en uploadretrytests. Testpaden en unittest-main-guards zijn geschikt gemaakt voor discovery. Oudere autoplay-/API-fixtures zijn bijgewerkt naar de actieve ArchiveQueue en huidige TOC/drivebewaking. Productiemodules zijn niet aangepast.

Geïnstalleerde SuperDrive-udevregels, begrensde wake-service en vinylservice zijn aanvullend alleen-lezen gecontroleerd; projectkopie van de udev-wakeregel was ouder. Actieve webservice was running. Geen POST-acties, streamstart, probe op de drive, sudo, reparatie of servicewijziging uitgevoerd.

Ontbreekt bewust: privéconfiguratie, runtime-data en derdepartijbinaries. Open herstelpunt: exacte DVD-vendor-package-lock/buildrecept. Nog nodig voor samenwerking: remote-URL; er is geen bestaande remote ingesteld. Hardwarepraktijk tijdens migratie niet opnieuw gevalideerd.

Git-controle: 90 bestanden; geen credentialpatronen of bestanden boven 2 MiB na controle van de expliciete voorbeeldtoken. Grootste binary is de bestaande haardfoto (451349 bytes). Bestaande whitespace in twee servicebestanden en static/index.html is behouden om de bronovername byte-identiek te houden. De historische deploy.py met toenmalige hashes is niet opgenomen als bruikbaar deploymentscript.

Vervolg: origin is inmiddels git@github.com:Tijmenjans/pi-cd-player.git en de overdrachtscommit 44939f4 is daar geverifieerd. De inventaris hierboven blijft het historische migratiemoment beschrijven. De daaropvolgende betrouwbaarheidswijzigingen staan in improvements.md en zijn afzonderlijk getest; hun bronbestanden zijn vanzelfsprekend niet meer byte-identiek aan de historische productiesnapshot. Er is nog geen live deployment uitgevoerd.
