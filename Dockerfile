FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the SQLite database can be written to the NFS share
# In K8s, we'll mount the volume to /app/data
ENV DATABASE_URL=sqlite:////app/data/workouts.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
