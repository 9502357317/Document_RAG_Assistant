FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    HF_HOME=/tmp/hf_cache \
    TESTING=0

WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Pre-download HF models during docker build to speed up container startup times
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" && \
    python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')" && \
    python -c "from transformers import pipeline; pipeline('text-generation', model='Qwen/Qwen2.5-0.5B-Instruct')"

# Copy the rest of the application files
COPY . /code

# Grant write permissions to the database directories
RUN chmod -R 777 /code

# Expose Hugging Face default port
EXPOSE 7860

# Run FastAPI using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
