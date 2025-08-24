import os, discord, logging
from discord.ext import commands, tasks
from flask import Flask
from threading import Thread
from tinydb import TinyDB, Query

# ---------- Config ----------
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

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, filename="bot_logs.txt",
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ---------- Flask pour Render ----------
app = Flask(__name__)

@app.get("/")
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ["PORT"])  # Utilise le port fourni par Render
    app.run(host="0.0.0.0", port=port)

# ---------- Discord ----------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Base de données ----------
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

# ---------- Lancement ----------
@bot.event
async def on_ready():
    if not award_points.is_running():
        award_points.start()
    logging.info(f"✅ Connecté en tant que {bot.user} ({bot.user.id})")

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

# ---------- Classement ----------
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

# ---------- Commandes ----------
# ... (garde tes commandes inchangées) ...

# ---------- Lancement ----------
if not TOKEN:
    raise RuntimeError("Le token Discord est manquant.")

# Flask en thread
Thread(target=run_flask).start()
bot.run(TOKEN)
