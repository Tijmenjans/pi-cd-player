# Vinyl via IKEA Bluetooth-speaker

Huidige status van de audiostabiliteit: de gebruiker meldt opnieuw korte haperingen. Ook een openbaar lokaal muziekbestand dat rechtstreeks via pw-play naar de VAPPEBY ging, haperde; vinyl-doorvoer en Shazam zijn daarmee niet de enige mogelijke oorzaak. Wifi gebruikt 2,4 GHz en power saving staat aan. Het uitschakelen daarvan is nog niet getest: de Pi weigert de wijziging zonder beheerdersrechten. De tijdelijke bestandstest is gestopt en vinyl plus automatische herkenning zijn hersteld. De hieronder beschreven bufferwijziging is dus geen bevestigd definitief herstel.

Volgende tijdelijke beheerderstest op de Pi: `sudo /usr/sbin/iw dev wlan0 set power_save off`. Pas na een luistertest beslissen of dit blijvend moet worden ingesteld.

Geïnstalleerd op de Raspberry Pi `cdspeler` op 31 oktober 2026.
Webapp: http://192.168.1.232:8080

Kies Vinyl om de UFO202-ingang in stereo door te geven naar de gekoppelde IKEA VAPPEBY 20 gen 3. Regel het volume op de speaker. Kies CD of Streaming om de vinyl-doorvoer te stoppen. Herken nummer en Automatisch herkennen gebruiken dezelfde gedeelde PipeWire-ingang en kunnen tijdens het luisteren actief blijven.

De gebruikersdienst `cdspeler-vinyl.service` wordt door de bronkeuze in de webapp gestart en gestopt. `vinyl_audio.py` zoekt de USB-ingang en de specifieke gekoppelde speaker, bewaakt beide audioverbindingen en probeert opnieuw te verbinden als de speaker verdwijnt. De status wordt in `data/vinyl-output.json` gepubliceerd en in de webapp getoond. Doorvoer valt niet automatisch terug op een andere uitgang.

ShazamIO blijft in de bestaande `.venv-vinyl`-omgeving draaien. De opname gebruikt nu `pw-record` in plaats van rechtstreeks de exclusieve ALSA-ingang. De systeemstandaard voor andere audio-uitgangen is niet aangepast.

Bij de installatie bleek een bestaande Bluetooth-verbinding stil te blijven ondanks actieve audioverbindingen. Opnieuw verbinden herstelde de weergave. De gebruiker bevestigde daarna zowel de testtoon als de plaat via de VAPPEBY. Het Pi-speakervolume is voor de test op 60% gezet.

Verificatie: 35 Python-tests voor vinyl, doorvoer, API, streaming en cd-archief; JavaScript-weergavecontroles; een gelijktijdige gedeelde stereo-opname van ruim 12 seconden bij circa -28 dBFS. De muziekweergave is door de gebruiker bevestigd. Een live Shazam-aanvraag tijdens de Bluetooth-doorvoer eindigde zonder match, terwijl de audiobrug onafgebroken actief bleef. Automatische herkenning is daarna weer ingeschakeld.

Back-up van de gewijzigde bestaande bestanden op de Pi:
`/home/tijmen/cdspeler/backups/vinyl-bluetooth-before-20261031-100013.tar.gz`

Terugzetten: stop eerst de gebruikersdienst cdspeler-vinyl en de webdienst cdspeler-web, herstel de back-up in /home/tijmen/cdspeler en start de webdienst opnieuw. De nieuw toegevoegde, niet ingeschakelde gebruikersdienst en helper mogen aanwezig blijven; de eerdere webapp start deze niet. De oude versie nam rechtstreeks via ALSA op en bood nog geen muziekdoorvoer.

Dit archief bevat de gewijzigde modules, webbestanden en controles voor de bestaande app; het is geen volledige vervanging van alle overige appmodules en privéconfiguratie. `deploy.py` is het bij deze update gebruikte script en controleert de hashes van de toenmalige bestanden. Het is geen algemene herinstallatieopdracht voor inmiddels gewijzigde broncode.

## Herstel van vinylherkenning — 31 oktober 2026

De eerste versie verwierp matches zodra tempo- of frequentieafwijking groter dan 1% was. De echte opname van Taylor Swift — All You Had To Do Was Stay werd door ShazamIO correct herkend met ongeveer 2,1% afwijking, maar de app filterde deze match weg. De bovengrens is verhoogd naar 5%; de controle op stilte, ontbrekende kwaliteitsvelden, niet-eindige waarden en extreem afwijkende matches blijft bestaan. Normaliseren, losse stereokanalen en de alternatieve ShazamIO-methode gaven op hetzelfde fragment dezelfde correcte titel.

