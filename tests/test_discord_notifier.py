from unittest.mock import MagicMock, patch
from clipscore.bot.discord_bot import DiscordNotifier


def test_notifier_schedules_channel_send():
    channel = MagicMock()
    loop = MagicMock()
    n = DiscordNotifier(channel=channel, loop=loop)
    with patch("clipscore.bot.discord_bot.asyncio.run_coroutine_threadsafe") as rct:
        n.send("hello")
    channel.send.assert_called_once_with("hello")
    rct.assert_called_once()   # coroutine handed to the bot's event loop


def test_notifier_noop_without_channel():
    # graceful: no channel configured -> send is a logged no-op, never raises
    DiscordNotifier(channel=None, loop=None).send("hi")
