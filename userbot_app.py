import os
import asyncio
import sqlite3
from urllib.parse import urlparse
import psycopg2
import datetime
import random
import re
import csv
import io
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import FloodWaitError, UserIsBlockedError, PeerFloodError

# --- 기본 설정 ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
DATABASE_URL = os.getenv('DATABASE_URL')
PHOTO_STORAGE_ID_STR = os.getenv('PHOTO_STORAGE_ID')
PHOTO_STORAGE_ID = int(PHOTO_STORAGE_ID_STR) if PHOTO_STORAGE_ID_STR else None

app = Flask(__name__)
# UPLOAD_FOLDER 설정은 더 이상 필요 없습니다.

# --- 데이터베이스 연결 함수 ---
def get_db_connection():
    if DATABASE_URL:
        url = urlparse(DATABASE_URL)
        return psycopg2.connect(dbname=url.path.split('?', 1)[0][1:], user=url.username, password=url.password, host=url.hostname, port=url.port)
    else:
        return sqlite3.connect('bot_config.db')

# --- DB 헬퍼 함수 ---
def query_db(query, args=(), one=False):
    with get_db_connection() as conn:
        is_postgres = hasattr(conn, 'tpc_begin')
        if is_postgres: query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, args)
        if query.lower().strip().startswith(('insert', 'update', 'delete')):
            conn.commit()
            return
        rv = [dict((cursor.description[_idx][0], value) for _idx, value in enumerate(row)) for row in cursor.fetchall()]
        return (rv[-1] if rv else None) if one else rv

def execute_db(query, args=()):
    with get_db_connection() as conn:
        is_postgres = hasattr(conn, 'tpc_begin')
        if is_postgres: query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, args)
        conn.commit()

# --- 스핀택스 처리 함수 ---
def process_spintax(text):
    pattern = re.compile(r'{([^{}]*)}')
    while True:
        match = pattern.search(text)
        if not match: break
        options = match.group(1).split('|')
        choice = random.choice(options)
        text = text[:match.start()] + choice + text[_match.end():]
    return text

# --- 데이터베이스 초기화 ---
def init_db():
    is_postgres = bool(DATABASE_URL)
    config_table_sql = '''CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, message TEXT, photo TEXT, interval_min INTEGER, interval_max INTEGER, scheduler_status TEXT, preview_id TEXT)'''
    promo_rooms_table_sql = f'''CREATE TABLE IF NOT EXISTS promo_rooms (id {'SERIAL' if is_postgres else 'INTEGER'} PRIMARY KEY {'AUTOINCREMENT' if not is_postgres else ''}, chat_id TEXT NOT NULL UNIQUE, room_name TEXT, room_group TEXT DEFAULT '기본', is_active INTEGER DEFAULT 1, last_status TEXT DEFAULT '확인 안됨')'''
    activity_log_table_sql = f'''CREATE TABLE IF NOT EXISTS activity_log (id {'SERIAL' if is_postgres else 'INTEGER'} PRIMARY KEY {'AUTOINCREMENT' if not is_postgres else ''}, timestamp {'TIMESTAMPTZ' if is_postgres else 'DATETIME'} DEFAULT CURRENT_TIMESTAMP, details TEXT)'''
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(config_table_sql)
        cursor.execute(promo_rooms_table_sql)
        cursor.execute(activity_log_table_sql)
        cursor.execute("SELECT * FROM config WHERE id = 1")
        if not cursor.fetchone():
            placeholder = '%s' if is_postgres else '?'
            insert_sql = f"INSERT INTO config (id, message, photo, interval_min, interval_max, scheduler_status, preview_id) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})"
            cursor.execute(insert_sql, (1, '', '', 30, 40, 'running', ''))
        conn.commit()

