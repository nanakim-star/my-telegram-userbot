import os
import asyncio
from telethon.sync import TelegramClient

# --- 설정 (자동으로 불러옴) ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_FILE = 'userbot.session'

async def main():
    print("사용자 계정이 참여 중인 모든 그룹/채널의 ID를 확인합니다...")
    
    # 텔레그램 클라이언트 생성 및 연결
    client = TelegramClient(SESSION_FILE, int(API_ID), API_HASH)
    await client.connect()

    print("="*30)
    # 모든 대화방(dialogs)을 가져옴
    async for dialog in client.iter_dialogs():
        # is_group 또는 is_channel이 True인 경우 (그룹 또는 채널인 경우)
        if dialog.is_group or dialog.is_channel:
            # 방 이름과 ID를 출력
            print(f"이름: {dialog.title}")
            print(f"ID: {dialog.id}")
            print("-"*30)
            
    await client.disconnect()
    print("확인이 완료되었습니다.")

# 스크립트 실행
if __name__ == "__main__":
    asyncio.run(main())