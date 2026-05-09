import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import os
from flask import Flask
from threading import Thread
import random
import asyncio
import time

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DB
# =========================
conn = sqlite3.connect("rooms.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS panels (
    channel_id INTEGER,
    message_id INTEGER
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT,
    game TEXT,
    max_people INTEGER,
    time TEXT,
    owner_id INTEGER,
    voice_channel_id INTEGER,
    channel_id INTEGER,
    message_id INTEGER
)
""")

# 컬럼 추가 (기존 DB 호환성)
try:
    cursor.execute("ALTER TABLE rooms ADD COLUMN channel_id INTEGER")
    cursor.execute("ALTER TABLE rooms ADD COLUMN message_id INTEGER")
except:
    pass

try:
    cursor.execute("ALTER TABLE participants ADD COLUMN tier TEXT DEFAULT '-'")
    cursor.execute("ALTER TABLE participants ADD COLUMN position TEXT DEFAULT '-'")
except:
    pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS participants (
    room_id TEXT,
    user_id INTEGER,
    category TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS voice_time (
    user_id INTEGER PRIMARY KEY,
    total_seconds INTEGER DEFAULT 0
)
""")

conn.commit()

# =========================
# 데이터 및 유틸
# =========================
GAME_DATA = {
    "롤": {"emoji": "⚔️", "color": 0x1f8b4c, "image": "https://i.namu.wiki/i/bcJDyma8areiVI20l4oUFYr6Y6LqPw3NczClG_r0PGkmwvFqEzbkdpUkUdIl1b15WotgqANrvYW4p0LcTcXyyA.webp"},
    "리그": {"emoji": "⚔️", "color": 0x1f8b4c, "image": "https://i.namu.wiki/i/bcJDyma8areiVI20l4oUFYr6Y6LqPw3NczClG_r0PGkmwvFqEzbkdpUkUdIl1b15WotgqANrvYW4p0LcTcXyyA.webp"},
    "옵치": {"emoji": "🔫", "color": 0xfa9c1e, "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRamwdKLcNDA5HmgJK6gNkrWN93hQLuSpMTkg&s"},
    "오버워치": {"emoji": "🔫", "color": 0xfa9c1e, "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRamwdKLcNDA5HmgJK6gNkrWN93hQLuSpMTkg&s"},
    "발로": {"emoji": "🎯", "color": 0xff4654, "image": "https://img.icons8.com/color/512/valorant.png"},
    "배그": {"emoji": "🍗", "color": 0xffd700, "image": "https://i.namu.wiki/i/-39mmyx2w53w1_YD7TH5AM55BukpjzibRZxSHbQOCTwdtNj8mxq2ZkxQrInLHr5WvR3wR9CuUEMSAon11jQ3aA.webp"},
    "마크": {"emoji": "🧱", "color": 0x2e8b57, "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRf5AbwiADFKcpD6O460H6-c6NVBKoax295xA&s"},
    "로아": {"emoji": "💎", "color": 0x00bfff, "image": "https://mblogthumb-phinf.pstatic.net/MjAxODExMTNfMTEy/MDAxNTQyMTEyMTczMjk3.YPwTVv5idsyihoiw7iweVjFZNziwV8qK8ADBIfxKk7Qg.4MQcdnHJT04oPLjr7KMOB7CUwjyBc5xNBi0rJSi55iIg.PNG.1ets_9o/bi-lostark.png?type=w800"},  # 로아 대체 (판타지 아이콘)
    "메이플": {"emoji": "🍁", "color": 0xff8c00, "image": "https://image.ytn.co.kr/general/jpg/2021/0311/202103110915014429_d.jpg"}, # 메이플 대체 (단풍잎 아이콘)
    "서든어택": {"emoji": "🔫", "color": 0x2b2d31, "image": "https://i.namu.wiki/i/1mH8Ae0cQRPdbxclfEKND_8aa6kpn86MSBYiJK7_Coh362VMvgbgyDCSm8H2raru-33_SnZ0xa6oK-tMbnQT3g.webp"},
    "스팀": {"emoji": "🎮", "color": 0x1b2838, "image": "https://i.namu.wiki/i/J0mA8KSg4QpPd07VtHqOSr4A8UhKNOaUUctpdJb6IVno4zqLCHDC_sM8z1hDz-RsaiOYLfOevgkrHTMgXslirA.svg"},
    "롤 내전": {"emoji": "⚔️", "color": 0x0099ff, "image": "https://i.namu.wiki/i/bcJDyma8areiVI20l4oUFYr6Y6LqPw3NczClG_r0PGkmwvFqEzbkdpUkUdIl1b15WotgqANrvYW4p0LcTcXyyA.webp"},
    "옵치 내전": {"emoji": "🛡️", "color": 0xfa9c1e, "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRamwdKLcNDA5HmgJK6gNkrWN93hQLuSpMTkg&s"},
    "옵치 6vs6": {"emoji": "🚀", "color": 0xfa9c1e, "image": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRamwdKLcNDA5HmgJK6gNkrWN93hQLuSpMTkg&s"},
}

# 알림 매핑 (줄임말 입력 시 여러 역할 멘션)
MENTION_MAPPING = {
    "옵치": ["오버워치", "옵치"],
    "옵치 내전": ["오버워치", "옵치"],
    "옵치 6vs6": ["오버워치", "옵치"],
    "오버워치": ["오버워치", "옵치"],
    "리그": ["롤", "리그오브레전드"],
    "리그오브레전드": ["롤", "리그오브레전드"],
    "롤": ["롤", "리그오브레전드"],
    "서든": ["서든어택"],
    "서든어택": ["서든어택"],
    "스팀": ["스팀"]
}

def get_count(room_id, category):
    cursor.execute("SELECT COUNT(*) FROM participants WHERE room_id=? AND category=?", (room_id, category))
    return cursor.fetchone()[0]

def add_user(room_id, user_id, category):
    remove_user(room_id, user_id)
    cursor.execute("INSERT INTO participants (room_id, user_id, category) VALUES (?, ?, ?)", (room_id, user_id, category))
    conn.commit()

def remove_user(room_id, user_id):
    cursor.execute("DELETE FROM participants WHERE room_id=? AND user_id=?", (room_id, user_id))
    conn.commit()

def get_users(room_id, category):
    cursor.execute("SELECT user_id FROM participants WHERE room_id=? AND category=?", (room_id, category))
    return [row[0] for row in cursor.fetchall()]

def get_users_info(room_id, category):
    cursor.execute("SELECT user_id, tier, position FROM participants WHERE room_id=? AND category=?", (room_id, category))
    return cursor.fetchall()

def update_user_info(room_id, user_id, tier, position):
    cursor.execute("UPDATE participants SET tier=?, position=? WHERE room_id=? AND user_id=?", (tier, position, room_id, user_id))
    conn.commit()

def make_embed(room_id, guild=None):
    cursor.execute("SELECT game, max_people, time, owner_id FROM rooms WHERE room_id=?", (room_id,))
    row = cursor.fetchone()
    if not row: return discord.Embed(title="오류", description="방 정보를 찾을 수 없습니다.")
    
    game, max_people, time_, owner_id = row

    # 게임 정보 매칭
    data = {"emoji": "🎮", "color": 0x2b2d31, "image": None}
    for key, val in GAME_DATA.items():
        if key in game:
            data = val
            break

    join = get_users_info(room_id, "참가")
    wait = get_users_info(room_id, "대기")
    watch = get_users_info(room_id, "관전")
    blue = get_users_info(room_id, "블루팀")
    red = get_users_info(room_id, "레드팀")

    embed = discord.Embed(
        title=f"{data['emoji']} {game}",
        description=f"**{time_}** 에 시작하는 모집입니다!",
        color=data['color']
    )
    
    if data['image']:
        embed.set_thumbnail(url=data['image'])

    # 인원 바 시각화
    filled = len(join)
    empty = max_people - filled
    progress_bar = "🔵" * filled + "⚪" * max(0, empty)
    
    embed.add_field(name="👥 현재 인원", value=f"{progress_bar} ({len(join)}/{max_people})", inline=False)
    
    embed.add_field(name="✅ 참가자", value="\n".join([f"└ <@{u}> `[{p}/{t}]`" for u, t, p in join]) or "└ -", inline=True)
    
    if blue or red:
        embed.add_field(name="🔵 블루팀", value="\n".join([f"└ <@{u}> `[{p}/{t}]`" for u, t, p in blue]) or "└ -", inline=True)
        embed.add_field(name="🔴 레드팀", value="\n".join([f"└ <@{u}> `[{p}/{t}]`" for u, t, p in red]) or "└ -", inline=True)
    
    embed.add_field(name="⏳ 대기", value="\n".join([f"└ <@{u}> `[{p}/{t}]`" for u, t, p in wait]) or "└ -", inline=True)
    embed.add_field(name="👀 관전", value="\n".join([f"└ <@{u}>" for u, t, p in watch]) or "└ -", inline=True)

    if guild:
        owner = guild.get_member(owner_id)
        if owner:
            embed.set_author(name=f"{owner.display_name}님의 모집", icon_url=owner.display_avatar.url)
    
    embed.set_footer(text="호야 모집 시스템 • 즐거운 게임 되세요!")
    embed.timestamp = discord.utils.utcnow()

    return embed

# =========================
# 버튼 로직
# =========================
async def handle_action(interaction, room_id, choice):
    cursor.execute("SELECT owner_id, max_people, voice_channel_id FROM rooms WHERE room_id=?", (room_id,))
    owner_id, max_people, voice_id = cursor.fetchone()

    voice_channel = interaction.guild.get_channel(voice_id)

    if choice == "참가":
        cursor.execute("SELECT game FROM rooms WHERE room_id=?", (room_id,))
        game_name = cursor.fetchone()[0]
        
        if "롤" in game_name or "리그" in game_name or "옵치" in game_name or "오버워치" in game_name:
            await interaction.response.send_message("🛡️ 자신의 **포지션**과 **티어**를 선택해주세요.", view=InfoSelectView(room_id, game_name), ephemeral=True)
            return

        if get_count(room_id, "참가") >= max_people:
            add_user(room_id, interaction.user.id, "대기")
            await interaction.response.edit_message(embed=make_embed(room_id, interaction.guild), view=RoomView(room_id))
            await interaction.followup.send("👥 인원이 가득 차 대기로 이동되었습니다.", ephemeral=True)
            return
        else:
            add_user(room_id, interaction.user.id, "참가")

            if interaction.user.voice:
                try:
                    await interaction.user.move_to(voice_channel)
                except:
                    pass

        # 닉네임에서 [관전] 제거 (참가 시)
        if interaction.user.display_name.startswith("[관전]"):
            try:
                new_nick = interaction.user.display_name.replace("[관전] ", "").replace("[관전]", "")
                await interaction.user.edit(nick=new_nick)
            except:
                pass

    elif choice == "대기":
        add_user(room_id, interaction.user.id, "대기")

        # 닉네임에서 [관전] 제거
        if interaction.user.display_name.startswith("[관전]"):
            try:
                new_nick = interaction.user.display_name.replace("[관전] ", "").replace("[관전]", "")
                await interaction.user.edit(nick=new_nick)
            except:
                pass

    elif choice == "관전":
        add_user(room_id, interaction.user.id, "관전")
        
        # 닉네임 앞에 [관전] 추가
        if not interaction.user.display_name.startswith("[관전]"):
            try:
                await interaction.user.edit(nick=f"[관전] {interaction.user.display_name}")
            except:
                pass

    elif choice == "나가기":
        remove_user(room_id, interaction.user.id)

        # 닉네임에서 [관전] 제거
        if interaction.user.display_name.startswith("[관전]"):
            try:
                new_nick = interaction.user.display_name.replace("[관전] ", "").replace("[관전]", "")
                await interaction.user.edit(nick=new_nick)
            except:
                pass

        if interaction.user.id == owner_id:
            # 방장이 나간 경우 다음 방장 선정 (참가자 -> 대기자 순)
            participants = get_users(room_id, "참가")
            waits = get_users(room_id, "대기")
            new_owner_id = (participants + waits + [None])[0]

            if new_owner_id:
                cursor.execute("UPDATE rooms SET owner_id=? WHERE room_id=?", (new_owner_id, room_id))
                conn.commit()
            else:
                # 남은 사람이 아무도 없으면 방 종료
                if voice_channel:
                    try:
                        await voice_channel.delete()
                    except discord.NotFound:
                        pass
                    except discord.HTTPException:
                        pass

                cursor.execute("DELETE FROM rooms WHERE room_id=?", (room_id,))
                cursor.execute("DELETE FROM participants WHERE room_id=?", (room_id,))
                conn.commit()
                await interaction.message.delete()
                return

    elif choice == "종료":
        if interaction.user.id != owner_id:
            await interaction.response.send_message("❌ 방장만 가능", ephemeral=True)
            return

        if voice_channel:
            try:
                await voice_channel.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass

        cursor.execute("DELETE FROM rooms WHERE room_id=?", (room_id,))
        cursor.execute("DELETE FROM participants WHERE room_id=?", (room_id,))
        conn.commit()
        await interaction.message.delete()
        return

    elif choice == "팀나누기":
        if interaction.user.id != owner_id:
            await interaction.response.send_message("❌ 방장만 가능", ephemeral=True)
            return
        
        participants = get_users(room_id, "참가")
        blue_existing = get_users(room_id, "블루팀")
        red_existing = get_users(room_id, "레드팀")
        
        all_players = participants + blue_existing + red_existing
        
        if len(all_players) < 2:
            await interaction.response.send_message("❌ 최소 2명 이상의 참가자가 필요합니다.", ephemeral=True)
            return
        
        random.shuffle(all_players)
        mid = len(all_players) // 2
        blue_team = all_players[:mid]
        red_team = all_players[mid:]
        
        # 기존 팀 정보 초기화 및 재배정
        cursor.execute("DELETE FROM participants WHERE room_id=? AND category IN ('참가', '블루팀', '레드팀')", (room_id,))
        for u in blue_team:
            cursor.execute("INSERT INTO participants VALUES (?, ?, ?)", (room_id, u, "블루팀"))
        for u in red_team:
            cursor.execute("INSERT INTO participants VALUES (?, ?, ?)", (room_id, u, "레드팀"))
        conn.commit()
        
        await interaction.response.edit_message(embed=make_embed(room_id, interaction.guild), view=RoomView(room_id))
        await interaction.followup.send("🎲 팀이 무작위로 배정되었습니다!", ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.edit_message(embed=make_embed(room_id, interaction.guild), view=RoomView(room_id))

# =========================
# UI
# =========================
class RoomView(discord.ui.View):
    def __init__(self, room_id):
        super().__init__(timeout=None)
        self.room_id = room_id
        # 버튼들에 고유 ID 부여
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.custom_id = f"{child.label}_{room_id}"

    @discord.ui.button(label="참가", style=discord.ButtonStyle.green)
    async def join(self, interaction, button):
        await handle_action(interaction, self.room_id, "참가")

    @discord.ui.button(label="대기", style=discord.ButtonStyle.gray)
    async def wait(self, interaction, button):
        await handle_action(interaction, self.room_id, "대기")

    @discord.ui.button(label="관전", style=discord.ButtonStyle.blurple)
    async def watch(self, interaction, button):
        await handle_action(interaction, self.room_id, "관전")

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.red)
    async def leave(self, interaction, button):
        await handle_action(interaction, self.room_id, "나가기")

    @discord.ui.button(label="종료", style=discord.ButtonStyle.danger)
    async def close(self, interaction, button):
        await handle_action(interaction, self.room_id, "종료")

    @discord.ui.button(label="팀 나누기", style=discord.ButtonStyle.secondary)
    async def shuffle(self, interaction, button):
        await handle_action(interaction, self.room_id, "팀나누기")

# =========================
# 포지션/티어 선택 UI
# =========================
class InfoSelectView(discord.ui.View):
    def __init__(self, room_id, game_name):
        super().__init__(timeout=60)
        self.room_id = room_id
        self.tier = "-"
        self.position = "-"
        
        # 게임별 옵션 설정
        if "롤" in game_name or "리그" in game_name:
            pos_options = [
                discord.SelectOption(label="탑", emoji="🛡️"),
                discord.SelectOption(label="정글", emoji="⚔️"),
                discord.SelectOption(label="미드", emoji="🔮"),
                discord.SelectOption(label="원딜", emoji="🏹"),
                discord.SelectOption(label="서폿", emoji="🌿"),
            ]
            tier_options = [
                discord.SelectOption(label="아이언", emoji="🌑"),
                discord.SelectOption(label="브론즈", emoji="🟤"),
                discord.SelectOption(label="실버", emoji="⚪"),
                discord.SelectOption(label="골드", emoji="🟡"),
                discord.SelectOption(label="플래티넘", emoji="🟢"),
                discord.SelectOption(label="에메랄드", emoji="✳️"),
                discord.SelectOption(label="다이아", emoji="💎"),
                discord.SelectOption(label="마스터+", emoji="🔮"),
            ]
        elif "옵치" in game_name or "오버워치" in game_name:
            pos_options = [
                discord.SelectOption(label="탱커", emoji="🛡️"),
                discord.SelectOption(label="딜러", emoji="⚔️"),
                discord.SelectOption(label="힐러", emoji="💉"),
            ]
            tier_options = [
                discord.SelectOption(label="브론즈", emoji="🟤"),
                discord.SelectOption(label="실버", emoji="⚪"),
                discord.SelectOption(label="골드", emoji="🟡"),
                discord.SelectOption(label="플래티넘", emoji="🟢"),
                discord.SelectOption(label="다이아", emoji="💎"),
                discord.SelectOption(label="마스터", emoji="🔮"),
                discord.SelectOption(label="그랜드마스터", emoji="✨"),
                discord.SelectOption(label="랭커", emoji="👑"),
            ]
        else:
            pos_options = [discord.SelectOption(label="일반", emoji="👤")]
            tier_options = [discord.SelectOption(label="일반", emoji="📊")]

        self.add_item(PositionSelect(pos_options))
        self.add_item(TierSelect(tier_options))
        self.add_item(ConfirmButton())

class PositionSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="포지션을 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.position = self.values[0]
        await interaction.response.defer()

class TierSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="티어를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.tier = self.values[0]
        await interaction.response.defer()

class ConfirmButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="선택 완료", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view.position == "-" or view.tier == "-":
            await interaction.response.send_message("❌ 포지션과 티어를 모두 선택해주세요.", ephemeral=True)
            return

        cursor.execute("SELECT max_people FROM rooms WHERE room_id=?", (view.room_id,))
        max_people = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM participants WHERE room_id=? AND category='참가'", (view.room_id,))
        count = cursor.fetchone()[0]

        if count >= max_people:
            category = "대기"
        else:
            category = "참가"

        remove_user(view.room_id, interaction.user.id)
        cursor.execute("INSERT INTO participants VALUES (?, ?, ?, ?, ?)", (view.room_id, interaction.user.id, category, view.tier, view.position))
        conn.commit()

        cursor.execute("SELECT channel_id, message_id FROM rooms WHERE room_id=?", (view.room_id,))
        ch_id, msg_id = cursor.fetchone()
        channel = bot.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=make_embed(view.room_id, interaction.guild), view=RoomView(view.room_id))
            except:
                pass

        # 선택창 제거 및 확인 메시지 (1초 후 자동 삭제)
        try:
            await interaction.response.edit_message(content="✅ 참가가 완료되었습니다!", view=None)
            # ephemeral 메시지는 delete_original_response로 삭제 가능
            await asyncio.sleep(1)
            await interaction.delete_original_response()
        except:
            pass
        view.stop()

