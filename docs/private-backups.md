# Private backup buiten het project

Git bewaart code en documentatie, niet .ssh/, runtimegegevens of herstelarchieven. Gebruik een afzonderlijke beveiligde schijf-/backupbestemming om ook verlies van de Mac/projectmap te kunnen herstellen.

```sh
python3 tools/private_backup.py create /Volumes/PRIVATE-BACKUP/pi-player-2026-11-07
python3 tools/private_backup.py verify /Volumes/PRIVATE-BACKUP/pi-player-2026-11-07
```

Het create-commando schrijft alleen naar een nieuwe bestemming buiten de projectmap. Het neemt .ssh/ en backups/ op, weigert symlinks, zet private rechten en verifieert ieder archieflid en de gehele archivechecksum. Verify leest alleen, pakt niets uit en drukt geen inhoud of gevonden geheimen af. Als bestanden tijdens de backup veranderen kan verificatie mislukken; originele bestanden worden niet gewijzigd of verwijderd.

Het archief is niet door dit hulpmiddel versleuteld. Gebruik een eigen beveiligde of versleutelde backupbestemming en houd toegang beperkt. Git-ignore en 0600 beschermen tegen onbedoeld delen, niet tegen verlies of onbevoegde toegang tot een ontgrendelde Mac. Sla nooit de private archive in Git, een publieke upload of het deploypakket op.

Herstel eerst naar een afzonderlijke private map. Verifieer de archive en herstel vervolgens bewust sleutels/backupmappen; overschrijf geen huidige runtimegegevens of nieuwe gebruikerskeuzes blind. De tool ondersteunt bewust geen automatisch live terugzetten op Pi/VPS.

De bestaande Pi-backup en Mac-kopie van de vorige uitrol blijven behouden. Deze ronde test de tool met synthetische private data; een echte externe bestemming is niet gekozen of aangemaakt.
