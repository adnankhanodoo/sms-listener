FROM python:3.11-slim
WORKDIR /app
RUN apt-get update -qq && apt-get install -y -qq ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir aiohttp
COPY server.py .
COPY static/ ./static/
EXPOSE 3000
CMD ["python", "server.py"]
