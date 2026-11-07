# Deployment en installatiegrenzen

Deze migratie voert geen deployment uit. Productie blijft `/home/tijmen/cdspeler` op Pi 192.168.1.232 (tijmen, armv7l, 32-bit Raspbian 13); VPS via bestaande SSH-alias `hetzner-coolify`. Gebruik bestaande SSH-authenticatie; sleutels horen niet in de repository. Sudo vereist normaal een wachtwoord.

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
