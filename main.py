import discord
from discord.ext import commands
import os
from dotenv import load_dotenv as loadDotenv
import asyncio
import sys
import threading
import logging
from pathlib import Path
from colorama import Fore, init
import updater

# Print each line straight away. Without a terminal (hosting panels) Python
# buffers stdout, so status lines would only show up much later or never.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Initialize colorama for Windows CMD
init(autoreset=True)

# Full log goes to bot.log; warnings and crashes also go to the console so a
# hosting panel (Cybrancee) shows why the bot stopped.
logFileHandler = logging.FileHandler("bot.log", encoding="utf-8")
logConsoleHandler = logging.StreamHandler()
logConsoleHandler.setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logFileHandler, logConsoleHandler],
    force=True,
)

# New commits on GitHub are downloaded before the bot starts (see updater.py).
updater.check_at_start()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# --- BOT SETUP ---
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    chunk_guilds_at_startup=False,
)

botVersion = "Version 2.3.2"

# --- SETTINGS ---
passwordNeeded = True   # True = require passkey, False = skip passkey system
resetIsOption = True    # True = enable restart prompt, False = disable it
restartPromptTask = None
commandsSynced = False

# --- ENV VARIABLES ---
loadDotenv()
token = os.getenv("discordToken") or os.getenv("DISCORD_TOKEN")
passkey = os.getenv("passkey") or os.getenv("PASSKEY")

passkeyFile = Path(".passkey_ok")

# --- PASSKEY SYSTEM ---
if passwordNeeded:
    if not passkeyFile.exists():
        if not passkey:
            print("[ERROR] passkey is missing from the environment or .env file.")
            print("[SYSTEM ASSISTANT] Add a line like passkey=yourkey to .env, then start the bot again.")
            sys.exit(1)
        # The prompt goes on its own line: hosting consoles (Cybrancee) only
        # show finished lines, so an inline input() prompt stays invisible.
        print("Enter bot passkey (type it in the console and press Enter):", flush=True)
        enteredKey = input().strip()
        if enteredKey != passkey:
            print("\n[ERROR] Passkey was invalid.\n")
            print("[SYSTEM ASSISTANT] Please contact the bot owner to get the correct passkey.")
            print("[SYSTEM ASSISTANT] Exiting...")
            sys.exit(1)

        print("\n[SYSTEM ASSISTANT] Passkey validated successfully.")
        passkeyFile.write_text("validated")
        print("[SYSTEM ASSISTANT] Bot load process will now continue.\n")
    else:
        print("")
        print(f"[SYSTEM ASSISTANT] Code running in Developer Mode. Python {sys.version.split()[0]}.")
        print("")
        print("[SYSTEM ASSISTANT] Passkey already validated for this session. Skipping prompt.")
        print("")
else:
    print("[SYSTEM ASSISTANT] Passkey system disabled — skipping check.")

# --- INTENTS ---


@bot.event
async def on_connect():
    print("[DISCORD] Gateway connected; waiting for READY event.", flush=True)


