# Plan en uitvoering: eenvoudiger onderhoud

Uitgangspunt: de bestaande Pi/VPS-verdeling, runtimepaden, MPD/PipeWire en afspeelcontracten behouden. De verbetering zit in beheer, controle en herstel; er wordt geen nieuwe speler gebouwd.

| Stap | Uitvoering | Controle |
|---|---|---|
| 1. Herhaalbare deployment | tools/deploy: schone commit, lokale proefmodus, expliciete apply/rollback, allowlist, hashes, service-identiteit, onderhoudslease en geverifieerde backup. | Positieve/negatieve transactietests met nep-services, inclusief drift, activiteit, corrupte backup, historisch herstel en herstel na rollback. |
| 2. Automatische controles | GitHub Actions voor Python 3.13/3.14 en Node 22; make setup/test/check/check-http. Repository-audit kan alle indexblobs controleren. | Offline regressies, frontend, syntaxis en synthetische HTTP-streaming. Geen automatische live deployment. |
| 3. Versie en gezondheid | release.json per uitrol; /health, /ready en /api/version; release bij /api/status. VPS-health kan de expliciete image-buildcommit tonen. | Endpointtests zonder drive-/MPD-probes, gevalideerde niet-geheime metadata, deployment vergelijkt versie en bestanden. |
| 4. Configuratie en testbaarheid | runtime_settings.py met bestaande defaults; tools/configure.py genereert alleen voorstellen. Standaard unittest met tijdelijke state en expliciete optische adapters. | Beide discoveryvormen met sentineldata; foutieve config, root/poortconsistentie en unitgeneratie. |
| 5. Inrichting en backups | Vastgezette testafhankelijkheden, setup-profielen, afzonderlijk productie-startpunt en private-backup-tool. | Setup is standaard slechts een plan; tests op backupintegriteit en bronpaden; echte loopback-responsstreaming. |

## Bewuste grenzen

- Geen ongevraagde VPS-uitrol, upgrade van distributiepakketten, speakerverbinding, fysieke driveprobe of databaseopruiming.
- De nieuwe deploymenttool is conservatief: alleen gestopte/gepauzeerde CD met volledig bekende, complete archiefstatus. Een nog gepauzeerde lokale stream wordt geweigerd. Afspelen wordt nooit automatisch gestart om een deployment mogelijk te maken.
- De normale Pi-service blijft app.py gebruiken tot een afzonderlijk beoordeeld unitvoorstel wordt geïnstalleerd. player_server.py biedt Waitress met één runtime-eigenaar en meerdere threads; import via een willekeurige multiworker-WSGI-starter is geen ondersteunde installatie.
- De VPS-HTTP-server wordt in deze ronde niet herschreven. Groeiende en grote uploads vragen een apart migratietestplan; dezelfde wijziging tegelijk met deploymentautomatisering zou de uitrol onnodig moeilijk maken.
- Een externe private backup vraagt een door de eigenaar gekozen bestemming. Het hulpmiddel is gereed; er wordt geen cloud- of schijfbestemming gegokt. Git bevat nooit de sleutel of private herstelbestanden.
- CI-code toevoegen is niet hetzelfde als GitHub-branchbescherming activeren. Die instelling is niet gewijzigd. Een lokale testuitslag is evenmin bewijs dat de externe matrix al is geslaagd.

## Dagelijks gebruik

```sh
make setup
make check
make check-http
./tools/deploy plan --dry-run
./tools/deploy inspect
```

Apply/rollback vereisen --apply en een veilig onderhoudsmoment. Zie deployment-tool.md, configuration.md, checks.md en private-backups.md. Het uitrolverslag beschrijft welke commit daadwerkelijk op de Pi draait; een hoger documentatiecommit hoeft geen andere runtime te betekenen.

Uitgevoerd en gevalideerd: runtime 01963cf is via de nieuwe procedure op de veilig gepauzeerde Pi geplaatst. Zie management-deployment-2026-11-07.md voor de gecontroleerde eindtoestand en de bewuste grenzen.
