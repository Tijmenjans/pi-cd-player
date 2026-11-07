# Private backup buiten het project

Git bewaart code en documentatie, niet .ssh/, runtimegegevens of herstelarchieven. Gebruik een afzonderlijke beveiligde schijf-/backupbestemming om ook verlies van de Mac/projectmap te kunnen herstellen.

```sh
python3 tools/private_backup.py create /Volumes/PRIVATE-BACKUP/pi-player-2026-11-07
python3 tools/private_backup.py verify /Volumes/PRIVATE-BACKUP/pi-player-2026-11-07
```

Het create-commando schrijft alleen naar een nieuwe bestemming buiten de projectmap. Het neemt .ssh/ en backups/ op, weigert symlinks, zet private rechten en verifieert ieder archieflid en de gehele archivechecksum. Verify leest alleen, pakt niets uit en drukt geen inhoud of gevonden geheimen af. Als bestanden tijdens de backup veranderen kan verificatie mislukken; originele bestanden worden niet gewijzigd of verwijderd.

Het archief is niet door dit hulpmiddel versleuteld. Gebruik een eigen beveiligde of versleutelde backupbestemming en houd toegang beperkt. Git-ignore en 0600 beschermen tegen onbedoeld delen, niet tegen verlies of onbevoegde toegang tot een ontgrendelde Mac. Sla nooit de private archive in Git, een publieke upload of het deploypakket op.

Herstel eerst naar een afzonderlijke private map. Verifieer de archive en herstel vervolgens bewust sleutels/backupmappen; overschrijf geen huidige runtimegegevens of nieuwe gebruikerskeuzes blind. De tool ondersteunt bewust geen automatisch live terugzetten op Pi/VPS.

## Werkelijke versleutelde VPS-backup: 7 november 2026

Op verzoek van de eigenaar staat een versleutelde kopie op `hetzner-coolify:/root/private-backups/pi-cd-player/20261107-completed-private.tar.age`. Maprechten 0700, bestandsrechten 0600. Er is uitsluitend ciphertext geüpload: manifest en private archief zitten samen binnen de versleuteling. Dit is een backup van de private Mac-projectbestanden, geen volledige snapshot van actuele Pi/VPS-mediadata.

[`age`](https://github.com/FiloSottile/age) 1.3.2 is lokaal gebruikt. De officiële darwin/arm64-download is gecontroleerd tegen de SHA-256 uit de officiële GitHub-releasegegevens. Homebrew was hier niet schrijfbaar; er zijn geen Homebrew-rechten veranderd.

Ontvangers zijn de bestaande publieke Mac-SSH-sleutel (`~/.ssh/id_ed25519.pub`) en project-Pi-sleutel (`.ssh/pi_ed25519.pub`). Er zijn geen nieuwe SSH-sleutels aangemaakt. De lokale terugleesproef met de Pi-identiteit heeft alle 39 bronbestanden en hun hashes gecontroleerd. De VPS berekende daarna dezelfde SHA-256 over het ontvangen ciphertext: `f64a0b900ca94c5f8c80720308972c35b5fb5ee90696b27f5d1130b8e06c89fd` (53.435.442 bytes). De eerdere eerste kopie blijft als afzonderlijk historisch checkpoint behouden. De afsluitende versie bevat ook de nieuwe Pi-webunitbackup en het VPS-broncode-/SQLite-herstelcheckpoint. De tijdelijke onversleutelde werkmappen zijn verwijderd; de originele private projectbestanden blijven behouden.

**Herstelsleutel apart bewaren:** minstens één bijbehorende privésleutel moet beschikbaar blijven, bijvoorbeeld de Mac-SSH-sleutel in een afzonderlijke beveiligde sleutelbackup. De Pi-sleutel binnen dit archief kan het archief niet zelf ontsluiten als alle andere kopieën verloren zijn. Er is in deze ronde geen afzonderlijke wachtwoordmanager- of offline sleutelbackup gemaakt. De privésleutels worden nooit naast het archief op de VPS opgeslagen.

Herstellen op een vertrouwde computer met `age` geïnstalleerd:

```sh
umask 077
scp hetzner-coolify:/root/private-backups/pi-cd-player/20261107-completed-private.tar.age ./private.tar.age
age --decrypt -i ~/.ssh/id_ed25519 -o private-bundle.tar private.tar.age
mkdir private-restore
tar -xf private-bundle.tar -C private-restore manifest.json private.tar.gz
python3 tools/private_backup.py verify private-restore
```

Gebruik eventueel de apart bewaarde Pi-identiteit als `-i`-pad. Voer geen sleutel of wachtwoord in chat of Git in. De Mac-sleutel kan bij ontsleuteling om zijn passphrase vragen; SSH-sleutelhanger-authenticatie betekent niet dat `age` die passphrase automatisch kan overnemen. Pak de binnenste backup pas na verificatie uit in een afzonderlijke private map.

Een volgende backup moet opnieuw lokaal worden gemaakt, versleuteld en teruggelezen vóór upload. Gebruik een nieuwe bestandsnaam; overschrijf nooit de enige herstelkopie. Het bestaande `private_backup.py create`-commando levert bewust eerst een plaintext-archief: upload dat nooit rechtstreeks naar de VPS.

Lokale ciphertext-kopieën staan onder de genegeerde `.local/private-backups/`, buiten de bronmappen van de backup-tool. Daarmee neemt een volgende snapshot eerdere ciphertext-kopieën niet opnieuw op.
