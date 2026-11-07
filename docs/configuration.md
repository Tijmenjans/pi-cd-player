# Installatie-instellingen en inrichting

Zonder extra configuratie blijven alle bestaande waarden werken: poort 8080, MPD 127.0.0.1:6601, de bestaande UFO202-node en gekoppelde speaker. Accountgegevens blijven uitsluitend in hun bestaande private bestanden; installatie-instellingen bevatten geen tokens.

Een optioneel `data/installation.json` volgt config/examples/installation.example.json. Onbekende velden, niet-lokale MPD, ongeldige poorten/adressen en verkeerd JSON worden geweigerd. Een expliciet CDSPELER_CONFIG naar een ontbrekend bestand geeft een fout in plaats van stil terugvallen. CDSPELER_ROOT kiest de absolute installatieroot; standaard is dit de map van de broncode. Statische resources en catalogus komen uit de actieve broncode, niet uit een willekeurige testdatamap.

Web-, MPD-, lokale audiorelay- en speakerinstellingen worden door de relevante modules gedeeld. De bronkeuze/systemd-dienstnamen en Plex/Soloist-protocollen behouden hun bestaande contract. Externe toegang en reverse-proxy worden hiermee niet geconfigureerd.

## Alleen voorstellen genereren

```sh
python3 tools/configure.py --root /home/tijmen/cdspeler \
  --config config/examples/installation.example.json \
  --output .local/generated-review
```

De outputmap moet nieuw zijn. Het hulpmiddel valideert instellingen en schrijft unit-/MPD-/Caldera-voorstellen plus installation.json; het kopieert niets naar systemd, doet geen daemon-reload en herstart niets. De SuperDrive-systeem-wake-unit wordt niet als user-service gegenereerd. Verander de bestaande systeemreparatie niet bij deze inrichting.

Voor het afzonderlijke productie-startpunt voeg je --production en --python /home/tijmen/cdspeler/.venv-player/bin/python toe. Beoordeel de voorstellen en installeer alleen tijdens gepland onderhoud. Paden met shell/systemd-uitbreidingen of spaties worden geweigerd; dit is een beperkte, voorspelbare renderer.

## Pythonomgeving

```sh
./tools/setup --profile test
./tools/setup --profile test --install
./tools/setup --profile pi
```

Zonder --install worden alleen commando's getoond. Het testprofiel gebruikt requirements-test.lock met ook transitieve versies. Het Pi-profiel controleert eerst de distributie-imports (Flask, native libdiscid, websocket), maakt .venv-player met system-site-packages en installeert de vastgezette runtime-/serververeisten. Distributie- en vendor-versies blijven onderdeel van het afzonderlijke afhankelijkheidsmanifest; een pip-lock vervangt die niet. Shazam blijft in zijn eigen bestaande omgeving.

## Productie-webserver

player_server.py gebruikt Waitress 3.0.2, één proces en een begrensd aantal threads/connections/buffers. RuntimeOwner weigert een tweede hardware-eigenaar voor dezelfde installatie. /health voert geen hardwarecheck uit; /ready vereist gestarte levende workers. Speaker- of internetuitval maakt lokale bediening niet automatisch onbereikbaar. Releasevelden bevatten geen paden, tokens of bestandsmanifest.

Waitress is een pure Python server met één proces en meerdere threads. De volledige requestbody wordt gebufferd; deze server is daarom alleen voor de Pi-entrypoint, niet als ongecontroleerde vervanging voor de VPS-WAV-uploadserver. Zie [Flask/Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/) en [Waitress-bufferinstellingen](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html).
