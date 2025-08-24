import os
import discord
import logging
from discord.ext import commands, tasks
from flask import Flask
from threading import Thread
from tinydb import TinyDB, Query

# ------------------ CONFIG ------------------ #
TOKEN = os.getenv("DISCORD_TOKEN")
ROLE_TIERS = {
    500: 710975465678045226,
    1500: 710975161314181174,
    5000: 710974719448449118,
    10000: 710974492566093867,
    25000: 710972777170993164,
    50000: 710973545773138030,
    100000: 710969412093476925
}
CLASSEMENT_CHANNEL = 711250866581274624
ANNOUNCE_CHANNEL_ID = 706503185266769993
DB_FILE = "points_db.json"

# ------------------ LOGGING ------------------ #
logging.basicConfig(level=logging.INFO, filename="bot_logs.txt",
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ------------------ FLASK KEEP-ALIVE ------------------ #
app = Flask("")

@app.route("/")
def home():
    return "Bot Okami actif !"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ------------------ INTENTS DISCORD ------------------ #
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ BASE DE DONNÉES ------------------ #
db = TinyDB(DB_FILE)
users_table = db.table("users")

def get_user(uid, name=None):
    User = Query()
    result = users_table.get(User.id == uid)
    if not result:
        result = {"id": uid, "points": 0, "name": name or "Inconnu"}
        users_table.insert(result)
    else:
        if name and result["name"] != name:
            users_table.update({"name": name}, User.id == uid)
            result["name"] = name
    return result

def add_points(uid, amount, name=None):
    data = get_user(uid, name)
    users_table.update({"points": data["points"] + amount}, Query().id == uid)
    logging.info(f"{name or uid} a reçu {amount} point(s). Total: {data['points'] + amount}")
    return data["points"] + amount

def set_points(uid, amount, name=None):
    users_table.upsert({"id": uid, "points": amount, "name": name or "Inconnu"}, Query().id == uid)
    logging.info(f"Points de {name or uid} réglés à {amount}.")

# ------------------ EVENTS ------------------ #
@bot.event
async def on_ready():
    if not award_points.is_running():
        award_points.start()
    print(f"✅ Connecté en tant que {bot.user} ({bot.user.id})")

# ------------------ TÂCHE RÉPÉTITIVE ------------------ #
@tasks.loop(minutes=1)
async def award_points():
    changed = False
    for guild in bot.guilds:
        announce_channel = guild.get_channel(ANNOUNCE_CHANNEL_ID)
        for channel in guild.voice_channels:
            members = [m for m in channel.members if not m.bot]
            if len(members) >= 2:
                for member in members:
                    uid = str(member.id)
                    new_pts = add_points(uid, 1, member.display_name)
                    changed = True
                    for pts_req, role_id in ROLE_TIERS.items():
                        role = guild.get_role(role_id)
                        if role and new_pts >= pts_req and role not in member.roles:
                            try:
                                await member.add_roles(role, reason=f"Atteint {pts_req} points")
                                logging.info(f"{member.display_name} a reçu le rôle {role.name}.")
                                if announce_channel:
                                    await announce_channel.send(
                                        f"🎉 **{member.display_name}** vient d’atteindre le rôle **{role.name}** !"
                                    )
                            except discord.Forbidden:
                                logging.warning(f"Impossible d'ajouter {role.name} à {member.display_name}.")
                            except discord.HTTPException as e:
                                logging.warning(f"Erreur Discord pour {member.display_name}: {e}")
    if changed:
        await update_classement()

# ------------------ CLASSEMENT ------------------ #
async def update_classement():
    for guild in bot.guilds:
        channel = guild.get_channel(CLASSEMENT_CHANNEL)
        if not channel:
            continue

        users = users_table.all()
        classement = sorted(users, key=lambda x: x["points"], reverse=True)[:15]

        embed = discord.Embed(
            title="🎌 Classement Clan Ōkami",
            description="Voici la pyramide des 15 meilleurs guerriers :",
            color=discord.Color.dark_red()
        )

        pyramid_lines = []
        emojis = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟","🏅","🏅","🏅","🏅","🏅"]
        spaces = ["", " ", "  ", "   ", "    "]

        for i, u in enumerate(classement):
            name = u["name"]
            pts = u["points"]
            indent = spaces[i//3]
            pyramid_lines.append(f"{indent}{emojis[i]} {name}: **{pts} pts**")

        embed.description = "\n".join(pyramid_lines)
        embed.set_footer(
            text="🐺 Paysans: 500 pts | Artisans: 1500 pts | Hatamoto: 5000 pts | Daimyō: 10000 pts | Rōnin: 25000 pts | Bushi: 50000 pts | Samouraï: 100000 pts",
            icon_url=guild.icon.url if guild.icon else None
        )

        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                await msg.edit(embed=embed)
                return
        await channel.send(embed=embed)

# ------------------ COMMANDES ------------------ #
@bot.command()
@commands.cooldown(1, 30, commands.BucketType.user)
async def points(ctx, member: discord.Member | None = None):
    member = member or ctx.author
    data = get_user(str(member.id), member.display_name)
    embed = discord.Embed(
        title=f"🔹 Points de {data['name']}",
        description=f"**{data['points']} points**",
        color=discord.Color.dark_blue()
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def givepoints(ctx, member: discord.Member, amount: int):
    if amount <= 0 or member.bot:
        return await ctx.send("⛔ Montant invalide ou membre bot.")
    from_data = get_user(str(ctx.author.id), ctx.author.display_name)
    if from_data["points"] < amount:
        return await ctx.send("⛔ Pas assez de points.")
    to_data = get_user(str(member.id), member.display_name)
    set_points(str(ctx.author.id), from_data["points"] - amount, ctx.author.display_name)
    set_points(str(member.id), to_data["points"] + amount, member.display_name)
    await ctx.send(f"🎁 {ctx.author.display_name} a donné {amount} points à {member.display_name}.")

@bot.command()
@commands.has_permissions(administrator=True)
async def setpoints(ctx, member: discord.Member, amount: int):
    set_points(str(member.id), amount, member.display_name)
    await ctx.send(f"✅ Points de {member.display_name} réglés à **{amount}**.")

@bot.command()
@commands.cooldown(1, 60, commands.BucketType.user)
async def compare(ctx, member: discord.Member):
    uid1, uid2 = str(ctx.author.id), str(member.id)
    pts1, pts2 = get_user(uid1, ctx.author.display_name)["points"], get_user(uid2, member.display_name)["points"]
    diff_msg = (
        f"{ctx.author.display_name} a **{pts1 - pts2} points de plus** que {member.display_name}"
        if pts1 > pts2 else
        f"{ctx.author.display_name} a **{pts2 - pts1} points de moins** que {member.display_name}"
        if pts1 < pts2 else
        f"{ctx.author.display_name} et {member.display_name} ont **le même nombre de points**."
    )
    await ctx.send(embed=discord.Embed(description=diff_msg, color=discord.Color.gold()))

@bot.command(name="aide")
async def aide(ctx):
    embed = discord.Embed(
        title="🌕 **Commandes du Clan Ōkami** 🐺",
        description="Maîtrise ton rang et tes points avec ces commandes :",
        color=discord.Color.dark_purple()
    )
    embed.add_field(name="⚔️ !points [@user]", value="Affiche tes points ou ceux d’un membre.", inline=False)
    embed.add_field(name="🏆 !top", value="Met à jour le classement pyramide des 15 premiers.", inline=False)
    embed.add_field(name="🛡️ !setpoints @user X", value="(Admin) Définit le nombre de points d’un membre.", inline=False)
    embed.add_field(name="🧭 !compare @user", value="Compare tes points avec un autre membre.", inline=False)
    embed.add_field(name="🎁 !givepoints @user X", value="Donne une partie de tes points à un autre membre.", inline=False)
    embed.add_field(name="📜 !aide", value="Affiche ce message.", inline=False)
    embed.set_footer(text="🐺 Honore le Clan Ōkami et grimpe dans la pyramide !",
                     icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    await update_classement()
    channel = ctx.guild.get_channel(CLASSEMENT_CHANNEL)
    if channel:
        await ctx.send(f"📜 Le classement pyramide a été mis à jour dans {channel.mention}.")

# ------------------ LANCEMENT ------------------ #
if not TOKEN:
    raise RuntimeError("Le token Discord est manquant.")

keep_alive()
bot.run(TOKEN)
