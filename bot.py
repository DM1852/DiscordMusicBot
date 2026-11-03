import logging
from logging.handlers import RotatingFileHandler
import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
import discord_bot_yt_search
import tempfile
import pyttsx3
from glob import glob
import subprocess

log = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SONG_QUEUES = {}
GUILD_ID = 730099461816189009
POWERSHELL_PATH = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" #path to powershell exe
SCRIPT_PATH = r"C:\Users\AMDUser1\Desktop\PZ_Server_Scripts\pz.ps1" #path to project zomboid remote server control script

# ---------------- Discord Setup ----------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def setup_logging():
    # Console output: reuse discord.py's nice coloured formatter, but apply it to the
    # ROOT logger so our own modules' messages appear too, not just discord.py's
    discord.utils.setup_logging(level=logging.INFO, root=True)

    # File output: bot.log, rotated so it can never grow forever
    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}",
        "%Y-%m-%d %H:%M:%S",
        style="{",
    ))
    logging.getLogger().addHandler(file_handler)

def get_queue(guild_id):
    if guild_id not in SONG_QUEUES:
        SONG_QUEUES[guild_id] = []
    return SONG_QUEUES[guild_id]

# ---------------- Play next Command ----------------
async def play_next(guild):
    queue = get_queue(guild.id)

    if not queue:
        #if queue empty disconnect if still connected
        vc = guild.voice_client
        if vc:
            await vc.disconnect()
        return

    next_song = queue.pop(0)  # get first song

    ffmpeg_path = r"C:\CODE_FOLDER\Python\Virtual_Environments\Python_DiscordBot\discordENV2\bin\ffmpeg\ffmpeg.exe"
    audio_source = discord.FFmpegPCMAudio(next_song, executable=ffmpeg_path)

    vc = guild.voice_client
    if vc is None:
        log.warning("play_next: no voice client in guild %s, dropping %r", guild.id, next_song)
        return  #shouldn't happen

    def after_playing(err):
        if err:
            log.error("Playback error in guild %s: %s", guild.id, err)
        coro = play_next(guild)
        asyncio.run_coroutine_threadsafe(coro, bot.loop)

    vc.play(audio_source, after=after_playing)

# ---------------- Play Command ----------------
@bot.tree.command(name="play", description="Play a song from YouTube.")
@app_commands.describe(song_query="Song name or query")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()

    user_vc = getattr(interaction.user.voice, "channel", None)
    if not user_vc:
        await interaction.followup.send("❌ You must be in a voice channel.")
        return

    # Voice connect/move logic
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        voice_client = await user_vc.connect()
    elif voice_client.channel != user_vc:
        await voice_client.move_to(user_vc)

    await interaction.followup.send(f"🔎 Searching YouTube for: **{song_query}**...")

    #YT search
    url, cookies = await asyncio.to_thread(discord_bot_yt_search.yt_search, song_query)
    if not url:
        log.warning("No YouTube results for query %r", song_query)
        await interaction.followup.send("❌ No results found.")
        return

    #save cookies
    tmp_cookiefile = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
    discord_bot_yt_search.save_selenium_cookies(cookies, tmp_cookiefile)

    #download MP3
    await asyncio.to_thread(discord_bot_yt_search.download_audio_with_ytdlp, url,tmp_cookiefile)
    mp3_files = glob("*.mp3")
    if not mp3_files:
        await interaction.followup.send("❌ Download failed.")
        return

    latest_file = max(mp3_files, key=os.path.getctime)  #newest

    #add to queue
    queue = get_queue(interaction.guild.id)
    queue.append(latest_file)

    await interaction.followup.send(f"🎶 Added to queue: **{os.path.basename(latest_file)}**")

    #if bot isn't playing anything start
    if not voice_client.is_playing():
        await play_next(interaction.guild)

