import asyncio
import websockets
import json

async def test():
    async with websockets.connect('ws://localhost:8000/api/ws/prices?token=dev-bypass') as ws:
        msg = await ws.recv() # initial-snapshot
        print("Initial:", len(msg))
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if data.get("event") == "sector-tick":
                print(json.dumps(data, indent=2, ensure_ascii=False))
                break

asyncio.run(test())
