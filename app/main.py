import os
import base64
import asyncio
import httpx
import urllib.parse

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

        return base64.b64decode(data).decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Decoding error: {e}")
        return ""


def create_dummy_link(text: str) -> str:
    """Создает нерабочую ссылку с нужным текстом в названии (больше не используется)."""
    # Кодируем текст для URL (пробелы -> %20 и т.д.)
    safe_name = urllib.parse.quote(text.strip())
    # UUID нулей, локальный адрес
    return (
        "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1234"
        "?encryption=none&security=none&type=tcp&headerType=none"
        f"#{safe_name}"
    )


@app.get("/{path:path}")
async def proxy_subscription(path: str, request: Request):
    servers_env = os.getenv("SERVERS", "")
    servers = [s.strip() for s in servers_env.replace(",", " ").split() if s.strip()]
    if not servers:
        raise HTTPException(status_code=500, detail="Configuration error: No servers")

    subscription_name = os.getenv("SUBSCRIPTION_NAME", "VPN-Subscription")
    info_text_env = os.getenv("INFO_TEXT", "")

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        tasks = []

        for server_base in servers:
            base = server_base.rstrip("/")
            clean_path = path.lstrip("/")
            url = f"{base}/{clean_path}"
            logger.info(f"Fetching from: {url}")
            tasks.append(client.get(url))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    collected_configs = []
    user_info_header = ""

    # Собираем реальные конфиги
    for i, response in enumerate(results):
        if isinstance(response, httpx.Response) and response.status_code == 200:
            # Пытаемся сохранить инфу о трафике (обычно от первого/локального сервера)
            if not user_info_header:
                # Ищем заголовок Subscription-Userinfo в любом регистре
                for k, v in response.headers.items():
                    if k.lower() == "subscription-userinfo":
                        user_info_header = v
                        break

            decoded = decode_base64(response.text)
            if decoded:
                # Добавляем перенос строки на всякий случай
                if collected_configs:
                    collected_configs.append("\n")
                collected_configs.append(decoded.strip())
        else:
            logger.error(f"Failed to fetch from {servers[i]}")

    if not collected_configs:
        raise HTTPException(status_code=404, detail="No subscriptions found")

    full_config = "\n".join(collected_configs)
    encoded_config = base64.b64encode(full_config.encode("utf-8")).decode("utf-8")

    # Формируем заголовки ответа
    response_headers = {
        "Content-Disposition": f'attachment; filename="{subscription_name}"',
        "Profile-Update-Interval": "24",
        "Content-Type": "text/plain; charset=utf-8",
        "profile-title": subscription_name[:25]
    }

    # Текстовые сообщения для Happ / Guava через заголовок announce
    if info_text_env:
        # Несколько сообщений через | -> несколько строк
        announce_text = info_text_env.replace("|", "\n").strip()
        # Рекомендуемый формат — base64 с префиксом base64:
        announce_b64 = base64.b64encode(announce_text.encode("utf-8")).decode("ascii")
        response_headers["announce"] = f"base64:{announce_b64}"

    # Если нашли инфу о трафике, добавляем её
    if user_info_header:
        response_headers["Subscription-Userinfo"] = user_info_header

    return Response(content=encoded_config, headers=response_headers)
