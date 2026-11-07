# Ontwikkelcontroles

Plan en uitvoering: standaardiseer eerst de offline checks, controleer daarna alle
Git-indexblobs en bied dezelfde controles lokaal aan. Hardwaregedrag blijft behouden. De gewone unittest-bootstrap isoleert runtime-state en de bestaande runner is een dunne compatibiliteitswrapper.

## Lokale commando's

- `make setup`: maak .venv en installeer requirements-test.lock. Dit kan packages downloaden.
- `make test`: offline Python-regressies en Node-frontendtests.
- `make check`: alle indexblobs auditen, Python compile zonder imports/bytecode,
  bash-syntaxiscontrole van SSH-wrappers en tools/deploy indien aanwezig, daarna tests.
- `make check-http`: echte lokale HTTP-response-streaming met synthetische media via Waitress; geen hardwareworkers.
- `make deploy-plan`: uitsluitend `tools/deploy --dry-run`; ontbreekt het hulpmiddel,
  dan stopt dit doel. Geen SSH of deployment als fallback.
- `make check-hardware ALLOW_INTEGRATION=1`: expliciete opt-in voor bestaande MPD-
  integratietests, met lokale testprocessen en loopback. Niet onderdeel van CI of
  make check. Vereist een geschikte, vrijgegeven testomgeving. Dit bewijst geen
  fysieke USB-, Bluetooth- of DVD-werking.

`PYTHON`, `VENV` en `TEST_PYTHON` zijn overschrijfbaar. Node major 22 is de vaste
CI-versie. De volledige testinstallatie staat vast in requirements-test.lock; requirements-test.txt beschrijft de directe vereisten.

## Repository-audit

`python3 tools/check_repository.py` (of `--staged`) controleert gewijzigde
indexblobs; nul staged bestanden betekent nul gecontroleerde bestanden.
`--tracked` controleert **alle huidige indexblobs**, dus ook in een schone
CI-checkout. Daar is de index gelijk aan HEAD. Bij lokale wijzigingen onderzoekt
het indexinhoud, inclusief nieuwe staged bestanden; niet de werkmap, oude commits,
untracked of genegeerde bestanden. Stage dus bewust vóór de definitieve controle.

De audit meldt uitsluitend JSON-gequote paden en vaste redenen, nooit gevonden
waarden. Hij blokkeert privé-/runtimepaden, media, packages, executables, grote
bestanden (meer dan 2 MiB) en herkenbare credentialpatronen. Voorbeelden zijn alleen
op expliciete paden toegestaan en blijven inhoudelijk gescand. release.json is een
runtimebestand en mag niet in Git; Pythoncode voor releasebeheer is wel toegestaan.
Importeren van de scanner voert geen Git-opdracht uit en beëindigt geen proces.

De scanner is een patrooncontrole, geen bewijs dat alle geheimen ontbreken.
Handmatige review van de geselecteerde bestanden blijft nodig. Er is bewust geen
optie om gevonden waarden af te drukken. Tests gebruiken uitsluitend synthetische
waarden in tijdelijke repositories.

## CI

.github/workflows/checks.yml draait bij push, pull request en handmatige start op
Ubuntu 24.04 met Python 3.13 en 3.14 en Node 22. Alleen contents:read is toegekend;
checkout bewaart geen credentials. Geen eigen secrets, SSH, hardwarechecks,
deployments of services. Python-bronnen worden met compile() gecontroleerd zonder
ze te importeren of bytecodebestanden te schrijven.

De actions zijn op een vaste major vastgezet, niet op een onveranderlijke SHA.
Versies volgen de officiële voorbeelden: [checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python) en
[setup-node](https://github.com/actions/setup-node). Controleer updates bewust.
De Node-versie van action-internals staat los van de geteste Node 22-runtime.

Deze workflow stelt **geen branch protection of verplichte mergechecks** in.
Dat vereist afzonderlijke repository-instellingen. Een lokale geslaagde run
betekent evenmin dat de GitHub-matrix al is uitgevoerd.

Voor native verificatie vanuit een complete Pi-stagingmap zonder Git: `python3 tools/run_tests.py --runtime-only`. De Git-afhankelijke audit-/deploymentgereedschapstests blijven onderdeel van de volledige Mac/CI-suite. Productie krijgt uitsluitend runtimebestanden; er wordt geen volledige ontwikkelcheckout op de Pi bijgehouden.
