import discord
from discord.ext import commands
import sqlite3
import os
from flask import Flask
from threading import Thread
import random

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
    category TEXT,
    tier TEXT DEFAULT '-',
    position TEXT DEFAULT '-'
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
}

# 알림 매핑 (줄임말 입력 시 여러 역할 멘션)
MENTION_MAPPING = {
    "옵치": ["오버워치", "옵치"],
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
        
        if "롤" in game_name or "리그" in game_name:
            await interaction.response.send_message("🛡️ 자신의 **포지션**과 **티어**를 선택해주세요.", view=InfoSelectView(room_id), ephemeral=True)
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

    elif choice == "대기":
        add_user(room_id, interaction.user.id, "대기")

    elif choice == "관전":
        add_user(room_id, interaction.user.id, "관전")

    elif choice == "나가기":
        remove_user(room_id, interaction.user.id)

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
        
        # 기존 팀 정보 초기화 및 재배정 (티어/포지션 유지)
        for u in blue_team:
            cursor.execute("UPDATE participants SET category=? WHERE room_id=? AND user_id=?", ("블루팀", room_id, u))
        for u in red_team:
            cursor.execute("UPDATE participants SET category=? WHERE room_id=? AND user_id=?", ("레드팀", room_id, u))
        conn.commit()
        
        await interaction.response.edit_message(embed=make_embed(room_id, interaction.guild), view=RoomView(room_id))
        try:
            await interaction.followup.send("🎲 팀이 무작위로 배정되었습니다!", ephemeral=True)
        except:
            pass
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
    def __init__(self, room_id):
        super().__init__(timeout=60)
        self.room_id = room_id
        self.tier = "-"
        self.position = "-"

    @discord.ui.select(
        placeholder="포지션을 선택하세요",
        options=[
            discord.SelectOption(label="탑", emoji="🛡️"),
            discord.SelectOption(label="정글", emoji="⚔️"),
            discord.SelectOption(label="미드", emoji="🔮"),
            discord.SelectOption(label="원딜", emoji="🏹"),
            discord.SelectOption(label="서폿", emoji="🌿"),
        ]
    )
    async def select_position(self, interaction, select):
        self.position = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="티어를 선택하세요",
        options=[
            discord.SelectOption(label="아이언", emoji="🌑"),
            discord.SelectOption(label="브론즈", emoji="🟤"),
            discord.SelectOption(label="실버", emoji="⚪"),
            discord.SelectOption(label="골드", emoji="🟡"),
            discord.SelectOption(label="플래티넘", emoji="🟢"),
            discord.SelectOption(label="에메랄드", emoji="✳️"),
            discord.SelectOption(label="다이아", emoji="💎"),
            discord.SelectOption(label="마스터+", emoji="🔮"),
        ]
    )
    async def select_tier(self, interaction, select):
        self.tier = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="선택 완료", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        if self.position == "-" or self.tier == "-":
            await interaction.response.send_message("❌ 포지션과 티어를 모두 선택해주세요.", ephemeral=True)
            return

        cursor.execute("SELECT max_people FROM rooms WHERE room_id=?", (self.room_id,))
        max_people = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM participants WHERE room_id=? AND category='참가'", (self.room_id,))
        count = cursor.fetchone()[0]

        if count >= max_people:
            category = "대기"
        else:
            category = "참가"

        remove_user(self.room_id, interaction.user.id)
        cursor.execute("INSERT INTO participants VALUES (?, ?, ?, ?, ?)", (self.room_id, interaction.user.id, category, self.tier, self.position))
        conn.commit()

        # 메시지 업데이트를 위해 원본 메시지 찾기
        cursor.execute("SELECT channel_id, message_id FROM rooms WHERE room_id=?", (self.room_id,))
        ch_id, msg_id = cursor.fetchone()
        channel = bot.get_channel(ch_id)
        if channel:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=make_embed(self.room_id, interaction.guild), view=RoomView(self.room_id))
            except:
                pass

        try:
            await interaction.response.send_message(f"✅ {self.position} / {self.tier} (으)로 참가가 완료되었습니다!", ephemeral=True)
        except:
            await interaction.followup.send(f"✅ {self.position} / {self.tier} (으)로 참가가 완료되었습니다!", ephemeral=True)
        self.stop()

class CreateModal(discord.ui.Modal, title="모집 생성"):
    game = discord.ui.TextInput(label="게임")
    people = discord.ui.TextInput(label="인원 (숫자)")
    time_ = discord.ui.TextInput(label="시간")

    async def on_submit(self, interaction):
        room_id = str(interaction.id)
        guild = interaction.guild

        # 음성 채널 이름 결정
        game_val = self.game.value
        if game_val in ["롤", "리그오브레전드"]:
            channel_name = "┋⚔️┋리그오브레전드"
        elif game_val in ["옵치", "오버워치"]:
            channel_name = "┋⌚┋오버워치"
        else:
            channel_name = f" {game_val}"

        category = guild.get_channel(1488774793497940080)
        try:
            voice_channel = await guild.create_voice_channel(channel_name, category=category)
        except:
            voice_channel = await guild.create_voice_channel(channel_name)

        cursor.execute(
            "INSERT INTO rooms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (room_id, self.game.value, int(self.people.value), self.time_.value, interaction.user.id, voice_channel.id, 0, 0)
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
    cursor.execute("SELECT message_id FROM panels")
    for (msg_id,) in cursor.fetchall():
        bot.add_view(PanelView())

    cursor.execute("SELECT room_id FROM rooms")
    for (room_id,) in cursor.fetchall():
        bot.add_view(RoomView(room_id))

    print("수정 완료")

# =========================
# 음성채널 자동 삭제
# =========================
@bot.event
async def on_voice_state_update(member, before, after):
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

keep_alive()
bot.run(os.getenv("TOKEN"))