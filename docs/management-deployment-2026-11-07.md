# Uitrol van de onderhoudsstandaardisatie

Op 7 november 2026 is runtimecommit **01963cf097dbb6836a9b45cd3c91ac0dbe03cb46** via de nieuwe onderhouden tools/deploy op de Pi geplaatst. De broncode- en documentatiehistorie in Git is leidend; dit verslag vervangt geen private herstelbackup.

## Uitgevoerde route

- Eerst een schone commit en lokaal dry-run-plan: 39 allowlisted runtime-/frontend-/catalogus-/hulpmiddelbestanden, geen remote contact of wijziging.
- Read-only inspect bevestigde de service-identiteit en veilige CD-pauzestand. De historische baseline 70eb61f is expliciet op hashes en modi gecontroleerd.
- In tijdelijke Pi-staging: 171 runtime/configuratietests geslaagd. De 46 Git-afhankelijke gereedschapstests zijn op de Mac uitgevoerd; op de Pi is geen Git geïnstalleerd. De volledige Mac-suite telt 217 tests; frontend en twee lokale HTTP-streamingtests slagen.
- Apply met de bestaande unit en vaste MPD: geverifieerde codebackup, alleen webservice stop/start, atomische bestandsvervanging, release-marker en controle van nieuwe endpoints en filehashes.
- Daarna opnieuw twee geïsoleerde echte MPD-tests geslaagd op de nieuwe bronversie: groeiende WAV/seek na unlink en circa drie seconden crossfade. Geen speaker of optische drive gebruikt.

## Eindtoestand

/health en /ready geven ok=true; /api/version meldt commit 01963cf en installed=true. De speler blijft CD, pause, track 13, elapsed 99.105; 25/25 tracks opgeslagen. MPD blijft PID 28787. De eindinspect meldt identity_matches=true en safe=true; er zijn geen nieuwe service-errorindicatoren gevonden.

De private backup op de Pi heet `/home/tijmen/cdspeler/backups/deploy-a1hjo8g4`. Plan, resultaat, verificatie en testlogs staan buiten Git op de Mac onder `backups/management-01963cf/`. De oorspronkelijke privéconfiguratie/backups en binaire installaties blijven behouden. Geen systemd-unit, speakerinstelling, VPS-configuratie of pakketinstallatie gewijzigd.

## Destijds nog afzonderlijk uit te voeren

Deze punten zijn inmiddels uitgevoerd; zie [vervolguitrol](production-rollout-2026-11-07.md). Onderstaande tekst beschrijft de stand bij de oorspronkelijke runtime-uitrol.

De CI-workflow is gepusht; de externe runstatus is vanuit deze sessie niet bevestigd. Verplichte branchchecks zijn niet ingesteld. Waitress/player_server.py is getest en als optionele ingang voorbereid, maar de bestaande app.py-service is niet omgeschakeld. De VPS is niet uitgerold. Het externe private-backup-hulpmiddel is getest met synthetische data; een echte externe bestemming blijft een keuze van de eigenaar. Langdurige fysieke import, hoorbare Bluetooth en Apple-TV-weergave zijn niet opnieuw getest.