@bot.event
async def on_ready():
    global commandsSynced, restartPromptTask
    print(f"[DISCORD] Logged in as {bot.user} (ID: {bot.user.id})", flush=True)
    if not commandsSynced:
        print("[DISCORD] Syncing commands...", flush=True)
        try:
            await asyncio.wait_for(bot.tree.sync(), timeout=30)
        except asyncio.TimeoutError as error:
            raise TimeoutError(
                "Discord slash-command synchronization timed out after 30 seconds."
            ) from error
        commandsSynced = True
        print("[DISCORD] Finished syncing commands.", flush=True)

    activity = discord.Activity(type=discord.ActivityType.watching, name="Overseeing coldd.")
    await bot.change_presence(status=discord.Status.dnd, activity=activity)
    print("[DISCORD] Presence updated.\n")
    print(Fore.CYAN + f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬| Bot is now online as {bot.user}. |▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n")
    print(f"")
    print(r"    A")
    print("")
    print(Fore.CYAN + r"""
        ___      ___ ___    ___ ________  _______   ___  ________         ___  _______   ________ _________  _______   ________         
       |\  \    /  /|\  \  /  /|\   __  \|\  ___ \ |\  \|\   ___  \      |\  \|\  ___ \ |\   ____\\___   ___\\  ___ \ |\   ___ \      
       \ \  \  /  / | \  \/  / | \  \|\  \ \   __/|\ \  \ \  \\ \  \     \ \  \ \   __/|\ \  \___\|___ \  \_\ \   __/|\ \  \_|\ \     
        \ \  \/  / / \ \    / / \ \   ____\ \  \_|/_\ \  \ \  \\ \  \  __ \ \  \ \  \_|/_\ \  \       \ \  \ \ \  \_|/_\ \  \ \\ \    
         \ \    / /   /     \/   \ \  \___|\ \  \_|\ \ \  \ \  \\ \  \|\  \\_\  \ \  \_|\ \ \  \____   \ \  \ \ \  \_|\ \ \  \_\\ \   
          \ \__/ /   /  /\   \    \ \__\    \ \_______\ \__\ \__\\ \__\ \________\ \_______\ \_______\  \ \__\ \ \_______\ \_______\  
           \|__|/   /__/ /\ __\    \|__|     \|_______|\|__|\|__| \|__|\|________|\|_______|\|_______|   \|__|  \|_______|\|_______|  
                    |__|/ \|__|                                                                                                       
                                                                                                                                      
    """)

    print(r"""
    Production. 
          
    © 2025 coldd Operations and VxpeInjected.
    coldd Discord Bot Assistant - Developed by @vxpe_injected.    
    All Rights Reserved.
                                                                                                
    """)

    # Run restart check if enabled
    if resetIsOption and (
        restartPromptTask is None or restartPromptTask.done()
    ):
        restartPromptTask = asyncio.create_task(restart_prompt())

# --- RESTART PROMPT ---
RESTART_PROMPT = """
    If at any point you wish to restart the bot, type 'yes'.
    If you type no, this prompt will reappear and the bot will continue to function normally.
        :"""


def read_console_line(loop, future):
    try:
        line = input(RESTART_PROMPT)
    except EOFError:
        line = None
    try:
        loop.call_soon_threadsafe(lambda: future.done() or future.set_result(line))
    except RuntimeError:
        pass


async def restart_prompt():
    loop = asyncio.get_running_loop()
    while True:
        # A daemon thread waits for the console line: a thread from asyncio's own pool
        # kept the process alive for minutes when the panel stopped or restarted it.
        future = loop.create_future()
        threading.Thread(target=read_console_line, args=(loop, future), daemon=True).start()
        restartBot = await future
        if restartBot is None:
            return

        print("")
        if restartBot.strip().lower() == "yes":
            print("")
            print("[SYSTEM ASSISTANT] Stopping bot...")
            await bot.close()
            await asyncio.sleep(0.1)  # Let Discord connection close
            print("[SYSTEM ASSISTANT] Success — bot stopped.")
            os._exit(0)  # Hard exit — no asyncio errors
            os.system("cls")
        else:
            print("[SYSTEM ASSISTANT] Bot will not restart.")
            await asyncio.sleep(1)

# --- LOAD COGS ---
async def load_cogs():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and filename != "__init__.py" and filename != "careers.py":
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"[SYSTEM ASSISTANT] Loaded cog: {filename}")

# --- MAIN BOT RUN ---
async def main():
    if not token:
        raise RuntimeError("discordToken is missing from the environment or .env file.")
    async with bot:
        await load_cogs()
        print("")
        print("[SYSTEM ASSISTANT] All cogs loaded.")
        print("[SYSTEM ASSISTANT] Starting bot...")
        print("")
        print("[DISCORD] Connecting to Discord...", flush=True)
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger(__name__).exception("Bot stopped unexpectedly")
        sys.exit(1)
    # Stop at once when the panel stops the bot, whatever threads are still waiting.
    logging.shutdown()
    sys.stdout.flush()
    os._exit(0)