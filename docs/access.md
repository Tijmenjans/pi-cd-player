# Zelfstandig beheer vanuit dit project

Deze repository en de private projectmappen zijn het vertrekpunt voor onderhoud. Oude chatwerkruimtes zijn niet meer nodig. De huidige broncode en tests staan in Git; de Pi draait de runtime van 01963cf. De feitelijke uitrol en herstelroute staan in management-deployment-2026-11-07.md (met de eerdere uitrol in pi-deployment-2026-11-07.md).

## Pi

Voer vanuit de projectroot uit:

```sh
./tools/pi-ssh
./tools/pi-ssh 'systemctl --user status cdspeler-web --no-pager'
./tools/pi-ssh --tty
```

De laatste variant vraagt een terminal aan voor eventueel interactief beheer. Het hulpmiddel voert zelf geen sudo, servicewijziging of driveprobe uit. Standaard: tijmen@192.168.1.232, project /home/tijmen/cdspeler. Het gebruikt uitsluitend de projectlokale sleutel `.ssh/pi_ed25519` en de normale ~/.ssh/known_hosts. Er worden geen hostcontroles uitgeschakeld. De bestaande sleutel is overgenomen en byte-identiek gecontroleerd; er is geen nieuwe sleutel gemaakt.

`.ssh/` is genegeerd door Git. De map heeft rechten 0700 en de privésleutel 0600. `.ssh/pi_ed25519.pub` is de bijbehorende publieke sleutel. Op een nieuwe Mac: herstel de bestaande sleutel uit je beveiligde private backup naar dit pad en zet dezelfde rechten. Een Git-clone bevat bewust geen authenticatie. Optionele overrides: CDSPELER_PI_KEY en CDSPELER_PI_TARGET; dit zijn paden/adressen, geen sleutelmateriaal.

## VPS en GitHub

```sh
./tools/vps-ssh 'test -d /opt/cd-archive'
```

De VPS-wrapper gebruikt de bestaande alias hetzner-coolify uit de normale Mac-SSH-configuratie. De alias gebruikt de bestaande gebruikerssleutel ~/.ssh/id_ed25519; die wordt niet gedupliceerd in het project. Een niet-geheim configuratievoorbeeld staat in deploy/ssh-config.example. CDSPELER_VPS_TARGET kan de alias vervangen.

GitHub blijft de bestaande lokale core.sshCommand met UseKeychain=yes gebruiken. Verander die instelling niet in een tijdelijke opdracht die de macOS-sleutelhanger uitschakelt. De projectlokale Pi-sleutel heeft geen rol bij GitHub of de VPS.

## Lokale private herstelbestanden

| Pad | Inhoud |
|---|---|
| backups/pi-deploy-20261107/ | Geverifieerde Pi-herstelbackup, uitrolplan, checkpoints en testlogs. Bevat privéinstellingen. |
| backups/pi-cleanup-20261107/ | Geverifieerd archief van de van de Pi verwijderde oude updates/installatiebestanden, inclusief herstelinputs voor vendor-software. |
| backups/legacy-original/ | Oorspronkelijk broncodearchief en SHA-256-manifest, uitsluitend als historische referentie. |
| docs/historical-delivery.md | Historische bron-README, al opgenomen in Git. Geen actueel uitrolscript. |

Alle backups blijven buiten Git. Gebruik actuele Git-bronnen bij wijzigingen, nooit oude deployscripts uit historische archieven. Private herstelbestanden horen ook in je eigen beveiligde backup; Git vervangt die backup niet.

Kopieer bij deployment nooit blind de volledige projectmap naar de Pi. Selecteer alleen de bedoelde bronbestanden en sluit .ssh/, backups/, data/, vendor/ en virtuele omgevingen uit. Runtimepaden en de huidige installatie blijven ongewijzigd. Deze beheermigratie wijzigt geen services, sleutels op de Pi/VPS, firewall of authenticatie-instellingen.
