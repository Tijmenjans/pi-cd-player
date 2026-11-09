"""One autoplay attempt per Bluetooth connection; manual choices then remain in force."""
import logging

log = logging.getLogger(__name__)


class ConnectionTrigger:
    def __init__(self):
        self.connected = False
        self.missing = 0

    def update(self, connected):
        # Unknown observations must not fabricate a disconnect/reconnect.
        if connected is None:
            return False
        if not connected:
            self.missing += 1
            if self.missing >= 2:
                self.connected = False
            return False
        self.missing = 0
        if self.connected:
            return False
        self.connected = True
        return True


def observe(snapshot, start, stop, pause=None):
    trigger = ConnectionTrigger()
    missing_speaker = 0
    while not stop.is_set():
        state = snapshot()
        connected = None if state.get('type') == 'unknown' else state.get('speaker_connected', False)
        if trigger.update(connected):
            try:
                start()
            except Exception:
                # URLs and account tokens may occur in network exceptions.
                log.warning('Speaker autoplay kon niet starten; kies Plex of verbind de speaker opnieuw.')
        any_speaker = state.get('bluetooth_speaker_connected')
        if any_speaker is True:
            missing_speaker = 0
        elif any_speaker is False:
            missing_speaker += 1
        else:
            missing_speaker = 0
        if pause is not None and missing_speaker >= 2:
            try:
                pause()
            except Exception:
                log.warning('Pauzeren zonder Bluetooth-speaker kon niet worden bevestigd.')
        stop.wait(2)
