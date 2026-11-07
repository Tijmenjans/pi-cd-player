"""Validated installation settings; account credentials stay in their private files."""
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re

@dataclass(frozen=True)
class Settings:
    install_root: Path
    web_host: str = '0.0.0.0'
    web_port: int = 8080
    mpd_host: str = '127.0.0.1'
    mpd_port: int = 6601
    speaker_address: str = '6C:5C:3D:3C:2B:A3'
    vinyl_source: str = 'alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-input'
    web_threads: int = 8

    @property
    def audio_base_url(self):
        return f'http://127.0.0.1:{self.web_port}'

    @classmethod
    def load(cls, code_root=None, environ=None):
        env=os.environ if environ is None else environ
        root=Path(env.get('CDSPELER_ROOT',code_root or Path(__file__).resolve().parent)).expanduser()
        if not root.is_absolute():raise ValueError('CDSPELER_ROOT moet absoluut zijn')
        config=Path(env.get('CDSPELER_CONFIG',root/'data/installation.json')).expanduser()
        data={}
        if 'CDSPELER_CONFIG' in env and not config.is_file():raise ValueError('Opgegeven installatieconfiguratie ontbreekt')
        if config.exists():
            try:data=json.loads(config.read_text())
            except (OSError,ValueError) as exc:raise ValueError('Installatieconfiguratie is niet leesbaar of geldig JSON') from exc
        if not isinstance(data,dict):raise ValueError('Installatieconfiguratie moet een object zijn')
        allowed=set(cls.__dataclass_fields__)-{'install_root'}
        if set(data)-allowed:raise ValueError('Onbekend installatieveld; bewaar credentials afzonderlijk')
        settings=cls(install_root=root,**data)
        if settings.web_host not in ('0.0.0.0','127.0.0.1'):raise ValueError('web_host moet 0.0.0.0 of 127.0.0.1 zijn voor de lokale audiorelay')
        for field in ('web_port','mpd_port'):
            value=getattr(settings,field)
            if type(value) is not int or not 1024<=value<=65535:raise ValueError('Ongeldige niet-geprivilegieerde poort')
        try:loopback=ipaddress.ip_address(settings.mpd_host).is_loopback
        except ValueError:loopback=settings.mpd_host=='localhost'
        if not loopback:raise ValueError('MPD moet lokaal bereikbaar zijn')
        if type(settings.web_threads) is not int or not 4<=settings.web_threads<=32:raise ValueError('web_threads moet tussen 4 en 32 liggen')
        if not isinstance(settings.speaker_address,str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',settings.speaker_address):raise ValueError('Ongeldig Bluetooth-adres')
        if not isinstance(settings.vinyl_source,str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,240}',settings.vinyl_source):raise ValueError('Ongeldige PipeWire-bron')
        return settings
