import asyncio
from backend.app.core.settings_store import load_settings_for_editing

async def main():
    settings = await load_settings_for_editing()
    for k in ['kiwoom_app_key_real', 'kiwoom_app_secret_real', 'kiwoom_account_no_real']:
        print(f"{k}: {repr(settings.get(k))}")

if __name__ == '__main__':
    asyncio.run(main())
