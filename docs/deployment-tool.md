# Onderhouden Pi-deployment

`tools/deploy` verpakt uitsluitend Git-blobs uit een gekozen commit. Geen kopie van de werkmap, geen secrets, geen services/configuratie uit deploy/, geen vendor, venvs, data of backups. De werkmap moet schoon zijn (ook geen ongevolgde bestanden). Alle reguliere root-`.py`-modules worden meegenomen, inclusief toekomstige runtime-modules; static-bestanden met bekende frontendextensies, catalogue/*.json en tools/dependency_manifest.py plus tools/import_discogs.py vormen de overige allowlist. Symlinks en niet-reguliere Git-objecten worden geweigerd.

## Plan zonder verbinding

```sh
./tools/deploy
./tools/deploy plan --commit HEAD --dry-run
./tools/deploy apply --commit HEAD --dry-run
```

Deze opdrachten lezen alleen lokaal Git, maken geen pakketbestand en benaderen de Pi niet. Het plan bevat de SHA-256 en modus per bestand. `apply` zonder `--apply` toont ook slechts een plan. `inspect` maakt expliciet een alleen-lezen SSH-verbinding, leest alleen release/status/MPD en creëert geen lock of tijdelijke directory.

## Geplande uitvoering

```sh
./tools/deploy inspect
./tools/deploy apply --commit HEAD --baseline-commit 70eb61f3eb78510ca9c161799fd7c97883033776 --apply
```

De baseline is een bewuste verklaring van de verwachte oorspronkelijke bestanden, geen optie om drift te negeren. De eerste bestaande Pi-installatie is volgens docs/pi-deployment-2026-11-07.md commit 70eb61f. Iedere afwijking in SHA of modus wordt geweigerd. Bestanden die nieuw zijn moeten ook daadwerkelijk ontbreken. Bij volgende uitrollen geldt het geverifieerde geïnstalleerde release.json als baseline. Toevoegen van nieuwe paden vereist een expliciete baseline; verwijderen van oude runtimepaden wordt geweigerd en vraagt aparte beoordeelde migratie.

Alleen `tools/pi-ssh` wordt gebruikt. Defaults zijn de bestaande runtime-root /home/tijmen/cdspeler, API 127.0.0.1:8080 en MPD 127.0.0.1:6601. Voor een andere root bestaat --root. De netwerkpoorten worden uit data/installation.json gelezen en op lokale endpoints gevalideerd; zonder bestand blijven de bestaande defaults gelden. Een afwijkend CDSPELER_CONFIG in de service vereist een afzonderlijk beoordeelde inrichting. Geen nieuwe dependencies. SSH-input is JSON op stdin; geen waarden uit CLI/payload in shellcommando's. Het remote programma wordt als gequote Pythoncode uitgevoerd. Uitvoer bevat geen configuratie, runtime-URL's of SSH-stderr.

## Conservatieve toestandsgrens

Alleen CD met stop of pause, een gezonde bekende status en volledig opgeslagen tracks wordt toegelaten. Afspelen, DVD, vinyl, Spotify/Plexamp, buffering, errors, overgang en ontbrekende/afwijkende archiefstatus worden geweigerd. Ook geblokkeerde of overgeslagen imports gelden niet als voltooid. Een gepauzeerde serverroute wordt eerst via HEAD op beschikbaarheid gecontroleerd. Voor iedere stop worden systemd-WorkingDirectory, de entrypoint en de effectieve proces-root/configuratie gecontroleerd. Een gezonde API van een andere installatie is onvoldoende. Dezelfde toestandscontrole loopt opnieuw na staging/backup, onmiddellijk vóór stoppen. MPD-state, songid en pauzepositie moeten gelijk blijven.

**Gepauzeerde lokale streamtokens worden geweigerd.** De historische uitrol heeft seekid-vervanging afzonderlijk getest, maar een generieke automatische overname wordt hier bewust nog niet uitgevoerd. Selecteer een bevestigde servertrack in een afzonderlijk onderhoudsmoment; hervat en pauzeer niet automatisch vanuit deployment. Nieuwe versies van de webapp weigeren POST-bediening zolang de exclusieve deploymentlease vaststaat; reeds lopende acties verhinderen het nemen van die lease. Externe directe MPD-bediening blijft buiten deze bescherming. De tool start of herstart MPD nooit en voert geen seek, eject of driveprobe uit. Een gestopte speler met lokale URL is toegestaan: er loopt dan geen stream die behouden moet blijven.

Er blijft een kleine race met externe bediening: een historische webservice zonder nieuwe actie-lease beschermt HTTP-acties nog niet. De tool controleert direct vóór en na stop en breekt bij gewijzigde MPD-state af. Bedien de speler daarom niet tijdens gepland onderhoud. Dit is geen garantie tegen een gelijktijdige gebruikersactie of stroomuitval.

## Transactie en herstel

Alleen de muterende route neemt een exclusieve niet-blokkerende flock op `.deployment.lock`. De payload wordt gevalideerd, begrensd en gecompileerd; daarna veilig in een private tijdelijke directory gestaged. Een private backup `backups/deploy-<ID>/` bewaart uitsluitend vervangen code, het vorige releasebestand en hashmetadata, geen privéconfiguratie. Alle backups worden geverifieerd vóór vervanging of verwijdering. Geen blind `rsync --delete`.

Alleen cdspeler-web wordt gestopt/gestart. Bestanden worden atomisch vervangen met juiste modi en fsync. `release.json` staat in de runtimeroot, nooit in data/, met schema 1, volledige commit, ISO-tijdzone, component pi-player en files met sha256/mode. Het markerbestand zelf staat niet in zijn eigen fileslijst. De backend moet /health en /ready met JSON `{"ok":true}` en /api/version met dezelfde schema/component/commit/built_at en installed=true leveren. Na start volgen health-, ready-, versie-, bestands- en MPD-controles. De bestaande systemd-unit blijft ongewijzigd.

Bij een fout worden vorige code en marker automatisch hersteld, uitsluitend de webservice gestart en de oude API/MPD-toestand gecontroleerd. Een falende rollback meldt alleen het backup-ID; inspecteer de Pi voordat je opnieuw uitrolt. Een afgebroken SSH-client of stroomuitval kan handmatig herstel nodig maken. Geen crashatomiciteit over meerdere bestanden.

```sh
./tools/deploy rollback --backup-id deploy-EXACT_ID
./tools/deploy rollback --backup-id deploy-EXACT_ID --apply
```

Een rollback zonder --apply schrijft niets en leest de backup niet op afstand. Expliciete rollback vereist de exacte nog geïnstalleerde release, ongewijzigde hashes en een geverifieerde backup. De rollback maakt eerst een nieuwe veiligheidsbackup. Hij herstelt ook een historische installatie zonder release.json en verwijdert uitsluitend aantoonbaar nieuw toegevoegde payloadbestanden. De oude API geldt dan als healthcheck; nieuwe endpoints bestonden daar nog niet. Terug naar een markervrije installatie krijgt commit=null en historical=true in het resultaat; voor een volgende uitrol is opnieuw een expliciete baseline nodig. De historische backup van vóór deze tooling heeft geen backup.json; daarvoor blijft de handmatige procedure in docs/pi-deployment-2026-11-07.md gelden.

## Verificatie

`python3 -m unittest discover -s tests -p test_deployment.py` test uitsluitend tijdelijke Git-repositories, tijdelijke runtimemappen en een nep-systeemadapter. Geen SSH, productie-MPD, hardware of servicewijzigingen. De volledige offline suite blijft aanvullend vereist. Dit bewijst geen USB-, Bluetooth-, stroomuitval- of hoorbaar pauzebehoud op de echte Pi.

Getest tijdens implementatie: 33 specifieke offline deploymenttests, met onder meer drift, lock-exclusiviteit, padtraversal, corrupte backups, activiteit, gewijzigde positie, mislukte healthcheck, gedeeltelijke schrijffout en historische rollback. Geen live verbindingen of deployments uitgevoerd.

Een veiligheidsbackup na terugzetten naar een historische installatie zonder release-marker kan eveneens expliciet worden teruggezet. De tool valideert daarvoor ook ontbrekende bestanden en het volledige historische bestandenset; geen force- of drift-override.
