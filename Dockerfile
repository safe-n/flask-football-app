FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
ENV DB_PATH=/data/football.db CACHE_DIR=/data/cache
VOLUME /data
EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "fbpred.web:app"]
