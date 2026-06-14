# test deploy
import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread
import asyncio
import sqlite3
import time
import datetime

# DB 파일 연결 및 테이블 생성
db_path = "bot_data.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS left_users (
    user_id INTEGER PRIMARY KEY
)
""")

# 마이그레이션 확인
try:
    cursor.execute("PRAGMA table_info(voice_usage);")
    columns = [info[1] for info in cursor.fetchall()]
    if columns and "use_date" not in columns:
        cursor.execute("DROP TABLE voice_usage;")
        print("⚠️ 마이그레이션: 기존 voice_usage 테이블을 삭제하고 새 스키마로 생성합니다.")
except Exception as migration_err:
    print(f"❌ 마이그레이션 검사 중 오류 발생: {migration_err}")

cursor.execute("""
CREATE TABLE IF NOT EXISTS voice_usage (
    user_id INTEGER,
    use_date TEXT,
    seconds INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, use_date)
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS voice_panel (
    channel_id INTEGER PRIMARY KEY,
    message_id INTEGER
)
""")
conn.commit()
conn.close()

# Active voice sessions tracking (user_id -> join_timestamp)
active_sessions = {}

def get_current_date():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def get_recent_dates():
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT use_date FROM voice_usage ORDER BY use_date DESC LIMIT 30")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"❌ 날짜 목록 조회 중 오류 발생: {e}")
        return []

def add_voice_time(user_id, use_date, seconds):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT seconds FROM voice_usage WHERE user_id = ? AND use_date = ?", (user_id, use_date))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE voice_usage SET seconds = seconds + ? WHERE user_id = ? AND use_date = ?", (seconds, user_id, use_date))
        else:
            cursor.execute("INSERT INTO voice_usage (user_id, use_date, seconds) VALUES (?, ?, ?)", (user_id, use_date, seconds))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ DB 이용시간 저장 중 오류 발생: {e}")

def get_realtime_today_stats():
    try:
        today_str = get_current_date()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, seconds FROM voice_usage WHERE use_date = ?", (today_str,))
        rows = cursor.fetchall()
        conn.close()
        
        stats = {user_id: seconds for user_id, seconds in rows}
        
        # 현재 음성 채널에 접속 중인 멤버들의 세션 시간 실시간 합산
        now = time.time()
        for uid, join_time in active_sessions.items():
            active_duration = int(now - join_time)
            if active_duration > 0:
                stats[uid] = stats.get(uid, 0) + active_duration
                
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        return sorted_stats
    except Exception as e:
        print(f"❌ 실시간 오늘의 통계 집계 중 오류 발생: {e}")
        return []

def get_realtime_cumulative_stats():
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, SUM(seconds) FROM voice_usage GROUP BY user_id")
        rows = cursor.fetchall()
        conn.close()
        
        stats = {user_id: (int(secs) if secs is not None else 0) for user_id, secs in rows}
        
        # 현재 음성 채널에 접속 중인 멤버들의 세션 시간 실시간 합산
        now = time.time()
        for uid, join_time in active_sessions.items():
            active_duration = int(now - join_time)
            if active_duration > 0:
                stats[uid] = stats.get(uid, 0) + active_duration
                
        sorted_stats = sorted(
            [(uid, secs) for uid, secs in stats.items() if secs > 0],
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_stats
    except Exception as e:
        print(f"❌ 실시간 누적 통계 집계 중 오류 발생: {e}")
        return []

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}시간")
    if minutes > 0:
        parts.append(f"{minutes}분")
    if secs > 0 or not parts:
        parts.append(f"{secs}초")
    return " ".join(parts)


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

class VoiceUsageView(discord.ui.View):
    def __init__(self, full_rows):
        super().__init__(timeout=86400)  # 24시간
        self.full_rows = full_rows

    @discord.ui.button(label="나머지 보기", style=discord.ButtonStyle.primary, custom_id="show_more_voice_usage")
    async def show_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📅 음성 채널 이용 시간 전체 랭킹",
            color=discord.Color.blue()
        )
        
        desc_lines = []
        for idx, (user_id, seconds) in enumerate(self.full_rows, 1):
            desc_lines.append(f"{idx}등: <@{user_id}> - {format_time(seconds)}")
            
        embed.description = "\n".join(desc_lines)
        
        # 버튼 제거
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)

class DateSelect(discord.ui.Select):
    def __init__(self, dates, placeholder="조회할 날짜를 선택하세요..."):
        options = [
            discord.SelectOption(label=f"{d}", value=d)
            for d in dates
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_date = self.values[0]
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, seconds FROM voice_usage WHERE use_date = ? ORDER BY seconds DESC", (selected_date,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            embed = discord.Embed(
                title=f"📅 {selected_date} 음성 채널 이용 시간 랭킹",
                description=f"{selected_date}에 음성 채널을 이용한 유저가 없습니다.",
                color=discord.Color.orange()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return
            
        embed = discord.Embed(
            title=f"📅 {selected_date} 음성 채널 이용 시간 랭킹",
            color=discord.Color.green()
        )
        
        top_5 = rows[:5]
        desc_lines = []
        for idx, (user_id, seconds) in enumerate(top_5, 1):
            desc_lines.append(f"{idx}등: <@{user_id}> - {format_time(seconds)}")
            
        if len(rows) > 5:
            desc_lines.append("\n*6등 이하의 기록은 아래 버튼을 눌러 확인하세요.*")
            embed.description = "\n".join(desc_lines)
            view = VoiceUsageView(rows)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            embed.description = "\n".join(desc_lines)
            await interaction.response.edit_message(embed=embed, view=None)

class DateSelectView(discord.ui.View):
    def __init__(self, dates):
        super().__init__(timeout=180)  # 3분 제한
        if len(dates) <= 15:
            self.add_item(DateSelect(dates, placeholder="조회할 날짜를 선택하세요..."))
        else:
            self.add_item(DateSelect(dates[:15], placeholder="최근 날짜 선택 (1~15일)..."))
            self.add_item(DateSelect(dates[15:30], placeholder="이전 날짜 선택 (16~30일)..."))

class VoiceUsagePanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 영구적인 뷰

    @discord.ui.button(label="오늘의 랭킹", style=discord.ButtonStyle.success, custom_id="check_voice_today_btn")
    async def check_today(self, interaction: discord.Interaction, button: discord.ui.Button):
        today_str = get_current_date()
        rows = get_realtime_today_stats()
        
        if not rows:
            embed = discord.Embed(
                title=f"📅 오늘의 음성 채널 이용 시간 랭킹 ({today_str})",
                description="오늘 음성 채널을 이용한 유저가 없습니다.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed = discord.Embed(
            title=f"📅 오늘의 음성 채널 이용 시간 랭킹 ({today_str})",
            color=discord.Color.green()
        )
        
        top_5 = rows[:5]
        desc_lines = []
        for idx, (user_id, seconds) in enumerate(top_5, 1):
            desc_lines.append(f"{idx}등: <@{user_id}> - {format_time(seconds)}")
            
        if len(rows) > 5:
            desc_lines.append("\n*6등 이하의 기록은 아래 버튼을 눌러 확인하세요.*")
            embed.description = "\n".join(desc_lines)
            view = VoiceUsageView(rows)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            embed.description = "\n".join(desc_lines)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="누적 전체 랭킹", style=discord.ButtonStyle.primary, custom_id="check_voice_cumulative_btn")
    async def check_cumulative(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = get_realtime_cumulative_stats()
        
        if not rows:
            embed = discord.Embed(
                title="🏆 누적 음성 채널 이용 시간 랭킹",
                description="누적된 음성 채널 이용 기록이 없습니다.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed = discord.Embed(
            title="🏆 누적 음성 채널 이용 시간 랭킹",
            color=discord.Color.gold()
        )
        
        top_5 = rows[:5]
        desc_lines = []
        for idx, (user_id, seconds) in enumerate(top_5, 1):
            desc_lines.append(f"{idx}등: <@{user_id}> - {format_time(seconds)}")
            
        if len(rows) > 5:
            desc_lines.append("\n*6등 이하의 기록은 아래 버튼을 눌러 확인하세요.*")
            embed.description = "\n".join(desc_lines)
            view = VoiceUsageView(rows)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            embed.description = "\n".join(desc_lines)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="날짜별 랭킹 조회", style=discord.ButtonStyle.secondary, custom_id="check_voice_select_date_btn")
    async def check_by_date(self, interaction: discord.Interaction, button: discord.ui.Button):
        dates = get_recent_dates()
        
        if not dates:
            embed = discord.Embed(
                title="📅 날짜별 랭킹 조회",
                description="조회 가능한 음성 채널 이용 기록이 데이터베이스에 존재하지 않습니다.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        embed = discord.Embed(
            title="📅 날짜별 랭킹 조회",
            description="아래 선택 메뉴에서 조회할 날짜를 선택해주세요.",
            color=discord.Color.blue()
        )
        view = DateSelectView(dates)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

def get_seconds_until_midnight():
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    midnight = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
    return (midnight - now).total_seconds()

async def daily_reset_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seconds = get_seconds_until_midnight()
        print(f"⏰ 다음 00시 데이터 분할 대기 시간: {seconds}초")
        await asyncio.sleep(seconds)
        
        try:
            # 현재 음성 채널에 남아 있는 유저들의 누적 시간을 어제 날짜로 기록하고 시작 시점을 자정으로 갱신
            now = time.time()
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            
            for uid, join_time in list(active_sessions.items()):
                duration = int(now - join_time)
                if duration > 0:
                    add_voice_time(uid, yesterday, duration)
                active_sessions[uid] = now
            print("📅 00시 정각: 자정 기준 음성 채널 이용 시간 데이터 정리가 완료되었습니다.")
        except Exception as e:
            print(f"❌ 일일 데이터 정리 중 오류 발생: {e}")
            
        await asyncio.sleep(10)

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name} ({bot.user.id})")
    
    # 1. 영구 뷰 등록
    bot.add_view(VoiceUsagePanel())
    
    # 2. 지정된 채널에 패널 메시지가 있는지 확인 및 자동 복구/생성
    target_channel_id = 1513160056214913144
    channel = bot.get_channel(target_channel_id)
    if channel:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT message_id FROM voice_panel WHERE channel_id = ?", (target_channel_id,))
            row = cursor.fetchone()
            panel_msg_id = row[0] if row else None
            
            panel_exists = False
            if panel_msg_id:
                try:
                    await channel.fetch_message(panel_msg_id)
                    panel_exists = True
                except discord.NotFound:
                    # 기존 메시지가 삭제됨
                    cursor.execute("DELETE FROM voice_panel WHERE channel_id = ?", (target_channel_id,))
                    conn.commit()
            
            if not panel_exists:
                embed = discord.Embed(
                    title="📊 음성 채널 이용 시간 조회",
                    description="아래 버튼을 누르면 오늘의 랭킹, 누적 전체 랭킹 또는 특정 날짜의 랭킹을 실시간으로 확인할 수 있습니다.",
                    color=discord.Color.blurple()
                )
                msg = await channel.send(embed=embed, view=VoiceUsagePanel())
                cursor.execute("INSERT OR REPLACE INTO voice_panel (channel_id, message_id) VALUES (?, ?)", (target_channel_id, msg.id))
                conn.commit()
                print(f"📊 이용 시간 조회 패널 메시지 생성 완료 (ID: {msg.id})")
            else:
                print("📊 이용 시간 조회 패널 메시지가 이미 존재합니다.")
            conn.close()
        except Exception as db_err:
            print(f"❌ 패널 메시지 확인/생성 중 DB 오류 발생: {db_err}")
    else:
        print(f"❌ 오류: 패널 채널 ID {target_channel_id}를 찾을 수 없습니다.")

    # 3. 현재 음성 채널에 있는 유저들 세션 초기화
    global active_sessions
    now = time.time()
    active_sessions.clear()
    voice_user_count = 0
    for guild in bot.guilds:
        for voice_channel in guild.voice_channels:
            for member in voice_channel.members:
                if not member.bot:
                    active_sessions[member.id] = now
                    voice_user_count += 1
    print(f"🎙️ 현재 음성 채널에 접속 중인 유저 {voice_user_count}명 세션 등록 완료")
    
    # 4. 일일 데이터 정렬/분할 스케줄러 태스크 시작
    asyncio.create_task(daily_reset_task())
    print("⏰ 일일 음성 채널 데이터 정리 태스크 시작 완료")

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
    # 최근 업데이트: 입장 시 1369712767631626313 부여 및 1497939431473287238 제거
    # 입장 시 역할 부여 (역할 ID: 1369712767631626313)
    target_role_id = 1369712767631626313
    role = member.guild.get_role(target_role_id)
    if role:
        try:
            await member.add_roles(role)
            print(f"✅ 역할 부여 완료: {member.name}에게 '{role.name}' 역할을 부여했습니다.")
        except discord.Forbidden:
            print(f"❌ 권한 부족: '{role.name}' 역할을 부여할 수 없습니다. 봇의 역할 서열을 올려주세요.")
        except Exception as e:
            print(f"❌ 역할 부여 중 오류 발생: {e}")
    else:
        print(f"❌ 오류: 역할 ID {target_role_id}를 서버에서 찾을 수 없습니다.")

    # 다른 자동화 시스템/봇에 의해 역할이 부여될 시간을 확보하기 위해 2초 대기 후 최신 멤버 정보 로드
    await asyncio.sleep(2)
    try:
        fresh_member = await member.guild.fetch_member(member.id)
    except Exception as fetch_err:
        print(f"❌ 최신 멤버 정보 로드 실패: {fetch_err}")
        fresh_member = member

    # 입장 시 역할 제거 (역할 ID: 1497939431473287238)
    remove_role_id = 1497939431473287238
    role_to_remove = member.guild.get_role(remove_role_id)
    if role_to_remove:
        try:
            await fresh_member.remove_roles(role_to_remove)
            print(f"✅ 역할 제거 완료: {fresh_member.name}에게서 '{role_to_remove.name}' 역할을 제거했습니다.")
        except discord.Forbidden:
            print(f"❌ 권한 부족: '{role_to_remove.name}' 역할을 제거할 수 없습니다. 봇의 역할 서열을 올려주세요.")
        except Exception as e:
            print(f"❌ 역할 제거 중 오류 발생: {e}")
    else:
        print(f"❌ 오류: 역할 ID {remove_role_id}를 서버에서 찾을 수 없습니다.")

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
    # 0. 음성 채널 이용 시간 기록
    if before.channel != after.channel:
        # 음성 채널에 새로 입장한 경우
        if before.channel is None and after.channel is not None:
            if not member.bot:
                active_sessions[member.id] = time.time()
                print(f"🎙️ 음성 채널 입장 감지: {member.name} ({member.id})")
        # 음성 채널에서 완전히 퇴장한 경우
        elif before.channel is not None and after.channel is None:
            if not member.bot:
                join_time = active_sessions.pop(member.id, None)
                if join_time:
                    duration = int(time.time() - join_time)
                    if duration > 0:
                        add_voice_time(member.id, get_current_date(), duration)
                        print(f"🎙️ 음성 채널 퇴장 감지: {member.name} ({member.id}) - 이용 시간: {duration}초 추가")

    # 다중 허브 채널 및 대상 설정
    CONFIGS = {
        1511038705932963991: {
            "category_id": 1357930212146286644,
            "channel_name": "⚡・『 메인게임 』"
        },
        1511037391765504130: {
            "category_id": 1427312936098992262,
            "channel_name": "💫・『 종합게임 』"
        },
        1510992054174351510: {
            "category_id": 1511040771241935069,
            "channel_name": "🫧・『 싱글게임 』"
        }
    }

    # 1. 허브 채널 입장 감지 및 채널 생성
    if after.channel and after.channel.id in CONFIGS:
        config = CONFIGS[after.channel.id]
        guild = member.guild
        category = guild.get_channel(config["category_id"])
        
        if category and isinstance(category, discord.CategoryChannel):
            try:
                # 지정된 카테고리 하위에 새 음성 채널 생성
                new_channel = await guild.create_voice_channel(
                    name=config["channel_name"],
                    category=category
                )
                print(f"🔊 새 음성 채널 생성 완료: '{config['channel_name']}' (ID: {new_channel.id})")
                
                # 유저를 생성된 채널로 이동
                await member.move_to(new_channel)
                print(f"➡️ {member.name} 님을 '{config['channel_name']}' 채널로 이동시켰습니다.")
            except discord.Forbidden:
                print("❌ 권한 부족: 채널 생성 또는 멤버 이동 권한이 없습니다.")
            except Exception as e:
                print(f"❌ 음성 채널 생성/이동 중 오류 발생: {e}")
        else:
            print(f"❌ 오류: 카테고리 ID {config['category_id']}를 찾을 수 없거나 올바른 카테고리가 아닙니다.")

    # 2. 유저 퇴장 감지 및 빈 임시 채널 삭제
    if before.channel and before.channel != after.channel:
        # 퇴장한 채널이 CONFIGS 설정 중 하나와 매칭되는지 확인
        for hub_id, config in CONFIGS.items():
            if before.channel.category and before.channel.category.id == config["category_id"]:
                if before.channel.name == config["channel_name"] and before.channel.id != hub_id:
                    # 채널이 비어 있는지 확인 (멤버 수가 0인 경우)
                    if len(before.channel.members) == 0:
                        try:
                            await before.channel.delete()
                            print(f"🗑️ 빈 음성 채널 삭제 완료: {before.channel.name} (ID: {before.channel.id})")
                        except discord.Forbidden:
                            print("❌ 권한 부족: 채널을 삭제할 수 없습니다.")
                        except Exception as e:
                            print(f"❌ 음성 채널 삭제 중 오류 발생: {e}")
                        break  # 채널이 매칭되어 삭제 처리되었으므로 루프 탈출

# Run Flask server and start Discord bot
keep_alive()
bot.run(os.getenv("TOKEN"))