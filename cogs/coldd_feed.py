"""Sends Parcel's purchase and review messages to coldd.dev.

Every message Parcel's bot posts in the purchases and reviews channels goes to
coldd.dev exactly as Discord gives it (text, embeds, components); coldd.dev
reads them. Messages from people are never sent.

Catching up: coldd.dev says which message it has last in each channel and the
bot sends everything after it, oldest first. That runs at start (the first
start sends the whole history), on every new message and every few minutes,
so nothing is lost while the bot was offline. Edits are sent again.

Signing in: the bot makes its own key (.coldd_key, never in the repo) and
prints a pairing code in the console. coldd.dev's owner approves that code
once; until then nothing is sent.
"""

import asyncio
import hashlib
import logging
import os
import secrets
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

from bot_config import load_bot_config

log = logging.getLogger(__name__)

KEY_FILE = Path(__file__).resolve().parent.parent / ".coldd_key"
BATCH = 100


def _load_key() -> str:
    try:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if len(key) >= 32:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    KEY_FILE.write_text(key, encoding="utf-8")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def _fingerprint(key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return (digest[:4] + "-" + digest[4:8]).upper()


class ColddFeed(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cfg = load_bot_config().get("coldd_feed") or {}
        self.endpoint = str(cfg["endpoint"])
        self.channels = {
            int(cfg["purchases_channel_id"]): "purchases",
            int(cfg["reviews_channel_id"]): "reviews",
        }
        # Parcel's purchase log in coldd's old server: read for history only.
        for channel_id in cfg.get("history_channel_ids") or []:
            self.channels[int(channel_id)] = "old purchases"
        self.key = _load_key()
        self.fingerprint = _fingerprint(self.key)
        self.session: aiohttp.ClientSession | None = None
        self.active = False
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self.warned: set[int] = set()
        self.sweep.change_interval(minutes=max(1, int(cfg.get("check_minutes") or 5)))

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        self.runner = asyncio.create_task(self.run())
        self.sweep.start()

    async def cog_unload(self):
        self.sweep.cancel()
        self.runner.cancel()
        if self.session:
            await self.session.close()

    async def post(self, payload: dict) -> tuple[int, dict]:
        assert self.session is not None
        async with self.session.post(self.endpoint, json=payload, headers={"x-bot-key": self.key}) as response:
            try:
                data = await response.json(content_type=None)
            except Exception:
                data = {}
            return response.status, data if isinstance(data, dict) else {}

    async def pair(self):
        """Waits until coldd.dev's owner approves this bot's key."""
        shown = False
        while not self.active:
            try:
                status, data = await self.post({
                    "bot": "pair", "label": "coldd-dc-bot",
                    "bot_user": str(self.bot.user), "bot_user_id": str(self.bot.user.id),
                })
                if status == 200 and data.get("status") == "active":
                    self.active = True
                    print("[COLDD FEED] Signed in to coldd.dev.", flush=True)
                    return
                if not shown:
                    print(f"[COLDD FEED] Pairing code {self.fingerprint}: waiting for approval on coldd.dev.", flush=True)
                    shown = True
            except Exception as error:
                log.warning("pairing failed: %s", error)
            await asyncio.sleep(60)

    @staticmethod
    def wanted(raw: dict) -> bool:
        author = raw.get("author") or {}
        return bool(author.get("bot") or raw.get("webhook_id"))

    def shape(self, raw: dict, channel: discord.abc.GuildChannel) -> dict:
        author = raw.get("author") or {}
        return {
            "id": raw.get("id"),
            "channel_id": str(channel.id),
            "guild_id": str(channel.guild.id),
            "author": {"id": author.get("id"), "name": author.get("global_name") or author.get("username"), "bot": bool(author.get("bot"))},
            "webhook_id": raw.get("webhook_id"),
            "created_at": raw.get("timestamp"),
            "edited_at": raw.get("edited_timestamp"),
            "content": raw.get("content") or "",
            "embeds": raw.get("embeds") or [],
            "components": raw.get("components") or [],
            "attachments": [
                {"url": a.get("url"), "filename": a.get("filename"), "content_type": a.get("content_type")}
                for a in raw.get("attachments") or []
            ],
        }

    async def send(self, messages: list[dict]) -> None:
        for start in range(0, len(messages), BATCH):
            chunk = messages[start:start + BATCH]
            for attempt in range(6):
                try:
                    status, data = await self.post({"bot": "messages", "messages": chunk})
                    if status == 200:
                        break
                    if status in (401, 403):
                        self.active = False
                        raise RuntimeError(f"coldd.dev refused the key ({data.get('error')})")
                    log.warning("send failed (%s): %s", status, data)
                except aiohttp.ClientError as error:
                    log.warning("send failed: %s", error)
                await asyncio.sleep(min(60, 5 * 2 ** attempt))
            else:
                raise RuntimeError("coldd.dev did not take the messages")

    def channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel, "guild"):
            if channel_id not in self.warned:
                print(f"[COLDD FEED] Can't see channel {channel_id}. Is the bot in that server?", flush=True)
                self.warned.add(channel_id)
            return None
        perms = channel.permissions_for(channel.guild.me)
        if not (perms.view_channel and perms.read_message_history):
            if channel_id not in self.warned:
                print(f"[COLDD FEED] Missing View Channel or Read Message History in #{channel.name}.", flush=True)
                self.warned.add(channel_id)
            return None
        self.warned.discard(channel_id)
        return channel

    async def catch_up(self) -> None:
        """Sends every Parcel message after the newest one coldd.dev has."""
        if not self.active:
            return
        async with self.lock:
            status, state = await self.post({"bot": "state"})
            if status != 200:
                if status in (401, 403):
                    self.active = False
                log.warning("state failed (%s): %s", status, state)
                return
            known = state.get("channels") or {}
            for channel_id, label in self.channels.items():
                channel = self.channel(channel_id)
                if channel is None:
                    continue
                cursor = int(known.get(str(channel_id)) or 1)
                first = cursor == 1
                sent = 0
                while True:
                    page = await self.bot.http.logs_from(channel_id, 100, after=cursor)
                    if not page:
                        break
                    page.sort(key=lambda m: int(m["id"]))
                    cursor = int(page[-1]["id"])
                    batch = [self.shape(m, channel) for m in page if self.wanted(m)]
                    if batch:
                        await self.send(batch)
                        sent += len(batch)
                    if len(page) < 100:
                        break
                if sent or first:
                    print(f"[COLDD FEED] Sent {sent} message(s) from #{channel.name}{' (full history)' if first else ''}.", flush=True)

    async def run(self):
        await self.bot.wait_until_ready()
        await self.pair()
        while True:
            try:
                await self.catch_up()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("catch-up failed", exc_info=True)
            if not self.active:
                await self.pair()
                continue
            self.wake.clear()
            await self.wake.wait()

    @tasks.loop(minutes=5)
    async def sweep(self):
        self.wake.set()

    @sweep.before_loop
    async def before_sweep(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id in self.channels and (message.author.bot or message.webhook_id) and message.author.id != self.bot.user.id:
            self.wake.set()

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.channel_id not in self.channels or not self.active:
            return
        channel = self.channel(payload.channel_id)
        if channel is None:
            return
        try:
            # Older messages go first, so coldd.dev's newest message stays the newest sent.
            await self.catch_up()
            raw = await self.bot.http.get_message(payload.channel_id, payload.message_id)
            if self.wanted(raw) and int(raw.get("author", {}).get("id") or 0) != self.bot.user.id:
                await self.send([self.shape(raw, channel)])
        except Exception:
            log.warning("could not send an edited message", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ColddFeed(bot))