Twaalf gerichte vinyl- en API-tests zijn geslaagd, inclusief een regressietest met deze echte match. De audiobrug blijft tijdens de herstart en herkenning actief. Back-up van de twee gewijzigde bestanden: `/home/tijmen/cdspeler/backups/shazam-filter-before-20261031-100448/`.

Live bevestigd na de correctie: de webapp herkende Taylor Swift — Shake It Off (Taylor's Version), album 1989 (Taylor's Version), inclusief hoes. Automatische herkenning en Bluetooth-weergave bleven beide actief. De tijdelijke diagnose-opnamen zijn verwijderd.

## Herkennen op overgangen — 31 oktober 2026

Automatische herkenning gebruikt nu een lokale gedeelde volumemeter via PipeWire (8 kHz mono). Na de eerste herkenning volgt een nieuwe zoekactie pas na een aanhoudende zachte/stille periode van circa 1,25 seconde en minimaal 1 seconde teruggekeerde muziek. De grens volgt het normale muziekniveau; korte dips en ontbrekende audiosamples tellen niet als overgang. Een herkend nummer blijft staan, ook langer dan 90 seconden.

De instelling **Minimaal tussen zoekacties** accepteert 20–600 seconden en staat standaard op 60 seconden. Deze waarde wordt bewaard in `data/vinyl-settings.json`. Bij geen match volgen maximaal twee herkansingen op dat interval; daarna wordt op een volgende overgang gewacht. Herken nummer blijft handmatig beschikbaar, ook bij doorlopende muziek zonder pauze. De volumemeter verstuurt geen Shazam-aanvragen; pas de overgangstrigger of een begrensde herkansing doet dat.

Verificatie van deze wijziging: 44 Python-tests voor de detector, begrensde herkansingen, instellingen, API en bestaande afspeelfuncties; JavaScript-weergavecontroles; echte lokale volumemetingen op de UFO202. Back-up: `/home/tijmen/cdspeler/backups/vinyl-transitions-before-20261031-101144.tar.gz`. Terugzetten herstelt de eerdere periodieke herkenning.

