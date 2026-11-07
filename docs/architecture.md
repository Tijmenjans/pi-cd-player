# Architectuur en gedragscontracten

`app.py` verzorgt Flask, status/acties en coördinatie. POST `/api/action` vereist JSON en `X-CDSpeler: 1`; GET `/api/status` leest de toestand. De frontend bewaakt volgorde van bronklikken en verouderde responses. Licht thema, mobiele donkere modus en kerstmodus op grote schermen zijn bestaande CSS/JS.

CD: `optical_device.py` detecteert de toegankelijke drive via sysfs, ook sr1. `optical_reader.py` beheert een door het childproces geërfde flock-lease, 45 seconden voortgangstimeout en totale deadline. `archive.py` leest één track tegelijk, bewaart herstelstatus, hergebruikt alleen gecontroleerd volledige WAVs en verzorgt uploads met backoff/bevestiging. Kleine leesblokken (8 sectoren), adaptieve snelheid en maximaal drie automatische pogingen voorkomen eindeloze retries. De huidige veilige configuratie is 4x; kopieer geen oude 24x-instelling uit historische documentatie.

`live_audio.py` ondersteunt groeiende WAVs. `archive_queue.py` houdt het huidige lokale bestand vast tot trackwisseling, ook als de serverkopie klaar is. Alleen volgende tracks kiezen de beschikbare serverkopie; decoderherstel bewaart positie. `queueing.py` is een oudere queue-implementatie met eigen tests; de actieve app gebruikt ArchiveQueue.

`disc_media.py`, `music_metadata.py` en `catalogue.py` combineren TOC, CD-Text, MusicBrainz en gecontroleerde catalogusentries. Metadatafouten mogen audio/opslag niet blokkeren. Discogs 29930347 bevat de bevestigde entry voor 50 Hollandse Toppers; de werkelijke TOC-duur van track 16 blijft leidend.

De VPS ontvangt complete WAVs via HTTPS, controleert ontvangst, converteert naar FLAC en publiceert metadata in Plex. `silence.py` behandelt randstilte; `artwork.py` draait afzonderlijk als systeemdienst. Database, mediabestanden en Plex-token blijven buiten Git.

DVD: `dvd.py` beheert één kijker, langste titel, exclusieve reader en stop/eject. `dvd_streaming.py` remuxt met dvdvideo, stream-copy en Nederlandse ondertitels (nl/nld/dut), palet, taalmarkering en defaultselectie. Geen volledige opslag. Tijdens streamen geen achtergrond-driveprobes. Geen ranges/seek of afleveringenkiezer. `dvd_metadata.py` cachet conservatief gematchte publieke IMDb-suggesties; uitval blokkeert afspelen niet. Rank is geen beoordeling.

Vinyl: `vinyl_audio.py` verbindt UFO202 via PipeWire met Bluetooth. `vinyl.py`, `vinyl_transitions.py` en de geïsoleerde ShazamIO-helper herkennen terughoudend op overgangen. Geen match geeft een rustige placeholder. Spotify gebruikt Soloist; Plexamp gebruikt de Caldera-adapter. `bluetooth-connect.py` en timer herstellen speakerverbinding/default sink; het adres is hardwareconfiguratie, geen credential.
