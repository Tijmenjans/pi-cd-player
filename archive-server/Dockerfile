FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server.py silence.py .
ARG RELEASE_COMMIT=unknown
ENV PYTHONUNBUFFERED=1 ARCHIVE_RELEASE=$RELEASE_COMMIT
USER 1000:1000
CMD ["python", "server.py"]
