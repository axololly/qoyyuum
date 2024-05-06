import discord, asqlite, time, re
from discord import app_commands, Interaction, ui, ButtonStyle as BS, utils
from discord.ext import commands, tasks
from datetime import datetime as dt, timedelta as td
from typing import Mapping

class ConfirmTimezone(ui.View):
    def __init__(self, user: discord.Member, timezone: int, formatted_timezone: str):
        super().__init__(timeout = 25)
        self.user = user
        self.timezone = timezone
        self.formatted_timezone = formatted_timezone

    async def disable_items(self):
        for item in self.children:
            item.disabled = True
    
    async def on_timeout(self) -> None:
        await self.disable_items()

        await self.message.edit(
            embed = discord.Embed(
                title = "Timed Out",
                description = '~~' + self.message.embeds[0].description + '~~',
                color = discord.Color.red()
            )
        )

    @ui.button(label = 'Yes', style = BS.green)
    async def yes(self, interaction: Interaction, _):
        async with self.cog.pool.acquire() as conn:
            await conn.execute("INSERT INTO timezones (user_id, utc_diff) VALUES (?, ?)", (self.user.id, self.timezone))
        
        await interaction.response.edit_message(
            ephemeral = True, embed = discord.Embed(
                title = "Confirmed Action",
                description = f"Your timezone has now been set to **UTC{self.formatted_timezone}**.",
                color = discord.Color.green()
            )
        )
        self.stop()

    @ui.button(label = 'No', style = BS.red)
    async def no(self, interaction: Interaction, _):
        await interaction.response.edit_message(
            ephemeral = True, embed = discord.Embed(
                title = "Cancelled Action",
                description = "Your timezone has not been set.",
                color = discord.Color.red()
            )
        )
        self.stop()

