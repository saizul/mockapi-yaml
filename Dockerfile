FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MOCKAPI_CONFIG=/config/mock.yaml \
    MOCKAPI_HOST=0.0.0.0 \
    MOCKAPI_PORT=4010
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples /config
RUN pip install . \
    && useradd --system --uid 10001 --no-create-home app \
    && rm -rf /app/build
USER app
EXPOSE 4010
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/__mockapi/health' % os.environ.get('MOCKAPI_PORT', '4010'), timeout=2)"]
ENTRYPOINT ["mockapi"]
CMD ["serve"]
