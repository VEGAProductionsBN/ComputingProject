import asyncio
import aiohttp
import json
import os

def load_env_file(file_path):
    if not os.path.exists(file_path):
        return

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_env_file(ENV_PATH)

HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123")
TOKEN = os.getenv("HA_TOKEN")
ENTITY_ID = os.getenv("LIGHT_ENTITY_ID", "light.eveready_rgbcct_led_bc_gls")

if not TOKEN:
    raise RuntimeError("Missing HA_TOKEN. Set it in environment or MetadataCollection/.env")

async def get_light_metadata():
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/api/states/{ENTITY_ID}", headers=headers) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=4))

asyncio.run(get_light_metadata())