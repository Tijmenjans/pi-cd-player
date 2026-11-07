# Cd-herkenning en USB-herstel — 7 november 2026

## Huidige cd

Barcode 5032044076128 hoort bij Bing Crosby, White Christmas, Planet Song 7612, Duitsland 2002, Discogs [1685005](https://www.discogs.com/release/1685005). De primaire release-API is gecontroleerd op barcode, volgorde, alle 14 tracks en alle gemeten TOC-lengtes; elke duur verschilt minder dan 1,5 seconde. De echte sectors/75 blijven leidend, ook in de nieuwe gecontroleerde catalogusentry.

Cd-ID: `olA1yZXd23ieopV4fnqmhg7y.Uk-`. TOC: `1 14 179001 150 11947 26255 39969 50308 63263 76392 88028 100132 113808 126453 138733 151745 165504`. CD-Text ontbreekt en deze cd heeft geen datatrack met coverbestanden. Een winkel vermeldde bij dezelfde barcode 17 tracks van een andere uitgave. Daarom is een barcode alleen nooit voldoende voor automatische overname.

De juiste metadata is zonder audioactie in de bestaande private cache en het VPS-manifest gezet, met een backup onder `/home/tijmen/cdspeler/backups/metadata-5_vcaxmr`. De bestaande app kan daardoor titel en tracknamen meteen uit de archiefstatus tonen. Dit repareert geen USB-fout en markeert geen onvolledige audio als opgeslagen.

## Herkenning verbeteren

Bij een onbekend album biedt de nieuwe interface een barcodeveld en opnieuw zoeken. Barcodevalidatie controleert EAN/UPC-lengte en controlecijfer. Het verzoek is aan de actuele cd-ID gebonden; een oud scherm kan een nieuw geplaatste cd niet overschrijven. De gekozen barcode blijft privé gekoppeld aan de TOC. De interface toont deze functie alleen als de backend de capability meldt.

Eerst worden gecontroleerde lokale entries gebruikt. Daarna zoekt de [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API) maximaal vijf barcodekandidaten op, met de bestaande begrensde, geserialiseerde metadataworker. Een kandidaat moet ook hetzelfde aantal tracks én alle gemeten duren binnen de bestaande marge hebben. Meerdere passende uitgaven blijven een keuze; onbekende of afwijkende tracks worden niet willekeurig ingevuld. Een nieuw lokaal catalogusresultaat krijgt ook voorrang op een recente negatieve zoekcache.

Netwerkfouten blijven herhaalbaar via de bestaande backoff. De barcode is geen garantie dat MusicBrainz de specifieke persing bevat. De oorspronkelijke cd-ID/TOC-zoekroute, CD-Text en lokale catalogus blijven beschikbaar. Een herstelde, uitgeworpen albumsessie laadt zijn metadata opnieuw uit cache/catalogus.

## USB is een afzonderlijk probleem

Alleen-lezen inspectie vond herhaalde SuperDrive-resets en een dwc_otg scatterlist error -121, met cdparanoia in kernelstatus D/blk_execute_rq. Er werd geen concurrerend cdrom_id-proces gevonden. Na het door de eigenaar opnieuw aansluiten van uitsluitend de SuperDrive hervatte het lezen. Rechten, services, udevregels en herstelinstallaties zijn niet aangepast. Kabel, hub, voeding en drive blijven mogelijke oorzaken; de inspectie onderscheidt die niet definitief.

De nieuwe drivebreker bewaart een blokkade in archive-recovery.json na watchdogstagnatie op twee verschillende tracks of een niet beëindigbare reader. Hij wordt niet stilletjes bij de volgende track gewist. Gewone leesfouten behouden hun maximum van drie pogingen per track; een defect nummer hoeft dus niet de hele import stil te leggen.

Tijdens een driveblokkade blijven gecontroleerd volledige bestaande WAVs en reeds ingeplande uploads doorstromen; er start alleen geen nieuwe optische read. Een gecachte WAV bewijst geen driveherstel en wist de watchdoghistorie niet. Alleen een echte succesvolle read of een expliciete herstelactie kan die historie wissen. De bestaande geërfde flock, 45s-watchdog, totale deadline, veilige snelheid, lokale pinning en uploadbevestiging blijven behouden.

Opnieuw proberen vereist dat geen reader/lease/legacy-reader meer actief is en de drive volgens sysfs/toegangscontrole bereikbaar is. Eerst wordt het nieuwe herstelcheckpoint duurzaam geschreven; pas daarna wordt de blokkade in geheugen vrijgegeven. Een schrijffout kan de reader niet onbedoeld weer starten. De webknop verschijnt bij een blokkade pas als de reader expliciet inactief is. Dit is een herstelverzoek, geen garantie dat de USB-hardware daarna stabiel blijft.

## Tests en uitrolgrens

Regressies simuleren barcodefouten, verkeerde trackaantallen en duren, de gecontroleerde huidige cd, negatieve cache, verouderde schermen, herstelde sessies, verschillende watchdogtracks, blijvende blokkade, WAV-hergebruik/upload tijdens blokkade en een falende herstelwrite. De browsercontrole test het barcodeformulier zonder een echte disc of externe metadata-aanvraag.

De softwarewijzigingen worden pas met gewone tools/deploy geïnstalleerd wanneer de speler veilig gepauzeerd/gestopt is en alle importtracks gereed zijn. De live metadatareparatie en de al geplaatste geluidloze haardvideo vereisten geen herstart. Lopende imports worden niet gestopt om een runtime-uitrol af te dwingen.

Controle tijdens herstel: na het opnieuw aansluiten liepen uitlezen en opslag weer op; 12/14 tracks waren gereed voordat de twee eerdere blokkades via de bestaande API opnieuw zijn vrijgegeven. De albumhoes is afzonderlijk gecachet, zonder audioactie. De uiteindelijke uitrol-/eindcontrole wordt privé naast het deploymentresultaat vastgelegd.
