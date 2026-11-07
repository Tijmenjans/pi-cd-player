# Onderhoud

Lees README.md en docs/ voordat je deployment of hardwaregedrag wijzigt. Dit is bestaande software met actieve muziek/imports. Houd runtime-modules in de root; behoud imports en relatieve paden.

- Geen serviceherstart, bronwissel, driveprobe, eject, deployment of systeemreparatie tijdens repositoryonderhoud.
- Gebruik alleen-lezen vergelijking en expliciete allowlists; kopieer nooit data/, privéconfiguratie, venvs, vendor of backups naar Git.
- Behoud lokale-track-pinning, positieherstel, uploadbevestiging/idempotentie, volledige-WAV-controle en reader-lock/watchdogs. Lees de regressietests.
- DVD blijft uitsluitend VLC-remux; nooit DVD-naar-Plex terugbrengen.
- Test offline met `.venv/bin/python tools/run_tests.py` en `node tests/test_frontend.cjs`. Hardwareclaims vereisen afzonderlijke praktijkcontrole.
- Controleer vóór elke commit staged bestanden op geheimen en grote/onbedoelde binaries met `python3 tools/check_repository.py`.
- `deploy/repair-superdrive.sh` is geen normale installatiestap. Alleen bij concrete diagnose en gepland onderhoud uitvoeren.
