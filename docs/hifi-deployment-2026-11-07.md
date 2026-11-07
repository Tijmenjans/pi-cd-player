# Hifi-interface en automatisch uitwerpen — 7 november 2026

De frontend is geheel vernieuwd volgens design-system.md: warme retro-hifi vormgeving, één zichtbare tracklist, vijf bronnen en toegankelijke desktop-/mobiele bediening. De implementatie van de interface en cd-sessies staat in ebecf2a; de gecontroleerde pauzeovername in 799ccb4. De laatste CSS-afwerking houdt de desktopbediening zichtbaar bij lange albums. De geïnstalleerde volledige release-identiteit staat op /api/version en in de private deploy-result.json.

## Uitrol zonder lopende import te onderbreken

De eerste controle vond een gepauzeerde cd met 24/26 opgeslagen nummers. Er is gewacht totdat alle 26 tracks ready waren. De eerste apply werd daarna vóór wijzigingen geweigerd omdat het huidige gepauzeerde nummer nog een lokale WAV vasthield. Geen force-override gebruikt.

Een afzonderlijk onderhouden hulpmiddel, tools/paused_handoff.py, is toegevoegd met zes offline fout-/hersteltests en een echte geïsoleerde MPD/null-outputproef op de Pi. De eerste synthetische stream miste Accept-Ranges en kon daarom niet seeken; na herstel naar het bestaande appcontract slaagde de proef. De overname gebruikt seekid, houdt pauzestand, positie, opvolger en consume-instelling vast en heeft een private herstelcheckpoint. Geen play, stop, clear of serviceherstart tijdens de overname.

De productie-overname slaagde op track 1 bij exact 11,898 seconden, met behoud van de overige MPD-entries. Private checkpoint: `/home/tijmen/cdspeler/backups/paused-handoff-7xhh_h72`. Daarna is de normale deploymenttool gebruikt met baseline 01963cf en de expliciet ontbrekende nieuwe module cd_session.py.

De eerste geslaagde uitrol plaatste runtime 799ccb4; private codebackup `/home/tijmen/cdspeler/backups/deploy-5zb1ih23`. De opvolgende CSS-afwerking volgt dezelfde onderhouden uitrolroute. Resultaten en hashplannen staan privé op de Mac onder `backups/hifi-ui-20261107/`; geen data, accountinstellingen, vendor, MPD-, Bluetooth- of VPS-configuratie vervangen.

## Controles

- 241 offline regressietests en frontend-DOM-tests op de Mac geslaagd.
- 187 runtime-regressies van de hifi-code op de Pi geslaagd, zonder productieprocessen of optische hardware aan te spreken; de Git-afhankelijke toolingtests zijn op de Mac uitgevoerd. De zes aanvullende handoff-tests slagen afzonderlijk en in de Mac-suite.
- Twee synthetische echte HTTP-streamingtests op loopback geslaagd.
- Browsercontrole op desktop 1440×1000 en telefoon 390×844/320×740: vijf bronnen, lege en uitgeworpen cd, thema’s, focusbehoud, overflow en vrije ruimte onder de laatste track. Ook een lange desktoptracklist met zichtbare transportbediening gecontroleerd. Alle testrequests gebruiken fictieve onderschepte data.
- De echte Pi-interface is daarnaast met geblokkeerde POST-acties bekeken: 26 tracks, geen aparte wachtrij en geen JavaScript-fouten.
- Automatisch uitwerpen is op de echte Pi uitgevoerd: daarna present=true (album), inserted=false en ejected=true, zonder eject-/scanfout. Herhaalde statusmetingen bevestigen dezelfde toestand.
- Track 1 blijft gepauzeerd op 11,898 seconden. Productie-MPD blijft PID 28787. De serveraudio-route geeft HTTP 206, Content-Range en leesbare bytes na uitwerpen. Health/ready zijn true.

Een korte statusovergang tijdens de omschakeling is niet als eindresultaat gebruikt; daarop volgden herhaalde stabiele controles. Er is geen hoorbare Bluetooth-luisterproef gestart en geen nieuwe dvd op Apple TV bekeken. Een volgende fysieke cd-invoer en langdurig afspelen na uitwerpen blijven gebruikers-/hardwarecontroles; de regressies voor nieuwe invoer en trackovergang simuleren die situaties.

## Herstelgrens

Gebruik de onderhouden tools/deploy en de private resultaten. De webunit blijft Waitress gebruiken; MPD wordt niet herstart. Een rollback naar code van vóór cd_session.py wordt tijdens een uitgeworpen albumsessie geweigerd, omdat die versie de fysieke cd nog nodig denkt te hebben. Dat beschermt de behouden afspeelsessie; plan zo’n terugkeer apart en zet geen runtime-data of checkpoints blind terug.