Live controle na installatie: Taylor Swift — Blank Space (Taylor's Version) werd herkend; de app bleef daarna in de stand “Wacht op een stille overgang tussen nummers.” met hetzelfde herkenningstijdstip. Bluetooth bleef spelen. De live intervalinstelling is op 90 seconden gezet, teruggelezen en weer op de standaard van 60 seconden gezet.

## Audiobuffering — 31 oktober 2026

Naar aanleiding van incidentele onderbrekingen is de vinyl-doorvoer op 48 kHz vastgezet, met 100 ms gevraagde streamlatentie en 200 ms extra doorvoerbuffer. De actieve route vergrendelt de graph-rate en quantum zodat opnameclients deze niet automatisch wijzigen. Deze instellingen gelden voor de vinylbrug; andere muziekbronnen behouden hun eigen instellingen zodra de brug stopt.

De Pi meldde geen onderspanning, herstarts of PipeWire-fouten. De uitval bleef volgens de gebruiker ook aanwezig met de automatische herkenning en volumemeter uitgeschakeld. Daarom is niet vastgesteld dat de volumemeter de oorzaak is. De eerste technische controle na de bufferwijziging toont lopende stereostromen op 48 kHz en nul PipeWire-fouten.

Back-up van de eerdere helper: `/home/tijmen/cdspeler/backups/vinyl-audio-before-buffer-20261031-102118.py`. De twee bestaande tests voor selectie van de juiste speaker en controle van de actieve audiolinks zijn geslaagd.

De gebruiker bevestigde na de bufferwijziging dat de muziek stabiel was. Daarna zijn de automatische overgangsherkenning en de volumemeter weer ingeschakeld voor een gecombineerde controle.

Gecombineerde live controle geslaagd: Shazam herkende All You Had To Do Was Stay terwijl de meter actief was. De audiobrug behield dezelfde actieve nodes, USB-ingang en Bluetooth-uitgang bleven op 48 kHz en alle getoonde PipeWire-fouttellers bleven nul. De automatische overgangsherkenning staat weer aan.

## CD-leessnelheid en overgang naar de server — 31 oktober 2026

De gevraagde leessnelheid is teruggezet op 24×, de hoogste eerder geteste instelling. De configuratie wordt per nieuwe track opnieuw gelezen. De actieve cdparanoia-opdracht is gecontroleerd en bevat -S 24. De daadwerkelijk behaalde snelheid hangt af van disc en drive; de eerdere 24×-test haalde circa 3,7× effectief.

Een geselecteerde lokale WAV blijft gedurende de hele track vastgehouden wanneer de serverkopie gereed komt. Pas voor een opvolgende track wordt de server gekozen als die track gereed is; anders gebruikt de app de lokale Pi-buffer. Het vooraf klaarzetten van een servertrack maakt de lokale bron van het huidige nummer niet vrij. Een decoderherstel bewaart de laatst bekende afspeelpositie en herlaadt de vastgehouden bron met een seek naar die positie.

Verificatie: 20 geslaagde controles, inclusief drie regressietests voor huidige-lokale-track/serverklaar, volgende track nog lokaal en decoderherstel op positie, plus geïsoleerde echte MPD-tests voor groeiende lokale audio, seek na unlink en crossfade. Na installatie speelt track 3 via de server zonder fout en met behouden afspeelpositie; de actieve lezer vraagt 24× aan. Back-up: `/home/tijmen/cdspeler/backups/cd-handoff-before-20261031-152913/`. Die map bevat ook de privéconfiguratie; deze wordt niet in dit archief gedeeld.

## Rustige tv-weergave — 31 oktober 2026

De luisterweergave gebruikt op brede schermen twee kolommen: grote hoes links, informatie en bediening rechts. Op een telefoon stapelt de indeling. Bedieningsknoppen zijn groter en pijltoetsen verplaatsen de focus tussen zichtbare knoppen.

Vinyl toont bij een gevonden nummer alleen titel, artiest, album en hoes. Tijdens luisteren, zoeken, stilte, geen match of een herkenningsfout blijft een rustige standaardweergave met getekende plaat staan. Zoekmeldingen, technische meetgegevens, geschiedenis en vinyl-invulvelden zijn verwijderd. Herkenning wordt op de achtergrond ingeschakeld bij het openen van de vinylweergave; de bestaande overgangstrigger en het ingestelde interval blijven behouden. De speakernaam is verborgen bij alle bronnen; het Bluetooth-icoon blijft staan.

Alleen statische webbestanden zijn vervangen; de backend en muziekweergave zijn niet herstart. De standaardweergave en de live herkende vinylweergave zijn visueel in Safari gecontroleerd. Rendercontroles omvatten luisteren, herkennen, geen match, stilte, fout, gevonden nummer, overgang, CD en Streaming. Back-up: `/home/tijmen/cdspeler/backups/tv-view-before-20261031-172321.tar.gz`.

## Bronwissels — 31 oktober 2026

Snelle bronklikken werden voorheen genegeerd zolang een andere opdracht bezig was. De webapp onthoudt nu de laatste bronkeuze en voert die na de lopende opdracht uit. Ook terugklikken naar de nog getoonde bron terwijl een andere bron geladen wordt, blijft behouden. Twee gerichte asynchrone controles met vertraagde bronopdrachten zijn geslaagd. De echte CD→Vinyl-wissel is via de API getest en beide stereolinks kwamen actief; de gebruiker bevestigde hoorbare vinylmuziek. Back-up: `/home/tijmen/cdspeler/backups/source-switch-before-20261031-203153/`.

## Compactere hoes — 31 oktober 2026

De hoes gebruikt op brede schermen maximaal 400 px en schaalt mee tot 42% van de schermhoogte; op lage schermen geldt een kleinere grens. Op mobiel is de hoes maximaal 160 px en 20% van de schermhoogte. Tussenruimtes, kopgroottes en de positionering van de wachtrij zijn overeenkomstig compacter gemaakt. De CD-weergave is live in Safari gecontroleerd met bronkeuze, informatie, bediening en wachtrij zichtbaar. De audiobackend is niet herstart.

## DVD rechtstreeks naar VLC — 1 november 2026

De DVD-weergave is uitsluitend voor lokaal streamen naar VLC op Apple TV. Er is geen dvd-import naar Plex, geen DVD-upload-API en geen tijdelijke dvd-staging meer. Circa 6,67 GB aan bronbestanden en de test-MKV-bestanden zijn op verzoek van de gebruiker van de Pi verwijderd. De lege Films-sectie en lege DVD-mappen op de server zijn verwijderd. De bestaande muziek-/CD-archivering en Plexamp blijven behouden.

Open in VLC als netwerkstream: `http://192.168.1.232:8080/dvd/live.mkv`. De oude `.mpg`-URL is een alias naar dezelfde MKV-stream. FFmpeg leest met de dvdvideo-demuxer de langste titel en kopieert beeld en alle audiotracks, zonder encoding. De eerste Nederlandse ondertitel (`nl`, `dut` of `nld`) wordt met taalmarkering en palet als standaardspoor meegestuurd. Zonder Nederlandse ondertitels toont de webapp dit expliciet. Er is geen automatische vertaling. Vooruitspoelen/HTTP-ranges en een afleveringenkiezer zijn nog niet ondersteund.

De webapp toont titel, hoofdfilmduur, gesproken talen, Nederlandse ondertitelstatus, resolutie en beeldverhouding. Het streamadres wordt als rustige tekst getoond; de kopieerknop is verwijderd. DVD uitwerpen en Stop stream gebruiken dezelfde transporticonen als de CD-weergave. Stop stream sluit de fysieke reader. DVD uitwerpen stopt de stream, wacht tot de optische drive vrij is en werpt uit. Er is maar één VLC-kijker tegelijk toegestaan. Een sessietoken voorkomt dat het opruimen van een oude HTTP-verbinding een nieuwere stream stopt. De achtergrondprobe zoekt niet op de dvd terwijl VLC kijkt.

Pi-tools: lsdvd en FFmpeg 7 uit officiële Raspbian-pakketten onder `vendor/dvd/usr`, plus VideoLAN libdvdcss 1.4.3 onder dezelfde prefix. De binaries staan niet in dit broncodearchief. Er is geen rootinstallatie nodig. FFmpeg gebruikt libdvdnav en libdvdread voor hoofdstuk- en ondertitelinformatie.

Validatie: zes tests voor duur/talen, ontbrekende ondertitels, exclusieve reader, oude sessie-opruiming, uitwerpen met actieve stream en foutafhandeling. Frontendtests voor DVD-details en uitwerpknop, naast CD/Vinyl/streaming en bronkeuzeregressie. De live Pi toont 6650 seconden, 720x576, Engels/Frans/Italiaans en Nederlands voor MARLEY AND ME; MKV-stream en stopcommando op echte dvd getest. De uitwerpactie is met een gesimuleerd drivecommando getest; de geplaatste dvd is bij oplevering niet fysiek uitgeworpen. VLC-weergave en Nederlandse ondertitels zijn eerder door de gebruiker op Apple TV bevestigd.

### Cover en filmgegevens

De DVD-weergave haalt op de achtergrond een filmposter, titel, jaartal en hoofdrolspelers uit de publieke IMDb-suggestieresultaten. Een IMDb-link staat bij de film. Geen API-sleutel nodig. De dvd-identiteit, label en speelduur vormen een cachesleutel; gegevens en kleine posters staan onder `data/dvd-metadata`, zonder volledige dvd-video op te slaan. De statussen “VLC op Apple TV” en “Klaar om te kijken op je Apple TV” zijn verwijderd.

Alleen exacte genormaliseerde titelmatches worden gebruikt; een jaartal in het dvd-label kan remakes onderscheiden. Ambigue resultaten en vervolgdelen worden niet willekeurig gekozen. Bij geen match blijft de gewone dvd-placeholder staan. De IMDb-rank is géén beoordeling en wordt niet als cijfer getoond. Beschrijving en IMDb-score worden niet opgehaald omdat de publieke filmpagina daarvoor geen bruikbare respons geeft. Cache: 30 dagen voor treffers, één dag voor geen match, vijf minuten bij netwerkfouten.

Validatie: zes gerichte matchingtests, bestaande DVD-/frontendtests, echte IMDb-ophaling van Marley & Me (2008), Owen Wilson/Jennifer Aniston, poster HTTP 200 (53 kB), en zichtbare weergave in Safari.

## 50 Hollandse Toppers — 3 november 2026

CD-ID XsvEEE9UjniOj_MDfNBwpdI9UDA- gekoppeld aan Discogs 29930347, barcode 886971698824, cd 1 van 3, 2008. Alle 17 titels/artiesten en de voorkant zijn bevestigd en op Pi/server opgeslagen. Shazam bevestigde Maak Me Gek — Gerard Joling en Slavenkoor — Assekruus. Bij track 16 bevat Discogs een afwijkende duur; de werkelijk gemeten TOC-lengte en audio blijven behouden. De catalogusentry bevat deze correctie voor betrouwbare toekomstige herkenning. De server heeft alle 17 bestaande tracks in Plex van labels voorzien. Geen herstart van de speler uitgevoerd. De webapp neemt bevestigde servermetadata en de bestaande cover over wanneer de lokale zoekstatus nog onbekend was.

## Betrouwbaardere CD-import — 7 november 2026

Werkelijke fout bij E87tXp1KRvbzoe4YQWn6PebonrE- (The Greatest Christmas Collection, cd 3): de Pi-USB-driver meldde herhaalde resets/scatterlistfouten, cdparanoia hing in kernel-I/O, udev startte daarnaast langdurig blokkerende `cdrom_id --lock-media`-probes. Na opnieuw aansluiten heette de drive sr1 in plaats van sr0 en stond deze tijdelijk als root-only geregistreerd. Geen onderspanning en geen volle opslag. De server was gezond.

De import heeft nu een watchdog op werkelijk groeiende bytes (45 seconden stilstand), een begrensde totale leespoging, kleinere leesblokken van 8 sectoren en adaptieve snelheid. Deze drive is gestart met een 4x-limiet; bij fouten wordt verder teruggeschakeld. Per track maximaal drie automatische pogingen, bewaard in `data/archive-recovery.json`; daarna expliciet 'wacht op herstel'. De overige tracks worden eerst verwerkt en de afspeelwachtrij blijft niet eindeloos bufferen op zo'n track. De webapp biedt opnieuw proberen als de overige leesopdrachten klaar zijn. Handmatig overgeslagen tracks blijven overgeslagen.

Een flock-lease blijft bij de child-reader open. Daardoor kan ook na een webserviceherstart geen tweede lezer starten terwijl een eerdere kernelopdracht nog bestaat. Stoppen gebruikt begrensde TERM/KILL-wachttijden; als de kernel niet loslaat meldt de app dat USB opnieuw aangesloten moet worden. `optical_device.py` vindt de verbonden SuperDrive via sysfs, inclusief wisseling sr0/sr1, en onderscheidt ontbrekende toegang van een ontbrekende cd. CD-tekst, eject en DVD gebruiken dezelfde detectie.

Uploads hebben kortere sockettimeouts, een totale tijdslimiet, bevestiging vóór verwijderen en herstel met backoff. Een mislukte upload gaat terug in de wachtrij zodat andere uploads voorrang kunnen krijgen; volledige WAV-bestanden en stagingplaatsen blijven bewaard. Na een verloren bevestiging wordt eerst nagevraagd of het bestand al is ontvangen. Bij herstart worden volledige WAV-bestanden gecontroleerd en hergebruikt; afgebroken WAV-bestanden (ook met een geldige maar misleidende header) worden niet geüpload. USB-/leesfouten worden niet meer als serverproblemen gemeld en verdwijnen niet door een succesvolle statuspoll.

Eenmalige systeemcorrectie is met gebruiker-sudo uitgevoerd via `repair-superdrive.sh`. Deze maakt backups, hergebruikt de distributieregels voor alle andere drives, slaat uitsluitend bij Apple 05ac:1500 de concurrerende udev-mediumprobe over, zet cdrom-groeprechten en verplaatst de wake-opdracht naar een begrensde systemd-oneshot. De vastgelopen udev-daemon is herstart en reageert weer binnen de controletimeout. Oude regels/backups staan op de Pi onder `backups/superdrive-system-*`. `cdspeler-web-stop-timeout.conf` staat als user-service drop-in onder `~/.config/systemd/user/cdspeler-web.service.d/stop-timeout.conf`.

Validatie: 35 import-, watchdog-, proces-, upload-, herstel-, drivewissel- en afspeeltests, waaronder echte child-process/lock- en vastgelopen-procesproeven; dezelfde 35 slagen op de Pi. Daarnaast 6 DVD- en 7 CD-teksttests slagen lokaal na de drivewijziging; frontendtests voor de herstelmelding en knop naast de bestaande mediaweergaven slagen. Praktijk: na herstel ging de huidige cd van 8 naar 10 opgeslagen tracks; tracks 12 en 13 zijn volledig verwerkt en track 14 staat op 67%, zonder nieuwe USB-resetstorm. De rest van de 25 tracks was bij oplevering nog bezig: geen garantie afgegeven dat de hele cd al voltooid was.
