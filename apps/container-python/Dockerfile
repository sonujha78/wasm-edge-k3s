FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn
COPY app.py .
USER 65532:65532
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "1", "--threads", "2", "app:app"]