class CreateModal(discord.ui.Modal, title="모집 생성"):
    game = discord.ui.TextInput(label="게임")
    people = discord.ui.TextInput(label="인원 (숫자)")
    time_ = discord.ui.TextInput(label="시간")

    async def on_submit(self, interaction):
        room_id = str(interaction.id)
        guild = interaction.guild

        # 음성 채널 이름 및 게임 이름 자동 조정 (옵치 12명인 경우 6vs6)
        game_val = self.game.value
        people_count = int(self.people.value)
        
        if ("옵치" in game_val or "오버워치" in game_val) and people_count == 12:
            if "6vs6" not in game_val:
                game_val = f"{game_val} 6vs6"

        if game_val in ["롤", "리그오브레전드"]:
            channel_name = "┋⚔️┋리그오브레전드"
        elif "옵치" in game_val or "오버워치" in game_val:
            channel_name = f"┋⌚┋{game_val}"
        else:
            channel_name = f" {game_val}"

        category = guild.get_channel(1488774793497940080)
        try:
            voice_channel = await guild.create_voice_channel(channel_name, category=category)
        except:
            voice_channel = await guild.create_voice_channel(channel_name)

        cursor.execute(
            "INSERT INTO rooms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (room_id, game_val, people_count, self.time_.value, interaction.user.id, voice_channel.id, 0, 0)
        )
        conn.commit()

        add_user(room_id, interaction.user.id, "참가")

        if interaction.user.voice:
            await interaction.user.move_to(voice_channel)

        # 게임 이름과 일치하는 역할들 찾기 (매핑 활용)
        game_input = self.game.value
        role_names = MENTION_MAPPING.get(game_input, [game_input])
        
        mentions = []
        for name in role_names:
            role = discord.utils.get(guild.roles, name=name)
            if role:
                mentions.append(role.mention)
        
        mention_str = " ".join(mentions)

        await interaction.response.send_message(
            content=mention_str,
            embed=make_embed(room_id, guild),
            view=RoomView(room_id)
        )
        
        # 메시지 ID 저장
        msg = await interaction.original_response()
        cursor.execute("UPDATE rooms SET channel_id=?, message_id=? WHERE room_id=?", (msg.channel.id, msg.id, room_id))
        conn.commit()

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="모집 만들기", style=discord.ButtonStyle.primary, custom_id="panel_create_btn")
    async def create(self, interaction, button):
        await interaction.response.send_modal(CreateModal())

