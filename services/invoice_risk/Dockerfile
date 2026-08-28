FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY contracts contracts
COPY services services
CMD ["uvicorn","services.invoice_risk.app:app","--host","0.0.0.0","--port","8001"]

