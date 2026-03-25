import asyncio
import aiohttp
import json
import datetime
import os

HA_URL = "http://homeassistant.local:8123"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI1ZTYxYzgwODY5NjY0ZjZkODQ1YjY5NTZkZWRiMDI2YiIsImlhdCI6MTc3MzMyMTQ4MCwiZXhwIjoyMDg4NjgxNDgwfQ.QPcRgynFSwWlpP0t1HuHg-nECBoyfA43-bGYCzepm2A"
LIGHT_ENTITY_ID = "light.eveready_rgbcct_led_bc_gls"
FLIC_ENTITY_ID = "binary_sensor.flic_80e4da79f712"
TAPO_ENTITY_ID = "switch.tapo_P110"
LOG_DIR = "home_assistant_logs"

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# Generate session filename based on current timestamp
session_start = datetime.datetime.now()
LOG_FILE = os.path.join(LOG_DIR, f"session_{session_start.strftime('%Y%m%d_%H%M%S')}.jsonl")

def save_to_file(data):
    with open(LOG_FILE, 'a') as f:
        json.dump(data, f)
        f.write('\n')

async def monitor_light():
    previous_brightness = None
    previous_color = None
    previous_last_changed = None

    while True:
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HA_URL}/api/states/{LIGHT_ENTITY_ID}", headers=headers) as resp:
                data = await resp.json()
                attributes = data.get('attributes', {})
                brightness = attributes.get('brightness')
                color_mode = attributes.get('color_mode')
                
                if color_mode == 'color_temp':
                    color = f"Color Temp: {attributes.get('color_temp_kelvin')}K"
                elif color_mode == 'hs':
                    color = f"HS: {attributes.get('hs_color')}"
                else:
                    color = "Unknown"
                
                last_changed = data.get('last_changed')
                
                if brightness != previous_brightness or color != previous_color or last_changed != previous_last_changed:
                    event_data = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "light_change",
                        "brightness": brightness,
                        "color": color,
                        "last_changed": last_changed
                    }
                    save_to_file(event_data)
                    
                    print(f"Brightness: {brightness}")
                    print(f"Colour: {color}")
                    print(f"Time changed: {last_changed}")
                    print("---")
                    
                    previous_brightness = brightness
                    previous_color = color
                    previous_last_changed = last_changed
        
        await asyncio.sleep(1)  # Poll every 1 second

async def monitor_flic():
    previous_state = None
    previous_last_changed = None

    while True:
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HA_URL}/api/states/{FLIC_ENTITY_ID}", headers=headers) as resp:
                data = await resp.json()
                state = data.get('state')
                last_changed = data.get('last_changed')
                attributes = data.get('attributes', {})
                
                if state != previous_state or last_changed != previous_last_changed:
                    event_data = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "flic_press",
                        "state": state,
                        "last_changed": last_changed,
                        "attributes": attributes
                    }
                    save_to_file(event_data)
                    
                    print(f"Flic Button State: {state}")
                    print(f"Flic Last Changed: {last_changed}")
                    print(f"Flic Attributes: {json.dumps(attributes, indent=2)}")
                    print("---")
                    
                    previous_state = state
                    previous_last_changed = last_changed
        
        await asyncio.sleep(1)  # Pull every 1 second

async def monitor_tapo():
    previous_state = None
    previous_last_changed = None

    while True:
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HA_URL}/api/states/{TAPO_ENTITY_ID}", headers=headers) as resp:
                data = await resp.json()
                state = data.get('state')
                last_changed = data.get('last_changed')
                attributes = data.get('attributes', {})

                if state != previous_state or last_changed != previous_last_changed:
                    event_data = {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "type": "tapo_p110_change",
                        "entity_id": TAPO_ENTITY_ID,
                        "state": state,
                        "last_changed": last_changed,
                        "attributes": attributes
                    }
                    save_to_file(event_data)

                    print(f"Tapo P110 State: {state}")
                    print(f"Tapo P110 Last Changed: {last_changed}")
                    print(f"Tapo P110 Attributes: {json.dumps(attributes, indent=2)}")
                    print("---")

                    previous_state = state
                    previous_last_changed = last_changed

        await asyncio.sleep(1)  # Pull every 1 second

async def main():
    print(f"Starting new session. Logging to: {LOG_FILE}")
    await asyncio.gather(
        monitor_light(),
        monitor_flic(),
        monitor_tapo()
    )

asyncio.run(main())