# --- Telethon(Userbot) 핵심 로직 ---
async def send_userbot_message(client, chat_id, message_template, photo_message_id):
    final_message = process_spintax(message_template)
    try:
        target_entity = int(chat_id)
    except ValueError:
        target_entity = chat_id

    if photo_message_id and PHOTO_STORAGE_ID:
        try:
            photo_message = await client.get_messages(PHOTO_STORAGE_ID, ids=int(photo_message_id))
            if photo_message and photo_message.media:
                # 파일 경로 대신 media 객체를 직접 전달
                await client.send_file(target_entity, file=photo_message.media, caption=final_message)
            else:
                await client.send_message(target_entity, final_message)
        except Exception as e:
            print(f"사진 메시지({photo_message_id}) 처리 중 오류: {e}")
            await client.send_message(target_entity, final_message)
    else:
        await client.send_message(target_entity, final_message)

async def scheduled_send():
    config = query_db("SELECT * FROM config WHERE id = 1", one=True)
    if not config or config.get('scheduler_status') != 'running':
        print("스케줄러가 '일시정지' 상태이거나 설정이 없습니다.")
        return

    active_rooms = query_db("SELECT chat_id FROM promo_rooms WHERE is_active = 1")
    log_detail = ""
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

    try:
        if not config.get('message') or not active_rooms:
            raise ValueError("홍보 메시지 또는 대상 방이 설정되지 않았습니다.")

        await client.connect()
        photo_msg_id = config.get('photo')

        for room in active_rooms:
            try:
                await send_userbot_message(client, room['chat_id'], config['message'], photo_msg_id)
                await asyncio.sleep(random.randint(5, 15))
            except (FloodWaitError, PeerFloodError) as e:
                log_detail = f"❌ [Userbot] 스팸 제한 오류, {e.seconds}초 대기합니다."
                await asyncio.sleep(e.seconds + 60)
                break
            except Exception as e:
                log_detail += f"❌ {room['chat_id']} 발송 실패: {e}\n"

        if not log_detail:
            log_detail = f"✅ [Userbot] {len(active_rooms)}개 활성 방에 메시지 발송 완료"
    except Exception as e:
        log_detail = f"❌ [Userbot] 스케줄러 오류: {e}"
    finally:
        if client.is_connected():
            await client.disconnect()
        execute_db("INSERT INTO activity_log (details) VALUES (?)", (log_detail,))
        print(log_detail)

# --- 스케줄러 설정 ---
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Seoul')

# --- 관리자 페이지 및 API 라우트 ---
@app.route('/', methods=['GET', 'POST'])
async def admin_page():
    page_message = None
    if request.method == 'POST':
        message, preview_id = request.form.get('message'), request.form.get('preview_id')
        interval_min = int(request.form.get('interval_min', 30))
        interval_max = int(request.form.get('interval_max', 40))
        photo_file = request.files.get('photo')

        current_config = query_db("SELECT * FROM config WHERE id = 1", one=True)
        photo_msg_id = current_config['photo']

        if photo_file and photo_file.filename:
            if not PHOTO_STORAGE_ID:
                page_message = "❌ 사진 저장용 채널 ID가 설정되지 않았습니다."
            else:
                client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
                try:
                    await client.connect()
                    uploaded_message = await client.send_file(PHOTO_STORAGE_ID, file=photo_file, caption=photo_file.filename)
                    photo_msg_id = uploaded_message.id
                except Exception as e:
                    page_message = f"사진 업로드 실패: {e}"
                finally:
                    if client.is_connected(): await client.disconnect()

        execute_db("UPDATE config SET message=?, photo=?, interval_min=?, interval_max=?, preview_id=? WHERE id = 1", (message, photo_msg_id, interval_min, interval_max, preview_id))

        if not page_message: page_message = "✅ 설정이 성공적으로 저장되었습니다."

    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
    sent_today_query = "SELECT COUNT(*) as count FROM activity_log WHERE details LIKE '✅%%' AND DATE(timestamp, '+9 hours') = ?" if not DATABASE_URL else "SELECT COUNT(*) as count FROM activity_log WHERE details LIKE '✅%%' AND (timestamp AT TIME ZONE 'utc' AT TIME ZONE 'Asia/Seoul')::date = CURRENT_DATE"
    sent_today = query_db(sent_today_query, (today,) if not DATABASE_URL else (), one=True)['count']
    log_query = "SELECT strftime('%Y-%m-%d %H:%M:%S', timestamp, '+9 hours') as ts, details FROM activity_log ORDER BY id DESC LIMIT 5" if not DATABASE_URL else "SELECT to_char(timestamp AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') as ts, details FROM activity_log ORDER BY id DESC LIMIT 5"
    recent_logs = query_db(log_query)
    promo_rooms = query_db("SELECT * FROM promo_rooms ORDER BY room_group, room_name")
    config = query_db("SELECT * FROM config WHERE id = 1", one=True)
    dashboard_data = {'sent_today': sent_today, 'recent_logs': recent_logs, 'room_count': len(promo_rooms)}
    return render_template('admin.html', config=config, message=page_message, dashboard=dashboard_data, promo_rooms=promo_rooms, scheduler_state=scheduler.state)

