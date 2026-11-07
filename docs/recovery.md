# Herstel zonder dataverlies

Begin alleen-lezen: webstatus en bestaande service-/kernelmeldingen bekijken. Statusmeldingen kunnen persoonlijke metadata bevatten; publiceer geen onbewerkte configuratie of tokens. Geen willekeurige driveprobes tijdens import of dvd-stream.

Bij een mislukte track: laat de overige tracks eerst verwerken. data/archive-recovery.json bewaart pogingen; de UI biedt opnieuw proberen nadat lopende leesopdrachten klaar zijn. Laat volledige lokale WAVs/staging bestaan tot serverontvangst bevestigd is. Een verloren bevestiging vraagt eerst de serverstatus na; upload niet blind opnieuw. Verwijder geen recovery-, skipped- of queuebestanden als generieke oplossing.

Bij driveproblemen onderscheidt de app ontbrekende toegang, USB/Linux-leesproblemen en netwerkproblemen. De drive kan na opnieuw aansluiten sr1 worden; hardcode geen sr0. Bij een oude vastgelopen kernelreader mag geen tweede reader worden gestart. De lock blijft bij het childproces; TERM/KILL kan kernel-I/O niet altijd direct beëindigen. Plan opnieuw aansluiten pas wanneer de gevolgen voor afspelen/import helder zijn.

De systeemreparatie van 7 november staat in deploy/repair-superdrive.sh en is al uitgevoerd. Niet opnieuw draaien als migratiestap. Het script stopt de webservice, wijzigt udev en heeft sudo nodig. Alleen concrete diagnose rechtvaardigt herhaling. Backups staan op de Pi onder backups/superdrive-system-*. deploy/config/60-cdrom_id.rules, 90-apple-superdrive.rules en de wake-unit zijn alleen-lezen vastgelegde geïnstalleerde voorbeelden; de oude projectkopie van de wake-regel was verouderd en is niet als actuele regel behouden. De distributieregels voor andere drives moeten intact blijven.

DVD stoppen/uitwerpen loopt via de app zodat eerst de reader eindigt. De publieke IMDb-interface kan veranderen; een ontbrekende poster is geen reden de videopipeline aan te passen. Geen DVD-upload of staging herstellen.

Bluetooth/vinyl: controleer eerst de bestaande reconnect-timer en PipeWire-links. Een eerdere melding van haperingen is niet definitief door een bufferwijziging verklaard. Wifi-power-saving niet zonder praktijkdiagnose blijvend aanpassen. De historische README bevat oude proefinstellingen en is geen huidig installatievoorschrift.
