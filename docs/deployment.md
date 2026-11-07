# Deployment en installatiegrenzen

Voor nieuwe Pi-uitrollen gebruik je de [onderhouden deploymenttool](deployment-tool.md). Deze vervangt de eerdere eenmalige scripts; hieronder staan ook de bestaande installatiepaden en herstelachtergrond. Configuratie- en servicewijzigingen volgen afzonderlijke [gegenereerde voorstellen](configuration.md).

Actuele status: de Pi is bijgewerkt naar 01963cf; de VPS is ongewijzigd. Zie [actueel uitrolverslag](management-deployment-2026-11-07.md). De onderstaande procedure beschrijft ook toekomstige updates. Productie blijft `/home/tijmen/cdspeler` op Pi 192.168.1.232 (tijmen, armv7l, 32-bit Raspbian 13); VPS via bestaande SSH-alias `hetzner-coolify`. Gebruik tools/pi-ssh en tools/vps-ssh zoals beschreven in access.md; de private Pi-sleutel staat in de genegeerde .ssh/-map en hoort nooit in Git. Sudo vereist normaal een wachtwoord.

## Bestaande installatie bijwerken

Plan een onderhoudsmoment nadat weergave en imports klaar zijn. Leg eerst codeversie, actieve configuratie en herstelbackup vast buiten Git. Stage uitsluitend gewijzigde Pythonmodules, static/ en catalogue/; laat data/, music/, vendor/, .venv-vinyl en privéconfiguratie ongemoeid. Gebruik nooit een blinde `rsync --delete` op de installatiemap. Kopieer configuratievoorbeelden niet over bestaande instellingen.

De runtimebestanden in de root gaan naar de root van cdspeler. `deploy/config/mpd.conf` en `caldera-alsa.conf` horen daar eveneens; systemd user-units horen in `~/.config/systemd/user`. De stop-timeout hoort als `cdspeler-web.service.d/stop-timeout.conf`. Systeemudevregels en de SuperDrive-wake-unit zijn afzonderlijke beheerdersconfiguratie; geen automatische installatie daarvan. Bestanden onder deploy zijn geen automatisch uitvoerbaar uitrolplan.

Na bewuste wijzigingen aan user-units: `systemctl --user daemon-reload`; herstart alleen betrokken diensten in het afgesproken onderhoudsmoment. De vinylservice kan audio onafhankelijk van de webservice verzorgen. Rollback: herstel de vorige code/configuratie uit de eigen backup, niet de runtime-data; start uitsluitend noodzakelijke diensten opnieuw. Controleer daarna status en luister/weergavegedrag.

## Benodigdheden op de Pi

Waargenomen: Python 3.13-runtime, python3-flask 3.1.1, python3-libdiscid 2.0.3, python3-websocket 1.8.0, MPD 0.24.4, PipeWire 1.4.2, BlueZ 5.82. requirements.txt beschrijft de Pythonlaag; op de Pi zijn distributiepakketten geschikt en is libdiscid native nodig. Verder cdparanoia, eject, sg_raw (sg3-utils), PipeWire-tools, WirePlumber en Bluetooth. Controleer beschikbaarheid/architectuur vóór installatie; geen upgrades vereist door deze migratie.

ShazamIO 0.8.1 en audioop-lts 0.2.2 blijven in `.venv-vinyl` (requirements-vinyl.txt). Soloist staat onder vendor/soloist, Caldera onder ~/caldera-music; ALSA-plugins staan onder vendor/caldera-audio. Deze gedownloade software en authenticatie ontbreken bewust in Git. Herstel hun bestaande installatie/versies uit privébackups en controleer de paden in servicebestanden.

Maak bij een nieuwe installatie privé `data/archive.json` op basis van config/examples/archive.example.json (modus 0600), met eigen URL/token en rip_speed 4. Bewaar data/soloist.env via de bestaande interactieve set-spotify-key.py. Caldera-accountconfiguratie staat onder ~/.config/caldera-music. Geen van deze privébestanden committen.

## DVD-tools herstellen

Behoud of backup `vendor/dvd/usr` apart. Dit bevat Raspbian armhf FFmpeg 7 met dvdvideo-demuxer, ffprobe, lsdvd, libdvdnav/libdvdread en VideoLAN libdvdcss 1.4.3. Een gewone desktop-FFmpeg is geen bewezen vervanging. Bij herstel: gebruik dezelfde vertrouwde Raspbian armhf-pakketten, pak ze met `dpkg-deb -x pakket.deb vendor/dvd` uit, inclusief gedeelde library-afhankelijkheden. Bouw/herstel libdvdcss met prefix voor deze lokale usr-boom. Stel geen globale librarypaden in: dvd.py zet LD_LIBRARY_PATH voor de childprocessen.

