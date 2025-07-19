import os
from telethon.sync import TelegramClient

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not all([API_ID, API_HASH]):
    print("오류: API_ID와 API_HASH를 먼저 Codespaces Secrets에 등록해주세요.")
else:
    # 'userbot' 이라는 이름의 세션 파일을 생성합니다.
    with TelegramClient('userbot', int(API_ID), API_HASH) as client:
        print("세션 파일 생성을 시작합니다...")
        me = client.get_me()
        print(f"로그인 성공! 사용자: {me.first_name}")
        print("userbot.session 파일이 성공적으로 생성되었습니다.")