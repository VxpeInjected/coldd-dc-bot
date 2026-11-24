import datetime
import logging
import re

import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import load_bot_config as loadBotConfig


logger = logging.getLogger(__name__)
maxPurgeAmount = 1000
durationPattern = re.compile(r"([1-9]\d*)([smhd])")


class PurgeRoleRequired(appCommands.CheckFailure):
    pass


class PurgeRoleNotConfigured(appCommands.CheckFailure):
    pass


def parse_duration(value: str) -> datetime.timedelta:
    match = durationPattern.fullmatch(value.strip().lower())
    if match is None:
        raise ValueError("Use a duration such as `30m`, `2h`, or `1d`.")

    amount = int(match.group(1))
    unit = match.group(2)
    maxAmount = {"s": 2_592_000, "m": 43_200, "h": 720, "d": 30}[unit]
    if amount > maxAmount:
        raise ValueError("The maximum time-based purge window is 30 days.")
    return {
        "s": datetime.timedelta(seconds=amount),
        "m": datetime.timedelta(minutes=amount),
        "h": datetime.timedelta(hours=amount),
        "d": datetime.timedelta(days=amount),
    }[unit]


async def has_staff_role(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        raise PurgeRoleRequired
    if not isinstance(interaction.client, commands.Bot):
        raise PurgeRoleRequired

    cog = interaction.client.get_cog("PurgeCog")
    if not isinstance(cog, PurgeCog):
        raise PurgeRoleRequired
    if cog.staffRoleId <= 0:
        raise PurgeRoleNotConfigured
    if not any(role.id == cog.staffRoleId for role in interaction.user.roles):
        raise PurgeRoleRequired
    return True


class PurgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        purgeConfig = loadBotConfig().get("purge", {})
        if not isinstance(purgeConfig, dict):
            raise ValueError("config.json 'purge' must be an object")

        staffRoleId = purgeConfig.get("staff_role_id")
        if (
            not isinstance(staffRoleId, int)
            or isinstance(staffRoleId, bool)
            or staffRoleId < 0
        ):
            raise ValueError(
                "config.json 'purge.staff_role_id' must be a non-negative integer"
            )
        self.staffRoleId = staffRoleId

    @appCommands.command(
        name="purge", description="Delete recent messages from this channel"
    )
    @appCommands.guild_only()
    @appCommands.check(has_staff_role)
    @appCommands.describe(
        amount="Number of recent messages to delete (1 to 1000)",
        time="Delete messages from this time window (for example 30m, 2h, or 1d)",
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: appCommands.Range[int, 1, maxPurgeAmount] | None = None,
        time: str | None = None,
    ) -> None:
        if (amount is None) == (time is None):
            await interaction.response.send_message(
                "Choose exactly one of `amount` or `time`.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> This command can only be used in a text channel or thread.",
                ephemeral=True,
            )
            return

        after = None
        limit = amount
        if time is not None:
            try:
                duration = parse_duration(time)
            except ValueError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            after = discord.utils.utcnow() - duration
            limit = None
            progressMessage = (
                "<a:discordLoadingGif:1572022903493361732> "
                f"Purging messages in the last {time.strip()}."
            )
        else:
            assert amount is not None
            progressMessage = (
                "<a:discordLoadingGif:1572022903493361732> "
                f"Purging {amount} messages"
            )

        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content=progressMessage)
        try:
            deleted = await channel.purge(
                limit=limit,
                after=after,
                oldest_first=False,
            )
        except discord.Forbidden:
            logger.warning("Bot cannot purge messages in channel %s", channel.id)
            await interaction.edit_original_response(
                content="<:XXsmallBoldIcon:1572022926251925545> I need permission to manage messages in this channel."
            )
            return
        except discord.HTTPException:
            logger.exception("Could not purge messages in channel %s", channel.id)
            await interaction.edit_original_response(
                content="<:XXsmallBoldIcon:1572022926251925545> The messages could not be purged. Check the bot logs for details."
            )
            return

        await interaction.edit_original_response(
            content=f"<:CircleCheckIcon:1572022898825232574> Deleted **{len(deleted)}** message(s)."
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: appCommands.AppCommandError
    ) -> None:
        if isinstance(error, PurgeRoleNotConfigured):
            message = "<:XXsmallBoldIcon:1572022926251925545> The staff role is not configured yet."
        elif isinstance(error, PurgeRoleRequired):
            message = "<:XXsmallBoldIcon:1572022926251925545> You need the configured staff role to use this command."
        else:
            raise error

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PurgeCog(bot))