class Timezones(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asqlite.Pool = bot.pool
    
    def cog_load(self):
        self.users_on_cooldown: Mapping[int, int] = {}

        self.clear_db.start()
    
    def cog_unload(self):
        self.clear_db.cancel()
    
    timezone = app_commands.Group(name = 'timezone', description = 'Set your timezone.')

    @timezone.command(name = 'set', description = 'Set your timezone based on the time for you today.')
    @app_commands.describe(given_time = 'The time for you now, given in HH:MM format.')
    @app_commands.rename(given_time = 'time')
    async def set_timezone(self, interaction: Interaction, given_time: str):
        try:
            time = re.findall('[1-9][1-9]:[1-9][1-9]', given_time)[0]
        except IndexError:
            await interaction.response.send_message("Invalid time format. Please use the format `HH:MM` and a 24-hour clock.", ephemeral = True)
            return
        
        hours, minutes = time.split(':')

        if 0 <= int(hours) < 24 or 0 <= int(minutes) < 59:
            await interaction.response.send_message("Invalid time format. Please use the format `HH:MM` and a 24-hour clock.", ephemeral = True)
            return

        if int(minutes) != dt.now().minute:
            await interaction.response.send_message("You can only set your timezone based on the current time. The minutes value given is incorrect.", ephemeral = True)
            return
        
        async with self.pool.acquire() as conn:
            req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (interaction.user.id,))
            row = await req.fetchone()
        
        if row:
            await interaction.response.send_message(
                ephemeral = True, embed = discord.Embed(
                    description = "You already have a timezone set. If you want to change it, please remove it first.",
                    color = discord.Color.red()
                )
            )
            return

        timezone = int(time.split(':')[0]) - dt.now().hour
        formatted_tz = f'+{timezone}' if timezone > 0 else timezone
        confirmation = ConfirmTimezone(interaction.user, timezone, formatted_tz)
        
        await interaction.response.send_message(
            embed = discord.Embed(
                title = "Confirm Timezone",
                description = f"Are you sure you want to set your timezone to `UTC{formatted_tz}`?",
                color = discord.Color.dark_embed()
            ),
            ephemeral = True,
            view = confirmation
        )
    
    @timezone.command(name = 'remove', description = 'Remove your timezone.')
    async def remove_timezone(self, interaction: Interaction):
        async with self.pool.acquire() as conn:
            req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (interaction.user.id,))
            row = await req.fetchone()
        
        if not row:
            await interaction.response.send_message(
                ephemeral = True, embed = discord.Embed(
                    description = "You don't have a timezone set.",
                    color = discord.Color.red()
                )
            )
            return
        
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM timezones WHERE user_id = ?", (interaction.user.id,))
        
        await interaction.response.send_message(
            ephemeral = True, embed = discord.Embed(
                description = "Your timezone has been removed.",
                color = discord.Color.green()
            )
        )

    @commands.Cog.listener('on_message')
    async def check_messages_per_minute(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        try:
            self.clear_db.start()
        except RuntimeError:
            pass
        
        async with self.pool.acquire() as conn:
            await conn.execute("""INSERT INTO messages (guild_id, channel_id) VALUES (?, ?)
                                  ON CONFLICT (guild_id, channel_id) DO SET count = count + 1"""
                                  (message.guild.id, message.channel.id)
                              )

            req = await conn.execute("SELECT * FROM cooldowns WHERE user_id = ?", (message.author.id,))
            row = await req.fetchone()

            if row:
                return
            
            await conn.execute("INSERT INTO cooldowns (user_id, cooldown) VALUES (?, ?)", (message.author.id, int(time.time()) + 15 * 60))

            self.update_cooldowns.restart()

        try:
            mention = re.findall("<@!?([0-9]+)>", message.content)[0]
        except IndexError:
            return
        
        userID = int(mention[2:-1])
        
        embed = discord.Embed(
            title = "Their Timezone",
            description = "Just to let you know:\n",
            color = discord.Color.dark_embed()
        )
        
        async with self.pool.acquire() as conn:
            req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (userID,))
            their_timezone_data = await req.fetchone()

            if not their_timezone_data:
                return
            
            their_tz = their_timezone_data['utc_diff']
            their_datetime = dt.now() + td(hours = their_tz)
            
            embed.description += f"- {mention}'s time is {utils.format_dt(their_datetime, style = 'f')} and their timezone is `UTC{f'+{their_tz}' if their_tz > 0 else their_tz}`\n"

            req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (message.author.id,))
            your_timezone_data = await req.fetchone()

            if your_timezone_data:
                return

            your_tz = your_timezone_data['utc_diff']
            your_datetime = dt.now() + td(hours = your_tz)
            
            embed.description += f"- {mention}'s time is {utils.format_dt(your_datetime, style = 'f')} and their timezone is `UTC{f'+{your_tz}' if your_tz > 0 else your_tz}`\n"
        
        embed.add_field(
            name = "Time Difference",
            value = f"You are {abs(your_tz - their_tz)} hours ahead of {mention}." if your_tz - their_tz > 0 else f"{mention} is {abs(your_tz - their_tz)} hours ahead of you."
        )
        embed.add_field(
            name = "Extra Information",
            value = f"\nIf you want to set your timezone, use `/timezone set`.\nIf you want to remove your timezone, use `/timezone remove`."
        )

        try:
            await message.reply(embed = embed)
        except:
            pass
        else:
            async with self.pool.acquire() as conn:
                await conn.execute("INSERT INTO cooldowns (user_id, ending_at) VALUES (?, ?)", (message.author.id, int(time.time()) + 15 * 60))

    @tasks.loop(minutes = 1)
    async def clear_db(self):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM messages")

            req = await conn.execute("SELECT changes()")
            row = await req.fetchone()
        
        changes = row['changes()']

        if changes == 0:
            self.clear_db.cancel()
    
    @tasks.loop()
    async def update_cooldowns(self):
        async with self.pool.acquire() as conn:
            req = await conn.execute("SELECT * FROM cooldowns LIMIT 1")
            row = await req.fetchone()
        
        if not row:
            self.update_cooldowns.cancel()
        
        await utils.sleep_until(row['cooldown'])

        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM cooldowns WHERE user_id = ?", (row['user_id'],))


async def setup(bot):
    await bot.add_cog(Timezones(bot))

if __name__ == '__main__':
    import main