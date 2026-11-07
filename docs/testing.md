# Verificatie

Offline: `.venv/bin/python tools/run_tests.py` en `node tests/test_frontend.cjs`. De runner gebruikt een tijdelijke broncodekopie, fictieve archiefconfiguratie en expliciete libdiscid-simulatie. Hij start geen Flask-server of productieworkers. Veel tests gebruiken mocks voor MPD, netwerk, drive en systemd; proces-/flock-tests starten wel kleine echte lokale childprocessen. De frontendtests gebruiken een beperkte DOM-simulatie, geen echte browser of visuele schermcontrole.

Bewaarde regressies omvatten lokale-track-pinning, opvolgende bronkeuze, seekherstel, stall/deadline/reader-lock, drie pogingen en trackprioriteit, uploadbackoff/verloren bevestiging, volledige versus afgebroken WAV, CD-Text/TOC, DVD-exclusiviteit/ondertitels, vinyltransities en verouderde bronstatus.

`tests/integration/test_live_mpd.py` en `test_fades_mpd.py` vereisen echte MPD met null/recorder-output en loopback HTTP. Ze gebruiken synthetische audio en eigen poorten; ze zitten buiten de standaard discovery. Voer ze uitsluitend in een geschikte testomgeving uit met `PYTHONPATH=.:tests python3 -m unittest discover -s tests/integration`. Ze testen geen echte USB-drive of Bluetooth. Tijdens deze migratie zijn ze niet uitgevoerd.

Echte hardwarecontroles blijven afzonderlijk: langlopende cd-import, USB-resets en kernelhangs, hoorbare bronwissels/Bluetooth, VLC op Apple TV en Nederlandse ondertitels, fysieke eject en gelijktijdigheid. Historische gebruikersbevestigingen staan in historical-delivery.md; ze zijn niet opnieuw uitgevoerd. Offline succes bewijst deze hardware-eigenschappen niet.

Resultaat op 7 november 2026, Mac/Python 3.14: 125 offline Python-tests geslaagd; frontendcontroles voor CD/Vinyl/streaming/DVD, herstelmelding en bronrace geslaagd. Native python-libdiscid kon op de Mac niet bouwen wegens ontbrekende discid/discid.h; de offline stub is expliciet, productie gebruikt de echte Pi-bibliotheek. Geen MPD-integratie- of hardwaretests uitgevoerd.

De verbeteringsronde voegt tests toe voor offline WAV-hergebruik, begrensde buffer, opslag-/metricsfouten, gedeelde CD/DVD-leases, herstel na stop-/MPD-/schrijffouten, responsieve status tijdens bronwissel, import zonder workers, idempotente runtime-start/stop, catalogusisolatie en Discogs-TOC-behoud. VPS-tests gebruiken tijdelijke SQLite/WAV-bestanden en gesimuleerde Plex-aanroepen: persistente retry/backoff, gelijktijdige refreshverzoeken, gereed FLAC zonder Plex-wachttijd, weesherstel en gecontroleerde artwork-cache.

Resultaat van deze verbeteringsronde op Mac/Python 3.14: **149 offline Python-tests geslaagd**, inclusief 24 nieuwe fout-/herstel-/concurrencycontroles. Frontendtests slagen ook met de buffer-volmelding, naast bestaande bronrace-, DVD- en herstelcontroles. Pythoncompilatie, JavaScript-syntaxis en CLI-help van beide nieuwe hulpmiddelen zijn gecontroleerd. Geen tests op de Pi/VPS, echte MPD, FFmpeg-conversie, USB, Bluetooth of Apple TV uitgevoerd.
