import asyncio
import logging

from discord.ext import commands, tasks

import updater

log = logging.getLogger(__name__)


class AutoUpdate(commands.Cog):
    """Checks GitHub every few minutes and restarts the bot on a new commit."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check.change_interval(minutes=updater.settings()["check_minutes"])
        self.check.start()

    def cog_unload(self):
        self.check.cancel()

    @tasks.loop(minutes=2)
    async def check(self):
        try:
            changed = await asyncio.to_thread(updater.check_and_update)
        except Exception:
            log.warning("update check failed", exc_info=True)
            return
        if changed:
            updater.restart()

    @check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoUpdate(bot))
