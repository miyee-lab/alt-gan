# bot.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import json
from datetime import datetime
import time
import traceback

# --- Load Config ---
CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("[ERROR] config.json not found!")
        exit()
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("[ERROR] Could not parse config.json")
        exit()

config = load_config()
BOT_TOKEN = config.get("bot_token")
LOG_CHANNEL_ID = config.get("logChannelId")
GETACC_COOLDOWN = config.get("getAccCooldown", 300)
BOT_PREFIX = config.get("bot_prefix", ".")

# --- Bot Setup ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# --- Logging Helper ---
async def send_log(message, log_type="info"):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} {message}")
    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            color = discord.Color.blue()
            if log_type == "error":
                color = discord.Color.red()
            elif log_type == "success":
                color = discord.Color.green()
            elif log_type == "warning":
                color = discord.Color.orange()
            embed = discord.Embed(description=message, color=color, timestamp=datetime.now())
            embed.set_footer(text="Bot Logs")
            await channel.send(embed=embed)

# --- Analytics ---
ANALYTICS_FILE = "analytics.json"

def load_analytics():
    if not os.path.exists(ANALYTICS_FILE):
        return {}
    try:
        with open(ANALYTICS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_analytics(data):
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=4)

analytics_data = load_analytics()

# --- Import Helpers ---
from helpers.roblox_version import RobloxVersion
from helpers.account_manager import AccountManager

# --- Initialize Helpers ---
roblox_version = RobloxVersion(send_log_func=send_log)
account_manager = AccountManager(getacc_cooldown=GETACC_COOLDOWN, send_log_func=send_log)

# --- Status Updater ---
status_messages = [
    lambda: account_manager.status_text(),
    lambda: "/getacc for free accounts",
    lambda: "/stock to check balance",
    lambda: roblox_version.status_text()
]

@tasks.loop(seconds=30)
async def update_status():
    current_status = status_messages[update_status.current_loop % len(status_messages)]()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=current_status))

# --- Events ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.tree.sync()
    update_status.start()
    await send_log("🤖 Bot is online and ready!", "success")

