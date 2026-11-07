"""Opt-in production entrypoint: one process, threaded response streaming.

Activate only with a reviewed systemd unit after installing requirements-server.
The existing app.py entrypoint remains compatible with the current Pi service.
"""
import signal


def run(serve=None):
    # Check the optional server before starting hardware workers.
    if serve is None:
        from waitress import serve
    import app as player
    try:
        player.start_runtime()
        serve(player.app,host=player.SETTINGS.web_host,port=player.SETTINGS.web_port,
              threads=player.SETTINGS.web_threads,connection_limit=32,
              max_request_body_size=1_048_576,outbuf_overflow=262_144,
              outbuf_high_watermark=1_048_576,channel_timeout=120,
              expose_tracebacks=False,clear_untrusted_proxy_headers=True)
    finally:player.stop_runtime()


def main():
    def terminate(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,terminate)
    run()

if __name__=='__main__':main()