@app.route('/preview', methods=['POST'])
async def preview_message():
    try:
        preview_id, message_template = request.form.get('preview_id'), request.form.get('message')
        photo_file = request.files.get('photo')
        if not preview_id or not message_template: return jsonify({'message': 'ID와 메시지를 입력해주세요.'}), 400

        client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
        await client.connect()
        try:
            final_message = process_spintax(message_template)
            if photo_file and photo_file.filename:
                await client.send_file(preview_id, file=photo_file, caption=final_message)
            else:
                config = query_db("SELECT photo FROM config WHERE id = 1", one=True)
                photo_msg_id = config.get('photo')
                await send_userbot_message(client, preview_id, final_message, photo_msg_id)
            return jsonify({'message': f'✅ {preview_id}로 미리보기 발송 성공.'})
        finally:
            if client.is_connected(): await client.disconnect()
    except Exception as e:
        return jsonify({'message': f'❌ 미리보기 전송 실패: {e}'}), 500

# (이하 /add_room, /delete_room 등 모든 다른 API 라우트는 이전과 동일)
@app.route('/add_room', methods=['POST'])
def add_room():
    chat_id, room_name, room_group = request.form.get('chat_id'), request.form.get('room_name'), request.form.get('room_group')
    if not chat_id: return "Chat ID는 필수입니다.", 400
    try:
        execute_db("INSERT INTO promo_rooms (chat_id, room_name, room_group) VALUES (?, ?, ?)", (chat_id, room_name, room_group))
    except (psycopg2.IntegrityError, sqlite3.IntegrityError):
        return "이미 존재하는 Chat ID 입니다.", 400
    return "성공적으로 추가되었습니다."

@app.route('/delete_room/<int:room_id>', methods=['POST'])
def delete_room(room_id):
    execute_db("DELETE FROM promo_rooms WHERE id = ?", (room_id,))
    return "삭제되었습니다."

@app.route('/import_rooms', methods=['POST'])
def import_rooms():
    file = request.files.get('file')
    if not file: return "파일이 없습니다.", 400
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    reader = csv.reader(stream)
    next(reader, None)
    for row in reader:
        if len(row) >= 3:
            try:
                execute_db("INSERT INTO promo_rooms (chat_id, room_name, room_group) VALUES (?, ?, ?) ON CONFLICT (chat_id) DO NOTHING", (row[_idx], row[_idx+1], row[_idx+2]))
            except (psycopg2.IntegrityError, sqlite3.IntegrityError):
                continue
    return "가져오기 완료!"

