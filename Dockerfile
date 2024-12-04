FROM --platform=linux/amd64 tiangolo/uvicorn-gunicorn-fastapi:python3.11-slim

WORKDIR /usr/src

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --upgrade -r requirements.txt


COPY ./app /usr/src/app

COPY entrypoint.sh /usr/src/app/entrypoint.sh
RUN chmod +x /usr/src/app/entrypoint.sh

EXPOSE 80
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]