# =========================
# 모집판 추가
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def 모집추가(ctx):
    embed = discord.Embed(
        title="🎮 호야 모집판",
        description="함께 게임할 팀원을 모집해보세요!\n아래 버튼을 눌러 모집을 시작할 수 있습니다.",
        color=0x5865f2
    )
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1494319173940023411/1501615259549565102/18b6c8f6-c2d8-4eba-8dda-2aba45b4bba5.png?ex=69fcb7b0&is=69fb6630&hm=1d058fe2f297afbb1b124deb8f7bac4dcc4bfdea8999f4bfd2f7c1a6f07fe952&")  # 대표 아이콘
    embed.set_footer(text="호야 모집 시스템 • 매너 게임 부탁드립니다!")
    
    msg = await ctx.send(embed=embed, view=PanelView())

    cursor.execute("INSERT INTO panels VALUES (?, ?)", (ctx.channel.id, msg.id))
    conn.commit()

    await ctx.message.delete()

# =========================
# 역할 부여 시스템
# =========================
class RoleAssignmentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # 게임 데이터의 키(이름) 순서대로 버튼 생성 (리그, 옵치, 서든은 제외)
        exclude = ["리그", "옵치", "서든"]
        for game_name in GAME_DATA.keys():
            if game_name in exclude:
                continue
            self.add_item(RoleButton(game_name))

