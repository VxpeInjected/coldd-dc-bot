import asyncio
import datetime
import json
import logging
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import discord
from discord import app_commands as appCommands
from discord.ext import commands

from bot_config import (
    load_bot_config as loadBotConfig,
    load_embed_color as loadEmbedColor,
)


logger = logging.getLogger(__name__)
reminderListPath = Path(__file__).resolve().parents[1] / "remindlist.json"
durationToken = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
maxReminderSeconds = 365 * 24 * 60 * 60 + 1 # 365 days and 1 second, to allow for leap years
maxRemindersPerUser = 10
maxReminderMessageLength = 1750 # Kept under 2000 to allow for formatting and extra text in the message
listPageLength = 1800


def parse_duration(value: str) -> datetime.timedelta:
    position = 0
    totalSeconds = 0
    units = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
    }

    while position < len(value):
        while position < len(value) and value[position].isspace():
            position += 1
        if position == len(value):
            break

        match = durationToken.match(value, position)
        if match is None:
            raise ValueError(
                "Use a duration such as `30m`, `2h`, `1d`, or `1d 2h`."
            )
        amountText, unit = match.groups()
        if len(amountText) > 9:
            raise ValueError("The maximum reminder time is 365 days.")
        totalSeconds += int(amountText) * units[unit.lower()]
        if totalSeconds > maxReminderSeconds:
            raise ValueError("The maximum reminder time is 365 days.")
        position = match.end()

    if totalSeconds <= 0:
        raise ValueError("The reminder time must be greater than zero.")
    return datetime.timedelta(seconds=totalSeconds)


def parse_reminder_time(value: str) -> datetime.datetime:
    try:
        reminderAt = datetime.datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("A reminder has an invalid saved time.") from error
    if reminderAt.tzinfo is None:
        raise ValueError("A saved reminder time must include a timezone.")
    return reminderAt.astimezone(datetime.timezone.utc)


class ReminderDeliveryView(discord.ui.LayoutView):
    def __init__(
        self, imageUrl: str, message: str, embedColor: discord.Colour
    ):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.MediaGallery(
                    discord.MediaGalleryItem(
                        imageUrl, description="coldd banner"
                    )
                ),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                discord.ui.TextDisplay(content="## <:TimerIcon:1572022924590850078> Your Reminder"),
                accent_colour=embedColor,
            )
        )
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(content="-# **REMINDER**"),
                discord.ui.TextDisplay(content=message),
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                ),
                accent_colour=embedColor,
            )
        )


class ReminderStatusView(discord.ui.LayoutView):
    def __init__(
        self, title: str, message: str, embedColor: discord.Colour
    ):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(content=f"## {title}"),
                discord.ui.TextDisplay(content=message),
                accent_colour=embedColor,
            )
        )


class ReminderClearButton(discord.ui.Button):
    def __init__(
        self, clearView: "ReminderClearConfirmationView", shouldClear: bool
    ):
        self.clearView = clearView
        self.shouldClear = shouldClear
        if shouldClear:
            super().__init__(label="Confirm clear", style=discord.ButtonStyle.danger)
        else:
            super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.clearView.handle_button(interaction, self.shouldClear)


