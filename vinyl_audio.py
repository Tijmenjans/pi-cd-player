from runtime_settings import Settings
"""Forward the UFO202 to the paired IKEA speaker while Vinyl is selected."""
import json
import signal
import subprocess
import time
from pathlib import Path

SETTINGS = Settings.load()
SOURCE = SETTINGS.vinyl_source
SPEAKER = SETTINGS.speaker_address
ROOT = SETTINGS.install_root


def endpoints(nodes):
    source = sink = None
    for node in nodes:
        props = node.get('info', {}).get('props', {})
        if props.get('node.name') == SOURCE:
            source = node
        if props.get('media.class') == 'Audio/Sink' and props.get('api.bluez5.address') == SPEAKER:
            sink = node
    return source, sink


def linked(nodes, source, sink):
    named = {node.get('info', {}).get('props', {}).get('node.name'): node['id'] for node in nodes}
    edges = {(node['info'].get('output-node-id'), node['info'].get('input-node-id'))
             for node in nodes if node.get('info', {}).get('state') == 'active'
             and node.get('type', '').endswith(':Link')}
    return ((source['id'], named.get('cdspeler-vinyl.capture')) in edges and
            (named.get('cdspeler-vinyl.playback'), sink['id']) in edges)


def command(source, sink):
    # Give Bluetooth scheduling room and prevent new capture clients from
    # renegotiating the running graph's rate or quantum.
    stable = ('node.dont-fallback=true audio.rate=48000 '
              'node.rate=1/48000 node.lock-rate=true node.lock-quantum=true')
    return ['/usr/bin/pw-loopback', '-n', 'cdspeler-vinyl', '-l', '100', '-d', '0.2',
            '-C', source, '-P', sink,
            '-i', 'node.name=cdspeler-vinyl.capture ' + stable,
            '-o', 'node.name=cdspeler-vinyl.playback ' + stable]


def publish(**state):
    state['updated_at'] = time.time()
    path = ROOT / 'data/vinyl-output.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state))
    temp.replace(path)


def main():
    running = True
    child = None
    target = None
    reconnect_at = 0

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            try:
                nodes = json.loads(subprocess.check_output(['pw-dump'], timeout=5))
                source, sink = endpoints(nodes)
                new_target = sink['info']['props']['node.name'] if source and sink else None
                if child and (target != new_target or child.poll() is not None):
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=3)
                    child = None
                if new_target and child is None:
                    child = subprocess.Popen(command(SOURCE, new_target),
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    target = new_target
                name = sink['info']['props'].get('node.description', 'IKEA VAPPEBY') if sink else 'IKEA VAPPEBY'
                active = bool(source and sink and child and child.poll() is None and linked(nodes, source, sink))
                publish(name=name, type='bluetooth', playing=active,
                        message=('Vinyl speelt via ' + name) if active else
                        'UFO202 niet aangesloten.' if not source else
                        'Bluetooth-speaker verbinden…' if not sink else 'Audioverbinding opbouwen…')
                if not sink and time.monotonic() >= reconnect_at:
                    reconnect_at = time.monotonic() + 20
                    subprocess.run(['/usr/bin/python3', str(ROOT / 'bluetooth-connect.py')],
                                   capture_output=True, timeout=25)
            except Exception:
                publish(name='IKEA VAPPEBY', type='bluetooth', playing=False,
                        message='Audioverbinding herstellen…')
            for _ in range(20):
                if not running:
                    break
                time.sleep(0.1)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        publish(name='IKEA VAPPEBY', type='bluetooth', playing=False, message='Vinyl-doorvoer uitgeschakeld.')


if __name__ == '__main__':
    main()
