import discord, asqlite, traceback
from discord.ext import commands
import os

TOKEN = os.getenv("TOKEN")

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

@bot.command()
async def sync(ctx):
    try:
        synced = await bot.tree.sync()
    except:
        embed = discord.Embed(
            name = "Oh No!",
            description = "Looks like something went wrong. Take a peek below.",
            color = discord.Color.red()
        )
        embed.add_field(
            name = "Error",
            value = f"```py\n{traceback.format_exc()}\n```"
        )
    else:
        embed = discord.Embed(
            name = "Success!",
            description = f"Successfully synced {len(synced)} commands.",
            color = discord.Color.green()
        )
        embed.add_field(
            name = "Commands Synced",
            value = "\n".join([f'- {cmd.name}' for cmd in synced])
        )
    finally:
        await ctx.reply(embed = embed)

if os.path.isfile('token.txt'):
  bot.run(open('token.txt').read())
bot.run(TOKEN)
