FROM python:3.12.14-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN addgroup -S -g 10001 gateway \
    && adduser -S -D -H -u 10001 -G gateway gateway \
    && mkdir -p /app/src /data \
    && chown -R gateway:gateway /app /data

WORKDIR /app
COPY --chown=gateway:gateway src/ /app/src/

USER gateway

ENTRYPOINT ["python", "-m", "rtkey_gateway"]
CMD ["run"]
