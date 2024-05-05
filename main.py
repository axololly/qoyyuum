import discord, asqlite
from discord.ext import commands

class DiscordBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix = '?',
            intents = discord.Intents.all()
        )

    async def setup_hook(self):
        self.pool = await asqlite.create_pool('timezones.sql')
        await self.load_extension('timezones')

bot = DiscordBot()

bot.run(open('token.txt').read())