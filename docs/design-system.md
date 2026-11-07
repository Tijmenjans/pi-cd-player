# Een rustige luisterkamer

De webapp gebruikt een lokaal onderhouden design system, gebaseerd op de kleur- en componentopbouw van [Radix](https://www.radix-ui.com/themes/docs/theme/color) en de ingetogen ontwerpprincipes van [Dieter Rams bij Vitsœ](https://www.vitsoe.com/us/about/good-design). Het is een eigen vertaling naar gewone HTML/CSS/JavaScript, geen geïnstalleerde Radix/React-interface en geen officiële Braun-interface.

## Vorm en bediening

- Warm Sand-achtig grijs, gebroken wit, donkere inkt en een klein koper-/bronsaccent. Kleurrollen staan als CSS-variabelen bij elkaar; donker en kerst wisselen alleen hun waarden.
- Een rustig serif-letterbeeld voor albumtitels; systeemletters voor bediening en tracknamen. Geen externe fonts, CDN, frontendbuild, nepmeters of technische dashboarddecoratie.
- Desktop/TV heeft twee gelijke kolommen. Links hoes, albuminformatie en bediening; rechts direct de albumtracklist. Andere bronnen krijgen rechts een rustige toelichting. De cover blijft klein genoeg voor de bediening. Bij lange albums blijft het linkerpaneel op grotere schermen in beeld tijdens scrollen.
- Mobiel heeft statusiconen bovenaan, een vaste compacte afspeelbediening en vijf bronknoppen onderaan. Extra onderruimte en safe-area voorkomen dat de laatste track achter de bediening blijft staan.
- Eén zichtbare lijst in albumvolgorde. Geen aparte wachtrij, rondes, herschikken of verwijderen. Vorige/volgende, trackkeuze en willekeurige volgorde blijven gewone afspeelbediening. De interne ArchiveQueue blijft noodzakelijk voor buffering, pinning, decoderherstel en de volgende track; de publieke queue-order/queue-skip-acties worden geweigerd.
- Echte knoppen, zichtbare focus, pijltjestoetsnavigatie en focusbehoud bij statusupdates. Schuifbediening heeft op mobiel een 44px-aanraakvlak. Herstelmeldingen en albumuitgavekeuze blijven bereikbaar.
- Alle vijf bronnen blijven aanwezig. Vinyl blijft rustig zonder herkenning. DVD behoudt remux, poster, taal-/ondertitelinformatie en het streamadres; geen DVD-archivering. Licht, mobiel donker en de kerstmodus op grotere schermen blijven beschikbaar.

## Cd uitwerpen terwijl het album blijft spelen

Fysieke aanwezigheid en het actieve album zijn afzonderlijk: `disc.present` betekent een beschikbaar album; `inserted=false` / `ejected=true` betekenen dat de fysieke cd eruit is. Status, tracklist en bediening blijven daarna werken.

Automatisch uitwerpen gebeurt uitsluitend bij CD als iedere track van precies die cd door het archief als ready is bevestigd, er geen overgeslagen/geblokkeerde tracks of opslagfouten zijn en de optische reader vrij is. De bestaande optical-lock wordt geërfd door eject; de fysieke cd-ID wordt eerst gecontroleerd. Een nieuwe poging volgt niet iedere halve seconde na een echte ejectfout. De bestaande onderhoudslease sluit automatisch uitwerpen tijdens deployment uit.

Uitwerpen voert geen MPD stop/clear uit en roept archive.cancel niet aan. Een lopende lokale WAV blijft gepind; na de track kiest de afspeellogica een beschikbare serverkopie. De reader begint geen nieuwe leesopdracht voor een uitgeworpen album. Een nieuw herkende cd vervangt het oude album; ook herinvoer van dezelfde cd wordt als nieuwe invoer behandeld.

Handmatig uitwerpen kan ook vóór volledige opslag, mits de reader vrij en de gepinde lokale WAV volledig is. Een groeiende WAV wordt niet afgebroken. Na een bevestigde serverinventaris worden nog niet bewaarde/afspeelbare nummers expliciet onbeschikbaar; volledige lokale bestanden en uploads blijven behouden. Albuminformatie of een mislukte metadatazoekactie verhindert veilig opslaan en afspelen niet. Server-ready betekent opgeslagen en afspeelbaar, niet noodzakelijk dat Plex al klaar is met metadata-indexering.

Een verloren bevestiging van de eject-opdracht stopt de stream niet. De sessie blijft behouden totdat een volgende scan bevestigt of de cd nog aanwezig is. Een mediarevisie voorkomt dat oudere scanresultaten of fouten die sessie ongedaan maken. Herhaald handmatig uitwerpen tijdens onzekerheid meldt expliciet dat bevestiging nog ontbreekt.

De uitgeworpen albumsessie wordt privé onder `data/cd-session.json` bewaard en begrensd/gevalideerd teruggelezen na een webprocesherstart. Dit is geen vervanging voor de serverbackup. Het bestand staat buiten Git en wordt bij nieuwe cd-invoer verwijderd.

## Verificatie

`make check` draait de offline regressies en DOM-tests; `make check-http` test synthetische HTTP-streaming op loopback. De cd-sessietests simuleren de drive en controleren onder andere volledigheid, verkeerde cd, lokale pin, doorlopen na eject, verloren bevestiging, oude scans en handmatig uitwerpen. Ze bedienen geen hardware.

Optionele echte browsercontrole met uitsluitend onderschepte fictieve data:

```sh
npm install --prefix /tmp/pi-player-browser playwright@1.65.0
NODE_PATH=/tmp/pi-player-browser/node_modules \
  BROWSER_EXECUTABLE='/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' \
  node tests/browser/check-ui.cjs
```

Gebruik een eigen geïnstalleerde Chromium-browser via BROWSER_EXECUTABLE of de standaard Playwright-browser als die beschikbaar is. Dit zijn ontwikkeltools buiten het project, geen appafhankelijkheden. Alle HTTP-verzoeken worden onderschept; er wordt geen Pi/VPS of externe coverbron benaderd. De controle omvat desktop 1440×1000 en telefoons 390×844 en 320×740, vijf bronnen, lege/uitgeworpen cd, focus, horizontale overflow en themawisseling. Screenshots staan standaard in de genegeerde `.local/ui-checks/`.

Fysieke eject, een echte nieuwe cd-invoer, langdurig afspelen, Bluetooth en DVD op Apple TV vereisen afzonderlijke praktijkcontrole. Een browser-/unittestuitslag bewijst die niet.

Terugrollen naar een versie van vóór cd_session.py is tijdens een uitgeworpen albumsessie bewust geweigerd: die oudere code kent alleen fysieke aanwezigheid. Gebruik een sessiecompatibele versie, of plan afzonderlijk herstel nadat het album is afgelopen en de fysieke media-/sessietoestand bewust is afgehandeld. Er wordt nooit automatisch muziek gestart, gestopt of een cd opnieuw geplaatst om rollback mogelijk te maken.

## Kersteditie

De kerstmodus op grote schermen combineert dennengroen, bordeaux, champagnegoud en warm gebroken wit. De bestaande haardfoto blijft zichtbaar achter een matte laag; album- en trackpanelen hebben voldoende dekking voor rustige tekst. Een gouden afspeelknop, fijne randen en een kleine groet maken het geheel feestelijk zonder technische decoratie.

Kerstgimmicks: warme lichtjes bovenaan, zestien langzaam vallende sneeuwvlokjes en “Een plaatje bij de haard.” De sterknop schakelt lichtjes en sneeuw gezamenlijk aan/uit; de voorkeur wordt lokaal bewaard en tussen tabbladen bijgewerkt. Er is geen geluidseffect en de decoratie vangt geen klikken. Sneeuw gebruikt alleen CSS-transform/opacity, geen JavaScript-lus; bij prefers-reduced-motion valt de sneeuw volledig weg. Op telefoons blijft donkere modus gewoon donker.

De browsercontrole test de kerstknop, opgeslagen effectvoorkeur, zestien vlokken, minder beweging, doorklikbare decoratie en terugschakelen naar mobiel donker. Screenshots gebruiken fictieve media. Alleen de static-bestanden worden via tools/deploy assets bijgewerkt; daarvoor hoeven webservice en MPD niet te herstarten.

De haard heeft een nauwere uitsnede, langzaam bewegende fotolagen en fluctuerende vuurgloed. Het is een CSS-animatie van de lokale haardfoto, geen vuurvideo; er wordt geen extra media- of audiostream gestart. De sneeuwvlokken variëren van 5 tot 11 pixels. De sterknop stopt ook de haardanimaties; minder beweging maakt de haard volledig statisch.
