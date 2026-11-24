import asyncio
import logging

import discord
from discord.ext import commands

from bot_config import (
    load_bot_config as loadBotConfig,
    load_embed_color as loadEmbedColor,
)


logger = logging.getLogger(__name__)

class WelcomeView(discord.ui.LayoutView):
    def __init__(
        self,
        member: discord.Member,
        imageUrl: str,
        embedColor: discord.Colour,
        invitedBy: discord.Member | None,
        inviteUrl: str | None,
    ):
        super().__init__(timeout=None)
        memberNumber = (
            f"#{member.guild.member_count}"
            if member.guild.member_count is not None
            else "Unknown"
        )
        joinDate = (
            discord.utils.format_dt(member.joined_at, style="F")
            if member.joined_at is not None
            else "Unknown"
        )
        if invitedBy is not None and inviteUrl is not None:
            inviterText = f"{invitedBy} & [This Link]({inviteUrl})"
        elif invitedBy is not None:
            inviterText = invitedBy
        else:
            inviterText = "Unknown"

        headerItems = [discord.ui.TextDisplay(content=member.mention)]
        if imageUrl:
            headerItems.extend(
                (
                    discord.ui.Separator(
                        visible=True, spacing=discord.SeparatorSpacing.small
                    ),
                    discord.ui.MediaGallery(
                        discord.MediaGalleryItem(
                            media=imageUrl, description="Welcome banner"
                        )
                    ),
                    discord.ui.Separator(
                        visible=True, spacing=discord.SeparatorSpacing.small
                    ),
                )
            )
        else:
            headerItems.append(
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                )
            )
        headerItems.append(
            discord.ui.TextDisplay(content="## <:coldd22:1571337228536381491> Welcome to coldd Development!")
        )

        self.add_item(
            discord.ui.Container(*headerItems, accent_colour=embedColor)
        )

        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    content=(
                        "-# **WELCOME**\n"
                        "Welcome to coldd! We're a professional **Development Store**"
                        " creating products"
                        " for **Roblox and Minecraft** - with a catalogue of over **700**"
                        " premium products"
                        " including **Roblox UIs, Vehicles, Systems, and Maps** - as well as"
                        " **Full Game Templates** too!\n"
                    )
                ),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                discord.ui.TextDisplay(
                    content=(
                        "\n-# **BEFORE YOU GET STARTED**\n"
                        "Make sure to read our **[Community Guidelines](https://discord.com/channels/1247414059909779578/1247414510680014928)** "
                        " and **[Terms of Service](https://discord.com/channels/1247414059909779578/1341772679140610089)** to make"
                        " sure you have the best experience possible here with us at"
                        " coldd! Consider"
                        " checking out our:\n"
                    )
                ),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                discord.ui.TextDisplay(
                    content=(
                        "\n-# **PLATFORMS**\n"
                        "- **[BuiltByBit [USD]](https://builtbybit.com/store/coldd-development.85/)**\n"
                        "- **[ClearlyDev [USD]](https://clearlydev.com/store/coldd)**\n"
                        "- **[Roblox Hub [R$]](https://www.roblox.com/games/18158461089/coldd-Storefront)**\n"
                        "> -# You can view our platform statuses here: <#1537592223640592476>.\n\n"
                        "-# **LINKS**\n"
                        "- **[Ongoing Events](https://discord.com/channels/1247414059909779578/1442148197324558336)**\n"
                        "- **[Development Sneak Peeks](https://discord.com/channels/1247414059909779578/1404685311916769300)**\n"
                        "- **[Hiring & Careers](https://discord.com/channels/1247414059909779578/1457140841171783700)**\n\n"
                        "-# **STATISTICS**\n"
                        f"-# **Member Number:** {memberNumber}\n"
                        f"-# **Invited By:** {inviterText}\n"
                        f"-# **Join Date:** {joinDate}"
                    )
                ),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                discord.ui.TextDisplay(
                    content="-# We hope you have a **great time** and **enjoy your stay** here at coldd!"
                ),
                accent_colour=embedColor,
            )
        )


class WelcomerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        config = loadBotConfig().get("welcomer", {})
        if not isinstance(config, dict):
            raise ValueError("config.json 'welcomer' must be an object")

        channelId = config.get("channel_id")
        if channelId is not None and (
            not isinstance(channelId, int)
            or isinstance(channelId, bool)
            or channelId <= 0
        ):
            raise ValueError(
                "config.json 'welcomer.channel_id' must be a positive integer or null"
            )
        self.channelId = channelId
        imageUrl = config.get("image_url", "")
        if not isinstance(imageUrl, str):
            raise ValueError("config.json 'welcomer.image_url' must be a URL string")
        self.imageUrl = imageUrl

        self.embedColor = discord.Colour(loadEmbedColor())
        self.inviteCache: dict[int, dict[str, discord.Invite]] = {}
        self.vanityUses: dict[int, int] = {}
        self.inviteLock = asyncio.Lock()

    async def _fetch_invites(
        self, guild: discord.Guild
    ) -> tuple[list[discord.Invite], discord.Invite | None] | None:
        try:
            invites = await asyncio.wait_for(guild.invites(), timeout=5)
        except discord.Forbidden:
            logger.warning(
                "Cannot track invites in guild %s; the bot needs Manage Server permission",
                guild.id,
            )
            return None
        except asyncio.TimeoutError:
            logger.warning("Timed out fetching invites for guild %s", guild.id)
            return None
        except discord.HTTPException:
            logger.exception("Could not fetch invites for guild %s", guild.id)
            return None

        vanityInvite = None
        if guild.vanity_url:
            try:
                vanityInvite = await asyncio.wait_for(
                    guild.vanity_invite(), timeout=5
                )
            except discord.Forbidden:
                logger.warning("Cannot read the vanity invite for guild %s", guild.id)
            except asyncio.TimeoutError:
                logger.warning("Timed out fetching vanity invite for guild %s", guild.id)
            except discord.HTTPException:
                logger.exception("Could not fetch vanity invite for guild %s", guild.id)
        return invites, vanityInvite

    async def _cache_guild_invites(self, guild: discord.Guild) -> None:
        async with self.inviteLock:
            snapshot = await self._fetch_invites(guild)
            if snapshot is None:
                return
            invites, vanityInvite = snapshot
            self.inviteCache[guild.id] = {
                invite.code: invite for invite in invites
            }
            if vanityInvite is not None:
                self.vanityUses[guild.id] = vanityInvite.uses or 0

    async def _identify_invite(
        self, guild: discord.Guild
    ) -> tuple[str | None, str | None]:
        async with self.inviteLock:
            snapshot = await self._fetch_invites(guild)
            if snapshot is None:
                return None, None

            invites, vanityInvite = snapshot
            previousInvites = self.inviteCache.get(guild.id)
            previousVanityUses = self.vanityUses.get(guild.id)
            currentInvites = {invite.code: invite for invite in invites}
            currentVanityUses = (
                vanityInvite.uses or 0 if vanityInvite is not None else None
            )
            self.inviteCache[guild.id] = currentInvites
            if currentVanityUses is not None:
                self.vanityUses[guild.id] = currentVanityUses

            if previousInvites is None:
                return None, None

            usedInvites = []
            for code, invite in currentInvites.items():
                previous = previousInvites.get(code)
                if previous is None:
                    continue
                uses = (invite.uses or 0) - (previous.uses or 0)
                if uses:
                    usedInvites.append((invite, uses))

            vanityWasUsed = (
                currentVanityUses is not None
                and previousVanityUses is not None
                and currentVanityUses > previousVanityUses
            )
            vanityUses = (
                currentVanityUses - previousVanityUses
                if vanityWasUsed
                else 0
            )

            if vanityUses == 1 and not usedInvites and vanityInvite is not None:
                return "Vanity URL", vanityInvite.url
            if (
                len(usedInvites) == 1
                and usedInvites[0][1] == 1
                and not vanityWasUsed
            ):
                invite = usedInvites[0][0]
                inviter = invite.inviter.mention if invite.inviter is not None else "Unknown"
                return inviter, invite.url
            return None, None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.channelId is None:
            return
        channel = self.bot.get_channel(self.channelId)
        if isinstance(channel, discord.TextChannel):
            await self._cache_guild_invites(channel.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if self.channelId is None:
            logger.warning(
                "Welcomer skipped for guild %s: set welcomer.channel_id in config.json",
                member.guild.id,
            )
            return

        channel = member.guild.get_channel(self.channelId)
        if not isinstance(channel, discord.TextChannel):
            logger.error(
                "Welcomer channel %s is unavailable in guild %s",
                self.channelId,
                member.guild.id,
            )
            return

        if not self.imageUrl:
            logger.warning("Welcomer image_url is empty in config.json")

        invitedBy, inviteUrl = await self._identify_invite(member.guild)
        try:
            await channel.send(
                view=WelcomeView(
                    member,
                    self.imageUrl,
                    self.embedColor,
                    invitedBy,
                    inviteUrl,
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except discord.HTTPException:
            logger.exception(
                "Could not send welcome message in channel %s", self.channelId
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomerCog(bot))
