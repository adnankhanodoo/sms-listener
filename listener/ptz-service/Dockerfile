FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask flask-cors paho-mqtt
COPY ptz.py .
EXPOSE 5002
CMD ["python", "ptz.py"]
