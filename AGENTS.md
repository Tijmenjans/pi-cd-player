# Onderhoud

Lees README.md, docs/access.md en docs/ voordat je deployment of hardwaregedrag wijzigt. Dit is bestaande software met actieve muziek/imports. Houd runtime-modules in de root; behoud imports en relatieve paden.

- Geen serviceherstart, bronwissel, driveprobe, eject, deployment of systeemreparatie tijdens repositoryonderhoud.
- Gebruik alleen-lezen vergelijking en expliciete allowlists; kopieer nooit data/, privéconfiguratie, venvs, vendor of backups naar Git.
- Behoud lokale-track-pinning, positieherstel, uploadbevestiging/idempotentie, volledige-WAV-controle en reader-lock/watchdogs. Lees de regressietests.
- DVD blijft uitsluitend VLC-remux; nooit DVD-naar-Plex terugbrengen.
- Test offline met `.venv/bin/python tools/run_tests.py` en `node tests/test_frontend.cjs`. Hardwareclaims vereisen afzonderlijke praktijkcontrole.
- Controleer vóór elke commit staged bestanden op geheimen en grote/onbedoelde binaries met `python3 tools/check_repository.py`.
- `deploy/repair-superdrive.sh` is geen normale installatiestap. Alleen bij concrete diagnose en gepland onderhoud uitvoeren.

- Gebruik dit project als enige werkbron. Oude chatwerkruimtes zijn historische herkomst, geen beheerafhankelijkheid.
- Pi-toegang: tools/pi-ssh met de genegeerde sleutel .ssh/pi_ed25519; VPS: tools/vps-ssh via de normale Mac-SSH-configuratie. Gebruik geen sleutelpaden uit oude chats.
- Private backups staan lokaal onder backups/; zie docs/access.md. Commit nooit .ssh/ of backups/ en kopieer de projectroot niet blind naar de Pi.
