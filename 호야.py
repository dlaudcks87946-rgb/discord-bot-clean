# test deploy
import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread
import asyncio
import sqlite3

# DB 파일 연결 및 테이블 생성
db_path = "bot_data.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS left_users (
    user_id INTEGER PRIMARY KEY
)
""")
conn.commit()
conn.close()

# Flask Web Server to keep the bot alive
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Intents configuration
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

# Bot initialization
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name} ({bot.user.id})")
    try:
        # Sync slash commands
        synced = await bot.tree.sync()
        print(f"✅ 슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as e:
        print(f"❌ 슬래시 명령어 동기화 오류: {e}")

# 양식 입력 확인 및 역할 제거 이벤트
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 지정한 채널 ID 확인
    if message.channel.id == 1497843456960364726:
        content = message.content
        # 양식에 필요한 핵심 키워드들이 모두 포함되어 있는지 검사
        keywords = ["닉네임/나이", "주로하는 게임", "플레이 시간대", "소개글"]
        if all(kw in content for kw in keywords):
            member = message.author
            if isinstance(member, discord.Member):
                target_role_id = 1369712767631626313
                role = message.guild.get_role(target_role_id)
                if role:
                    if role in member.roles:
                        try:
                            await member.remove_roles(role)
                            await message.add_reaction("✅")
                            # 안내 메시지 전송 후 5초 뒤 자동 삭제
                            msg = await message.reply(f"✅ 양식 작성이 확인되어 **{role.name}** 역할이 제거되었습니다.", mention_author=False)
                            await asyncio.sleep(5)
                            await msg.delete()
                        except discord.Forbidden:
                            print(f"❌ 권한 부족: '{role.name}' 역할을 제거할 수 없습니다. 봇의 역할 서열을 올려주세요.")
                        except Exception as e:
                            print(f"❌ 역할 제거 오류: {e}")
                    else:
                        # 이미 역할이 없는 경우에도 확인 리액션은 달아줌
                        await message.add_reaction("✅")
                else:
                    print(f"❌ 오류: 역할 ID {target_role_id}를 서버에서 찾을 수 없습니다.")

    await bot.process_commands(message)

# 유저 퇴장 감지 이벤트
@bot.event
async def on_member_remove(member):
    # 유저가 서버를 나가면 DB에 기록
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO left_users (user_id) VALUES (?)", (member.id,))
        conn.commit()
        conn.close()
        print(f"📥 유저 퇴장 기록 완료: {member.name} ({member.id})")
    except Exception as e:
        print(f"❌ 퇴장 기록 중 오류 발생: {e}")

# 유저 입장 감지 이벤트
@bot.event
async def on_member_join(member):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM left_users WHERE user_id = ?", (member.id,))
        row = cursor.fetchone()
        
        if row:
            # 이전에 나갔던 기록이 있는 유저가 다시 들어온 경우
            channel_id = 1498300372479901817
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(f"👤 **재입장 감지:** <@{member.id}> (ID: {member.id}) 님이 서버에 다시 입장하셨습니다.")
                except Exception as send_err:
                    print(f"❌ 메시지 전송 실패: {send_err}")
            else:
                print(f"❌ 알림 채널({channel_id})을 찾을 수 없습니다.")
                
            # 기록에서 삭제
            cursor.execute("DELETE FROM left_users WHERE user_id = ?", (member.id,))
            conn.commit()
            print(f"📤 재입장 확인 후 DB 기록 삭제: {member.name} ({member.id})")
            
        conn.close()
    except Exception as e:
        print(f"❌ 입장 확인 중 오류 발생: {e}")

# 동적 음성 채널 생성 이벤트
@bot.event
async def on_voice_state_update(member, before, after):
    # 허브 채널 및 대상 설정
    HUB_CHANNEL_ID = 1510992054174351510
    CATEGORY_ID = 1370683863096889384
    NEW_CHANNEL_NAME = "🫧・『 싱글게임 』"

    # 1. 허브 채널 입장 감지 및 채널 생성
    if after.channel and after.channel.id == HUB_CHANNEL_ID:
        guild = member.guild
        category = guild.get_channel(CATEGORY_ID)
        
        if category and isinstance(category, discord.CategoryChannel):
            try:
                # 지정된 카테고리 하위에 새 음성 채널 생성
                new_channel = await guild.create_voice_channel(
                    name=NEW_CHANNEL_NAME,
                    category=category
                )
                print(f"🔊 새 음성 채널 생성 완료: '{NEW_CHANNEL_NAME}' (ID: {new_channel.id})")
                
                # 유저를 생성된 채널로 이동
                await member.move_to(new_channel)
                print(f"➡️ {member.name} 님을 '{NEW_CHANNEL_NAME}' 채널로 이동시켰습니다.")
            except discord.Forbidden:
                print("❌ 권한 부족: 채널 생성 또는 멤버 이동 권한이 없습니다.")
            except Exception as e:
                print(f"❌ 음성 채널 생성/이동 중 오류 발생: {e}")
        else:
            print(f"❌ 오류: 카테고리 ID {CATEGORY_ID}를 찾을 수 없거나 올바른 카테고리가 아닙니다.")

    # 2. 유저 퇴장 감지 및 빈 임시 채널 삭제
    if before.channel and before.channel != after.channel:
        # 퇴장한 채널이 대상 카테고리에 속해 있고, 허브 채널이 아닌 경우
        if before.channel.category and before.channel.category.id == CATEGORY_ID:
            if before.channel.id != HUB_CHANNEL_ID:
                # 채널이 비어 있는지 확인 (멤버 수가 0인 경우)
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                        print(f"🗑️ 빈 음성 채널 삭제 완료: {before.channel.name} (ID: {before.channel.id})")
                    except discord.Forbidden:
                        print("❌ 권한 부족: 채널을 삭제할 수 없습니다.")
                    except Exception as e:
                        print(f"❌ 음성 채널 삭제 중 오류 발생: {e}")

# Run Flask server and start Discord bot
keep_alive()
bot.run(os.getenv("TOKEN"))