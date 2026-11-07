# Pi-uitrol — 7 november 2026

De Pi-runtime is bijgewerkt naar commit **70eb61f3eb78510ca9c161799fd7c97883033776**, inclusief de betrouwbaarheidsverbeteringen van 4ba146a. De VPS is niet gewijzigd; Plex-refresh/crashherstel op de VPS wacht nog op een afzonderlijke uitrol.

## Uitvoering

Vooraf was CD actief maar gepauzeerd: track 13 op 99,105 seconden, 25/25 tracks opgeslagen, geen reader/upload/DVD-stream. De bestaande Pi-bronnen kwamen overeen met de historische overname. De release is afzonderlijk gestaged; native Flask/libdiscid/websocket-imports en 151 geïsoleerde regressietests slaagden op de Pi.

Een geïsoleerde MPD met null-output bevestigde eerst dat seekid naar een vervangende stream de pauzestand en afspeelpositie behoudt. De gepauzeerde lokale track is vervolgens overgezet naar de reeds opgeslagen serverkopie, zodat een verlopen lokaal streamtoken geen probleem oplevert na de webserviceherstart. De track is niet hoorbaar gestart als onderdeel van deze procedure.

Daarna zijn 33 expliciet geselecteerde Python-/frontend-/catalogus-/hulpmiddelbestanden geplaatst. Alleen cdspeler-web is gestopt en gestart. Geen systemd-units, vendor-assets, Bluetooth-instellingen of sudo-systeemreparaties gewijzigd. Data en privéconfiguratie zijn behouden. De uitrol controleerde oorspronkelijke en nieuwe hashes en had automatische code-rollback bij een mislukte verificatie.

Een aanvullende opstartcorrectie geeft de onafhankelijke servercontrole maximaal twee seconden voorsprong voordat een nieuwe cd lokaal wordt gelezen. Dit voorkomt een onnodige read van een al opgeslagen track bij snelle serverrespons; offline lokale buffering blijft beschikbaar. Daarvoor zijn twee regressies toegevoegd.

## Verificatie

- 151 offline/gesimuleerde regressietests op Mac én Pi geslaagd; frontendtests op de Mac geslaagd.
- Twee echte maar geïsoleerde MPD-integratietests op de Pi geslaagd: groeiende WAV, seek na unlink en crossfade. Gemeten overlap uit totale duur: 2,981 seconden; MPD begon na 0,305 seconde terwijl de writer nog niet klaar was.
- DVD-tools zonder drivegebruik gecontroleerd: FFmpeg bevat dvdvideo, ffprobe start correct.
- Productie-MPD bleef PID 28787; alleen de webservice veranderde van PID 24515 naar 27719.
- Track 13 bleef gepauzeerd op 99,105 seconden, nu via server; geen speler- of archieffout, 25/25 opgeslagen.
- Alle geplaatste bestanden hebben de verwachte releasehash. Privé-archief-/Spotifyconfiguratie, MPD-/Caldera-configuratie en rip-staging bleven ongewijzigd.
- Geen hoorbare Bluetooth-luistertest, fysieke cd-import, USB-resetproef of DVD-weergave op Apple TV uitgevoerd. De speaker was bij de statuscontrole niet verbonden; er is geen nieuwe verbinding geforceerd.

## Herstel

Private Pi-backup: `/home/tijmen/cdspeler/backups/deploy-70eb61f-20261107-132631/`.

Deze bevat oorspronkelijke code, instellingen, MPD-/webcheckpoint, deploymentplan, resultaat en een manifest met distributieversies en hashes van de bestaande vendor-/Caldera-binaries. Een geverifieerde kopie staat op de Mac onder `backups/pi-deploy-20261107/restore-70eb61f.tar.gz`; die map is privé en genegeerd door Git. De package-/bronherkomst voor een volledig reproduceerbare vendor-build blijft aanvullende documentatie vereisen.

Rollback alleen tijdens een vrij onderhoudsmoment: stop de webservice, herstel uitsluitend de oorspronkelijke bestanden uit code/ en verwijder alleen de volgens deployment-plan nieuwe bestanden. Laat runtime-data en vendor staan. Start de webservice opnieuw en controleer de echte MPD-pauzestand, URL en positie. Zet instellingen/checkpoints niet blind over nieuwe gebruikerskeuzes heen.
