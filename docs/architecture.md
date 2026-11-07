# Architectuur en gedragscontracten

`app.py` verzorgt Flask, status/acties en coördinatie. POST `/api/action` vereist JSON en `X-CDSpeler: 1`; GET `/api/status` leest de toestand. De frontend bewaakt volgorde van bronklikken en verouderde responses. Licht thema, mobiele donkere modus en kerstmodus op grote schermen zijn bestaande CSS/JS.

CD: `optical_device.py` detecteert de toegankelijke drive via sysfs, ook sr1. `optical_reader.py` beheert een door het childproces geërfde flock-lease, 45 seconden voortgangstimeout en totale deadline. `archive.py` leest één track tegelijk, bewaart herstelstatus, hergebruikt alleen gecontroleerd volledige WAVs en verzorgt uploads met backoff/bevestiging. Kleine leesblokken (8 sectoren), adaptieve snelheid en maximaal drie automatische pogingen voorkomen eindeloze retries. De huidige veilige configuratie is 4x; kopieer geen oude 24x-instelling uit historische documentatie.

`live_audio.py` ondersteunt groeiende WAVs. `archive_queue.py` houdt het huidige lokale bestand vast tot trackwisseling, ook als de serverkopie klaar is. Alleen volgende tracks kiezen de beschikbare serverkopie; decoderherstel bewaart positie. `queueing.py` is een oudere queue-implementatie met eigen tests; de actieve app gebruikt ArchiveQueue.

`disc_media.py`, `music_metadata.py` en `catalogue.py` combineren TOC, CD-Text, MusicBrainz en gecontroleerde catalogusentries. Metadatafouten mogen audio/opslag niet blokkeren. Discogs 29930347 bevat de bevestigde entry voor 50 Hollandse Toppers; de werkelijke TOC-duur van track 16 blijft leidend.

De VPS ontvangt complete WAVs via HTTPS, controleert ontvangst, converteert naar FLAC en publiceert metadata in Plex. `silence.py` behandelt randstilte; `artwork.py` draait afzonderlijk als systeemdienst. Database, mediabestanden en Plex-token blijven buiten Git.

DVD: `dvd.py` beheert één kijker, langste titel, exclusieve reader en stop/eject. `dvd_streaming.py` remuxt met dvdvideo, stream-copy en Nederlandse ondertitels (nl/nld/dut), palet, taalmarkering en defaultselectie. Geen volledige opslag. Tijdens streamen geen achtergrond-driveprobes. Geen ranges/seek of afleveringenkiezer. `dvd_metadata.py` cachet conservatief gematchte publieke IMDb-suggesties; uitval blokkeert afspelen niet. Rank is geen beoordeling.

Vinyl: `vinyl_audio.py` verbindt UFO202 via PipeWire met Bluetooth. `vinyl.py`, `vinyl_transitions.py` en de geïsoleerde ShazamIO-helper herkennen terughoudend op overgangen. Geen match geeft een rustige placeholder. Spotify gebruikt Soloist; Plexamp gebruikt de Caldera-adapter. `bluetooth-connect.py` en timer herstellen speakerverbinding/default sink; het adres is hardwareconfiguratie, geen credential.

## Verbeteringen na de beoordeling

Optische TOC-/CD-Text-probes, CD-reader, eject en DVD-stream delen nu dezelfde lease. CD-Text, eject en DVD-childprocessen erven de descriptor. Een tijdelijke leaseconflict betekent wachten; een aantoonbaar niet te stoppen child blijft een expliciete herstelmelding geven. Geen extra lock nemen binnen een reeds geleasede probe.

Bronwissels en overige enginebediening worden geserialiseerd met transition_lock. De toestandslock beschermt alleen korte snapshots/updates; systemd/MPD-opdrachten houden hem niet vast. Status gebruikt bij bezette enginebediening de laatste snapshot met overgangsstatus, zodat polls niet op een timeout wachten. Stop-, start-, gereedheids- en opslagfouten lopen door dezelfde herstelroute. Fouten tijdens herstel blijven zichtbaar in transition.error; herstel van externe services kan nooit gegarandeerd worden.

Constructie start geen DVD-observer meer. start_runtime() heeft één eigenaar en start alle workers expliciet; stop_runtime() signaleert stoppen en wacht begrensd. Netwerkopdrachten kunnen hun eigen timeout nog afmaken. Er worden geen extra webworkers gestart: die zouden eigen queues/hardware-eigenaars maken. De huidige HTTP-serverimplementaties zijn behouden; vervanging vraagt afzonderlijke deploymentvalidatie van groeiende audio en lange DVD-streams.

Registratie gebeurt in monitor/upload, niet in de lokale reader. Maximaal twee volledige stagingtracks blijven gereserveerd tot bevestigde ontvangst. Bij serveruitval kan de beperkte lokale buffer dus vol raken; dat is zichtbaar en voorkomt onbeperkte schijfgroei. De fallback is 4x, met lagere adaptieve snelheden. Opslag/configuratie- en metricsfouten verbruiken geen optische retry.

De VPS heeft een persistente, samengevoegde Plex-refresh-taak in SQLite met backoff. FLAC-conversie wacht niet op Plex; conversiefouten krijgen een eigen melding. Startup-reconciliatie controleert uitsluitend eigen raw/<cd-id>/<nummer>.wav-bestanden, behoudt ongeldige/onbekende bestanden en herregistreert gevalideerde wezen. Publicatie vereist nu ook een bruikbare artiest; audio zonder voldoende metadata blijft in unmatched en via het archief bereikbaar. Artwork-herstel hergebruikt gecachete Plex-album-ID's pas na verificatie van de werkelijke mediapaden.

Catalogusentries worden afzonderlijk gevalideerd; bevestigde disc_ids krijgen voorrang op lengtematching en blijven zelf aan TOC-lengtes getoetst. Trackduur wordt nooit door Discogs overschreven. state_store.py verzorgt atomische private instellingen; herstel- en queuebestanden worden ook naar opslag gesynchroniseerd.

Bij een nieuwe cd krijgt de onafhankelijke serverstatuscontrole maximaal twee seconden voorsprong vóór de eerste lokale read. Een snel beschikbare archiefkopie voorkomt zo onnodig opnieuw rippen; een trage/onbereikbare server houdt de lokale reader niet gedurende een netwerk-timeout tegen.
