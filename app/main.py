import os
import base64
import asyncio
import httpx
from fastapi import FastAPI, Response, Request, HTTPException
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


def decode_base64(data: str) -> str:
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
    servers_env = os.getenv("SERVERS", "")
    servers = [s.strip() for s in servers_env.replace(',', ' ').split() if s.strip()]

    if not servers:
        raise HTTPException(status_code=500, detail="Configuration error: No servers")

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        tasks = []
        for server_base in servers:
            base = server_base.rstrip('/')
            clean_path = path.lstrip('/')
            url = f"{base}/{clean_path}"
            logger.info(f"Fetching from: {url}")
            tasks.append(client.get(url))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    collected_configs = []
    # Переменная для хранения имени файла (названия подписки)
    subscription_filename = "VPN-Subscription"

    for i, response in enumerate(results):
        if isinstance(response, httpx.Response) and response.status_code == 200:
            # Пытаемся вытащить имя подписки из заголовков первого сервера (обычно локального)
            # или любого другого, если имя еще не найдено
            if i == 0 or subscription_filename == "VPN-Subscription":
                content_disp = response.headers.get("content-disposition", "")
                if "filename=" in content_disp:
                    try:
                        # Парсим "filename="MySub"" -> MySub
                        parts = content_disp.split('filename=')
                        if len(parts) > 1:
                            fname = parts[1].strip().strip('"').strip("'")
                            if fname:
                                subscription_filename = fname
                    except Exception:
                        pass

            decoded = decode_base64(response.text)
            if decoded:
                collected_configs.append(decoded)
        else:
            logger.error(f"Failed fetch: {servers[i]}")

    if not collected_configs:
        raise HTTPException(status_code=404, detail="No subscriptions found")

    full_config = "".join(collected_configs)
    encoded_config = base64.b64encode(full_config.encode('utf-8')).decode('utf-8')

    # Возвращаем ответ с заголовком
    return Response(
        content=encoded_config,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{subscription_filename}"',
            "Profile-Update-Interval": "24",  # Частота обновления (в часах) для некоторых клиентов
            "Subscription-Userinfo": ""  # Можно добавить инфу о трафике, если нужно заморочиться
        }
    )
