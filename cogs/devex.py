import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import load_embed_color as loadEmbedColor

devexRates = {
    "USD": 0.0038,
    "EUR": 0.0033,
    "GBP": 0.0029,
    "JPY": 0.52,
    "INR": 0.29,
    "AUD": 0.0053,
    "CAD": 0.0048,
    "BRL": 0.019,
    "KRW": 4.76,
    "MXN": 0.063,
}

currencyChoices = [
    appCommands.Choice(name=f"{code} ({name})", value=code)
    for code, name in [
        ("USD", "US Dollar"),
        ("EUR", "Euro"),
        ("GBP", "Great British Pound"),
        ("JPY", "Japanese Yen"),
        ("INR", "Indian Rupee"),
        ("AUD", "Australian Dollar"),
        ("CAD", "Canadian Dollar"),
        ("BRL", "Brazilian Real"),
        ("KRW", "South Korean Won"),
        ("MXN", "Mexican Peso"),
    ]
]

class DevexResultView(discord.ui.LayoutView):
    def __init__(
        self,
        title: str,
        inputLabel: str,
        outputLabel: str,
        footerText: str,
        embedColor: discord.Colour,
    ):
        super().__init__()
        
        self.container = discord.ui.Container(
            discord.ui.TextDisplay(content=f"### {title}"),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(content=f"**Input:** {inputLabel}\n**Output:** {outputLabel}"),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay(content=f"*{footerText}*"),
            accent_colour=embedColor
        )
        self.add_item(self.container)

class DevexGroup(appCommands.Group):
    def __init__(self, embedColor: discord.Colour):
        super().__init__(name="devex", description="DevEx conversion commands using Components v2")
        self.embedColor = embedColor

    @appCommands.command(name="robux", description="Convert Robux into real-world currency")
    @appCommands.describe(amount="Amount of Robux", currency="Target fiat currency")
    @appCommands.choices(currency=currencyChoices)
    async def robux(self, interaction: discord.Interaction, amount: int, currency: appCommands.Choice[str]):
        if amount <= 0:
            return await interaction.response.send_message("<:XXsmallBoldIcon:1572022926251925545> Value must be greater than zero.", ephemeral=True)

        code = currency.value
        rate = devexRates[code]
        converted = amount * rate

        view = DevexResultView(
            title="<:BookCheckIcon:1572022894496587846> DevEx Calculator (Robux → Cash)",
            inputLabel=f"`{amount:,}` Robux",
            outputLabel=f"`{converted:,.2f}` {code}",
            footerText=f"Current Rate: 1 Robux = {rate} {code}",
            embedColor=self.embedColor,
        )
        await interaction.response.send_message(view=view, ephemeral=True)

    @appCommands.command(name="currency", description="Convert real-world currency into Robux")
    @appCommands.describe(amount="Amount of cash", currency="Source fiat currency")
    @appCommands.choices(currency=currencyChoices)
    async def currency(self, interaction: discord.Interaction, amount: float, currency: appCommands.Choice[str]):
        if amount <= 0:
            return await interaction.response.send_message("<:XXsmallBoldIcon:1572022926251925545> Value must be greater than zero.", ephemeral=True)

        code = currency.value
        rate = devexRates[code]
        converted = round(amount / rate)

        view = DevexResultView(
            title="<:BookCheckIcon:1572022894496587846> DevEx Calculator (Cash → Robux)",
            inputLabel=f"`{amount:,.2f}` {code}",
            outputLabel=f"`{converted:,}` Robux",
            footerText=f"Current Rate: 1 Robux = {rate} {code}",
            embedColor=self.embedColor,
        )
        await interaction.response.send_message(view=view, ephemeral=True)

class DevexCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.tree.add_command(DevexGroup(discord.Colour(loadEmbedColor())))

async def setup(bot: commands.Bot):
    await bot.add_cog(DevexCog(bot))