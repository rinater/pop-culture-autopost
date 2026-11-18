FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY autopost ./autopost
ENV DB_PATH=/data/state.db
CMD ["python", "-m", "autopost"]
