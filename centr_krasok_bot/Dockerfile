FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY bot.py .
COPY company_data.py .

# Запуск
CMD ["python", "bot.py"]
