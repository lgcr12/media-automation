FROM python:3.12-slim

ARG FFMPEG_URL=
ENV FFMPEG_URL=${FFMPEG_URL}

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Download a static ffmpeg build for the target CPU architecture.
# linux64 is used on Windows/Linux x86_64, linuxarm64 on Apple Silicon.
RUN python - <<'PY'
import io
import os
import tarfile
import urllib.request

machine = os.uname().machine.lower()
suffix = "linux64" if machine in {"x86_64", "amd64"} else "linuxarm64"
default_url = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    f"ffmpeg-master-latest-{suffix}-gpl.tar.xz"
)
url = os.environ.get("FFMPEG_URL") or default_url
archive = urllib.request.urlopen(url, timeout=300).read()
with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as bundle:
    member = next(item for item in bundle.getmembers() if item.name.endswith("/bin/ffmpeg"))
    with bundle.extractfile(member) as source, open("/usr/local/bin/ffmpeg", "wb") as target:
        target.write(source.read())
PY
RUN chmod +x /usr/local/bin/ffmpeg

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY tests ./tests

ENV PYTHONUNBUFFERED=1
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)"

CMD ["python", "app.py"]
