from runtime_settings import Settings
"""Read the actual output away from the web request path."""
import json
import subprocess
import time
import threading

SETTINGS = Settings.load()

output = {'name': 'Audio-uitgang', 'type': 'unknown', 'speaker_connected': False}


def snapshot():
    return dict(output)


def bluetooth_speakers(nodes):
    return any(n.get('info', {}).get('props', {}).get('media.class') == 'Audio/Sink' and
               n['info']['props'].get('device.api') == 'bluez5' for n in nodes)


def observe(stop=None):
    stop=stop or threading.Event()
    global output
    while not stop.is_set():
        speakers = None
        try:
            nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=5))
            speakers = bluetooth_speakers(nodes)
            metadata = next(n for n in nodes if n.get('type', '').endswith(':Metadata')
                            and n.get('props', {}).get('metadata.name') == 'default')
            name = next(m['value']['name'] for m in metadata['metadata']
                        if m['key'] == 'default.audio.sink')
            props = next(n['info']['props'] for n in nodes
                         if n.get('info', {}).get('props', {}).get('node.name') == name)
            speaker_connected = any(n.get('info', {}).get('props', {}).get('media.class') == 'Audio/Sink' and
                n['info']['props'].get('api.bluez5.address') == SETTINGS.speaker_address for n in nodes)
            bluetooth = name.startswith('bluez_output.')
            output = {'name': props.get('node.description', 'Bluetooth') if bluetooth else 'AUX',
                      'type': 'bluetooth' if bluetooth else 'aux', 'speaker_connected': speaker_connected,
                      'bluetooth_speaker_connected': speakers}
        except Exception:
            output = {'name': 'Audio-uitgang onbekend', 'type': 'unknown', 'speaker_connected': False, 'bluetooth_speaker_connected': speakers}
        stop.wait(5)
