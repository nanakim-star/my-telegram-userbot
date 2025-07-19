import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not all([API_ID, API_HASH]):
    print("오류: API_ID와 API_HASH를 먼저 Codespaces Secrets에 등록해주세요.")
else:
    # 기존 세션 파일을 읽어와서 문자열로 변환합니다.
    with TelegramClient('userbot', int(API_ID), API_HASH) as client:
        string_session = StringSession.save(client.session)
        print("\n✅ 아래의 String Session 값을 복사하여 Render 환경 변수에 등록하세요.")
        print("="*50)
        print(string_session)
        print("="*50)
        print("\n이 값은 비밀번호와 같으니 절대로 다른 사람에게 공유하지 마세요.")