class RoleButton(discord.ui.Button):
    def __init__(self, game_name):
        data = GAME_DATA[game_name]
        super().__init__(
            label=game_name,
            emoji=data['emoji'],
            style=discord.ButtonStyle.secondary,
            custom_id=f"role_assign_{game_name}"
        )
        self.game_name = game_name

    async def callback(self, interaction: discord.Interaction):
        role = discord.utils.get(interaction.guild.roles, name=self.game_name)
        if not role:
            await interaction.response.send_message(f"❌ '{self.game_name}' 역할이 서버에 없습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(f"✅ '{self.game_name}' 역할이 제거되었습니다.", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"✅ '{self.game_name}' 역할이 부여되었습니다.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ 권한이 부족합니다. 서버 설정에서 **봇의 역할 순위**를 '{self.game_name}' 역할보다 위로 올려주세요!", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def 역할설정(ctx):
    embed = discord.Embed(
        title="🎭 게임 역할 부여",
        description="아래 버튼을 클릭하여 관심 있는 게임의 역할을 받을 수 있습니다.\n역할을 받으면 해당 게임의 **모집 알림**을 받을 수 있습니다!",
        color=0x2b2d31
    )
    embed.set_footer(text="버튼을 다시 누르면 역할을 취소할 수 있습니다.")
    await ctx.send(embed=embed, view=RoleAssignmentView())
    await ctx.message.delete()

# =========================
# 초기 설정 (역할 생성)
# =========================
@bot.command()
@commands.has_permissions(administrator=True)
async def 초기설정(ctx):
    # "리그" 역할을 "리그오브레전드"로 미리 변경 (유저 정보 유지)
    old_role = discord.utils.get(ctx.guild.roles, name="리그")
    if old_role:
        await old_role.edit(name="리그오브레전드")

    target_roles = ["롤", "리그오브레전드", "오버워치", "발로", "배그", "마크", "로아", "메이플", "서든어택", "스팀"]
    created = []
    existed = []

    for role_name in target_roles:
        if not discord.utils.get(ctx.guild.roles, name=role_name):
            await ctx.guild.create_role(name=role_name, mentionable=True)
            created.append(role_name)
        else:
            existed.append(role_name)

    res = f"✅ **초기 설정 완료**\n"
    if created:
        res += f"- 생성됨: {', '.join(created)}\n"
    if existed:
        res += f"- 이미 존재함: {', '.join(existed)}\n"
    
    await ctx.send(res, delete_after=10)
    await ctx.message.delete()

# =========================
# 닉네임 변경 시스템
# =========================
class NicknameModal(discord.ui.Modal, title="닉네임 변경"):
    new_nick = discord.ui.TextInput(label="변경할 닉네임", placeholder="원하는 닉네임을 입력하세요.", max_length=32)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.user.edit(nick=self.new_nick.value)
            await interaction.response.send_message(f"✅ 닉네임이 `{self.new_nick.value}`(으)로 변경되었습니다.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ **권한 부족**: 닉네임을 변경할 수 없습니다.\n\n"
                "**해결 방법:**\n"
                "1. 봇에게 **'닉네임 관리'** 권한이 있는지 확인해주세요.\n"
                "2. 서버 설정 > 역할에서 **봇의 역할 순위**를 변경하려는 유저보다 위로 올려주세요.\n"
                "3. 서버 소유자의 닉네임은 봇이 변경할 수 없습니다.", 
                ephemeral=True
            )

class NicknameView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="닉네임 변경", style=discord.ButtonStyle.primary, custom_id="change_nickname_btn")
    async def change_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NicknameModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def 닉네임설정(ctx):
    embed = discord.Embed(
        title="📝 서버 닉네임 설정",
        description="아래 버튼을 눌러 이 서버에서 사용할 닉네임을 변경할 수 있습니다.",
        color=0x2b2d31
    )
    await ctx.send(embed=embed, view=NicknameView())
    await ctx.message.delete()

