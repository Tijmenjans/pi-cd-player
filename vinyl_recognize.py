"""Short-lived ShazamIO worker, isolated from the system Python webapp."""
import asyncio
import json
import sys


async def recognize(path):
    from shazamio import Shazam
    shazam = Shazam(language='nl-NL', endpoint_country='NL', segment_duration_seconds=12)
    return await asyncio.wait_for(shazam.recognize(path), timeout=40)


if __name__ == '__main__':
    try:
        result = asyncio.run(recognize(sys.argv[1]))
        print(json.dumps(result))
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        sys.exit(1)
