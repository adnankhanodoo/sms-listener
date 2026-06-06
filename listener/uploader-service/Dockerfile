FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask requests
COPY uploader.py .
RUN mkdir -p /downloads
EXPOSE 5001
CMD ["python", "uploader.py"]
