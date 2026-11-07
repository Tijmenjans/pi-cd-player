# Verificatie

## Onderhouden controles

`make check` voert de audit van Git-indexblobs, syntaxiscontroles, offline Python-tests en frontendtests uit. `make check-http` test echte loopback-HTTP via Waitress met synthetische media, zonder hardwareworkers. GitHub Actions gebruikt Python 3.13/3.14 en Node 22 met dezelfde controles.

De gewone vormen werken beide:

```sh
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m unittest discover -s tests
```

`tools/run_tests.py` is een compatibiliteitswrapper. tests/__init__.py maakt tijdelijke runtime-state en fictieve archiefconfiguratie. App-importerende tests laden die bootstrap ook bij korte discovery. optical_disc en de device-provider zijn expliciet geïnjecteerd; sys.modules wordt niet vervangen en er wordt geen broncodekopie gemaakt. Sentineltests controleren in aparte processen dat bestaande runtimegegevens bij beide discoveryvormen onaangeroerd blijven.

Veel tests gebruiken mocks voor netwerk, systemd en drive; proces-/flock-tests starten wel kleine echte lokale childprocessen. Frontendtests gebruiken een beperkte DOM-simulatie, geen echte browser of visuele controle. De deploytests gebruiken tijdelijke bestanden en nep-services: ze bewijzen rollbacklogica, geen hoorbaar pauzebehoud bij een echte herstart.

## Bestaande contracten en nieuwe beheercontroles

De suite bewaart lokale-track-pinning, positieherstel, uploadidempotentie, volledige-WAV-validatie, drivewatchdogs, CD-Text/TOC, DVD-exclusiviteit/ondertitels, vinyltransities en bronstatusvolgorde. Nieuwe tests dekken release-identiteit, configvalidatie, servicevoorstellen, runtime-/onderhoudslocks, veilige discovery, repository-audit, private-backup-integriteit en deploy-/rollbackfouten.

De HTTP-tests controleren responsegegevens vóór voltooiing, gelijktijdige health en echte Range/HEAD op de bestaande lokale-audioroute. Dit ondersteunt het afzonderlijke productie-startpunt; het bewijst geen langdurige Apple-TV- of Bluetooth-werking.

## Geïsoleerde MPD-integratie en echte hardware

`make check-hardware ALLOW_INTEGRATION=1` start uitsluitend de bestaande synthetische MPD/null-/recorderproeven. Dit vereist een vrijgegeven omgeving met geschikte MPD. Gewone CI start deze proeven niet. USB-resets, beschadigde cd's, hoorbare bronwissels, Bluetooth, fysieke eject en DVD op Apple TV blijven afzonderlijke praktijkcontroles.

Historisch: op 7 november slaagden de eerste 125 offline tests; na de betrouwbaarheidscorrecties 151 op Mac én Pi. Bij uitrol van 70eb61f slaagden twee echte, geïsoleerde MPD-tests voor groeiende WAV/seek na unlink en crossfade. Zie pi-deployment-2026-11-07.md. Die uitkomsten zijn geen bewijs dat latere bronwijzigingen al live of op hardware zijn getest.

## Resultaat onderhoudsstandaardisatie

Release 01963cf: 217 tests op de Mac, frontendchecks en twee echte loopback-HTTP-tests geslaagd. Op de Pi slaagden 171 runtime-/configuratietests en twee geïsoleerde MPD-tests; de overige 46 Git-afhankelijke gereedschapstests zijn op de Mac uitgevoerd, omdat Git op de Pi ontbreekt. Native libdiscid heeft FEATURE_READ=1, overeenkomstig de adapter. Beide gewone discoveryvormen zijn getest. De externe GitHub-matrix is met de workflow aangevraagd maar niet via de terminal als geslaagd bevestigd.

Voor een volledige broncode-stagingmap op een Pi zonder Git is nu `python3 tools/run_tests.py --runtime-only` beschikbaar. Dit is een standaard unittest-modulelijst; tests worden niet in de productieruntime geïnstalleerd. Gewone CI blijft de volledige suite uitvoeren. Dit profiel verandert geen runtimegegevens of services.