@app.route('/export_rooms')
def export_rooms():
    rows = query_db("SELECT chat_id, room_name, room_group FROM promo_rooms")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Chat ID', 'Room Name', 'Group'])
    for row in rows:
        writer.writerow([row['chat_id'], row['room_name'], row['room_group']])
    encoded_output = output.getvalue().encode('utf-8-sig')
    return Response(encoded_output, mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=rooms.csv"})

@app.route('/toggle_scheduler/<string:action>', methods=['POST'])
def toggle_scheduler(action):
    status_to_set = 'paused' if action == 'pause' else 'running'
    try:
        if action == 'pause' and scheduler.state == 1: scheduler.pause()
        elif action == 'resume' and scheduler.state == 2: scheduler.resume()
        execute_db("UPDATE config SET scheduler_status = ? WHERE id = 1", (status_to_set,))
        return f"스케줄러가 {status_to_set} 상태가 되었습니다."
    except Exception as e:
        return f"오류 발생: {e}", 500

@app.route('/check_rooms', methods=['POST'])
async def check_rooms():
    rooms = query_db("SELECT id, chat_id FROM promo_rooms")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.connect()

    for room in rooms:
        status = ''
        try:
            entity = await client.get_entity(int(room['chat_id']))
            status = f"✅ OK ({getattr(entity, 'title', 'N/A')})"
        except Exception as e:
            status = f"❌ Error: {e.__class__.__name__}"

        execute_db("UPDATE promo_rooms SET last_status = ? WHERE id = ?", (status, room['id']))

    await client.disconnect()
    return "상태 확인 완료!"

@app.route('/dialogs')
async def dialogs_page():
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    dialog_list = []
    try:
        await client.connect()
        registered_rooms = query_db("SELECT chat_id FROM promo_rooms")
        registered_ids = {str(room['chat_id']) for room in registered_rooms}
        async for dialog in client.iter_dialogs():
            dialog_type = "유저"
            if dialog.is_group: dialog_type = "그룹"
            if dialog.is_channel: dialog_type = "채널"
            dialog_list.append({'name': dialog.name, 'id': dialog.id, 'type': dialog_type, 'is_registered': str(dialog.id) in registered_ids})
    except Exception as e:
        print(f"대화방 목록 로딩 오류: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
    return render_template('dialogs.html', dialogs=dialog_list)

@app.route('/register_all', methods=['POST'])
async def register_all():
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    try:
        await client.connect()
        registered_rooms = query_db("SELECT chat_id FROM promo_rooms")
        registered_ids = {str(room['chat_id']) for room in registered_rooms}
        count = 0
        async for dialog in client.iter_dialogs():
            if (dialog.is_group or dialog.is_channel) and str(dialog.id) not in registered_ids:
                execute_db("INSERT INTO promo_rooms (chat_id, room_name, room_group) VALUES (?, ?, ?) ON CONFLICT (chat_id) DO NOTHING",(str(dialog.id), dialog.name, '기본'))
                count += 1
        print(f"{count}개의 새로운 방을 등록했습니다.")
    except Exception as e:
        print(f"전체 등록 중 오류: {e}")
    finally:
        if client.is_connected():
            await client.disconnect()
    return "<script>alert('미등록된 그룹/채널을 모두 등록했습니다!'); window.location.href='/dialogs';</script>"

@app.route('/register_selected', methods=['POST'])
def register_selected():
    selected_rooms = request.form.getlist('selected_rooms')
    count = 0
    for room_data in selected_rooms:
        chat_id, room_name = room_data.split('|', 1)
        try:
            execute_db("INSERT INTO promo_rooms (chat_id, room_name, room_group) VALUES (?, ?, ?) ON CONFLICT (chat_id) DO NOTHING",(chat_id, room_name, '기본'))
            count += 1
        except Exception as e:
            print(f"선택 등록 중 오류: {e}")
    return f"<script>alert('{count}개의 방을 선택하여 등록했습니다!'); window.location.href='/dialogs';</script>"


# --- 애플리케이션 실행 ---
init_db()

if __name__ == '__main__':
    config = query_db("SELECT interval_min, interval_max FROM config WHERE id = 1", one=True)
    interval_min = config['interval_min'] if config else 30
    interval_max = config['interval_max'] if config else 40

    scheduler.add_job(lambda: asyncio.run(scheduled_send()), 'interval', minutes=random.randint(interval_min, interval_max), id='promo_job')
    scheduler.start()

    execute_db("UPDATE config SET scheduler_status = ? WHERE id = 1", ('running',))

    print("Userbot 데이터베이스와 스케줄러가 준비되었습니다.")
    app.run(host='0.0.0.0', port=8080)
