import os
import base64
import asyncio
import httpx
from fastapi import FastAPI, Response, Request, HTTPException
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


def decode_base64(data: str) -> str:
    """Безопасное декодирование base64 с восстановлением паддинга."""
    data = data.strip()
    if not data:
        return ""
    try:
        padding = 4 - (len(data) % 4)
        if padding != 4:
            data += "=" * padding
        return base64.b64decode(data).decode('utf-8', errors='ignore')
    except Exception as e:
        logger.error(f"Decoding error: {e}")
        return ""


@app.get("/{path:path}")
async def proxy_subscription(path: str, request: Request):
    """
    Перехватывает любой путь после порта (например, /sub_path/uuid).
    """
    servers_env = os.getenv("SERVERS", "")
    # Разделяем по пробелам или запятым
    servers = [s.strip() for s in servers_env.replace(',', ' ').split() if s.strip()]

    if not servers:
        logger.error("SERVERS env variable is empty")
        raise HTTPException(status_code=500, detail="Configuration error: No servers")

    # path здесь содержит путь из URL, например "mysecretpath/1234-5678..."
    # Нам нужно приклеить этот хвост к базовым URL серверов.

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        tasks = []
        for server_base in servers:
            # Убираем конечный слеш у базы и начальный у пути, чтобы не дублировать
            base = server_base.rstrip('/')
            clean_path = path.lstrip('/')
            url = f"{base}/{clean_path}"

            logger.info(f"Fetching from: {url}")
            tasks.append(client.get(url))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    collected_configs = []

    for i, response in enumerate(results):
        if isinstance(response, httpx.Response) and response.status_code == 200:
            decoded = decode_base64(response.text)
            if decoded:
                collected_configs.append(decoded)
            else:
                logger.warning(f"Server {servers[i]} returned empty or invalid base64")
        else:
            error_msg = response if not isinstance(response, httpx.Response) else response.status_code
            logger.error(f"Failed to fetch from {servers[i]}: {error_msg}")

    if not collected_configs:
        raise HTTPException(status_code=404, detail="No subscriptions found")

    # Объединяем и кодируем обратно
    full_config = "".join(collected_configs)
    encoded_config = base64.b64encode(full_config.encode('utf-8')).decode('utf-8')

    return Response(content=encoded_config, media_type="text/plain; charset=utf-8")
