"""Reconnect the paired IKEA speaker and keep it the default audio output."""
import json
import subprocess
import time

ADDRESS = '6C:5C:3D:3C:2B:A3'

def main():
    info = subprocess.run(['bluetoothctl', 'info', ADDRESS], capture_output=True, text=True, timeout=5)
    if 'Paired: yes' not in info.stdout:
        return
    if 'Connected: yes' not in info.stdout:
        subprocess.run(['bluetoothctl', '--timeout', '10', 'power', 'on'], capture_output=True, timeout=15)
        subprocess.run(['bluetoothctl', '--timeout', '15', 'connect', ADDRESS], capture_output=True, timeout=20)
    for _ in range(6):
        nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=5))
        sink = next((node for node in nodes if
            node.get('info', {}).get('props', {}).get('media.class') == 'Audio/Sink' and
            node['info']['props'].get('api.bluez5.address') == ADDRESS), None)
        if sink:
            name = json.dumps({'name': sink['info']['props']['node.name']})
            for key in ('default.configured.audio.sink', 'default.audio.sink'):
                subprocess.run(['pw-metadata', '-n', 'default', '0', key, name, 'Spa:String:JSON'], check=True, capture_output=True, timeout=5)
            print('Default audio output: ' + sink['info']['props'].get('node.description', 'IKEA VAPPEBY'))
            return
        if _ == 0 and 'Connected: yes' in info.stdout:
            subprocess.run(['bluetoothctl', '--timeout', '10', 'connect', ADDRESS,
                            '0000110b-0000-1000-8000-00805f9b34fb'],
                           capture_output=True, timeout=12)
        time.sleep(1)

if __name__ == '__main__':
    main()
