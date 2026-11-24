import discord
from discord import app_commands as appCommands
from discord.ext import commands


class TestingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @appCommands.command(name="test", description="Check that the bot is responding")
    async def test(self, interaction: discord.Interaction):
        await interaction.response.send_message("<:CircleCheckIcon:1572022898825232574> The bot is online and working correctly.", ephemeral=True)

    @appCommands.command(name="ping", description="Show the bot's latency")
    async def ping(self, interaction: discord.Interaction):
        latencyMs = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"<:TimerIcon:1572022924590850078> ***Pong!*** - The bot's latency is `{latencyMs}` ms.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TestingCog(bot))
