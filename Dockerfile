# code updated - container instructions
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AWS_REGION=ap-southeast-2

WORKDIR /app

COPY custodian_acp/requirements.txt /tmp/acp-requirements.txt
COPY custodian_mcp/requirements.txt /tmp/mcp-requirements.txt

RUN pip install --no-cache-dir \
    -r /tmp/acp-requirements.txt \
    -r /tmp/mcp-requirements.txt

COPY custodian_acp /app/custodian_acp
COPY custodian_mcp /app/custodian_mcp

EXPOSE 7331

CMD ["python", "custodian_acp/websocket_server.py", "--host", "0.0.0.0", "--port", "7331", "--verbose"]