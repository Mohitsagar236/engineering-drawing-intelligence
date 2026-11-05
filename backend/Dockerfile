FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/appuser PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements.lock requirements-easyocr.txt requirements-ocr.txt ./
RUN pip install --no-cache-dir --upgrade pip==26.3 setuptools==84.2.1 && pip install --no-cache-dir --require-hashes -r requirements.lock && pip install --no-cache-dir torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -c requirements.lock -r requirements-easyocr.txt
ARG INSTALL_PADDLE=false
RUN if [ "$INSTALL_PADDLE" = "true" ]; then pip install --no-cache-dir -c requirements.lock -r requirements-ocr.txt; fi
RUN pip check
RUN useradd --create-home appuser && mkdir -p /app/data /app/uploads /home/appuser/.EasyOCR /home/appuser/.paddlex && chown -R appuser:appuser /app/data /app/uploads /home/appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser scripts ./scripts
COPY alembic.ini ./
USER appuser
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
