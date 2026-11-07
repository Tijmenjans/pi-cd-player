# Gecontroleerde Discogs-import

De speler behoudt MusicBrainz, CD-Text en lokale bevestigde entries. Het hulpmiddel tools/import_discogs.py gebruikt een door jou opgeslagen JSON-response van een specifieke Discogs-release en een gemeten cd-snapshot. Het doet geen netwerkzoekactie, vraagt geen token en leest geen drive.

```sh
python3 tools/import_discogs.py https://www.discogs.com/release/29930347 \
  --input /tmp/discogs-release.json --toc /tmp/measured-cd.json \
  --positions 1-1,1-2,1-3,1-4 --disc-number 1 --disc-total 3 \
  --output /tmp/catalogue-proposal.json
```

De posities zijn een voorbeeld: geef exact één echte Discogs-trackpositie per gemeten track in dezelfde volgorde. De TOC-snapshot bevat id en tracks met number en sectors. Het hulpmiddel weigert ontbrekende/dubbele posities en een afwijkende release-ID. Controleer medium, alle titels/artiesten en de volgorde. Alleen na eigen bevestiging kan --confirmed de gemeten cd-ID aan het voorstel koppelen. Het resultaat gaat eerst buiten catalogue/ en kan geen bestaand bestand overschrijven; neem een gecontroleerd voorstel daarna bewust op in Git.

Duren komen uitsluitend uit sectors/75; de oorspronkelijke Discogs-duur en positie blijven als herkomstinformatie bewaard. De bevestigde 50 Hollandse Toppers-entry heeft nu expliciet disc_ids voor cd 1; de bestaande track-16-correctie blijft intact. Zonder bevestigde ID blijft de conservatieve TOC-lengtematching beschikbaar. Defecte entries worden overgeslagen.

Een algemene zoekfunctie op barcode/titel is niet toegevoegd: dat vereist uitgavekeuze en actuele verificatie van Discogs-API-authenticatie en limieten. Het offline hulpmiddel is daar niet van afhankelijk.
