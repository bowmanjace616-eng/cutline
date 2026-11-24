# Cutline web app: landing page + editor + API. Runs anywhere that runs a container.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fontconfig \
    && for f in fonts-inter fonts-liberation2 fonts-roboto-unhinted fonts-open-sans fonts-lato fonts-montserrat \
         fonts-urw-base35 fonts-noto-color-emoji; do \
         apt-get install -y --no-install-recommends "$f" || echo "skipping $f"; done \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cutline ./cutline
RUN pip install --no-cache-dir '.[web,transcribe]'
# Bake the speech model into the image so the first edit doesn't wait on a download.
ENV HF_HOME=/opt/models CUTLINE_WHISPER_MODEL=base
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', compute_type='int8')" \
    || echo "Whisper model not pre-downloaded; it will download on first use"
ENV CUTLINE_HOME=/data HOST=0.0.0.0 PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["cutline-web"]
