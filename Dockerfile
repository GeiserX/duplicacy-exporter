FROM python:3.13-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY duplicacy_exporter.py .

EXPOSE 9750

ENTRYPOINT ["python", "-u", "duplicacy_exporter.py"]