# =========================
# 자동 복구
# =========================
@bot.event
async def on_ready():
    bot.add_view(RoleAssignmentView()) # 역할 부여 뷰 등록
    bot.add_view(NicknameView()) # 닉네임 변경 뷰 등록
    bot.add_view(VoiceStatView()) # 음성 통계 뷰 등록
    bot.add_view(ReportView()) # 불편 신고 뷰 등록
    bot.add_view(OutingView()) # 외출 신청 뷰 등록
    cursor.execute("SELECT message_id FROM panels")
    for (msg_id,) in cursor.fetchall():
        bot.add_view(PanelView())

    cursor.execute("SELECT room_id FROM rooms")
    for (room_id,) in cursor.fetchall():
        bot.add_view(RoomView(room_id))

    # 봇 재시작 시 이미 음성 채널에 있는 유저들 추적 시작
    for guild in bot.guilds:
        for voice_channel in guild.voice_channels:
            for member in voice_channel.members:
                if not member.bot:
                    voice_tracking[member.id] = time.time()

    print("완전 최종 실행 완료")

# =========================
# 음성채널 이용 시간 측정
# =========================
voice_tracking = {}

@bot.event
async def on_voice_state_update(member, before, after):
    # 1. 이용 시간 측정 로직
    if before.channel != after.channel:
        # 퇴장하거나 채널을 이동한 경우 (이전 채널에서의 시간 정산)
        if before.channel is not None:
            if member.id in voice_tracking:
                join_time = voice_tracking.pop(member.id)
                duration = int(time.time() - join_time)
                
                cursor.execute("INSERT OR IGNORE INTO voice_time (user_id, total_seconds) VALUES (?, 0)", (member.id,))
                cursor.execute("UPDATE voice_time SET total_seconds = total_seconds + ? WHERE user_id = ?", (duration, member.id))
                conn.commit()
                
                # 등급 업데이트 체크
                cursor.execute("SELECT total_seconds FROM voice_time WHERE user_id = ?", (member.id,))
                total = cursor.fetchone()[0]
                await update_member_role(member, total)

        # 새로운 채널에 입장한 경우 (시작 시간 기록)
        if after.channel is not None:
            # 봇이 재시작되어도 이미 채널에 있던 유저는 정산이 안될 수 있으므로 입장 시각 기록
            voice_tracking[member.id] = time.time()

    # 2. 기존 로직: 음성채널 자동 삭제
    if before.channel and len(before.channel.members) == 0:
        cursor.execute("SELECT room_id, channel_id, message_id FROM rooms WHERE voice_channel_id=?", (before.channel.id,))
        row = cursor.fetchone()

        if row:
            room_id, channel_id, message_id = row
            
            # 음성 채널 삭제
            try:
                await before.channel.delete()
            except:
                pass

            # 모집글 삭제
            try:
                channel = bot.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
            except:
                pass

            cursor.execute("DELETE FROM rooms WHERE room_id=?", (room_id,))
            cursor.execute("DELETE FROM participants WHERE room_id=?", (room_id,))
            conn.commit()

