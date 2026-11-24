import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import load_bot_config as loadBotConfig


class CustomerServiceRoleRequired(appCommands.CheckFailure):
    pass


class CustomerServiceRoleNotConfigured(appCommands.CheckFailure):
    pass


async def has_customer_service_role(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        raise CustomerServiceRoleRequired
    if not isinstance(interaction.client, commands.Bot):
        raise CustomerServiceRoleRequired

    cog = interaction.client.get_cog("TicketIntroCog")
    if not isinstance(cog, TicketIntroCog):
        raise CustomerServiceRoleRequired
    if cog.customerServiceRoleId <= 0:
        raise CustomerServiceRoleNotConfigured
    if not any(
        role.id == cog.customerServiceRoleId for role in interaction.user.roles
    ):
        raise CustomerServiceRoleRequired
    return True


class TicketIntroCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ticketConfig = loadBotConfig().get("ticket_intro", {})
        if not isinstance(ticketConfig, dict):
            raise ValueError("config.json 'ticket_intro' must be an object")

        roleId = ticketConfig.get("customer_service_role_id")
        if not isinstance(roleId, int) or isinstance(roleId, bool) or roleId < 0:
            raise ValueError(
                "config.json 'ticket_intro.customer_service_role_id' "
                "must be a non-negative integer"
            )
        message = ticketConfig.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("config.json 'ticket_intro.message' must be a non-empty string")
        if "{ping}" not in message:
            raise ValueError(
                "config.json 'ticket_intro.message' must include the {ping} placeholder"
            )

        self.customerServiceRoleId = roleId
        self.message = message

    @appCommands.command(
        name="ticket-intro", description="Send the configured ticket introduction"
    )
    @appCommands.guild_only()
    @appCommands.check(has_customer_service_role)
    async def ticket_intro(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            self.message.replace("{ping}", interaction.user.mention),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(
                users=[interaction.user], roles=False, everyone=False
            ),
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: appCommands.AppCommandError
    ) -> None:
        if isinstance(error, CustomerServiceRoleNotConfigured):
            message = "<:XXsmallBoldIcon:1572022926251925545> The customer service role is not configured yet."
        elif isinstance(error, CustomerServiceRoleRequired):
            message = "<:XXsmallBoldIcon:1572022926251925545> You need the configured customer service role to use this command."
        else:
            raise error

        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketIntroCog(bot))
