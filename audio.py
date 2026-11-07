"""Read the actual output away from the web request path."""
import json
import subprocess
import time

output = {'name': 'Audio-uitgang', 'type': 'unknown', 'speaker_connected': False}


def snapshot():
    return dict(output)


def observe():
    global output
    while True:
        try:
            nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=5))
            metadata = next(n for n in nodes if n.get('type', '').endswith(':Metadata')
                            and n.get('props', {}).get('metadata.name') == 'default')
            name = next(m['value']['name'] for m in metadata['metadata']
                        if m['key'] == 'default.audio.sink')
            props = next(n['info']['props'] for n in nodes
                         if n.get('info', {}).get('props', {}).get('node.name') == name)
            speaker_connected = any(n.get('info', {}).get('props', {}).get('media.class') == 'Audio/Sink' and
                n['info']['props'].get('api.bluez5.address') == '6C:5C:3D:3C:2B:A3' for n in nodes)
            bluetooth = name.startswith('bluez_output.')
            output = {'name': props.get('node.description', 'Bluetooth') if bluetooth else 'AUX',
                      'type': 'bluetooth' if bluetooth else 'aux', 'speaker_connected': speaker_connected}
        except Exception:
            output = {'name': 'Audio-uitgang onbekend', 'type': 'unknown', 'speaker_connected': False}
        time.sleep(5)
