# test deploy
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import sys
import urllib.request
import json
from flask import Flask
from threading import Thread
import asyncio
import sqlite3
import psycopg2
import time
import datetime
import random
import re

DATABASE_URL = os.getenv("DATABASE_URL")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")

# ==========================================
# [임시 음성 채널 설정]
# ==========================================
TEMP_CHANNEL_CONFIG = {
    1511038705932963991: {
        "category_id": 1357930212146286644,
        "name": "⚡ㆍ메인 게임"
    },
    1511037391765504130: {
        "category_id": 1427312936098992262,
        "name": "💫ㆍ종합 게임"
    },
    1510992054174351510: {
        "category_id": 1511040771241935069,
        "name": "🔊ㆍ음성 채널"
    }
}

# 생성된 임시 채널 ID 추적용 집합
created_temp_channels = set()

def get_db_connection():
    if DATABASE_URL:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, "bot_data.db")
        return sqlite3.connect(db_path)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        print("🔌 [데이터베이스] Railway PostgreSQL 모드로 정상 연결되었습니다.")
    else:
        print("💾 [데이터베이스] 로컬 SQLite 모드로 연결되었습니다.")
    
    user_id_type = "BIGINT" if DATABASE_URL else "INTEGER"
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS left_users (
        user_id {user_id_type} PRIMARY KEY,
        last_application TEXT,
        last_messages TEXT
    )
    """)
    
    try:
        cursor.execute("ALTER TABLE left_users ADD COLUMN last_application TEXT")
        conn.commit()
    except Exception:
        if DATABASE_URL:
            try:
                conn.rollback()
            except Exception:
                pass
            
    try:
        cursor.execute("ALTER TABLE left_users ADD COLUMN last_messages TEXT")
        conn.commit()
    except Exception:
        if DATABASE_URL:
            try:
                conn.rollback()
            except Exception:
                pass
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS voice_usage (
        user_id {user_id_type},
        use_date TEXT,
        seconds INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, use_date)
    )
    """)
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS voice_panel (
        channel_id {user_id_type} PRIMARY KEY,
        message_id {user_id_type}
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS users (
        user_id {user_id_type} PRIMARY KEY,
        xp INTEGER DEFAULT 0,
        coin INTEGER DEFAULT 0,
        random_box INTEGER DEFAULT 0,
        premium_box INTEGER DEFAULT 0,
        jackpot_box INTEGER DEFAULT 0,
        booster_until BIGINT DEFAULT 0,
        voice_minutes INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS user_quests (
        user_id {user_id_type},
        quest_id TEXT,
        progress INTEGER DEFAULT 0,
        claimed INTEGER DEFAULT 0,
        quest_date TEXT,
        PRIMARY KEY (user_id, quest_id, quest_date)
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS lotto_tickets (
        id {"SERIAL" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"},
        user_id {user_id_type},
        round_no INTEGER,
        numbers TEXT,
        channel_id {user_id_type},
        is_checked INTEGER DEFAULT 0,
        match_count INTEGER DEFAULT 0,
        has_bonus INTEGER DEFAULT 0,
        prize_rank INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS lotto_results (
        round_no INTEGER PRIMARY KEY,
        numbers TEXT,
        bonus INTEGER,
        drawn_at TEXT
    )
    """)

    if not DATABASE_URL:
        try:
            cursor.execute("PRAGMA table_info(voice_usage);")
            columns = [info[1] for info in cursor.fetchall()]
            if columns and "use_date" not in columns:
                cursor.execute("DROP TABLE voice_usage;")
                cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS voice_usage (
                    user_id {user_id_type},
                    use_date TEXT,
                    seconds INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, use_date)
                )
                """)
        except Exception as migration_err:
            print(f"❌ 마이그레이션 검사 중 오류 발생: {migration_err}")
            
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# ==========================================
# [로또 시스템 헬퍼 함수 및 클래스]
# ==========================================
def get_kst_now():
    kst_tz = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(kst_tz).replace(tzinfo=None)

def get_current_lotto_round():
    first_round_time = datetime.datetime(2002, 12, 7, 20, 45)
    now = get_kst_now()
    delta = now - first_round_time
    weeks = delta.days // 7
    return weeks + 2

def fetch_lotto_result_sync(round_no):
    timestamp = int(time.time() * 1000)
    url = f"https://www.dhlottery.co.kr/lt645/selectPstLt645Info.do?srchLtEpsd={round_no}&_={timestamp}"
    try:
        req = urllib.request.Request(
            url, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.dhlottery.co.kr/'
            }
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            lst = data.get("data", {}).get("list", [])
            if lst:
                item = lst[0]
                raw_date = str(item.get("ltRflYmd", ""))
                formatted_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else raw_date
                
                return {
                    "round_no": round_no,
                    "numbers": f"{item['tm1WnNo']},{item['tm2WnNo']},{item['tm3WnNo']},{item['tm4WnNo']},{item['tm5WnNo']},{item['tm6WnNo']}",
                    "bonus": item['bnsWnNo'],
                    "drawn_at": formatted_date
                }
    except Exception as e:
        print(f"❌ [로또] {round_no}회차 데이터 가져오기 실패: {e}")
    return None

async def fetch_lotto_result_async(round_no):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fetch_lotto_result_sync, round_no)

async def sync_historical_lotto_data():
    try:
        current_round = get_current_lotto_round()
        start_round = max(1, current_round - 100)
        end_round = current_round - 1
        
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT round_no FROM lotto_results WHERE round_no >= {p}", (start_round,))
        cached_rounds = {row[0] for row in cursor.fetchall()}
        missing_rounds = [r for r in range(start_round, end_round + 1) if r not in cached_rounds]
        
        if missing_rounds:
            for r in missing_rounds:
                result = await fetch_lotto_result_async(r)
                if result:
                    cursor.execute(
                        f"INSERT INTO lotto_results (round_no, numbers, bonus, drawn_at) VALUES ({p}, {p}, {p}, {p})",
                        (result["round_no"], result["numbers"], result["bonus"], result["drawn_at"])
                    )
                    conn.commit()
                    await asyncio.sleep(0.1)
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ [로또] 과거 데이터 캐싱 중 오류 발생: {e}")

def get_lotto_stats_from_db():
    frequencies = {i: 0 for i in range(1, 46)}
    last_seen_round = {i: 0 for i in range(1, 46)}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        current_round = get_current_lotto_round()
        start_round = max(1, current_round - 100)
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT round_no, numbers FROM lotto_results WHERE round_no >= {p} ORDER BY round_no ASC", (start_round,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        actual_count = len(rows)
        for round_no, numbers_str in rows:
            nums = [int(n) for n in numbers_str.split(",")]
            for n in nums:
                if n in frequencies:
                    frequencies[n] += 1
                    last_seen_round[n] = max(last_seen_round[n], round_no)
        return frequencies, last_seen_round, actual_count
    except Exception as e:
        print(f"❌ [로또] 통계 데이터 계산 중 오류: {e}")
        return frequencies, last_seen_round, 0

def is_balanced_lotto(nums):
    total_sum = sum(nums)
    if not (100 <= total_sum <= 180): return False
    odds = sum(1 for n in nums if n % 2 != 0)
    if odds not in [2, 3, 4]: return False
    lows = sum(1 for n in nums if n <= 22)
    if lows not in [2, 3, 4]: return False
    return True

def has_consecutive(nums):
    for i in range(len(nums) - 1):
        if nums[i+1] - nums[i] == 1: return True
    return False

def generate_lotto_game(fixed_nums, excluded_nums, pattern):
    available_pool = [n for n in range(1, 46) if n not in excluded_nums and n not in fixed_nums]
    needed_count = 6 - len(fixed_nums)
    if needed_count < 0 or len(available_pool) < needed_count: return None
        
    for _ in range(1000):
        selected = random.sample(available_pool, needed_count)
        game = sorted(list(fixed_nums) + selected)
        if pattern == "balanced" and is_balanced_lotto(game): return game
        elif pattern == "no_consecutive" and not has_consecutive(game): return game
        elif pattern == "odd_heavy" and sum(1 for n in game if n % 2 != 0) >= 4: return game
        elif pattern == "even_heavy" and sum(1 for n in game if n % 2 == 0) >= 4: return game
        elif pattern == "high_heavy" and sum(1 for n in game if n >= 23) >= 4: return game
        elif pattern == "low_heavy" and sum(1 for n in game if n <= 22) >= 4: return game
        elif pattern == "random": return game
            
    selected = random.sample(available_pool, needed_count)
    return sorted(list(fixed_nums) + selected)

def parse_number_list(num_str):
    if not num_str: return set(), None
    tokens = re.split(r'[\s,]+', num_str.strip())
    numbers = set()
    for tok in tokens:
        if not tok: continue
        try:
            val = int(tok)
            if not (1 <= val <= 45): return set(), f"번호는 1에서 45 사이여야 합니다: `{tok}`"
            if val in numbers: return set(), f"중복된 번호가 있습니다: `{tok}`"
            numbers.add(val)
        except ValueError:
            return set(), f"올바른 숫자가 아닙니다: `{tok}`"
    return numbers, None

def get_saved_lotto_tickets_embed(user_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT numbers, round_no, created_at FROM lotto_tickets WHERE user_id = {p} AND is_checked = 0 ORDER BY id DESC LIMIT 10", (user_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return discord.Embed(
                title="🎫 보관된 로또 티켓",
                description="현재 대기 중인 로또 티켓이 없습니다. `!로또`로 번호를 추천받아 저장해보세요!",
                color=discord.Color.orange()
            )

        embed = discord.Embed(
            title="🎫 보관된 로또 티켓 목록",
            description=f"<@{user_id}> 님이 보관 중인 추첨 대기 티켓입니다.",
            color=0x39FF14
        )
        for idx, (nums_str, r_no, c_at) in enumerate(rows, 1):
            embed.add_field(name=f"#{idx} | 제 {r_no}회차 대비 ({c_at})", value=f"`{nums_str}`", inline=False)
        return embed
    except Exception as e:
        return discord.Embed(title="❌ 오류", description=f"로또 티켓 조회 중 오류 발생: {e}", color=discord.Color.red())

class LottoFilterSelect(discord.ui.Select):
    def __init__(self, current_filter):
        options = [
            discord.SelectOption(label="기본 균형형", value="balanced", description="총합, 홀짝, 고저 비율 균형", emoji="⚖️"),
            discord.SelectOption(label="연속수 배제형", value="no_consecutive", description="연속 번호 제외", emoji="🚫"),
            discord.SelectOption(label="홀수 강조형", value="odd_heavy", description="홀수 4개 이상", emoji="🔴"),
            discord.SelectOption(label="짝수 강조형", value="even_heavy", description="짝수 4개 이상", emoji="🔵"),
            discord.SelectOption(label="고수 강조형", value="high_heavy", description="23~45 번호 4개 이상", emoji="🟢"),
            discord.SelectOption(label="소수 강조형", value="low_heavy", description="1~22 번호 4개 이상", emoji="🟡"),
            discord.SelectOption(label="순수 무작위형", value="random", description="완전 무작위 조합", emoji="🎰")
        ]
        for opt in options:
            if opt.value == current_filter:
                opt.default = True
                break
        super().__init__(placeholder="AI 패턴 필터 선택...", min_values=1, max_values=1, options=options, custom_id="lotto_filter_select")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.user_id:
            return await interaction.response.send_message("❌ 소유자만 변경 가능합니다.", ephemeral=True)
        self.view.pattern = self.values[0]
        self.view.regenerate_numbers()
        for opt in self.options:
            opt.default = (opt.value == self.view.pattern)
        await interaction.response.edit_message(embed=self.view.create_embed(), view=self.view)

class LottoRecommendView(discord.ui.View):
    def __init__(self, user_id, count, fixed_nums, excluded_nums, pattern="balanced"):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.count = count
        self.fixed_nums = fixed_nums
        self.excluded_nums = excluded_nums
        self.pattern = pattern
        self.games = []
        self.add_item(LottoFilterSelect(self.pattern))
        self.regenerate_numbers()

    def regenerate_numbers(self):
        self.games = []
        for _ in range(self.count):
            game = generate_lotto_game(self.fixed_nums, self.excluded_nums, self.pattern)
            if game:
                self.games.append(game)
            else:
                available = [n for n in range(1, 46) if n not in self.excluded_nums and n not in self.fixed_nums]
                self.games.append(sorted(list(self.fixed_nums) + random.sample(available, 6 - len(self.fixed_nums))))

    def create_embed(self):
        frequencies, last_seen, _ = get_lotto_stats_from_db()
        current_round = get_current_lotto_round()
        embed = discord.Embed(title="🎰 HEAVEN 로또 연구소", color=0xFF007F)
        
        def get_emoji(num):
            if 1 <= num <= 10: return "🟡"
            elif 11 <= num <= 20: return "🔵"
            elif 21 <= num <= 30: return "🔴"
            elif 31 <= num <= 40: return "⚫"
            else: return "🟢"

        if self.count == 1:
            game = self.games[0]
            embed.add_field(name="🎫 추천 번호 조합", value="  ".join([f"{get_emoji(n)} `{n:02d}`" for n in game]), inline=False)
            total_sum = sum(game)
            odds = sum(1 for n in game if n % 2 != 0)
            lows = sum(1 for n in game if n <= 22)
            embed.add_field(name="📊 분석 요약", value=f"총합: `{total_sum}` | 홀짝: `{odds}:{6-odds}` | 고저: `{lows}:{6-lows}`", inline=False)
        else:
            game_list_text = [f"**🎫 {i:02d}번째:** " + " ".join([f"{get_emoji(n)} `{n:02d}`" for n in g]) for i, g in enumerate(self.games, 1)]
            embed.description = "\n".join(game_list_text)
        return embed

    @discord.ui.button(label="재생성", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        self.regenerate_numbers()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="번호 저장", style=discord.ButtonStyle.success, emoji="💾", row=1)
    async def save_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)
        current_round = get_current_lotto_round()
        now_str = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            p = "%s" if DATABASE_URL else "?"
            for game in self.games:
                nums_str = ",".join(str(n) for n in game)
                cursor.execute(
                    f"INSERT INTO lotto_tickets (user_id, round_no, numbers, channel_id, is_checked, match_count, has_bonus, prize_rank, created_at) VALUES ({p}, {p}, {p}, {p}, 0, 0, 0, 0, {p})",
                    (interaction.user.id, current_round, nums_str, interaction.channel_id, now_str)
                )
            conn.commit()
            cursor.close()
            conn.close()
            button.disabled = True
            button.label = "저장 완료"
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("💾 번호가 정상적으로 저장되었습니다.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 저장 실패: {e}", ephemeral=True)

# Active voice sessions tracking
active_sessions = {}

def get_current_date():
    adjusted_now = datetime.datetime.now() - datetime.timedelta(hours=6)
    return adjusted_now.strftime("%Y-%m-%d")

def add_voice_time(user_id, use_date, seconds):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        query = f"""
        INSERT INTO voice_usage (user_id, use_date, seconds)
        VALUES ({p}, {p}, {p})
        ON CONFLICT (user_id, use_date)
        DO UPDATE SET seconds = voice_usage.seconds + EXCLUDED.seconds
        """
        cursor.execute(query, (user_id, use_date, seconds))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ DB 이용시간 저장 중 오류 발생: {e}")

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours > 0: parts.append(f"{hours}시간")
    if minutes > 0: parts.append(f"{minutes}분")
    if secs > 0 or not parts: parts.append(f"{secs}초")
    return " ".join(parts)

# User Pass DB logic
def ensure_user(user_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        else:
            cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ ensure_user 오류: {e}")

def get_user(user_id: int):
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT xp, coin, random_box, premium_box, jackpot_box, booster_until, voice_minutes FROM users WHERE user_id={p}", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row or (0, 0, 0, 0, 0, 0, 0)
    except Exception as e:
        print(f"❌ get_user 오류: {e}")
        return (0, 0, 0, 0, 0, 0, 0)

def add_coin(user_id: int, amount: int):
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (amount, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ add_coin 오류: {e}")

def add_item(user_id: int, item: str, amount: int):
    if item not in ["random_box", "premium_box", "jackpot_box"]: return
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"UPDATE users SET {item} = {item} + {p} WHERE user_id={p}", (amount, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ add_item 오류: {e}")

REWARDS = {
    5: ("coin", None, 500, "💰 재화 500"),
    10: ("item", "random_box", 1, "📦 랜덤 상자 1개"),
    15: ("coin", None, 1000, "💰 재화 1,000"),
    20: ("item", "random_box", 2, "📦 랜덤 상자 2개"),
    25: ("coin", None, 2500, "💰 재화 2,500"),
    30: ("item", "premium_box", 1, "🎁 프리미엄 상자 1개"),
    35: ("coin", None, 3000, "💰 재화 3,000"),
    40: ("item", "premium_box", 2, "🎁 프리미엄 상자 2개"),
    45: ("item", "random_box", 5, "📦 랜덤 상자 5개"),
    50: ("item", "jackpot_box", 1, "👑 잭팟 상자 1개")
}

DAILY_QUESTS = {
    "voice_30m": {"title": "🎙️ 음성 참여 30분", "target": 30, "xp_reward": 100, "coin_reward": 500},
    "open_box": {"title": "📦 상자 1회 오픈", "target": 1, "xp_reward": 50, "coin_reward": 300},
    "buy_shop": {"title": "🛒 상점 상품 1회 구매", "target": 1, "xp_reward": 50, "coin_reward": 300}
}

def level_from_xp(xp: int):
    level = 1
    need = 300
    while xp >= need:
        xp -= need
        level += 1
        need = 300 + (level - 1) * 100
    return level, xp, need

def check_and_grant_level_rewards(cursor, p, user_id, old_xp, new_xp):
    old_level, _, _ = level_from_xp(old_xp)
    new_level, _, _ = level_from_xp(new_xp)
    rewards_granted = []
    if new_level > old_level:
        for lv in range(old_level + 1, new_level + 1):
            if lv in REWARDS:
                r_type, r_target, r_amount, r_name = REWARDS[lv]
                if r_type == "coin":
                    cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (r_amount, user_id))
                elif r_type == "item":
                    cursor.execute(f"UPDATE users SET {r_target} = {r_target} + {p} WHERE user_id={p}", (r_amount, user_id))
                rewards_granted.append(r_name)
    return rewards_granted

def add_xp(user_id: int, amount: int):
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT xp FROM users WHERE user_id={p}", (user_id,))
        row = cursor.fetchone()
        old_xp = row[0] if row else 0
        new_xp = old_xp + amount
        cursor.execute(f"UPDATE users SET xp = xp + {p} WHERE user_id={p}", (amount, user_id))
        rewards = check_and_grant_level_rewards(cursor, p, user_id, old_xp, new_xp)
        conn.commit()
        cursor.close()
        conn.close()
        return rewards
    except Exception as e:
        print(f"❌ add_xp 오류: {e}")
        return []

# Flask Web Server
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Discord Bot initialization
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name} ({bot.user.id})")
    asyncio.create_task(sync_historical_lotto_data())
    try:
        await bot.tree.sync()
        print("✅ 슬래시 명령어 동기화 완료")
    except Exception as e:
        print(f"❌ 슬래시 동기화 에러: {e}")

@bot.tree.command(name="로또", description="로또 6/45 번호를 추천받습니다.")
async def slash_lotto(interaction: discord.Interaction, 수량: int = 1):
    if 수량 < 1 or 수량 > 20:
        return await interaction.response.send_message("❌ 수량은 1~20개 사이여야 합니다.", ephemeral=True)
    view = LottoRecommendView(interaction.user.id, 수량, set(), set(), "balanced")
    await interaction.response.send_message(embed=view.create_embed(), view=view)

@bot.event
async def on_message(message):
    if message.author.bot: return

    if message.content.strip() in ["로또", "!로또"]:
        view = LottoRecommendView(message.author.id, 1, set(), set(), "balanced")
        await message.channel.send(embed=view.create_embed(), view=view)
        return

    if message.content.strip() in ["로또조회", "!로또조회", "내로또", "!내로또"]:
        embed = get_saved_lotto_tickets_embed(message.author.id)
        await message.channel.send(embed=embed)
        return

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return

    # 1. 음성 이용 시간 집계 처리
    if before.channel is None and after.channel is not None:
        active_sessions[member.id] = time.time()
    elif before.channel is not None and after.channel is None:
        join_time = active_sessions.pop(member.id, None)
        if join_time:
            duration = int(time.time() - join_time)
            if duration > 0:
                add_voice_time(member.id, get_current_date(), duration)

    # 2. 지정된 트리거 채널 입장 시 임시 채널 자동 생성 및 사용자 이동
    if after.channel and after.channel.id in TEMP_CHANNEL_CONFIG:
        config = TEMP_CHANNEL_CONFIG[after.channel.id]
        category = member.guild.get_channel(config["category_id"])
        
        try:
            new_channel = await member.guild.create_voice_channel(
                name=config["name"],
                category=category
            )
            created_temp_channels.add(new_channel.id)
            await member.move_to(new_channel)
        except Exception as e:
            print(f"❌ 임시 음성 채널 생성 또는 이동 실패: {e}")

    # 3. 임시로 생성된 채널에서 모든 멤버가 퇴장했을 때 자동 삭제
    if before.channel and before.channel.id in created_temp_channels:
        if len(before.channel.members) == 0:
            try:
                channel_to_delete = before.channel
                created_temp_channels.remove(channel_to_delete.id)
                await channel_to_delete.delete()
            except Exception as e:
                print(f"❌ 임시 음성 채널 삭제 실패: {e}")

# Keep-alive 웹 서버 및 봇 실행
if __name__ == "__main__":
    keep_alive()
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ 오류: DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")