# --- Automatic Command Logging + Analytics ---
@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    try:
        user = str(interaction.user)
        cmd_name = command.qualified_name

        # --- Update Analytics ---
        if user not in analytics_data:
            analytics_data[user] = {}
        if cmd_name not in analytics_data[user]:
            analytics_data[user][cmd_name] = {"count": 0, "last_used": None}

        analytics_data[user][cmd_name]["count"] += 1
        analytics_data[user][cmd_name]["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_analytics(analytics_data)

        # --- Log the command usage ---
        params = ", ".join(f"{k}={v}" for k, v in interaction.namespace.__dict__.items() if not k.startswith('_'))
        if params:
            log_msg = f"📌 User `{user}` used `/{cmd_name}` with params: {params}"
        else:
            log_msg = f"📌 User `{user}` used `/{cmd_name}`"
        await send_log(log_msg, "success")

    except Exception as e:
        print(f"[WARN] Could not log command usage: {e}")

# --- Global Error Logging ---
@bot.tree.error
async def global_command_error(interaction: discord.Interaction, error):
    user = interaction.user
    cmd_name = interaction.command.qualified_name if interaction.command else "Unknown"
    err_text = "".join(traceback.format_exception_only(type(error), error)).strip()
    msg = f"❌ Command `{cmd_name}` by `{user}` failed → {err_text}"
    await send_log(msg, "error")
    try:
        await interaction.response.send_message(f"⚠️ {err_text}", ephemeral=True)
    except:
        pass

# --- Commands ---
# Add Account
@bot.tree.command(name="addacc", description="Add account (Admins only)")
async def add_account_cmd(interaction: discord.Interaction, account_string: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
        raise app_commands.MissingPermissions(["administrator"])
    success, msg = account_manager.add_account(account_string)
    await interaction.response.send_message(f"{'✅' if success else '⚠️'} {msg}", ephemeral=True)

# Get Account
@bot.tree.command(name="getacc", description="Get an account via DM")
async def get_account_cmd(interaction: discord.Interaction):
    acc, msg = account_manager.get_account(interaction.user.id)
    if acc:
        try:
            await interaction.user.send(f"🔑 {acc}")
            await interaction.response.send_message("✅ Sent via DM!", ephemeral=True)
        except Exception as e:
            accounts = account_manager.load_accounts()
            accounts.insert(0, acc)
            account_manager.save_accounts(accounts)
            await interaction.response.send_message("⚠️ Enable DMs!", ephemeral=True)
            account_manager._log(f"⚠️ Failed to DM {interaction.user}. Account restored.", "error")
            raise e
    else:
        await interaction.response.send_message(f"⚠️ {msg}", ephemeral=True)

# Stock
@bot.tree.command(name="stock", description="Check account stock")
async def stock_cmd(interaction: discord.Interaction):
    count = account_manager.stock()
    msg = f"✅ {count} accounts left" if count > 0 else "⚠️ None left"
    await interaction.response.send_message(msg, ephemeral=True)

# Ping
@bot.tree.command(name="ping", description="Bot latency")
async def ping_cmd(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 {latency}ms", ephemeral=True)

# Roblox Version
@bot.tree.command(name="version", description="Current Roblox version")
async def version_cmd(interaction: discord.Interaction):
    data = roblox_version.fetch()
    ver = data.get("version")
    date = data.get("date")
    if ver:
        embed = discord.Embed(title="Roblox Version", color=0x43B581)
        embed.add_field(name="Platform", value="Windows", inline=True)
        embed.add_field(name="Version", value=ver, inline=True)
        embed.add_field(name="Date", value=date if date else "Unknown", inline=True)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("⚠️ Could not fetch Roblox version.")

# Refresh Roblox Version (Admin only)
refresh_cooldowns = {}
REFRESH_COOLDOWN = 60

@bot.tree.command(name="refreshversion", description="Force refresh Roblox version cache (Admins only)")
async def refresh_version(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
        raise app_commands.MissingPermissions(["administrator"])
    uid = interaction.user.id
    now = time.time()
    last = refresh_cooldowns.get(uid, 0)
    if now - last < REFRESH_COOLDOWN:
        wait = round(REFRESH_COOLDOWN - (now - last), 1)
        await interaction.response.send_message(f"⏳ Cooldown: {wait}s left", ephemeral=True)
        return
    refresh_cooldowns[uid] = now
    data = roblox_version.force_refresh()
    ver = data.get("version")
    date = data.get("date")
    if ver:
        embed = discord.Embed(title="Roblox Version (Refreshed)", color=0x43B581)
        embed.add_field(name="Platform", value="Windows", inline=True)
        embed.add_field(name="Version", value=ver, inline=True)
        embed.add_field(name="Date", value=date if date else "Unknown", inline=True)
        await interaction.response.send_message(embed=embed)
        try:
            current_index = update_status.current_loop % len(status_messages)
            if status_messages[current_index] == status_messages[3]:
                new_status = roblox_version.status_text()
                await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=new_status))
        except Exception as e:
            print(f"[WARN] Failed to update presence immediately: {e}")
    else:
        await interaction.response.send_message("⚠️ Could not fetch Roblox version.")

# Analytics Command (Admin only)
@bot.tree.command(name="analytics", description="View command usage analytics (Admins only)")
async def analytics_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
        return

    if not analytics_data:
        await interaction.response.send_message("⚠️ No analytics data yet.", ephemeral=True)
        return

    msg_lines = []
    for user, commands_used in analytics_data.items():
        msg_lines.append(f"**{user}**")
        for cmd, info in commands_used.items():
            msg_lines.append(f"  - {cmd}: {info['count']} times (last: {info['last_used']})")
    msg_text = "\n".join(msg_lines)

    if len(msg_text) > 1900:
        with open("analytics.txt", "w", encoding="utf-8") as f:
            f.write(msg_text)
        await interaction.response.send_message("📊 Analytics too long, sending file:", file=discord.File("analytics.txt"), ephemeral=True)
    else:
        await interaction.response.send_message(f"📊 **Command Usage Analytics:**\n{msg_text}", ephemeral=True)

# Leaderboard Command (Admin only)
@bot.tree.command(name="leaderboard", description="View top users of a specific command (Admins only)")
async def leaderboard_cmd(interaction: discord.Interaction, command_name: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
        return

    leaderboard = []
    for user, commands_used in analytics_data.items():
        if command_name in commands_used:
            leaderboard.append((user, commands_used[command_name]["count"], commands_used[command_name]["last_used"]))

    if not leaderboard:
        await interaction.response.send_message(f"⚠️ No usage data found for `/{command_name}`.", ephemeral=True)
        return

    leaderboard.sort(key=lambda x: x[1], reverse=True)

    msg_lines = [f"🏆 **Leaderboard for /{command_name}**"]
    for i, (user, count, last_used) in enumerate(leaderboard[:10], start=1):
        msg_lines.append(f"{i}. {user} — {count} times (last: {last_used})")

    msg_text = "\n".join(msg_lines)
    await interaction.response.send_message(msg_text, ephemeral=True)

# --- Run Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("[ERROR] Missing bot token!")
    else:
        bot.run(BOT_TOKEN)
