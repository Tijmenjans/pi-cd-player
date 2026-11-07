# Productie-ingang, VPS, backup en CI — 7 november 2026

Dit is het vervolg op management-deployment-2026-11-07.md. De eigenaar heeft de afzonderlijke resterende punten laten uitvoeren en de VPS gekozen als uitsluitend versleutelde externe backupbestemming.

## Pi: Waitress geactiveerd

De runtimecode blijft commit **01963cf097dbb6836a9b45cd3c91ac0dbe03cb46**. Er zijn geen appbestanden gewijzigd. De gegenereerde webunit gebruikt nu `.venv-player/bin/python player_server.py` met `CDSPELER_ROOT=/home/tijmen/cdspeler`. De bestaande `TimeoutStopSec=10`-drop-in blijft behouden.

De afzonderlijke venv gebruikt bestaande distributiepakketten via system-site-packages. Alleen de vastgezette, pure Python-wheel Waitress 3.0.2 is met `--no-index --no-deps` geïnstalleerd. Geen globale pakketupgrade, vendorwijziging of tweede runtime-eigenaar. De twee synthetische HTTP-tests zijn op de Pi met deze venv geslaagd: streaming vóór voltooiing met gelijktijdige health-respons, en audio Range/HEAD.

De unitwissel gebeurde onder de bestaande exclusieve onderhoudslock, na controle van complete imports, huidige servertrack, codehashes en MPD-pauzestand. Alleen de webservice is gestopt/gestart. Bij een fout zou de oude unit worden hersteld. De private oude unit, drop-in en verificatie staan op de Pi onder `backups/production-server-e6m7c6x9`, met een private Mac-kopie onder `backups/production-20261107/`.

## VPS: bestaande archiefverbeteringen uitgerold

De archiefcode komt uit **2c937505b3a5c7c4c43ff6b2ad4476288195c6d4**. De nieuwe health-respons toont deze volledige commit. Server.py en artwork.py bevatten nu de eerder beoordeelde onafhankelijke Plex-refresh met persistent herstel/backoff, begrensde raw-reconciliatie, conservatievere publicatie en gecontroleerde album-ID-cache.

Alle 865 bestaande tracks behouden onder de nieuwe metadataregels dezelfde bestemming. Er waren geen wachtende raw-conversies, foutrecords of gedeeltelijke uploads. Open verbindingen bleken status-/health-polling; voor de wissel is de Pi-webservice onder de onderhoudslock stilgelegd, zonder MPD te stoppen. De archiefcontrole weigerde overdrachten met socket-wachtrijen en actieve FFmpeg-processen.

De nieuwe image is gebouwd door uitsluitend de nieuwe server.py/silence.py en release-identiteit bovenop de bestaande image te plaatsen. Zo bleven Python, FFmpeg en libraries gelijk. Dit is een bewuste bevroren basis voor deze uitrol; de repository-Dockerfile blijft de toekomstige volledige build beschrijven. Een toekomstige basisimage-upgrade vereist afzonderlijke beoordeling.

- Vorige image: `sha256:3fc9a9cc640464e11b480e5ad563f03c443b37704c3a4ab93862c9a59a07285b`, behouden als `cd-archive-rollback:20261107`.
- Nieuwe image: `sha256:6e5388a871f5520c0e6a42a16f5edaa3eae6dd35c1c38e500e083ad3019a8c61`, ook `cd-archive-release:2c93750`.
- Alleen hostbestanden server.py, artwork.py en Dockerfile zijn bijgewerkt. Compose, .env, mounts, netwerken, containerrechten, mediadata en Plex-configuratie zijn behouden.
- Oude bronbestanden en een SQLite-backup via de backup-API staan onder `/opt/cd-archive/backups/deploy-2c93750-20261107`. De snapshot is genomen met gestopte archief- en artwork-schrijvers; integrity_check geeft ok.
- Alleen de Compose-service archive is opnieuw aangemaakt en de artwork-service herstart. De identiteit en starttijd van `plex-l0dbpo3rcbqoa0g6oirt9rje` zijn ongewijzigd.

Twee voorcontroles stopten veilig vóór de VPS-wijzigingen: de Plex-containernaam verschilde van de aanname en Docker top vereiste een PID-kolom. Na correctie is de uitrol afgerond. De Pi-webservice is ook na deze geweigerde pogingen steeds terug gestart met dezelfde MPD-positie.

### Herstel

Pi: bewaar eerst de actuele unit, vergelijk de private oude unit en plaats die alleen tijdens een veilige onderhoudstoestand terug onder `~/.config/systemd/user/cdspeler-web.service`. Voer daemon-reload uit en herstart uitsluitend cdspeler-web. Verwijder de venv niet tijdens herstel; oude app.py met systeem-Python blijft beschikbaar. Controleer daarna health/ready, code-identiteit en onveranderde MPD-positie.

VPS: tijdens gepland, vrijgegeven onderhoud artwork en archive stoppen, de drie oude hostbestanden herstellen, de behouden oude image terug taggen als `cd-archive-archive`, en uitsluitend `docker compose up -d --no-build --no-deps archive` uitvoeren vanuit `/opt/cd-archive`. Artwork daarna starten en health, hashes en tracktoegang controleren. **Zet de SQLite-backup niet automatisch terug:** nieuw ontvangen tracks zouden verloren kunnen gaan. De vorige code kan de extra plex_refresh-tabel negeren. Laat raw, unmatched en music behouden.

## Externe backup en CI

Een echte private Mac-projectbackup is lokaal met age versleuteld, teruggelezen en op de VPS op ciphertext-checksum gecontroleerd. Er is geen plaintext-projectbackup of privésleutel geüpload. Zie private-backups.md voor bestemming, inhoud, sleutelafhankelijkheid en herstel. Dit is geen backup van de volledige muziekcollectie of alle actuele accountinstellingen.

De echte [GitHub Actions-run voor 2c93750](https://github.com/Tijmenjans/pi-cd-player/actions/runs/42375748612) is bekeken: Python 3.13 en 3.14 zijn beide geslaagd. Dit bevestigt de externe CI van de uitgerolde VPS-bronversie; verplichte branchchecks zijn niet ingesteld.

## Onafhankelijke eindcontrole

Na ruim drie minuten is de container nog healthy en artwork actief zonder herstarts. Runtime server.py/silence.py en host artwork.py komen op SHA-256 overeen met de repository. SQLite heeft 865 tracks, nul fouten en nul wachtende raw-tracks; Plex-refresh-generatie 865 is afgehandeld zonder pending/retries/fout.

Een bestaande track geeft geauthenticeerd HEAD 200 en Range GET 206 met 1024 bytes en geldige FLAC-signatuur. Vanaf de Pi geeft de bestaande audio-route eveneens 206 met Content-Range en 64 gelezen bytes. Hierbij is geen afspelen gestart.

De Pi heeft health/ready=true, runtime 01963cf, 25/25 opgeslagen tracks en blijft CD/pause, track 13 op 99.105. MPD blijft PID 28787. Dit is een status-/HTTP-controle, geen nieuwe luisterproef.

## Praktijkgrenzen

Geen fysieke rip, nieuwe Bluetooth-luisterproef of Apple-TV-dvd-weergave uitgevoerd. De HTTP-tests gebruiken synthetische media; de bestaande MPD-integratietests gebruiken geïsoleerde null/recorder-uitvoer. De controles bewijzen geen foutloos gedrag bij toekomstige USB-resets, netwerkuitslag of wijzigingen van externe metadata-interfaces.
