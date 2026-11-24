import logging

import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import load_bot_config as loadBotConfig


logger = logging.getLogger(__name__)


def load_authorized_user_ids() -> set[int]:
    sayConfig = loadBotConfig().get("say", {})
    if not isinstance(sayConfig, dict):
        raise ValueError("config.json 'say' must be an object")

    configuredIds = sayConfig.get("authorized_user_ids")
    if not isinstance(configuredIds, list):
        raise ValueError("config.json 'say.authorized_user_ids' must be a list")

    authorizedIds = set()
    for userId in configuredIds:
        if isinstance(userId, bool):
            raise ValueError("Authorized user IDs must be positive integers")
        if isinstance(userId, str) and userId.isdecimal():
            userId = int(userId)
        if not isinstance(userId, int) or userId <= 0:
            raise ValueError("Authorized user IDs must be positive integers")
        authorizedIds.add(userId)
    return authorizedIds


class SayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.authorizedUserIds = load_authorized_user_ids()

    @appCommands.command(name="say", description="Send a message as the bot")
    @appCommands.guild_only()
    @appCommands.describe(
        message=r"The message to send; use \n for a new line (up to 2,000 characters)",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
    ) -> None:
        if interaction.user.id not in self.authorizedUserIds:
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> You are not authorized to use this command.", ephemeral=True
            )
            return

        message = message.replace("\\n", "\n")
        if len(message) > 2000:
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> Messages must be 2,000 characters or fewer.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> I can't send a message in this channel.", ephemeral=True
            )
            return

        try:
            await channel.send(message)
        except discord.Forbidden:
            logger.warning("Bot cannot send a /say message in channel %s", channel.id)
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> I don't have permission to send messages in this channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Could not send /say message in channel %s", channel.id)
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> The message could not be sent. Check the bot logs for details.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Message sent.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SayCog(bot))
