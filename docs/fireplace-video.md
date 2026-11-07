# Geluidloze haardvideo

UI-bestand: static/christmas-fire.mp4. Een korte, lokale decoratieve video, geen persoonlijke media of dvd-archief. Dit is de enige expliciete MP4-uitzondering in Git-ignore, repository-audit en deployment; de bestaande limiet van 2 MiB blijft gelden. Alle overige MP4-/runtime-/mediabestanden blijven uitgesloten.

Bron: [Kaminfeuer.webm](https://commons.wikimedia.org/wiki/File:Kaminfeuer.webm), auteur [Larvis](https://commons.wikimedia.org/wiki/User:Larvis), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). De afgeleide video wordt eveneens onder CC BY-SA 4.0 verspreid. Wijzigingen: geluid verwijderd, 720p/24 fps H.264 yuv420p, hercompressie en 0,6 seconde overvloeien tussen einde en begin. De zichtbare “Haardbeeld”-link vermeldt bron/auteur/licentie en bewerking. De oorspronkelijke download blijft buiten Git.

De afgeleide video duurt 10,333 seconden en is 1.659.428 bytes. Controle met ffprobe: één H.264-videostream, 1280×720; geen audiostream. SHA-256 en het concrete buildcommando staan hieronder. FFmpeg 8.1 is alleen op de Mac gebruikt; op de Pi wordt niets getranscodeerd.

```sh
ffmpeg -i original.webm -filter_complex \
 '[0:v]fps=24,scale=1280:720,format=yuv420p,split[a][b];[a]trim=start=0.6,setpts=PTS-STARTPTS[main];[b]trim=end=0.6,setpts=PTS-STARTPTS[head];[main][head]xfade=transition=fade:duration=0.6:offset=9.76[v]' \
 -map '[v]' -an -c:v libx264 -preset medium -crf 27 -profile:v main -level 3.1 \
 -maxrate 1200k -bufsize 2400k -pix_fmt yuv420p -movflags +faststart christmas-fire.mp4
```

De browser laadt de video pas in kerstmodus met ingeschakelde effecten, zonder minder-bewegingvoorkeur en met een zichtbaar tabblad. Muted, loop, playsinline en afwezigheid van een audiotrack voorkomen dat de achtergrond de muziek overneemt. Tabblad verbergen, thema-/effectwisseling en minder beweging pauzeren direct. Bij laad-/codecproblemen of geweigerde autoplay blijft de bestaande foto zichtbaar. Geen externe videohost wordt door de webapp benaderd.

De browserproef decodeert de echte meegeleverde MP4, controleert voortgang, geluidloos herhalen, geen download bij minder beweging, pauzeren bij verborgen tabblad/effecten uit en terugval bij videofouten. Dit is een Chromium/Mac-proef; niet ieder tv-/Safari-model is afzonderlijk getest. Bij een browser op de Pi zelf moet de hardwaredecodebelasting apart worden gecontroleerd.

De eerste statische uitrol van dit ene nieuwe bestand vereist een expliciete baseline waarin het pad ontbreekt. Andere nieuwe paden en runtimewijzigingen blijven geweigerd. Backup slaat het ontbrekende pad als null op; automatisch herstel verwijdert alleen het aantoonbaar nieuwe bestand. Er worden geen services of hardwareprocessen gestart/gestopt. HTML wordt na zijn afhankelijkheden gepubliceerd.

SHA-256 afgeleide MP4: `849824f932996bd644d89fb67e482f9abb2422a704a0cfa2d2ef105750223b6b`.