class ReminderClearConfirmationView(discord.ui.LayoutView):
    def __init__(
        self,
        remindersCog: "RemindersCog",
        interaction: discord.Interaction,
        reminders: list[dict],
    ):
        super().__init__(timeout=300)
        self.remindersCog = remindersCog
        self.userId = interaction.user.id
        self.reminderIds = [reminder["id"] for reminder in reminders]
        self.embedColor = remindersCog.embedColor

        for start in range(0, len(reminders), 8):
            pageReminders = reminders[start : start + 8]
            items = []
            if start == 0:
                items.extend(
                    (
                        discord.ui.TextDisplay(
                            content="## <:TimerIcon:1572022924590850078> Clear all reminders?"
                        ),
                        discord.ui.TextDisplay(
                            content=f"This will remove all {len(reminders)} reminders listed below:"
                        ),
                    )
                )
            for reminder in pageReminders:
                reminderAt = parse_reminder_time(reminder["reminder_at"])
                timestamp = int(reminderAt.timestamp())
                message = reminder["message"].replace("\n", " | ")
                items.append(
                    discord.ui.TextDisplay(
                        content=(
                            f"{message} - `{reminder['id']}` - "
                            f"<t:{timestamp}:F> (<t:{timestamp}:R>)"
                        )
                    )
                )
            self.add_item(
                discord.ui.Container(*items, accent_colour=self.embedColor)
            )

        self.add_item(
            discord.ui.Container(
                discord.ui.ActionRow(
                    ReminderClearButton(self, shouldClear=True),
                    ReminderClearButton(self, shouldClear=False),
                ),
                accent_colour=self.embedColor,
            )
        )

    async def handle_button(
        self, interaction: discord.Interaction, shouldClear: bool
    ) -> None:
        if interaction.user.id != self.userId:
            await interaction.response.send_message(
                "Only the person who opened this confirmation can use it.",
                ephemeral=True,
            )
            return

        if not shouldClear:
            self.stop()
            await interaction.response.edit_message(
                view=ReminderStatusView(
                    "Clear cancelled",
                    "Your reminders were not removed.",
                    self.embedColor,
                )
            )
            return

        try:
            removedIds = self.remindersCog._remove_reminders(
                self.userId, self.reminderIds
            )
        except OSError:
            logger.exception(
                "Could not clear reminders for user %s", self.userId
            )
            await interaction.response.send_message(
                "The reminders could not be cleared. Check the bot logs for details.",
                ephemeral=True,
            )
            return

        for reminderId in removedIds:
            task = self.remindersCog.tasks.get(reminderId)
            if task is not None:
                task.cancel()

        self.stop()
        await interaction.response.edit_message(
            view=ReminderStatusView(
                "Reminders cleared",
                f"Removed {len(removedIds)} reminder(s).",
                self.embedColor,
            )
        )


