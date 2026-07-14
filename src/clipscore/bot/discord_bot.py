"""Thin discord.py adapter. Manual-acceptance: needs a real token/channel/network.
All decision logic lives in bot.notify/dispatch (CI-tested); this only bridges to
Discord and schedules jobs. Discord failures must never break ingest/scoring.

IMPORTANT: `discord` / `discord.app_commands` are imported lazily, inside
build_bot(), NOT at module top level. This lets tests (and any environment
without discord.py installed) import DiscordNotifier from this module without
requiring the discord.py package.
"""
import asyncio
import structlog
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from clipscore.config import get_settings
from clipscore.bot.dispatch import poll_and_alert, dispatch_summary
from clipscore.jobs.rank import ranked_rows
from clipscore.bot.messages import format_top

log = structlog.get_logger()


class DiscordNotifier:
    """Notifier that posts to a discord.TextChannel from a sync scheduler thread."""

    def __init__(self, channel, loop):
        self._channel = channel
        self._loop = loop

    def send(self, text: str) -> None:
        if self._channel is None or self._loop is None:
            log.info("discord_notifier_noop", reason="no channel configured")
            return
        asyncio.run_coroutine_threadsafe(self._channel.send(text), self._loop)


def build_bot(session_factory):
    """Assemble the discord.py client, /top command, and scheduler. Returns (client,
    scheduler). Not exercised in CI — see manual acceptance."""
    import discord
    from discord import app_commands

    settings = get_settings()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    sched = BackgroundScheduler()

    @tree.command(name="top", description="Top campaigns by within-niche screening percentile")
    async def top(interaction, niche: str | None = None):
        await interaction.response.defer()   # 3s ACK; ranked_rows may be slow as scores grow
        with session_factory() as s:
            text = format_top(ranked_rows(s, top=10, niche=niche), niche)
        await interaction.followup.send(text)

    @client.event
    async def on_ready():
        await tree.sync()
        channel = client.get_channel(settings.discord_alert_channel_id) if settings.discord_alert_channel_id else None
        notifier = DiscordNotifier(channel=channel, loop=asyncio.get_running_loop())

        def poll_job():
            with session_factory() as s:
                poll_and_alert(s, notifier)

        def summary_job():
            with session_factory() as s:
                dispatch_summary(s, notifier)

        sched.add_job(poll_job, "interval", minutes=settings.poll_interval_minutes, id="poll_alert")
        sched.add_job(summary_job, CronTrigger(hour=settings.summary_hour_et,
                      timezone=ZoneInfo("America/New_York")), id="daily_summary")
        sched.start()
        log.info("bot_ready", channel=settings.discord_alert_channel_id)

    return client, sched


def run_bot(session_factory):
    client, _ = build_bot(session_factory)
    client.run(get_settings().discord_token)
