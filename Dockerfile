# Cutline web app: landing page + editor + API. Runs anywhere that runs a container.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cutline ./cutline
RUN pip install --no-cache-dir '.[web,transcribe]'
ENV CUTLINE_HOME=/data HOST=0.0.0.0 PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["cutline-web"]
