# test deploy
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import sys
from flask import Flask
from threading import Thread
import asyncio
import sqlite3
import psycopg2
import time
import datetime
import random

# Railway 프로젝트에서 데이터베이스 영구 보존을 위해 PostgreSQL 서비스를 추가한 후,
# 봇 서비스의 Variables 탭에서 DATABASE_URL 변수를 추가하고 값으로 ${{Postgres.DATABASE_URL}} 을 연결해 주어야 이 환경변수를 인식합니다.
DATABASE_URL = os.getenv("DATABASE_URL")

# DATABASE_URL 환경변수(Railway PostgreSQL) 유무에 따라 자동으로 PostgreSQL 또는 로컬 SQLite 데이터베이스를 반환합니다.
def get_db_connection():
    if DATABASE_URL:
        # Railway PostgreSQL (postgres://를 postgresql://로 치환하여 psycopg2 호환)
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        # SQLite
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, "bot_data.db")
        return sqlite3.connect(db_path)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        print("🔌 [데이터베이스] Railway PostgreSQL 모드로 정상 연결되었습니다.")
    else:
        print("💾 [데이터베이스] 로컬 SQLite 모드로 연결되었습니다. (Railway 배포 환경에서는 재시작 시 데이터가 유실되므로 PostgreSQL 추가가 필요합니다.)")
    
    # user_id 등 디스코드 ID를 다루기 위해 SQLite는 INTEGER, PostgreSQL은 BIGINT로 설정
    user_id_type = "BIGINT" if DATABASE_URL else "INTEGER"
    
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS left_users (
        user_id {user_id_type} PRIMARY KEY
    )
    """)
    
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
    
    # SQLite 마이그레이션 확인 (PostgreSQL에서는 신규 테이블이므로 패스)
    if not DATABASE_URL:
        try:
            cursor.execute("PRAGMA table_info(voice_usage);")
            columns = [info[1] for info in cursor.fetchall()]
            if columns and "use_date" not in columns:
                cursor.execute("DROP TABLE voice_usage;")
                print("⚠️ 마이그레이션: 기존 voice_usage 테이블을 삭제하고 새 스키마로 생성합니다.")
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

# DB 초기화 실행
init_db()

# Active voice sessions tracking (user_id -> join_timestamp)
active_sessions = {}

def get_current_date():
    # 현재 시간에서 6시간을 빼서 오전 6시를 하루의 시작 기준으로 설정
    adjusted_now = datetime.datetime.now() - datetime.timedelta(hours=6)
    return adjusted_now.strftime("%Y-%m-%d")

def get_recent_dates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT use_date FROM voice_usage ORDER BY use_date DESC LIMIT 100")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"❌ 날짜 목록 조회 중 오류 발생: {e}")
        return []

def add_voice_time(user_id, use_date, seconds):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        # ON CONFLICT 구문은 SQLite 3.24.0+ 및 PostgreSQL에서 작동합니다.
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

def get_realtime_today_stats():
    try:
        today_str = get_current_date()
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT user_id, seconds FROM voice_usage WHERE use_date = {p}", (today_str,))
        rows = cursor.fetchall()
        cursor.close()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, SUM(seconds) FROM voice_usage GROUP BY user_id")
        rows = cursor.fetchall()
        cursor.close()
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


# ==========================================
# HEAVEN 시즌 패스 DB 헬퍼 및 비즈니스 로직
# ==========================================
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
        cursor.execute(f"""
            SELECT xp, coin, random_box, premium_box, jackpot_box, booster_until, voice_minutes
            FROM users WHERE user_id={p}
        """, (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row
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
    allowed_items = ["random_box", "premium_box", "jackpot_box"]
    if item not in allowed_items:
        raise ValueError("Invalid item name")
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

def use_item(user_id: int, item: str):
    allowed_items = ["random_box", "premium_box", "jackpot_box"]
    if item not in allowed_items:
        raise ValueError("Invalid item name")
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT {item} FROM users WHERE user_id={p}", (user_id,))
        row = cursor.fetchone()
        count = row[0] if row else 0

        if count <= 0:
            cursor.close()
            conn.close()
            return False

        cursor.execute(f"UPDATE users SET {item} = {item} - 1 WHERE user_id={p}", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ use_item 오류: {e}")
        return False

# 레벨업 보상 테이블
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
    "voice_30m": {
        "title": "🎙️ 음성 채널 30분 참여하기",
        "target": 30,
        "xp_reward": 100,
        "coin_reward": 500
    },
    "open_box": {
        "title": "📦 아무 상자 1회 오픈하기",
        "target": 1,
        "xp_reward": 50,
        "coin_reward": 300
    },
    "buy_shop": {
        "title": "🛒 상점에서 상품 1회 구매하기",
        "target": 1,
        "xp_reward": 50,
        "coin_reward": 300
    }
}

def level_from_xp(xp: int):
    level = 1
    need = 300
    while xp >= need:
        xp -= need
        level += 1
        need = 300 + (level - 1) * 100
    return level, xp, need

def progress_bar(current, total, size=10):
    filled = int((current / total) * size) if total > 0 else 0
    return "█" * filled + "░" * (size - filled)

def next_reward(level: int):
    for lv, (_, _, _, r_name) in REWARDS.items():
        if lv > level:
            return f"Lv.{lv} 달성 시 {r_name}"
    return "모든 패스 보상 달성 완료"

def get_season_pass_rankings():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, xp FROM users ORDER BY xp DESC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"❌ get_season_pass_rankings 오류: {e}")
        return []

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
                elif r_type == "booster":
                    now = int(time.time())
                    duration = r_amount * 86400
                    cursor.execute(f"SELECT booster_until FROM users WHERE user_id={p}", (user_id,))
                    row = cursor.fetchone()
                    curr_booster = row[0] if row else 0
                    new_booster = max(curr_booster, now) + duration
                    cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
                rewards_granted.append(r_name)
    return rewards_granted
def update_quest_progress(user_id: int, quest_id: str, amount: int = 1):
    try:
        today = get_current_date()
        ensure_user(user_id)
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        
        if DATABASE_URL:
            cursor.execute("""
                INSERT INTO user_quests (user_id, quest_id, progress, claimed, quest_date)
                VALUES (%s, %s, %s, 0, %s)
                ON CONFLICT (user_id, quest_id, quest_date)
                DO UPDATE SET progress = user_quests.progress + EXCLUDED.progress
            """, (user_id, quest_id, amount, today))
        else:
            cursor.execute("""
                INSERT INTO user_quests (user_id, quest_id, progress, claimed, quest_date)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT (user_id, quest_id, quest_date)
                DO UPDATE SET progress = user_quests.progress + EXCLUDED.progress
            """, (user_id, quest_id, amount, today))
            
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ update_quest_progress 오류: {e}")

def claim_all_quests_calc(user_id: int):
    today = get_current_date()
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        
        cursor.execute(f"""
            SELECT quest_id, progress, claimed FROM user_quests
            WHERE user_id = {p} AND quest_date = {p}
        """, (user_id, today))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        quest_data = {row[0]: {"progress": row[1], "claimed": row[2]} for row in rows}
        
        total_xp = 0
        total_coins = 0
        claimed_quests = []
        
        for q_id, q_info in DAILY_QUESTS.items():
            db_info = quest_data.get(q_id, {"progress": 0, "claimed": 0})
            if db_info["progress"] >= q_info["target"] and not db_info["claimed"]:
                total_xp += q_info["xp_reward"]
                total_coins += q_info["coin_reward"]
                claimed_quests.append(q_id)
                
        if not claimed_quests:
            return False, "수령할 수 있는 퀘스트 보상이 없습니다."
            
        return True, (total_xp, total_coins, claimed_quests)
        
    except Exception as e:
        print(f"❌ claim_all_quests_calc 오류: {e}")
        return False, "보상 계산 중 오류가 발생했습니다."

def apply_claimed_quests(user_id: int, total_xp: int, total_coins: int, claimed_quests: list):
    today = get_current_date()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        
        placeholders = ", ".join([p] * len(claimed_quests))
        cursor.execute(f"""
            UPDATE user_quests SET claimed = 1
            WHERE user_id = {p} AND quest_date = {p} AND quest_id IN ({placeholders})
        """, (user_id, today) + tuple(claimed_quests))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        add_coin(user_id, total_coins)
        rewards_granted = add_xp(user_id, total_xp)
        
        msg = f"🎉 **일일 퀘스트 보상 일괄 수령 완료**\n\n계정으로 아래 보상이 즉시 지급되었습니다:\n\n* 💰 **+{total_coins:,} 코인**\n* ⭐ **+{total_xp:,} XP**"
        if rewards_granted:
            msg += f"\n\n🎁 **레벨업 달성 보상 획득!**\n└ {', '.join(rewards_granted)}"
            
        return msg
    except Exception as e:
        print(f"❌ apply_claimed_quests 오류: {e}")
        return "보상을 지급하는 도중 오류가 발생했습니다."

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
        
        cursor.execute(f"UPDATE users SET xp = xp + {p} WHERE user_id={p}",
                       (amount, user_id))
        
        rewards = check_and_grant_level_rewards(cursor, p, user_id, old_xp, new_xp)
        conn.commit()
        cursor.close()
        conn.close()
        return rewards
    except Exception as e:
        print(f"❌ add_xp 오류: {e}")
        return []

# 상점 구매 비즈니스 로직
def buy_shop_item(user_id: int, item_type: str, cost: int, count: int = 1):
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT coin, booster_until FROM users WHERE user_id={p}", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return False, "유저 정보를 찾을 수 없습니다."
        
        coins, booster_until = row
        total_cost = cost * count
        if coins < total_cost:
            cursor.close()
            conn.close()
            return False, f"❌ 재화가 부족합니다. (보유: {coins:,} / 필요: {total_cost:,})"
        
        cursor.execute(f"UPDATE users SET coin = coin - {p} WHERE user_id={p}", (total_cost, user_id))
        
        now = int(time.time())
        if item_type == "random_box":
            cursor.execute(f"UPDATE users SET random_box = random_box + {p} WHERE user_id={p}", (count, user_id))
            msg = f"📦 랜덤 상자 {count}개를 구매했습니다!"
        elif item_type == "premium_box":
            cursor.execute(f"UPDATE users SET premium_box = premium_box + {p} WHERE user_id={p}", (count, user_id))
            msg = f"🎁 프리미엄 랜덤 상자 {count}개를 구매했습니다!"
        elif item_type == "booster_1d":
            new_booster = max(booster_until, now) + count * 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            msg = f"💎 XP 부스터 1일 {count}개를 구매했습니다!"
        elif item_type == "booster_7d":
            new_booster = max(booster_until, now) + count * 7 * 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            msg = f"💎 XP 부스터 7일 {count}개를 구매했습니다!"
        else:
            cursor.close()
            conn.close()
            return False, "올바르지 않은 상품입니다."
            
        conn.commit()
        cursor.close()
        conn.close()
        update_quest_progress(user_id, "buy_shop", count)
        return True, msg
    except Exception as e:
        print(f"❌ buy_shop_item 오류: {e}")
        return False, "구매 처리 중 오류가 발생했습니다."

# 상자 열기 비즈니스 로직
def open_random_box(user_id: int):
    roll = random.randint(1, 100)
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        now = int(time.time())
        
        if roll <= 40:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (1000, user_id))
            result = "💰 재화 1,000 획득!"
        elif roll <= 65:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (2500, user_id))
            result = "💰 재화 2,500 획득!"
        elif roll <= 80:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (5000, user_id))
            result = "💰 재화 5,000 획득!"
        elif roll <= 90:
            cursor.execute(f"SELECT booster_until FROM users WHERE user_id={p}", (user_id,))
            row = cursor.fetchone()
            curr_booster = row[0] if row else 0
            new_booster = max(curr_booster, now) + 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            result = "💎 XP 부스터 1일 획득!"
        elif roll <= 97:
            cursor.execute(f"UPDATE users SET premium_box = premium_box + 1 WHERE user_id={p}", (user_id,))
            result = "🎁 프리미엄 랜덤 상자 1개 획득!"
        else:
            cursor.execute(f"UPDATE users SET jackpot_box = jackpot_box + 1 WHERE user_id={p}", (user_id,))
            result = "👑 잭팟 상자 1개 획득!"
            
        conn.commit()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        print(f"❌ open_random_box 오류: {e}")
        return "상자를 여는 도중 오류가 발생했습니다."

def open_random_box_multiple(user_id: int, count: int):
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        now = int(time.time())
        
        # Check current random boxes
        cursor.execute(f"SELECT random_box, coin, premium_box, jackpot_box, booster_until FROM users WHERE user_id={p}", (user_id,))
        row = cursor.fetchone()
        if not row or row[0] < count:  # random_box is the 1st column (index 0) in the SELECT list: random_box, coin, premium_box, jackpot_box, booster_until
            cursor.close()
            conn.close()
            return None, "보유한 랜덤 상자가 부족합니다."
            
        curr_random_box, curr_coin, curr_premium_box, curr_jackpot, curr_booster = row
        
        added_coins = 0
        added_booster_seconds = 0
        added_premium_boxes = 0
        added_jackpot_boxes = 0
        
        rewards_summary = {
            "coins": 0,
            "booster_days": 0,
            "premium_boxes": 0,
            "jackpot_boxes": 0
        }
        
        for _ in range(count):
            roll = random.randint(1, 100)
            if roll <= 40:
                added_coins += 1000
                rewards_summary["coins"] += 1000
            elif roll <= 65:
                added_coins += 2500
                rewards_summary["coins"] += 2500
            elif roll <= 80:
                added_coins += 5000
                rewards_summary["coins"] += 5000
            elif roll <= 90:
                added_booster_seconds += 86400
                rewards_summary["booster_days"] += 1
            elif roll <= 97:
                added_premium_boxes += 1
                rewards_summary["premium_boxes"] += 1
            else:
                added_jackpot_boxes += 1
                rewards_summary["jackpot_boxes"] += 1
                
        new_booster = max(curr_booster, now) + added_booster_seconds
        
        cursor.execute(
            f"""
            UPDATE users 
            SET random_box = random_box - {p},
                coin = coin + {p},
                premium_box = premium_box + {p},
                jackpot_box = jackpot_box + {p},
                booster_until = {p}
            WHERE user_id = {p}
            """,
            (count, added_coins, added_premium_boxes, added_jackpot_boxes, new_booster, user_id)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        return rewards_summary, None
    except Exception as e:
        print(f"❌ open_random_box_multiple 오류: {e}")
        return None, "상자를 여는 도중 오류가 발생했습니다."

def open_premium_box(user_id: int):
    roll = random.randint(1, 100)
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        now = int(time.time())
        
        if roll <= 40:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (5000, user_id))
            result = "💰 재화 5,000 획득!"
        elif roll <= 65:
            cursor.execute(f"UPDATE users SET random_box = random_box + 10 WHERE user_id={p}", (user_id,))
            result = "📦 랜덤 상자 10개 획득!"
        elif roll <= 80:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (7500, user_id))
            result = "💰 재화 7,500 획득!"
        elif roll <= 90:
            cursor.execute(f"SELECT booster_until FROM users WHERE user_id={p}", (user_id,))
            row = cursor.fetchone()
            curr_booster = row[0] if row else 0
            new_booster = max(curr_booster, now) + 7 * 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            result = "💎 XP 부스터 7일 획득!"
        elif roll <= 97:
            cursor.execute(f"SELECT booster_until FROM users WHERE user_id={p}", (user_id,))
            row = cursor.fetchone()
            curr_booster = row[0] if row else 0
            new_booster = max(curr_booster, now) + 30 * 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            result = "💎 XP 부스터 30일 획득!"
        else:
            cursor.execute(f"UPDATE users SET jackpot_box = jackpot_box + 1 WHERE user_id={p}", (user_id,))
            result = "👑 잭팟 상자 1개 획득!"
            
        conn.commit()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        print(f"❌ open_premium_box 오류: {e}")
        return "상자를 여는 도중 오류가 발생했습니다."

def open_jackpot_box(user_id: int):
    roll = random.randint(1, 100)
    ensure_user(user_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        now = int(time.time())
        
        if roll <= 50:
            cursor.execute(f"UPDATE users SET coin = coin + {p} WHERE user_id={p}", (10000, user_id))
            result = "💰 재화 10,000 획득!"
        elif roll <= 80:
            cursor.execute(f"UPDATE users SET premium_box = premium_box + 5 WHERE user_id={p}", (user_id,))
            result = "🎁 프리미엄 랜덤 상자 5개 획득!"
        elif roll <= 95:
            cursor.execute(f"SELECT booster_until FROM users WHERE user_id={p}", (user_id,))
            row = cursor.fetchone()
            curr_booster = row[0] if row else 0
            new_booster = max(curr_booster, now) + 90 * 86400
            cursor.execute(f"UPDATE users SET booster_until = {p} WHERE user_id={p}", (new_booster, user_id))
            result = "💎 XP 부스터 90일 획득!"
        else:
            result = "🎁 기프티콘 획득! (관리자에게 문의해주세요.)"
            
        conn.commit()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        print(f"❌ open_jackpot_box 오류: {e}")
        return "상자를 여는 도중 오류가 발생했습니다."

# 임베드 생성 함수들
def pass_embed(member: discord.Member):
    xp, coin, random_box, premium_box, jackpot_box, booster_until, voice_minutes = get_user(member.id)
    level, current_xp, need_xp = level_from_xp(xp)

    embed = discord.Embed(
        title="🎫 HEAVEN 시즌 패스",
        description=f"{member.mention}님의 실시간 패스 정보",
        color=0x8e44ad
    )

    embed.add_field(name="레벨", value=f"Lv.{level}", inline=True)
    embed.add_field(name="XP", value=f"{current_xp} / {need_xp}", inline=True)
    embed.add_field(name="진행도", value=progress_bar(current_xp, need_xp), inline=False)

    embed.add_field(name="💰 보유 재화", value=f"{coin:,}", inline=True)
    embed.add_field(name="🎤 누적 음성시간", value=f"{voice_minutes:,}분", inline=True)

    embed.add_field(
        name="📦 보유 상자",
        value=f"랜덤 상자: {random_box}개\n프리미엄 상자: {premium_box}개\n잭팟 상자: {jackpot_box}개",
        inline=False
    )

    now = int(time.time())
    if booster_until > now:
        booster_status = f"🔥 활성화 중 (만료: <t:{booster_until}:F> / <t:{booster_until}:R>)"
    else:
        booster_status = "❌ 비활성화"
    embed.add_field(name="💎 XP 부스터", value=booster_status, inline=False)

    embed.add_field(name="🎁 다음 보상", value=next_reward(level), inline=False)
    return embed

def quest_embed(user_id: int):
    today = get_current_date()
    ensure_user(user_id)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    p = "%s" if DATABASE_URL else "?"
    
    cursor.execute(f"""
        SELECT quest_id, progress, claimed FROM user_quests
        WHERE user_id = {p} AND quest_date = {p}
    """, (user_id, today))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    quest_data = {row[0]: {"progress": row[1], "claimed": row[2]} for row in rows}
    
    embed = discord.Embed(
        title="📜 오늘의 일일 퀘스트",
        description="매일 오전 6시에 초기화되는 시즌 패스 일일 미션입니다.\n미션을 달성하고 보상을 수령하세요!",
        color=0x3498db
    )
    
    for q_id, q_info in DAILY_QUESTS.items():
        db_info = quest_data.get(q_id, {"progress": 0, "claimed": 0})
        progress = min(db_info["progress"], q_info["target"])
        target = q_info["target"]
        
        status_str = ""
        if db_info["claimed"]:
            status_str = "✅ **보상 수령 완료**"
        elif progress >= target:
            status_str = "🎁 **수령 가능 (아래 일괄 수령 버튼을 누르세요)**"
        else:
            status_str = f"⚡ 진행도: `{progress}/{target}`"
            
        embed.add_field(
            name=q_info["title"],
            value=(
                f"{status_str}\n"
                f"└ 보상: ⭐ {q_info['xp_reward']} XP / 💰 {q_info['coin_reward']} 코인"
            ),
            inline=False
        )
        
    return embed

class QuestPanelView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label="보상 일괄 수령", emoji="🎁", style=discord.ButtonStyle.success, custom_id="heaven_quest:claim_all")
    async def claim_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ 본인의 퀘스트 보상만 수령할 수 있습니다.", ephemeral=True)
            
        await interaction.response.send_message("🎁 퀘스트 보상 가방을 여는 중... ⚙️", ephemeral=True)
        await asyncio.sleep(0.5)
        
        success, res = claim_all_quests_calc(interaction.user.id)
        if not success:
            return await interaction.edit_original_response(content=f"❌ {res}")
            
        total_xp, total_coins, claimed_quests = res
        
        await interaction.edit_original_response(content=f"💰 재화 정산 중... (+{total_coins:,} 코인) 💸")
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content=f"⭐ 경험치 획득 중... (+{total_xp:,} XP) ✨")
        await asyncio.sleep(0.5)
        
        msg = apply_claimed_quests(interaction.user.id, total_xp, total_coins, claimed_quests)
        await interaction.edit_original_response(content=msg)
        
        new_embed = quest_embed(interaction.user.id)
        await interaction.message.edit(embed=new_embed, view=self)

def shop_embed():
    embed = discord.Embed(
        title="🛒 HEAVEN 상점",
        description="버튼으로 구매할 상품을 선택하세요.",
        color=0x2ecc71
    )
    embed.add_field(name="📦 랜덤 상자", value="2,000 재화", inline=False)
    embed.add_field(name="💎 XP 부스터 1일", value="1,000 재화", inline=False)
    embed.add_field(name="💎 XP 부스터 7일", value="5,000 재화", inline=False)
    embed.add_field(name="🎁 프리미엄 랜덤 상자", value="8,000 재화", inline=False)
    return embed

def box_info_embed():
    embed = discord.Embed(
        title="📦 상자 확률표",
        color=0xf1c40f
    )
    embed.add_field(
        name="📦 랜덤 상자",
        value=(
            "40% → 💰 재화 1,000\n"
            "25% → 💰 재화 2,500\n"
            "15% → 💰 재화 5,000\n"
            "10% → 💎 XP 부스터 1일\n"
            "7% → 🎁 프리미엄 랜덤 상자\n"
            "3% → 👑 잭팟 상자"
        ),
        inline=False
    )
    embed.add_field(
        name="🎁 프리미엄 랜덤 상자",
        value=(
            "40% → 💰 재화 5,000\n"
            "25% → 📦 랜덤 상자 10개\n"
            "15% → 💰 재화 7,500\n"
            "10% → 💎 XP 부스터 7일\n"
            "7% → 💎 XP 부스터 30일\n"
            "3% → 👑 잭팟 상자"
        ),
        inline=False
    )
    embed.add_field(
        name="👑 잭팟 상자",
        value=(
            "50% → 💰 재화 10,000\n"
            "30% → 🎁 프리미엄 랜덤 상자 5개\n"
            "15% → 💎 XP 부스터 90일\n"
            "5% → 🎁 기프티콘"
        ),
        inline=False
    )
    return embed

def rewards_info_embed():
    embed = discord.Embed(
        title="🎫 HEAVEN 시즌 패스 전체 보상 목록",
        description="레벨 달성 시 인벤토리 및 계정에 즉시 자동 지급되는 보상들입니다.",
        color=0x9b59b6
    )
    
    reward_lines = [
        "⭐ **Lv.5** : 💰 재화 500",
        "⭐ **Lv.10** : 📦 랜덤 상자 1개",
        "⭐ **Lv.15** : 💰 재화 1,000",
        "⭐ **Lv.20** : 📦 랜덤 상자 2개",
        "⭐ **Lv.25** : 💰 재화 2,500",
        "⭐ **Lv.30** : 🎁 프리미엄 상자 1개",
        "⭐ **Lv.35** : 💰 재화 3,000",
        "⭐ **Lv.40** : 🎁 프리미엄 상자 2개",
        "⭐ **Lv.45** : 📦 랜덤 상자 5개",
        "⭐ **Lv.50** : 👑 잭팟 상자 1개"
    ]
    
    embed.description = "\n".join(reward_lines)
    return embed


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

class PassRankingView(discord.ui.View):
    def __init__(self, full_rows):
        super().__init__(timeout=180)  # 3분 제한
        self.full_rows = full_rows

    @discord.ui.button(label="더보기", style=discord.ButtonStyle.primary, custom_id="show_more_pass_ranking")
    async def show_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏆 HEAVEN 시즌 패스 전체 랭킹",
            color=0x8e44ad
        )
        
        desc_lines = []
        # 디스코드 글자 수 제한(4096자)을 방지하기 위해 상위 50명까지 표시
        limit_rows = self.full_rows[:50]
        for idx, (user_id, xp) in enumerate(limit_rows, 1):
            level, _, _ = level_from_xp(xp)
            desc_lines.append(f"{idx}등: <@{user_id}> - Lv.{level} ({xp:,} XP)")
            
        if len(self.full_rows) > 50:
            desc_lines.append("\n*상위 50명까지 표시됩니다.*")
            
        embed.description = "\n".join(desc_lines)
        
        # 버튼 제거
        self.clear_items()
        await interaction.response.edit_message(embed=embed, view=self)

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
        
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT user_id, seconds FROM voice_usage WHERE use_date = {p} ORDER BY seconds DESC", (selected_date,))
        rows = cursor.fetchall()
        cursor.close()
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
        # 디스코드 선택 메뉴는 최대 25개 옵션까지 지원하므로, 날짜 데이터를 20개 단위로 쪼개어 드롭다운을 생성합니다.
        # 최대 5개의 드롭다운(총 100일 분량)까지 한 메시지에 등록 가능합니다.
        chunk_size = 20
        visible_dates = dates[:100]
        
        for i in range(0, len(visible_dates), chunk_size):
            chunk = visible_dates[i:i+chunk_size]
            start_num = i + 1
            end_num = i + len(chunk)
            if i == 0:
                placeholder = f"최근 날짜 선택 (1~{end_num}일)..."
            else:
                placeholder = f"이전 날짜 선택 ({start_num}~{end_num}일)..."
            self.add_item(DateSelect(chunk, placeholder=placeholder))

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


# =========================
# 상자 일괄 개봉을 위한 Select Menu 및 View
# =========================
class BoxOpenSelect(discord.ui.Select):
    def __init__(self, box_count: int):
        options = []
        if box_count <= 25:
            for i in range(1, box_count + 1):
                options.append(discord.SelectOption(
                    label=f"{i}개",
                    value=str(i),
                    emoji="📦",
                    description=f"랜덤 상자 {i}개를 엽니다."
                ))
        else:
            standard_options = [1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 100, 150, 200, 250, 300, 400, 500]
            options_to_add = [val for val in standard_options if val < box_count]
            
            for val in options_to_add:
                options.append(discord.SelectOption(
                    label=f"{val}개",
                    value=str(val),
                    emoji="📦",
                    description=f"랜덤 상자 {val}개를 엽니다."
                ))
                
            if len(options) >= 25:
                options = options[:24]
                
            options.append(discord.SelectOption(
                label=f"모두 열기 ({box_count}개)",
                value=str(box_count),
                emoji="🔥",
                description=f"보유 중인 {box_count}개의 상자를 모두 엽니다."
            ))
            
        super().__init__(
            placeholder="열고 싶은 상자의 개수를 선택하세요...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        await interaction.response.edit_message(content="📦 상자를 개봉하는 중입니다... 잠시만 기다려주세요.", view=self.view)
        
        count = int(self.values[0])
        rewards, error_msg = open_random_box_multiple(interaction.user.id, count)
        
        if error_msg:
            return await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
            
        update_quest_progress(interaction.user.id, "open_box", count)
        
        await interaction.edit_original_response(content="📦 흔들흔들... 상자들이 일제히 빛나기 시작합니다! 💫", view=None)
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content="✨ 눈부신 빛의 기둥과 함께 모든 보상이 쏟아져 나옵니다! ✨")
        await asyncio.sleep(0.5)
        
        desc_parts = [f"축하합니다! 상자 {count}개에서 다음 보상들을 획득했습니다:\n"]
        if rewards["coins"] > 0:
            desc_parts.append(f"* 💰 **재화 {rewards['coins']:,} 코인**")
        if rewards["booster_days"] > 0:
            desc_parts.append(f"* 💎 **XP 부스터 {rewards['booster_days']}일권**")
        if rewards["premium_boxes"] > 0:
            desc_parts.append(f"* 🎁 **프리미엄 랜덤 상자 {rewards['premium_boxes']}개**")
        if rewards["jackpot_boxes"] > 0:
            desc_parts.append(f"* 👑 **잭팟 상자 {rewards['jackpot_boxes']}개**")
            
        if len(desc_parts) == 1:
            desc_parts.append("* 꽝 (보상이 없습니다)")
            
        embed = discord.Embed(
            title="📦 랜덤 상자 일괄 개봉 완료",
            description="\n".join(desc_parts),
            color=0x9b59b6
        )
        await interaction.edit_original_response(content=None, embed=embed)

class BoxOpenSelectView(discord.ui.View):
    def __init__(self, box_count: int):
        super().__init__(timeout=60)
        self.add_item(BoxOpenSelect(box_count))


# =========================
# 버튼 View (시즌 패스 및 상점)
# =========================
class PassPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="내 패스 보기", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="heaven_pass:my_pass")
    async def my_pass(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=pass_embed(interaction.user),
            ephemeral=True
        )

    @discord.ui.button(label="상점 보기", emoji="🛒", style=discord.ButtonStyle.success, custom_id="heaven_pass:shop")
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=shop_embed(),
            view=ShopPanelView(),
            ephemeral=True
        )

    @discord.ui.button(label="상자 확률", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="heaven_pass:box_info")
    async def box_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=box_info_embed(),
            ephemeral=True
        )

    @discord.ui.button(label="전체 보상", emoji="🎁", style=discord.ButtonStyle.secondary, custom_id="heaven_pass:all_rewards")
    async def all_rewards(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=rewards_info_embed(),
            ephemeral=True
        )

    @discord.ui.button(label="랭킹 보기", emoji="🏆", style=discord.ButtonStyle.secondary, custom_id="heaven_pass:ranking")
    async def ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = get_season_pass_rankings()
        if not rows:
            embed = discord.Embed(
                title="🏆 HEAVEN 시즌 패스 랭킹",
                description="시즌 패스 랭킹 기록이 없습니다.",
                color=0x8e44ad
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 HEAVEN 시즌 패스 랭킹 (Top 5)",
            color=0x8e44ad
        )
        
        top_5 = rows[:5]
        desc_lines = []
        for idx, (user_id, xp) in enumerate(top_5, 1):
            level, _, _ = level_from_xp(xp)
            desc_lines.append(f"{idx}등: <@{user_id}> - Lv.{level} ({xp:,} XP)")
            
        if len(rows) > 5:
            desc_lines.append("\n*6등 이하의 기록은 아래 버튼을 눌러 확인하세요.*")
            embed.description = "\n".join(desc_lines)
            view = PassRankingView(rows)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            embed.description = "\n".join(desc_lines)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="일일 퀘스트", emoji="📋", style=discord.ButtonStyle.primary, custom_id="heaven_pass:quests")
    async def quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=quest_embed(interaction.user.id),
            view=QuestPanelView(interaction.user.id),
            ephemeral=True
        )

    @discord.ui.button(label="랜덤 상자 열기", emoji="📦", style=discord.ButtonStyle.secondary, custom_id="heaven_pass:open_random")
    async def open_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = get_user(interaction.user.id)
        random_box = row[2] if row else 0
        
        if random_box <= 0:
            return await interaction.response.send_message("❌ 보유한 랜덤 상자가 없습니다.", ephemeral=True)
            
        view = BoxOpenSelectView(random_box)
        await interaction.response.send_message(
            f"📦 **랜덤 상자 개봉**\n개봉할 상자 개수를 선택해주세요. (보유 중: `{random_box}`개)",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="프리미엄 상자 열기", emoji="🎁", style=discord.ButtonStyle.danger, custom_id="heaven_pass:open_premium")
    async def open_premium(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not use_item(interaction.user.id, "premium_box"):
            return await interaction.response.send_message("❌ 보유한 프리미엄 랜덤 상자가 없습니다.", ephemeral=True)
            
        update_quest_progress(interaction.user.id, "open_box", 1)
        
        await interaction.response.send_message("🎁 프리미엄 상자를 조심스럽게 여는 중... 🔍", ephemeral=True)
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content="🎁 흔들흔들... 상자가 빛나기 시작합니다! 💫")
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content="✨ 눈부신 빛과 함께 보상이 튀어나옵니다! ✨")
        await asyncio.sleep(0.5)
        
        result = open_premium_box(interaction.user.id)
        
        embed = discord.Embed(
            title="🎁 프리미엄 랜덤 상자 개봉 완료",
            description=f"축하합니다! 상자에서 다음 보상이 나왔습니다:\n\n* **{result}**",
            color=0xe74c3c
        )
        await interaction.edit_original_response(content=None, embed=embed)

    @discord.ui.button(label="잭팟 상자 열기", emoji="👑", style=discord.ButtonStyle.danger, custom_id="heaven_pass:open_jackpot")
    async def open_jackpot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not use_item(interaction.user.id, "jackpot_box"):
            return await interaction.response.send_message("❌ 보유한 잭팟 상자가 없습니다.", ephemeral=True)
            
        update_quest_progress(interaction.user.id, "open_box", 1)
        
        await interaction.response.send_message("👑 잭팟 상자를 조심스럽게 여는 중... 🔍", ephemeral=True)
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content="👑 흔들흔들... 상자가 빛나기 시작합니다! 💫")
        await asyncio.sleep(0.5)
        await interaction.edit_original_response(content="✨ 눈부신 빛과 함께 보상이 튀어나옵니다! ✨")
        await asyncio.sleep(0.5)
        
        result = open_jackpot_box(interaction.user.id)
        
        embed = discord.Embed(
            title="👑 잭팟 상자 개봉 완료",
            description=f"축하합니다! 상자에서 다음 보상이 나왔습니다:\n\n* **{result}**",
            color=0xf1c40f
        )
        await interaction.edit_original_response(content=None, embed=embed)
        
        if "기프티콘" in result:
            channel_id = 1518304536136253674
            try:
                channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(f"🎉 **[기프티콘 당첨]** {interaction.user.mention}님이 잭팟 상자에서 **기프티콘**에 당첨되었습니다! (관리자분들은 확인 후 기프티콘을 지급해 주세요.)")
            except Exception as e:
                print(f"❌ 기프티콘 당첨 알림 전송 실패: {e}")


# =========================
# 상점 일괄 구매를 위한 Select Menu 및 View
# =========================
class ShopBuySelect(discord.ui.Select):
    def __init__(self, item_type: str, base_cost: int, item_name: str):
        self.item_type = item_type
        self.base_cost = base_cost
        self.item_name = item_name
        
        options = []
        for i in range(1, 11):
            total_cost = base_cost * i
            options.append(discord.SelectOption(
                label=f"{i}개",
                value=str(i),
                description=f"구매 비용: {total_cost:,} 재화"
            ))
            
        super().__init__(
            placeholder=f"구매할 {item_name}의 개수를 선택하세요...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        await interaction.response.edit_message(content="🪙 구매를 처리하는 중입니다...", view=self.view)
        
        count = int(self.values[0])
        success, msg = buy_shop_item(interaction.user.id, self.item_type, self.base_cost, count)
        
        if success:
            await interaction.edit_original_response(content=f"✅ {msg}", view=None)
        else:
            await interaction.edit_original_response(content=f"❌ {msg}", view=None)

class ShopBuySelectView(discord.ui.View):
    def __init__(self, item_type: str, base_cost: int, item_name: str):
        super().__init__(timeout=60)
        self.add_item(ShopBuySelect(item_type, base_cost, item_name))


class ShopPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📦 랜덤 상자 구매", style=discord.ButtonStyle.success, custom_id="heaven_shop:buy_random")
    async def buy_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopBuySelectView("random_box", 2000, "📦 랜덤 상자")
        await interaction.response.send_message("구매할 개수를 선택해주세요.", view=view, ephemeral=True)

    @discord.ui.button(label="💎 부스터 1일 구매", style=discord.ButtonStyle.success, custom_id="heaven_shop:buy_booster_1d")
    async def buy_booster_1d(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopBuySelectView("booster_1d", 1000, "💎 부스터 1일")
        await interaction.response.send_message("구매할 개수를 선택해주세요.", view=view, ephemeral=True)

    @discord.ui.button(label="💎 부스터 7일 구매", style=discord.ButtonStyle.success, custom_id="heaven_shop:buy_booster_7d")
    async def buy_booster_7d(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopBuySelectView("booster_7d", 5000, "💎 부스터 7일")
        await interaction.response.send_message("구매할 개수를 선택해주세요.", view=view, ephemeral=True)

    @discord.ui.button(label="🎁 프리미엄 상자 구매", style=discord.ButtonStyle.danger, custom_id="heaven_shop:buy_premium")
    async def buy_premium(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ShopBuySelectView("premium_box", 8000, "🎁 프리미엄 상자")
        await interaction.response.send_message("구매할 개수를 선택해주세요.", view=view, ephemeral=True)

def get_seconds_until_next_reset():
    now = datetime.datetime.now()
    # 오늘 오전 6시 설정
    reset_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    # 현재 시간이 이미 오늘 오전 6시 이후라면, 다음 초기화는 내일 오전 6시임
    if now >= reset_time:
        reset_time += datetime.timedelta(days=1)
    return (reset_time - now).total_seconds()

async def daily_reset_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        seconds = get_seconds_until_next_reset()
        print(f"⏰ 다음 오전 06시 데이터 분할 및 재시작 대기 시간: {seconds}초")
        await asyncio.sleep(seconds)
        
        try:
            # 현재 음성 채널에 남아 있는 유저들의 누적 시간을 어제 날짜로 기록하고 시작 시점을 오전 6시로 갱신
            now = time.time()
            # 6시 정각 리셋이므로, 이전 날짜(6시간 1분 전)를 기준으로 저장
            target_date = (datetime.datetime.now() - datetime.timedelta(hours=6, minutes=1)).strftime("%Y-%m-%d")
            
            for uid, join_time in list(active_sessions.items()):
                duration = int(now - join_time)
                if duration > 0:
                    add_voice_time(uid, target_date, duration)
                active_sessions[uid] = now
            print(f"📅 오전 06시 정각: {target_date} 기준 음성 채널 이용 시간 데이터 정리가 완료되었습니다.")
            
            # 오전 6시 자동 재시작 진행
            print("🔄 오전 06시 자동 재시작을 진행합니다...")
            await bot.close()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"❌ 일일 데이터 정리 및 재시작 중 오류 발생: {e}")
            
        await asyncio.sleep(10)


# =========================
# 음성 XP 분당 적립 루프
# =========================
@tasks.loop(minutes=1)
async def voice_xp_loop():
    user_ids = list(active_sessions.keys())
    if not user_ids:
        return
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        
        # 1. 유저 데이터 존재 보장
        for uid in user_ids:
            if DATABASE_URL:
                cursor.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (uid,))
            else:
                cursor.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (uid,))
        conn.commit()
        
        # 2. XP, 부스터, 음성 시간 확인 및 일괄 업데이트
        placeholders = ", ".join([p] * len(user_ids))
        cursor.execute(f"SELECT user_id, xp, booster_until, voice_minutes FROM users WHERE user_id IN ({placeholders})", tuple(user_ids))
        rows = cursor.fetchall()
        user_data = {row[0]: {"xp": row[1], "booster_until": row[2], "voice_minutes": row[3]} for row in rows}
        
        now = int(time.time())
        today_str = get_current_date()
        for uid in user_ids:
            data = user_data.get(uid, {"xp": 0, "booster_until": 0, "voice_minutes": 0})
            old_xp = data["xp"]
            booster_until = data["booster_until"]
            old_voice_mins = data["voice_minutes"] if data["voice_minutes"] is not None else 0
            
            is_booster_active = booster_until > now
            # 기본 분당 1에서 5로 변경 (부스터 2배 시 10)
            xp_to_add = 10 if is_booster_active else 5
            coin_to_add = 20  # 분당 20 코인 기본 지급
            
            # 누적 음성 60분 도달 시마다 보너스 50 XP 및 500 코인 추가 지급
            new_voice_mins = old_voice_mins + 1
            if new_voice_mins > 0 and new_voice_mins % 60 == 0:
                xp_to_add += 50
                coin_to_add += 500
                print(f"🎁 [시즌패스] {uid}님 누적 음성 {new_voice_mins}분 달성 보너스 50 XP & 500 코인 지급!")
                
            new_xp = old_xp + xp_to_add
            
            cursor.execute(
                f"UPDATE users SET xp = xp + {p}, coin = coin + {p}, voice_minutes = voice_minutes + 1 WHERE user_id = {p}",
                (xp_to_add, coin_to_add, uid)
            )
            
            # 일일 퀘스트 진행도 적립
            if DATABASE_URL:
                cursor.execute("""
                    INSERT INTO user_quests (user_id, quest_id, progress, claimed, quest_date)
                    VALUES (%s, 'voice_30m', 1, 0, %s)
                    ON CONFLICT (user_id, quest_id, quest_date)
                    DO UPDATE SET progress = user_quests.progress + EXCLUDED.progress
                """, (uid, today_str))
            else:
                cursor.execute("""
                    INSERT INTO user_quests (user_id, quest_id, progress, claimed, quest_date)
                    VALUES (?, 'voice_30m', 1, 0, ?)
                    ON CONFLICT (user_id, quest_id, quest_date)
                    DO UPDATE SET progress = user_quests.progress + EXCLUDED.progress
                """, (uid, today_str))
            
            check_and_grant_level_rewards(cursor, p, uid, old_xp, new_xp)
            
        conn.commit()
        cursor.close()
        conn.close()
        print(f"🎙️ [시즌패스] 음성 활성 유저 {len(user_ids)}명 XP 지급 및 레벨업 체크 완료")
    except Exception as e:
        print(f"❌ voice_xp_loop 오류: {e}")

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name} ({bot.user.id})")
    
    # 1. 영구 뷰 등록
    bot.add_view(VoiceUsagePanel())
    bot.add_view(PassPanelView())
    bot.add_view(ShopPanelView())
    
    # 2. 지정된 채널에 패널 메시지가 있는지 확인 및 자동 복구/생성
    target_channel_id = 1513160056214913144
    channel = bot.get_channel(target_channel_id)
    if channel:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            p = "%s" if DATABASE_URL else "?"
            cursor.execute(f"SELECT message_id FROM voice_panel WHERE channel_id = {p}", (target_channel_id,))
            row = cursor.fetchone()
            panel_msg_id = row[0] if row else None
            
            panel_exists = False
            if panel_msg_id:
                try:
                    await channel.fetch_message(panel_msg_id)
                    panel_exists = True
                except discord.NotFound:
                    # 기존 메시지가 삭제됨
                    cursor.execute(f"DELETE FROM voice_panel WHERE channel_id = {p}", (target_channel_id,))
                    conn.commit()
            
            if not panel_exists:
                embed = discord.Embed(
                    title="📊 음성 채널 이용 시간 조회",
                    description="아래 버튼을 누르면 오늘의 랭킹, 누적 전체 랭킹 또는 특정 날짜의 랭킹을 실시간으로 확인할 수 있습니다.",
                    color=discord.Color.blurple()
                )
                msg = await channel.send(embed=embed, view=VoiceUsagePanel())
                
                # SQLite와 PostgreSQL 공용 ON CONFLICT 문법
                query = f"""
                INSERT INTO voice_panel (channel_id, message_id)
                VALUES ({p}, {p})
                ON CONFLICT (channel_id)
                DO UPDATE SET message_id = EXCLUDED.message_id
                """
                cursor.execute(query, (target_channel_id, msg.id))
                conn.commit()
                print(f"📊 이용 시간 조회 패널 메시지 생성 완료 (ID: {msg.id})")
            else:
                print("📊 이용 시간 조회 패널 메시지가 이미 존재합니다.")
            cursor.close()
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
    
    # 5. 시즌 패스 XP 적립 루프 시작
    if not voice_xp_loop.is_running():
        voice_xp_loop.start()
        print("⏰ 시즌 패스 음성 XP 적립 루프 시작 완료")

    try:
        # 기존에 복사 등록되어 중복 노출을 유발하던 길드 명령어들을 삭제합니다.
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        # 이제 글로벌 명령어로만 1개 노출되도록 동기화합니다.
        await bot.tree.sync()
        print("✅ 글로벌 슬래시 명령어 동기화 및 길드 중복 제거 완료")
    except Exception as e:
        print(f"❌ 슬래시 명령어 동기화 오류: {e}")


# =========================
# 관리자 명령어 (시즌 패스)
# =========================
@bot.tree.command(name="패스패널생성", description="HEAVEN 시즌 패스 버튼 패널을 생성합니다.")
@app_commands.default_permissions(administrator=True)
async def create_pass_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 HEAVEN 시즌 패스",
        description=(
            "음성 채널에 참여하여 패스 레벨을 올리고 풍성한 보상을 획득하세요!\n\n"
            "**💡 획득 방식**\n"
            "🎤 **음성 채널 참여:** 1분당 **5 XP** (부스터 적용 시 **10 XP**) & 💰 **20 코인** 지급\n"
            "🎁 **누적 참여 보너스:** 60분마다 **+50 XP** & 💰 **+500 코인** 추가 지급\n\n"
            "📦 아래 버튼을 눌러 내 시즌 패스 정보를 확인하거나 상점을 이용하실 수 있습니다."
        ),
        color=0x9b59b6
    )
    await interaction.response.send_message(embed=embed, view=PassPanelView())

@bot.tree.command(name="재화지급", description="관리자용 재화 지급")
@app_commands.default_permissions(administrator=True)
async def give_coin(interaction: discord.Interaction, member: discord.Member, amount: int):
    add_coin(member.id, amount)
    await interaction.response.send_message(f"✅ {member.mention}에게 재화 {amount:,} 지급 완료.", ephemeral=True)

@bot.tree.command(name="상자지급", description="관리자용 상자 지급")
@app_commands.default_permissions(administrator=True)
@app_commands.choices(box_type=[
    app_commands.Choice(name="📦 랜덤 상자", value="random_box"),
    app_commands.Choice(name="🎁 프리미엄 상자", value="premium_box"),
    app_commands.Choice(name="👑 잭팟 상자", value="jackpot_box")
])
async def give_box(interaction: discord.Interaction, member: discord.Member, box_type: str, amount: int):
    add_item(member.id, box_type, amount)
    box_names = {
        "random_box": "랜덤 상자",
        "premium_box": "프리미엄 상자",
        "jackpot_box": "잭팟 상자"
    }
    await interaction.response.send_message(f"✅ {member.mention}에게 {box_names[box_type]} {amount}개 지급 완료.", ephemeral=True)

@bot.tree.command(name="xp지급", description="관리자용 XP 지급")
@app_commands.default_permissions(administrator=True)
async def give_xp(interaction: discord.Interaction, member: discord.Member, amount: int):
    rewards = add_xp(member.id, amount)
    msg = f"✅ {member.mention}에게 XP {amount:,} 지급 완료."
    if rewards:
        msg += f"\n🎁 지급 과정에서 레벨업 보상 획득: {', '.join(rewards)}"
    await interaction.response.send_message(msg, ephemeral=True)


# 양식 입력 확인 및 역할 제거 이벤트
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 특정 채널(ID: 1516049566535909439)의 메시지는 봇이 무시하도록 설정
    if message.channel.id == 1516049566535909439:
        return

    # 지정한 채널 ID 확인
    if message.channel.id == 1497843456960364726:
        content = message.content
        # 공백을 모두 제거하여 띄어쓰기 오차 무시
        content_stripped = "".join(content.split())
        
        # 유연한 키워드 매칭 조건 설정
        has_nickname = "닉네임/나이" in content_stripped or "닉넴/나이" in content_stripped
        has_game = "주로하는게임" in content_stripped
        has_time = "플레이시간대" in content_stripped
        has_intro = "소개글" in content_stripped
        
        if has_nickname and has_game and has_time and has_intro:
            member = message.author
            if isinstance(member, discord.Member):
                # 제거할 역할 (ID: 1369712767631626313)
                target_role_id = 1369712767631626313
                role_to_remove = message.guild.get_role(target_role_id)
                
                # 부여할 역할 (ID: 1497939431473287238)
                grant_role_id = 1497939431473287238
                role_to_grant = message.guild.get_role(grant_role_id)
                
                # 역할 부여 처리
                grant_success = False
                if role_to_grant:
                    try:
                        await member.add_roles(role_to_grant)
                        print(f"✅ 역할 부여 완료: {member.name}에게 '{role_to_grant.name}' 역할을 부여했습니다.")
                        grant_success = True
                    except discord.Forbidden:
                        print(f"❌ 권한 부족: '{role_to_grant.name}' 역할을 부여할 수 없습니다. 봇의 역할 서열을 올려주세요.")
                    except Exception as e:
                        print(f"❌ 역할 부여 오류: {e}")
                else:
                    print(f"❌ 오류: 역할 ID {grant_role_id}를 서버에서 찾을 수 없습니다.")

                # 역할 제거 처리
                if role_to_remove:
                    if role_to_remove in member.roles:
                        try:
                            await member.remove_roles(role_to_remove)
                            await message.add_reaction("✅")
                            # 안내 메시지 전송 후 5초 뒤 자동 삭제
                            msg = await message.reply(f"✅ 양식 작성이 확인되어 **{role_to_remove.name}** 역할이 제거되고 **{role_to_grant.name if role_to_grant else '새로운'}** 역할이 부여되었습니다.", mention_author=False)
                            await asyncio.sleep(5)
                            await msg.delete()
                        except discord.Forbidden:
                            print(f"❌ 권한 부족: '{role_to_remove.name}' 역할을 제거할 수 없습니다. 봇의 역할 서열을 올려주세요.")
                        except Exception as e:
                            print(f"❌ 역할 제거 오류: {e}")
                    else:
                        # 이미 역할이 없는 경우에도 확인 리액션은 달아줌
                        await message.add_reaction("✅")
                        if grant_success and role_to_grant:
                            msg = await message.reply(f"✅ 양식 작성이 확인되어 **{role_to_grant.name}** 역할이 부여되었습니다.", mention_author=False)
                            await asyncio.sleep(5)
                            await msg.delete()
                else:
                    print(f"❌ 오류: 역할 ID {target_role_id}를 서버에서 찾을 수 없습니다.")

    await bot.process_commands(message)

# 유저 퇴장 감지 이벤트
@bot.event
async def on_member_remove(member):
    # 유저가 서버를 나가면 DB에 기록
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        query = f"INSERT INTO left_users (user_id) VALUES ({p}) ON CONFLICT (user_id) DO NOTHING"
        cursor.execute(query, (member.id,))
        conn.commit()
        cursor.close()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT user_id FROM left_users WHERE user_id = {p}", (member.id,))
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
            cursor.execute(f"DELETE FROM left_users WHERE user_id = {p}", (member.id,))
            conn.commit()
            print(f"📤 재입장 확인 후 DB 기록 삭제: {member.name} ({member.id})")
            
        cursor.close()
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