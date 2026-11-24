import asyncio
import json
import logging
from pathlib import Path

import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import (
    load_bot_config as loadBotConfig,
    load_embed_color as loadEmbedColor,
)


logger = logging.getLogger(__name__)
configPath = Path(__file__).resolve().parents[1] / "ping_on_join.json"
maxDelay = 604800


class PingOnJoinRoleRequired(appCommands.CheckFailure):
    pass


async def has_ping_on_join_role(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        raise PingOnJoinRoleRequired
    if not isinstance(interaction.client, commands.Bot):
        raise PingOnJoinRoleRequired

    cog = interaction.client.get_cog("PingOnJoinCog")
    if not isinstance(cog, PingOnJoinCog):
        raise PingOnJoinRoleRequired
    if not any(role.id == cog.authorizedRoleId for role in interaction.user.roles):
        raise PingOnJoinRoleRequired
    return True


class PingOnJoinResponse(discord.ui.LayoutView):
    def __init__(
        self, title: str, message: str, embedColor: discord.Colour
    ):
        super().__init__()
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(content=f"### {title}"),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                discord.ui.TextDisplay(content=message),
                accent_colour=embedColor,
            )
        )


class PingOnJoinCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        pingConfig = loadBotConfig().get("ping_on_join", {})
        if not isinstance(pingConfig, dict):
            raise ValueError("config.json 'ping_on_join' must be an object")
        defaultDelay = pingConfig.get("default_deletion_delay_seconds")
        authorizedRoleId = pingConfig.get("authorized_role_id")
        if (
            not isinstance(defaultDelay, int)
            or isinstance(defaultDelay, bool)
            or not 1 <= defaultDelay <= maxDelay
        ):
            raise ValueError(
                "config.json 'ping_on_join.default_deletion_delay_seconds' "
                f"must be an integer from 1 to {maxDelay}"
            )
        if (
            not isinstance(authorizedRoleId, int)
            or isinstance(authorizedRoleId, bool)
            or authorizedRoleId <= 0
        ):
            raise ValueError(
                "config.json 'ping_on_join.authorized_role_id' must be a positive integer"
            )
        self.defaultDelay = defaultDelay
        self.authorizedRoleId = authorizedRoleId
        self.embedColor = discord.Colour(loadEmbedColor())
        self.config = self._load_config()
        self.deleteTasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _load_config() -> dict[str, dict]:
        if not configPath.exists():
            return {}

        data = json.loads(configPath.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{configPath} must contain a JSON object")

        for guildId, settings in data.items():
            if (
                not guildId.isdecimal()
                or not isinstance(settings, dict)
                or not isinstance(settings.get("channels"), list)
                or any(
                    not isinstance(channelId, int) or isinstance(channelId, bool)
                    for channelId in settings["channels"]
                )
                or not isinstance(settings.get("delay"), int)
                or isinstance(settings.get("delay"), bool)
                or not 1 <= settings["delay"] <= maxDelay
                or not isinstance(settings.get("enabled"), bool)
            ):
                raise ValueError(f"Invalid ping-on-join settings for guild {guildId}")

        return data

    def _save_config(self, config: dict[str, dict]) -> None:
        temporaryPath = configPath.with_suffix(".tmp")
        temporaryPath.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        temporaryPath.replace(configPath)
        self.config = config

    def _settings_for(self, guildId: int) -> dict:
        return self.config.get(
            str(guildId),
            {"channels": [], "delay": self.defaultDelay, "enabled": True},
        )

    def _update_settings(self, guildId: int, **updates) -> dict:
        settings = {**self._settings_for(guildId), **updates}
        config = {**self.config, str(guildId): settings}
        self._save_config(config)
        return settings

    async def _respond(
        self, interaction: discord.Interaction, title: str, message: str
    ) -> None:
        await interaction.response.send_message(
            view=PingOnJoinResponse(title, message, self.embedColor), ephemeral=True
        )

    async def _delete_after(self, message: discord.Message, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("Could not delete ping-on-join message %s", message.id)

    def _schedule_delete(self, message: discord.Message, delay: int) -> None:
        task = asyncio.create_task(self._delete_after(message, delay))
        self.deleteTasks.add(task)
        task.add_done_callback(self.deleteTasks.discard)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        settings = self._settings_for(member.guild.id)
        if not settings["enabled"]:
            return

        allowedMentions = discord.AllowedMentions(
            users=True, roles=False, everyone=False
        )
        for channelId in settings["channels"]:
            channel = member.guild.get_channel(channelId)
            if not isinstance(channel, discord.TextChannel):
                logger.warning(
                    "Configured ping-on-join channel %s is missing from guild %s",
                    channelId,
                    member.guild.id,
                )
                continue
            try:
                message = await channel.send(
                    f"{member.mention} joined the server.",
                    allowed_mentions=allowedMentions,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not send ping-on-join message in channel %s", channelId
                )
                continue
            self._schedule_delete(message, settings["delay"])

    @appCommands.command(
        name="ping-on-join-add", description="Add a channel to ping when someone joins"
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    @appCommands.describe(channel="Text channel for join notifications")
    async def add_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        assert interaction.guild is not None
        settings = self._settings_for(interaction.guild.id)
        if channel.id in settings["channels"]:
            await self._respond(
                interaction, "<:XXsmallBoldIcon:1572022926251925545> Already configured", f"{channel.mention} is already set."
            )
            return

        channels = [*settings["channels"], channel.id]
        self._update_settings(interaction.guild.id, channels=channels)
        await self._respond(
            interaction, "<:CircleCheckIcon:1572022898825232574> Channel added", f"{channel.mention} will be notified on joins."
        )

    @appCommands.command(
        name="ping-on-join-remove",
        description="Remove a channel from join notifications",
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    @appCommands.describe(channel="Text channel to remove")
    async def remove_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        assert interaction.guild is not None
        settings = self._settings_for(interaction.guild.id)
        if channel.id not in settings["channels"]:
            await self._respond(
                interaction, "<:XXsmallBoldIcon:1572022926251925545> Not configured", f"{channel.mention} is not set."
            )
            return

        channels = [
            channelId
            for channelId in settings["channels"]
            if channelId != channel.id
        ]
        self._update_settings(interaction.guild.id, channels=channels)
        await self._respond(
            interaction, "<:CircleCheckIcon:1572022898825232574> Channel removed", f"{channel.mention} will no longer be notified."
        )

    @appCommands.command(
        name="ping-on-join-delay-set",
        description="Set how long join notification messages remain",
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    @appCommands.describe(seconds="Deletion delay in seconds (1 to 604800)")
    async def set_delay(
        self,
        interaction: discord.Interaction,
        seconds: appCommands.Range[int, 1, maxDelay],
    ) -> None:
        assert interaction.guild is not None
        self._update_settings(interaction.guild.id, delay=seconds)
        await self._respond(
            interaction,
            "<:CircleCheckIcon:1572022898825232574> Delay updated.",
            f"Join notifications **will be deleted** after **{seconds} seconds**.",
        )

    @appCommands.command(
        name="ping-on-join-halt-all", description="Pause join notifications"
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    async def halt_all(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        self._update_settings(interaction.guild.id, enabled=False)
        await self._respond(interaction, "Notifications halted", "Join notifications are paused.")

    @appCommands.command(
        name="ping-on-join-restart", description="Resume join notifications"
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    async def restart(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        self._update_settings(interaction.guild.id, enabled=True)
        await self._respond(interaction, "<:CircleCheckIcon:1572022898825232574> Notifications restarted", "Join notifications are active.")

    @appCommands.command(
        name="ping-on-join-simulate",
        description="Send a test join notification to every configured channel",
    )
    @appCommands.guild_only()
    @appCommands.check(has_ping_on_join_role)
    async def simulate(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        settings = self._settings_for(interaction.guild.id)
        if not settings["enabled"]:
            await self._respond(
                interaction, "<:CircleCheckIcon:1572022898825232574> Notifications halted", "Restart join notifications before simulating."
            )
            return
        if not settings["channels"]:
            await self._respond(
                interaction, "<:XXsmallBoldIcon:1572022926251925545> No channels configured", "Add a channel before simulating."
            )
            return

        await interaction.response.defer(ephemeral=True)
        allowedMentions = discord.AllowedMentions(
            users=True, roles=False, everyone=False
        )
        sent = 0
        failed = 0
        for channelId in settings["channels"]:
            channel = interaction.guild.get_channel(channelId)
            if not isinstance(channel, discord.TextChannel):
                failed += 1
                continue
            try:
                message = await channel.send(
                    f"{interaction.user.mention} (simulated join)",
                    allowed_mentions=allowedMentions,
                )
            except discord.HTTPException:
                logger.exception(
                    "Could not simulate ping-on-join in channel %s", channelId
                )
                failed += 1
                continue
            sent += 1
            self._schedule_delete(message, settings["delay"])

        result = f"Sent test notifications to **{sent}** channel(s)."
        if failed:
            result += f"\nCould not send to **{failed}** channel(s); check channel access."
        await interaction.edit_original_response(
            view=PingOnJoinResponse(
                "Simulation complete", result, self.embedColor
            )
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: appCommands.AppCommandError
    ) -> None:
        if isinstance(error, PingOnJoinRoleRequired):
            await self._respond(
                interaction,
                "<:XXsmallBoldIcon:1572022926251925545> Permissions required.",
                "You need the configured Ping-on-Join role to use this command.",
            )
            return
        raise error


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingOnJoinCog(bot))
