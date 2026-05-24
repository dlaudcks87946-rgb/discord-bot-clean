import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread
import asyncio

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

# Run Flask server and start Discord bot
keep_alive()
bot.run(os.getenv("TOKEN"))