class RemindersCog(commands.Cog):
    remindersGroup = appCommands.Group(
        name="reminders", description="Manage your personal reminders"
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        remindersConfig = loadBotConfig().get("reminders", {})
        if not isinstance(remindersConfig, dict):
            raise ValueError("config.json 'reminders' must be an object")

        imageUrl = remindersConfig.get("image_url")
        parsedImageUrl = urlparse(imageUrl) if isinstance(imageUrl, str) else None
        if (
            parsedImageUrl is None
            or parsedImageUrl.scheme != "https"
            or not parsedImageUrl.netloc
        ):
            raise ValueError(
                "config.json 'reminders.image_url' must be a valid HTTPS URL"
            )

        self.imageUrl = imageUrl
        self.embedColor = discord.Colour(loadEmbedColor())
        self.reminders = self._load_reminders()
        self.tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    def _load_reminders() -> dict[str, dict]:
        if not reminderListPath.exists():
            return {}

        data = json.loads(reminderListPath.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{reminderListPath} must contain a JSON list")

        reminders = {}
        for entry in data:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), str)
                or not re.fullmatch(r"[0-9a-f]{8}", entry["id"])
                or not isinstance(entry.get("user_id"), int)
                or isinstance(entry.get("user_id"), bool)
                or entry["user_id"] <= 0
                or not isinstance(entry.get("message"), str)
                or not isinstance(entry.get("reminder_at"), str)
            ):
                raise ValueError(f"Invalid reminder entry in {reminderListPath}")
            parse_reminder_time(entry["reminder_at"])
            if entry["id"] in reminders:
                raise ValueError(f"Duplicate reminder ID {entry['id']}")
            reminders[entry["id"]] = entry
        return reminders

    def _save_reminders(self, reminders: dict[str, dict]) -> None:
        temporaryPath = reminderListPath.with_suffix(".tmp")
        temporaryPath.write_text(
            json.dumps(list(reminders.values()), indent=2) + "\n",
            encoding="utf-8",
        )
        temporaryPath.replace(reminderListPath)
        self.reminders = reminders

    async def cog_load(self) -> None:
        if self.bot.is_ready():
            self._schedule_saved_reminders()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self._schedule_saved_reminders()

    def _schedule_saved_reminders(self) -> None:
        for reminder in self.reminders.values():
            self._schedule_reminder(reminder)

    def cog_unload(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()

    def _schedule_reminder(self, reminder: dict) -> None:
        reminderId = reminder["id"]
        if reminderId in self.tasks:
            return
        task = asyncio.create_task(self._deliver_reminder(reminder))
        self.tasks[reminderId] = task
        task.add_done_callback(
            lambda completed, itemId=reminderId: self._task_finished(
                itemId, completed
            )
        )

    def _task_finished(
        self, reminderId: str, task: asyncio.Task[None]
    ) -> None:
        if self.tasks.get(reminderId) is task:
            self.tasks.pop(reminderId, None)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error(
                    "Reminder task %s failed",
                    reminderId,
                    exc_info=(type(error), error, error.__traceback__),
                )

    def _remove_reminders(
        self, userId: int, reminderIds: list[str]
    ) -> list[str]:
        removedIds = [
            reminderId
            for reminderId in reminderIds
            if reminderId in self.reminders
            and self.reminders[reminderId]["user_id"] == userId
        ]
        if not removedIds:
            return []

        removedIdSet = set(removedIds)
        updated = {
            key: value
            for key, value in self.reminders.items()
            if key not in removedIdSet
        }
        self._save_reminders(updated)
        return removedIds

    def _remove_reminder(self, reminderId: str) -> bool:
        reminder = self.reminders.get(reminderId)
        if reminder is None:
            return False
        return bool(self._remove_reminders(reminder["user_id"], [reminderId]))

    async def _deliver_reminder(self, reminder: dict) -> None:
        reminderId = reminder["id"]
        reminderAt = parse_reminder_time(reminder["reminder_at"])
        delay = max(
            0.0,
            (reminderAt - discord.utils.utcnow()).total_seconds(),
        )
        await asyncio.sleep(delay)

        while reminderId in self.reminders:
            try:
                user = self.bot.get_user(reminder["user_id"])
                if user is None:
                    user = await self.bot.fetch_user(reminder["user_id"])
                await user.send(
                        view=ReminderDeliveryView(
                            self.imageUrl, reminder["message"], self.embedColor
                        ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.Forbidden:
                logger.warning(
                    "Could not DM reminder %s to user %s; their DMs may be closed",
                    reminderId,
                    reminder["user_id"],
                )
                self._remove_reminder(reminderId)
                return
            except discord.NotFound:
                logger.warning(
                    "Could not find user %s for reminder %s",
                    reminder["user_id"],
                    reminderId,
                )
                self._remove_reminder(reminderId)
                return
            except discord.HTTPException:
                logger.exception(
                    "Could not send reminder %s to user %s; retrying in one minute",
                    reminderId,
                    reminder["user_id"],
                )
                await asyncio.sleep(60)
                continue

            try:
                self._remove_reminder(reminderId)
            except OSError:
                logger.exception(
                    "Reminder %s was sent but could not be removed from %s",
                    reminderId,
                    reminderListPath,
                )
            return

    @remindersGroup.command(name="add", description="Set a reminder for yourself")
    @appCommands.describe(
        message="What to remind you about; use \\n to add a new line",
        time="When to remind you, e.g. 30m, 2h, or 1d 2h",
    )
    async def remind_me(
        self, interaction: discord.Interaction, message: str, time: str
    ) -> None:
        try:
            duration = parse_duration(time)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        message = message.replace("\\n", "\n").strip()
        if not message:
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> The reminder message cannot be empty.", ephemeral=True
            )
            return
        if len(message) > maxReminderMessageLength:
            await interaction.response.send_message(
                f"<:XXsmallBoldIcon:1572022926251925545> Reminder messages must be {maxReminderMessageLength} characters or fewer.",
                ephemeral=True,
            )
            return

        userReminders = [
            reminder
            for reminder in self.reminders.values()
            if reminder["user_id"] == interaction.user.id
        ]
        if len(userReminders) >= maxRemindersPerUser:
            await interaction.response.send_message(
                f"<:XXsmallBoldIcon:1572022926251925545> You can have up to {maxRemindersPerUser} active reminders.",
                ephemeral=True,
            )
            return

        reminderId = uuid.uuid4().hex[:8]
        while reminderId in self.reminders:
            reminderId = uuid.uuid4().hex[:8]

        reminderAt = discord.utils.utcnow() + duration
        reminder = {
            "id": reminderId,
            "user_id": interaction.user.id,
            "message": message,
            "reminder_at": reminderAt.isoformat(),
        }
        updated = {**self.reminders, reminderId: reminder}
        try:
            self._save_reminders(updated)
        except OSError:
            logger.exception("Could not save reminder %s", reminderId)
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> The reminder could not be saved. Contact a bot developer.",
                ephemeral=True,
            )
            return

        self._schedule_reminder(reminder)
        await interaction.response.send_message(
            f"Reminder `{reminderId}` set for {discord.utils.format_dt(reminderAt, style='F')} "
            f"({discord.utils.format_dt(reminderAt, style='R')}).",
            ephemeral=True,
        )

    @remindersGroup.command(
        name="list", description="List your active reminders"
    )
    async def remind_list(self, interaction: discord.Interaction) -> None:
        reminders = sorted(
            (
                reminder
                for reminder in self.reminders.values()
                if reminder["user_id"] == interaction.user.id
            ),
            key=lambda reminder: reminder["reminder_at"],
        )
        if not reminders:
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> You don't have any active reminders.", ephemeral=True
            )
            return

        lines = []
        for reminder in reminders:
            reminderAt = parse_reminder_time(reminder["reminder_at"])
            timestamp = int(reminderAt.timestamp())
            message = reminder["message"].replace("\n", " | ")
            lines.append(
                f"{message} - `{reminder['id']}` - <t:{timestamp}:F> (<t:{timestamp}:R>)"
            )

        pages = []
        currentPage = f"**<:TimerIcon:1572022924590850078> Your reminders ({len(reminders)}):**\n\n"
        for line in lines:
            if len(currentPage) + len(line) + 1 > listPageLength:
                pages.append(currentPage)
                currentPage = ""
            currentPage += f"{line}\n"
        if currentPage:
            pages.append(currentPage)

        allowedMentions = discord.AllowedMentions.none()
        await interaction.response.send_message(
            pages[0], ephemeral=True, allowed_mentions=allowedMentions
        )
        for page in pages[1:]:
            await interaction.followup.send(
                page, ephemeral=True, allowed_mentions=allowedMentions
            )

    @remindersGroup.command(
        name="remove", description="Remove one of your active reminders"
    )
    @appCommands.rename(reminderId="reminder_id")
    @appCommands.describe(reminderId="ID shown by /reminders list")
    async def remove_reminder(
        self, interaction: discord.Interaction, reminderId: str
    ) -> None:
        reminderId = reminderId.strip().lower()
        reminder = self.reminders.get(reminderId)
        if reminder is None or reminder["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> That reminder ID was not found in your active reminders.",
                ephemeral=True,
            )
            return

        try:
            self._remove_reminder(reminderId)
        except OSError:
            logger.exception("Could not remove reminder %s", reminderId)
            await interaction.response.send_message(
                "<:XXsmallBoldIcon:1572022926251925545> This reminder could not be removed. Contact a bot developer.",
                ephemeral=True,
            )
            return

        task = self.tasks.get(reminderId)
        if task is not None:
            task.cancel()
        await interaction.response.send_message(
            f"<:CircleCheckIcon:1572022898825232574> Reminder `{reminderId}` removed.",
            ephemeral=True,
        )

    @remindersGroup.command(
        name="clear", description="Clear all of your active reminders"
    )
    async def clear_reminders(self, interaction: discord.Interaction) -> None:
        reminders = sorted(
            (
                reminder
                for reminder in self.reminders.values()
                if reminder["user_id"] == interaction.user.id
            ),
            key=lambda reminder: reminder["reminder_at"],
        )
        if not reminders:
            await interaction.response.send_message(
                view=ReminderStatusView(
                    "<:CircleCheckIcon:1572022898825232574> No reminders to clear",
                    "<:CircleCheckIcon:1572022898825232574> You don't have any active reminders.",
                    self.embedColor,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            view=ReminderClearConfirmationView(self, interaction, reminders),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersCog(bot))
