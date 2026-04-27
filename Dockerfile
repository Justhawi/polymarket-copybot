FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir aiohttp python-dotenv

COPY . .

RUN mkdir -p logs

CMD ["python", "src/bot.py"]