Controleer zonder disc `vendor/dvd/usr/bin/ffmpeg -demuxers` op dvdvideo, `ffprobe -version`, `lsdvd --help` en met `ldd` of libraries ontbreken. Test echte decryptie, lange titel, geluid en Nederlandse ondertitels pas op een vrijgegeven drive in een onderhoudsmoment. Exacte package-lock/checksums en een reproduceerbare vendor-build zijn nog niet beschikbaar; behoud daarom de bestaande vendorbackup.

## VPS

Broncode in archive-server/ hoort in /opt/cd-archive. compose.yaml beschrijft de bestaande Docker-netwerken, mounts en reverse-proxy. Pas infrastructuurwaarden bewust aan voor een andere omgeving. Houd .env met ARCHIVE_TOKEN privé. `/data/media/cd-archive`, `/data/media/music` en Plex Preferences.xml blijven bestaande data/configuratie. artwork.py draait via cd-archive-artwork.service buiten de container; server.py en silence.py moeten daarvoor ook beschikbaar blijven. `/opt/plex/plex_api.py` is een bestaande privéhelper: niet overgenomen omdat deze mogelijk toegangsmateriaal bevat en buiten deze servicecode staat. Docker rebuilds, restarts en Plex-wijzigingen zijn niet uitgevoerd.

## Uitrol van de beoordeelde verbeteringen

De Pi-wijzigingen zijn uitgerold; de VPS-wijzigingen zijn alleen in Git voorbereid. Neem bij toekomstige uitrol ook de nieuwe runtime-module state_store.py mee. Installeer de Pi-modules, DVD-module en frontend uit dezelfde commit; start de app via app.py, zodat start_runtime() werkelijk wordt aangeroepen. Import door een willekeurige WSGI-starter start bewust geen workers. Houd één proces als runtime-eigenaar. Rol pas uit wanneer muziek, DVD en imports klaar zijn; laat alle bestaande data en vendor-assets staan.

Backup vóór VPS-uitrol ook de SQLite-database met een consistente SQLite-backup en de bestaande code. initialize() voegt de tabel plex_refresh toe zonder bestaande tracks te herschrijven. Bij rollback kan de vorige versie die extra tabel negeren. Behoud raw-, unmatched- en music-bestanden altijd. Startup controleert maximaal 1000 raw-mappen en een tijdsbudget van 10 seconden tussen bestanden; een reeds begonnen bestandscontrole wordt afgemaakt. Voor een groter archief kan tijdens gepland onderhoud expliciet `python3 -c 'import server; server.initialize(); print(server.reconcile_raw(limit=100000, seconds=3600))'` vanuit /opt/cd-archive worden uitgevoerd. Dit leest en registreert volledige WAVs; het verwijdert niets. Dit commando is tijdens de ontwikkeling niet op de VPS uitgevoerd.

### Derdepartijmanifest

Maak tijdens gepland onderhoud op de Pi een manifest naast de privébackup:

```sh
python3 tools/dependency_manifest.py --root /home/tijmen/cdspeler --caldera /home/tijmen/caldera-music --output /tmp/cdspeler-dependencies.json
```

Het hulpmiddel inventariseert geselecteerde vendor-executables/libraries en distributieversies. Het leest geen accountconfiguratie, start geen driveprobe en overschrijft geen bestaand manifest. Voeg na review herkomst-URL's, pakketversies en buildopties aan de privébackup toe. De exacte huidige hashes zijn niet op de Pi verzameld: dit hulpmiddel levert de voorbereiding, geen claim van een al bewezen schone herinstallatie.

### Netwerkgrens

De Pi-webapp is bedoeld voor het vertrouwde thuis-LAN. X-CDSpeler en Origin-controle zijn bescherming tegen ongewenste browseracties, geen gebruikerslogin. Publiceer poort 8080 niet rechtstreeks op internet. Voor externe bediening is een afzonderlijke beveiligde toegangspoort nodig; de vaste VLC-stream blijft lokaal beschikbaar. De VPS-archiefroute blijft achter bestaande HTTPS/authenticatie en proxy. Geen firewall-, router- of proxyinstellingen zijn tijdens deze wijziging aangepast.