# ---------------- Replay Command ----------------
@bot.tree.command(name="replay", description="Play the last song again.")
async def replay(interaction: discord.Interaction):
    await interaction.response.defer()

    last_song = LAST_PLAYED.get(interaction.guild.id)
    if not last_song or not os.path.exists(last_song):
        await interaction.followup.send("❌ Nothing to replay yet.")
        return

    user_vc = getattr(interaction.user.voice, "channel", None)
    if not user_vc:
        await interaction.followup.send("❌ You must be in a voice channel.")
        return

    # Voice connect/move logic (same as /play)
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        voice_client = await user_vc.connect()
    elif voice_client.channel != user_vc:
        await voice_client.move_to(user_vc)

    # Put the song at the FRONT of the queue so it plays next
    queue = get_queue(interaction.guild.id)
    queue.insert(0, last_song)

    await interaction.followup.send(f"🔁 Replaying: **{os.path.basename(last_song)}**")

    if voice_client.is_playing():
        voice_client.stop()   # ends the current song; after_playing -> play_next picks up our song
    else:
        await play_next(interaction.guild)


# ---------------- Skip Command ----------------
@bot.tree.command(name="skip", description="Skip the current song.")
@app_commands.default_permissions()
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client

    if not vc or not vc.is_playing():
        await interaction.response.send_message("❌ Nothing is currently playing.")
        return

    vc.stop()
    await interaction.response.send_message("⏭️ Skipped!")

# ---------------- Stop Command ----------------
@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    queue = get_queue(guild_id)
    queue.clear()

    vc = interaction.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()

    await interaction.response.send_message("⛔ Stopped playback & cleared queue.")



@bot.tree.command(name="say", description="Make the bot join and say something in your voice channel.")
async def say(interaction: discord.Interaction, text: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ You need to be in a voice channel first!", ephemeral=True)
        return

    #await interaction.response.send_message(f"🎙️ Saying: **{text}**", ephemeral=True)
    vc = interaction.user.voice.channel
    voice_client = await vc.connect()

    # Generate speech with pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[0].id)  # choose male/female, etc.
    engine.setProperty('volume', 0.8)  # 0.0 to 1.0
    engine.setProperty('rate', 150)

    tts_path = "tts_output.mp3"
    engine.save_to_file(text, tts_path)
    engine.runAndWait()

    # Play the file through Discord voice
    ffmpeg_path = r"C:\CODE_FOLDER\Python\Virtual_Environments\Python_DiscordBot\discordENV2\bin\ffmpeg\ffmpeg.exe" #path to ffmpeg exe

    audio_source = discord.FFmpegPCMAudio(tts_path, executable=ffmpeg_path)
    voice_client.play(audio_source)

    # Wait until finished
    while voice_client.is_playing():
        await asyncio.sleep(1)

    await voice_client.disconnect()
    os.remove(tts_path)



@bot.tree.command(name="pz", description="Control the Project Zomboid server")
@app_commands.choices(action=[
    app_commands.Choice(name="start", value="start"),
    app_commands.Choice(name="stop", value="stop"),
    app_commands.Choice(name="restart", value="restart"),
    app_commands.Choice(name="status", value="status"),
])
async def pz(interaction: discord.Interaction, action: app_commands.Choice[str]):
    #acknowledge immediately
    await interaction.response.defer(thinking=True)

    #move the blocking call into a background function
    def run_powershell():
        return subprocess.run(
            [
                POWERSHELL_PATH,
                "-ExecutionPolicy", "Bypass",
                "-File", SCRIPT_PATH,
                action.value
            ],
            capture_output=True,
            text=True
        )

    #run it without blocking Discord
    result = await asyncio.to_thread(run_powershell)

    output = result.stdout.strip() or "No output."

    await interaction.followup.send(
        f"🧟 **Project Zomboid — {action.value}**\n```\n{output}\n```"
    )

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    log.info("Globally synced %d commands", len(synced))
    for c in synced:
        log.info(" * %s", c.name)
    log.info("%s is online", bot.user)

setup_logging()
if not TOKEN:
    log.critical("DISCORD_TOKEN not found - is the .env file in the bot folder?")
    raise SystemExit(1)
bot.run(TOKEN, log_handler=None)