@bot.command()
async def 음성시간(ctx):
    cursor.execute("SELECT total_seconds FROM voice_time WHERE user_id = ?", (ctx.author.id,))
    row = cursor.fetchone()
    
    total_seconds = row[0] if row else 0
    
    # 실시간 접속 중인 경우 현재까지의 시간 합산해서 보여주기
    if ctx.author.id in voice_tracking:
        total_seconds += int(time.time() - voice_tracking[ctx.author.id])
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    embed = discord.Embed(
        title=f"📊 {ctx.author.display_name}님의 음성 통계",
        description=f"총 이용 시간: **{hours}시간 {minutes}분 {seconds}초**",
        color=0x5865f2
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

# =========================
# 음성 등급 설정
# =========================
VOICE_LEVELS = {
    500 * 3600: 1490300613060460815,
    300 * 3600: 1490300585721729104,
    100 * 3600: 1490300554851778721,
    10 * 3600: 1488702425798803598
}

async def update_member_role(member, total_seconds):
    if not isinstance(member, discord.Member):
        return

    # 달성한 가장 높은 등급 찾기
    target_role_id = None
    achieved_threshold = 0
    sorted_thresholds = sorted(VOICE_LEVELS.keys(), reverse=True)
    for threshold in sorted_thresholds:
        if total_seconds >= threshold:
            target_role_id = VOICE_LEVELS[threshold]
            achieved_threshold = threshold
            break

    # 모든 등급 역할 ID 목록
    all_level_role_ids = list(VOICE_LEVELS.values())
    
    # 현재 유저가 가진 등급 관련 역할들 확인
    current_level_roles = [r for r in member.roles if r.id in all_level_role_ids]
    
    # 대상 역할이 이미 있고, 다른 등급 역할이 없다면 이미 승급된 상태이므로 종료
    if target_role_id and any(r.id == target_role_id for r in current_level_roles) and len(current_level_roles) == 1:
        return

    try:
        # 1. 기존 모든 등급 역할 제거
        if current_level_roles:
            await member.remove_roles(*current_level_roles)
        
        # 2. 새로운 등급 역할 부여
        if target_role_id:
            role = member.guild.get_role(target_role_id)
            if role:
                await member.add_roles(role)
                
                # 3. 승급 축하 메시지 전송 (기존에 없던 새로운 등급을 달성한 경우에만)
                if not any(r.id == target_role_id for r in current_level_roles):
                    congrats_channel = member.guild.get_channel(1488701016328241203)
                    if congrats_channel:
                        hours = achieved_threshold // 3600
                        
                        embed = discord.Embed(
                            title="🎊 LEVEL UP - 승급을 축하드립니다! 🎊",
                            description=f"**{member.mention}** 님이 새로운 경지에 도달하셨습니다!",
                            color=0xf1c40f  # 골드 색상
                        )
                        embed.add_field(name="🏆 달성 등급", value=f"**{role.name}**", inline=True)
                        embed.add_field(name="⏱️ 누적 이용 시간", value=f"**{hours}시간**", inline=True)
                        
                        # 고급스러운 효과를 위해 썸네일에 유저 아바타 설정
                        embed.set_thumbnail(url=member.display_avatar.url)
                        
                        embed.timestamp = discord.utils.utcnow()
                        
                        # 화려한 배너 이미지 (고급스러운 골드 테두리 느낌의 이미지)
                        embed.set_image(url="https://i.ibb.co/vXvR8xR/congratulations-banner.png") # 임시 고화질 이미지 URL
                        
                        await congrats_channel.send(content=member.mention, embed=embed)
    except Exception as e:
        print(f"등급 업데이트 오류: {e}")

# =========================
# 음성 통계 버튼 UI
# =========================
class VoiceStatView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="내 음성 시간 확인", style=discord.ButtonStyle.primary, custom_id="check_voice_time_btn")
    async def check_voice_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        cursor.execute("SELECT total_seconds FROM voice_time WHERE user_id = ?", (interaction.user.id,))
        row = cursor.fetchone()
        
        total_seconds = row[0] if row else 0
        
        if interaction.user.id in voice_tracking:
            total_seconds += int(time.time() - voice_tracking[interaction.user.id])
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name}님의 음성 통계",
            description=f"총 이용 시간: **{hours}시간 {minutes}분 {seconds}초**",
            color=0x5865f2
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # 권한 체크 (관리자 또는 특정 역할 보유자)
        allowed_role_id = 1488734131717148793
        is_admin = interaction.user.guild_permissions.administrator or any(role.id == allowed_role_id for role in interaction.user.roles)
        
        view = AdminTimeView() if is_admin else None
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="음성 순위 확인", style=discord.ButtonStyle.secondary, custom_id="check_voice_ranking_btn")
    async def check_voice_ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        cursor.execute("SELECT user_id, total_seconds FROM voice_time")
        db_data = {row[0]: row[1] for row in cursor.fetchall()}
        
        current_time = time.time()
        for u_id, join_time in voice_tracking.items():
            elapsed = int(current_time - join_time)
            db_data[u_id] = db_data.get(u_id, 0) + elapsed
            
        sorted_data = sorted(db_data.items(), key=lambda x: x[1], reverse=True)[:10]
        
        if not sorted_data:
            await interaction.response.send_message("❌ 기록된 데이터가 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 음성 채널 이용 시간 순위 (TOP 10)",
            description="이 서버에서 가장 오래 대화한 유저분들입니다!",
            color=0xffd700
        )
        
        ranking_text = ""
        for i, (u_id, total_seconds) in enumerate(sorted_data, 1):
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
            ranking_text += f"{medal} **{i}위**: <@{u_id}> - {hours}시간 {minutes}분\n"
            
        embed.add_field(name="순위표", value=ranking_text, inline=False)
        embed.set_footer(text="실시간 접속 시간이 포함된 순위입니다.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# =========================
# 관리자 시간 설정 시스템
# =========================
class SetTimeModal(discord.ui.Modal, title="유저 음성 시간 설정"):
    user_id = discord.ui.TextInput(label="유저 ID", placeholder="시간을 설정할 유저의 ID를 입력하세요.", required=True)
    minutes = discord.ui.TextInput(label="설정할 시간 (분)", placeholder="숫자만 입력하세요 (예: 600)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_id = int(self.user_id.value)
            target_minutes = int(self.minutes.value)
        except ValueError:
            await interaction.response.send_message("❌ 유저 ID와 시간은 숫자로만 입력해 주세요.", ephemeral=True)
            return

        # 해당 유저 객체 가져오기 (등급 업데이트용)
        member = interaction.guild.get_member(target_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(target_id)
            except:
                await interaction.response.send_message("❌ 서버에서 해당 유저를 찾을 수 없습니다.", ephemeral=True)
                return

        new_seconds = target_minutes * 60
        cursor.execute("INSERT OR IGNORE INTO voice_time (user_id, total_seconds) VALUES (?, 0)", (target_id,))
        cursor.execute("UPDATE voice_time SET total_seconds = ? WHERE user_id = ?", (new_seconds, target_id))
        conn.commit()
        
        # 등급 업데이트
        await update_member_role(member, new_seconds)
        
        await interaction.response.send_message(f"✅ {member.mention}님의 음성 시간이 **{target_minutes}분**으로 설정되었습니다.", ephemeral=True)

class AdminTimeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="[관리자] 유저 시간 설정", style=discord.ButtonStyle.danger, emoji="⚙️", custom_id="admin_set_time_btn")
    async def set_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetTimeModal())

    @discord.ui.button(label="시간 부여 (+10시간)", style=discord.ButtonStyle.success, custom_id="test_add_10h_btn")
    async def add_10h_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._add_time(interaction, 10)

    @discord.ui.button(label="시간 부여 (+100시간)", style=discord.ButtonStyle.success, custom_id="test_add_100h_btn")
    async def add_100h_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._add_time(interaction, 100)

    async def _add_time(self, interaction, hours):
        add_seconds = hours * 3600
        cursor.execute("INSERT OR IGNORE INTO voice_time (user_id, total_seconds) VALUES (?, 0)", (interaction.user.id,))
        cursor.execute("UPDATE voice_time SET total_seconds = total_seconds + ? WHERE user_id = ?", (add_seconds, interaction.user.id))
        conn.commit()
        
        cursor.execute("SELECT total_seconds FROM voice_time WHERE user_id = ?", (interaction.user.id,))
        new_total = cursor.fetchone()[0]
        
        await update_member_role(interaction.user, new_total)
        await interaction.response.send_message(f"✅ 테스트를 위해 **{hours}시간**이 부여되었습니다. (현재: {new_total//3600}시간)", ephemeral=True)

    @discord.ui.button(label="시간 초기화", style=discord.ButtonStyle.danger, custom_id="test_reset_time_btn")
    async def reset_time_test(self, interaction: discord.Interaction, button: discord.ui.Button):
        cursor.execute("UPDATE voice_time SET total_seconds = 0 WHERE user_id = ?", (interaction.user.id,))
        conn.commit()
        
        # 추적 중인 실시간 시간도 초기화 (현재 채널에 있다면 지금부터 다시 시작)
        if interaction.user.id in voice_tracking:
            voice_tracking[interaction.user.id] = time.time()
            
        await update_member_role(interaction.user, 0)
        await interaction.response.send_message("✅ 누적 음성 이용 시간이 초기화되었습니다.", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def 음성통계설정(ctx):
    target_channel_id = 1488708916660404246
    channel = bot.get_channel(target_channel_id)
    
    if not channel:
        await ctx.send(f"❌ 채널(ID: {target_channel_id})을 찾을 수 없습니다.")
        return

    embed = discord.Embed(
        title="🎙️ 음성 채널 이용 통계",
        description="아래 버튼을 누르면 이 서버에서의 **총 음성 채널 이용 시간**을 확인할 수 있습니다.",
        color=0x2b2d31
    )
    embed.set_footer(text="자신에게만 보이는 메시지로 안내됩니다.")
    
    await channel.send(embed=embed, view=VoiceStatView())
    
    # 명령어 및 확인 메시지 삭제
    await ctx.message.delete()
    confirm_msg = await ctx.send(f"✅ <#{target_channel_id}> 채널에 음성 통계 버튼을 생성했습니다.")
    await asyncio.sleep(3)
    try:
        await confirm_msg.delete()
    except:
        pass

@bot.command()
async def 음성순위(ctx):
    # DB에서 모든 데이터 가져오기
    cursor.execute("SELECT user_id, total_seconds FROM voice_time")
    db_data = {row[0]: row[1] for row in cursor.fetchall()}
    
    # 실시간 접속 중인 유저들의 시간 합산
    current_time = time.time()
    for u_id, join_time in voice_tracking.items():
        elapsed = int(current_time - join_time)
        db_data[u_id] = db_data.get(u_id, 0) + elapsed
        
    # 시간 순으로 정렬 (내림차순)
    sorted_data = sorted(db_data.items(), key=lambda x: x[1], reverse=True)[:10]
    
    if not sorted_data:
        await ctx.send("❌ 기록된 데이터가 없습니다.")
        return

    embed = discord.Embed(
        title="🏆 음성 채널 이용 시간 순위 (TOP 10)",
        description="이 서버에서 가장 오래 대화한 유저분들입니다!",
        color=0xffd700 # 금색
    )
    
    ranking_text = ""
    for i, (u_id, total_seconds) in enumerate(sorted_data, 1):
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "👤"
        ranking_text += f"{medal} **{i}위**: <@{u_id}> - {hours}시간 {minutes}분\n"
        
    embed.add_field(name="순위표", value=ranking_text, inline=False)
    embed.set_footer(text="실시간 접속 시간이 포함된 순위입니다.")
    
    await ctx.send(embed=embed)

@bot.command()
async def 시간설정(ctx, member: discord.Member, minutes: int):
    # 권한 체크: 관리자 또는 특정 역할(1488734131717148793) 보유자
    allowed_role_id = 1488734131717148793
    has_role = any(role.id == allowed_role_id for role in ctx.author.roles)
    
    if not (ctx.author.guild_permissions.administrator or has_role):
        await ctx.send("❌ 이 명령어를 사용할 권한이 없습니다.", delete_after=3)
        await ctx.message.delete()
        return

    new_seconds = minutes * 60
    cursor.execute("INSERT OR IGNORE INTO voice_time (user_id, total_seconds) VALUES (?, 0)", (member.id,))
    cursor.execute("UPDATE voice_time SET total_seconds = ? WHERE user_id = ?", (new_seconds, member.id))
    conn.commit()
    
    # 설정된 시간에 맞춰 등급 역할 업데이트
    await update_member_role(member, new_seconds)
    
    await ctx.send(f"✅ {member.mention}님의 누적 음성 시간을 **{minutes}분**으로 설정했습니다.")

# =========================
# 불편 신고 시스템
# =========================
class ReportModal(discord.ui.Modal, title="불편 신고 접수"):
    content = discord.ui.TextInput(
        label="신고 및 불편 사항",
        style=discord.TextStyle.paragraph,
        placeholder="어떤 점이 불편하셨나요? 상세히 적어주시면 빠른 처리에 도움이 됩니다.",
        required=True,
        min_length=10,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        report_channel_id = 1489253932000743485
        channel = bot.get_channel(report_channel_id)
        
        if not channel:
            await interaction.response.send_message("❌ 신고 접수 채널을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚨 새로운 불편 신고 접수",
            color=0xff4654, # 레드 계열
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 신고자", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
        embed.add_field(name="📝 내용", value=self.content.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="신고 시스템 • 신속하게 확인해 주세요.")

        await channel.send(embed=embed)
        await interaction.response.send_message("✅ 신고가 정상적으로 접수되었습니다. 관리자가 확인 후 처리해 드리겠습니다.", ephemeral=True)

class ReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="불편 신고하기", style=discord.ButtonStyle.danger, emoji="📢", custom_id="report_complaint_btn")
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReportModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def 불편신고설정(ctx):
    target_channel_id = 1488781964084514926
    channel = bot.get_channel(target_channel_id)
    
    if not channel:
        await ctx.send(f"❌ 채널(ID: {target_channel_id})을 찾을 수 없습니다.")
        return

    embed = discord.Embed(
        title="📢 불편 신고 및 건의",
        description=(
            "서버 이용 중 불편한 점이나 건의하고 싶은 사항이 있으신가요?\n"
            "아래 버튼을 눌러 신고를 접수해 주세요.\n\n"
            "접수된 내용은 관리자에게 직접 전달되며, 신속하게 확인하겠습니다."
        ),
        color=0x2b2d31
    )
    embed.set_footer(text="신고 내용은 관리자에게만 공개됩니다.")
    
    await channel.send(embed=embed, view=ReportView())
    await ctx.message.delete()
    
    msg = await ctx.send(f"✅ <#{target_channel_id}> 채널에 불편 신고 버튼을 생성했습니다.")
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except:
        pass

# =========================
# 외출 신청 시스템
# =========================
class OutingModal(discord.ui.Modal, title="외출 신청서 작성"):
    period = discord.ui.TextInput(
        label="외출 기간",
        placeholder="예: 5월 10일 ~ 5월 12일 (3일간)",
        required=True,
        max_length=100
    )
    reason = discord.ui.TextInput(
        label="외출 사유",
        style=discord.TextStyle.paragraph,
        placeholder="외출 사유를 상세히 입력해 주세요.",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        target_channel_id = 1490125825574572175
        channel = bot.get_channel(target_channel_id)
        
        if not channel:
            await interaction.response.send_message("❌ 외출 신청 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚪 외출 신청서 접수",
            description=f"**{interaction.user.mention}** 님이 외출을 신청하셨습니다.",
            color=0x3498db, # 푸른색 계열
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="📅 외출 기간", value=f"```\n{self.period.value}\n```", inline=False)
        embed.add_field(name="📝 외출 사유", value=f"```\n{self.reason.value}\n```", inline=False)
        embed.set_footer(text=f"신청자 ID: {interaction.user.id}")

        await channel.send(embed=embed)
        await interaction.response.send_message("✅ 외출 신청이 정상적으로 완료되었습니다.", ephemeral=True)

class OutingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="외출 신청하기", style=discord.ButtonStyle.primary, emoji="🚶", custom_id="outing_request_btn")
    async def outing(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OutingModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def 외출신청설정(ctx):
    target_channel_id = 1490125067323965440
    channel = bot.get_channel(target_channel_id)
    
    if not channel:
        await ctx.send(f"❌ 채널(ID: {target_channel_id})을 찾을 수 없습니다.")
        return

    embed = discord.Embed(
        title="🏠 외출 신청 안내",
        description=(
            "외출이 필요하신 분은 아래 버튼을 눌러 신청서를 작성해 주세요.\n\n"
            "**작성 항목:**\n"
            "1. 외출 기간 (정확한 날짜 및 시간)\n"
            "2. 외출 사유\n\n"
            "제출된 신청서는 관리자가 확인 후 승인해 드립니다."
        ),
        color=0x2b2d31
    )
    
    await channel.send(embed=embed, view=OutingView())
    await ctx.message.delete()
    
    msg = await ctx.send(f"✅ <#{target_channel_id}> 채널에 외출 신청 버튼을 생성했습니다.")
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except:
        pass

# =========================
# 이모지 역할 부여 시스템
# =========================
CHECK_ROLE_ID = 1488695398682988574
CHECK_EMOJI = "✅"
TARGET_CHANNEL_ID = 1488706365026340864

@bot.event
async def on_raw_reaction_add(payload):
    if payload.channel_id != TARGET_CHANNEL_ID:
        return

    if str(payload.emoji) == CHECK_EMOJI:
        guild = bot.get_guild(payload.guild_id)
        if not guild: return
        
        role = guild.get_role(CHECK_ROLE_ID)
        if not role: return
        
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            pass

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.channel_id != TARGET_CHANNEL_ID:
        return

    if str(payload.emoji) == CHECK_EMOJI:
        guild = bot.get_guild(payload.guild_id)
        if not guild: return
        
        role = guild.get_role(CHECK_ROLE_ID)
        if not role: return
        
        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except:
                return
                
        try:
            await member.remove_roles(role)
        except discord.Forbidden:
            pass

keep_alive()
bot.run(os.getenv("TOKEN"))