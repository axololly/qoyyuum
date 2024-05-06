# Timezones Bot

I made a bot to track your timezones and alert users who ping you about their time and timezone (if they have set one) compared to yours.

## Reader's Notice
Some of the things in this README will not be reflected in the file it's referencing. This is because I realised some things _after_ finishing everything. The changes will be updated soon. :D

## How it works
Below, I go through my entire process of creating this bot. From start to finish.
I hope you enjoy your read! :D

## Step 1: Listening for Messages
Using the power of `on_message` listeners, we can measure how active a channel's chat is. As a baseline, I have chosen to use 20 messages per minute (1 message every 3 seconds) as a benchmark for an active chat. We first start with a task loop and an `on_message` listener to count the number of messages in a minute:
```python
from discord.ext import commands

class Timezones(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        
        self.messages_per_minute = 0

    @commands.Cog.listener('on_message')
    async def message_counter(self, message):
        self.messages_per_minute += 1
```

### Our first problems
Now, this doesn't just count messages in a channel, but it counts _every_ message sent that the bot can "see". This includes:
- other channels
- other servers
- private messages

We can easily include in our cog message listener to ignore messages from private messages, since those would have also counted towards the total, and below is how we do this.
```python
from discord.ext import commands

class Timezones(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        
        self.messages_per_minute = 0

    @commands.Cog.listener('on_message')
    async def message_counter(self, message):
        if not message.guild:
            return
        
        self.messages_per_minute += 1
```

The `guild` attribute of our message object can either be in two types: a `Guild` instance or a `NoneType`. We can check for this `NoneType` with an `if not ` check, and by returning if it's true, any private messages do not pass this first layer and get kicked out immediately.

However, messages in guilds pass this check, and of course, all messages in all channels in all guilds is **not** what we want to happen. So to counter this, we need to centralise the scope of our search, and we can do this with an SQL table. So for this, we can create a `messages` table to count all messages in all channes in all servers and measure activity that way.
```sql
CREATE TABLE IF NOT EXISTS messages (
    guild_id INTEGER NOT NULL UNIQUE,
    channel_id INTEGER NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, channel_id)
);
```

As you can see, we have:
- a `guild_id` column for a guild ID
- a `channel_id` column for a channel ID
- a `count` to represent the number of messages sent in that channel

This is a lot more reliable than the scope of our previous search, and the `PRIMARY KEY` will be very helpful for upserting into the table with one SQL transaction. We've also given `count` a default, meaning we don't need to specify a number when inserting.

### Rectifying our first problems
We can now include in our message listener to update our database based on message activity, as follows.
```python
from discord import Message
from discord.ext import commands

class Timezones(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool

    @commands.Cog.listener('on_message')
    async def message_counter(self, message: Message):
        if not message.guild:
            return
        
        async with self.pool.acquire() as conn:
            await conn.execute("""INSERT INTO messages (guild_id, channel_id) VALUES (?, ?)
                                  ON CONFLICT (guild_id, channel_id) DO SET count = count + 1"""
                                  (message.guild.id, message.channel.id)
                              )
```

Using Rapptz's [asqlite wrapper](https://github.com/Rapptz/asqlite), we acquire a connection from the connection pool and use that to run our SQL transaction. In the transaction, we try to insert a new row with the guild and channel IDs of the `Message` object, and when this fails due to our `PRIMARY KEY` that only lets us have one copy of the data, we can update the row blocking us from inserting and raise the count by 1.

This SQL table change also means we can remove that variable.

### "To infinity and beyond!"
In case you didn't notice, we never reset our message counters, so effectively, all we've done is just "all messages sent from here, here and here, since this time". We need to reset our counts every minute and we can do this by deleting all the rows in the table. The reason we delete the rows from the table instead of resetting them all to zero, is that if a channel is deleted or a guild is deleted, the rows will still remain there, creating "ghost logs" of channels / guilds that don't exist.

We can make use of discord.py's `tasks` module, which lets us loop in the background and clear the database every minute, as follows.
```python
from discord.ext import tasks

@tasks.loop(minutes = 1)
async def clear_db(self):
    async with self.pool.acquire() as conn:
        await conn.execute("DELETE FROM messages")
```

And integrating with the rest of the code:
```python
from discord import Message
from discord.ext import commands, tasks

class Timezones(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool

    @commands.Cog.listener('on_message')
    async def message_counter(self, message: Message):
        if not message.guild:
            return
        
        async with self.pool.acquire() as conn:
            await conn.execute("""INSERT INTO messages (guild_id, channel_id) VALUES (?, ?)
                                  ON CONFLICT (guild_id, channel_id) DO SET count = count + 1"""
                                  (message.guild.id, message.channel.id)
                              )
    
    @tasks.loop(minutes = 1)
    async def clear_db(self):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM messages")
```

### Loop cancelling
Just in case the database is empty and no messages are sent for over an hour, we can add an extra query after deleting all the messages to see how many changes we've made to the database. Using the `changes()` function in SQLite, we can do exactly that, and this can go neatly under the "delete all messages" line.
```python
    @tasks.loop(minutes = 1)
    async def clear_db(self):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM messages")

            req = await conn.execute("SELECT changes()")
            row = await conn.fetchone()
        
        changes = row['changes()']
        
        if changes == 0:
            self.clear_db.stop()
```
If there are no changes then stop the loop and don't keep clearing the database. The changes() function returns the number of times these operations have been performed on the transaction directly before:
- inserting records into the database
- updating records in the database
- deleting records from the database

Because we've just run a "delete all records" statement, the only actions that the function can count are deleting records, so we can get the number of records we've deleted from the database. If that number is 0, then stop the loop.

### Listening for Mentions
We can use regex (regular expressions) on the message content to check if any users have been pinged in the message. When this happens, we can get the user from the ID in the mention and then get the user from the message object's guild by performing first, a get request (getting the information from cache) and if that returns `None`, perform a fetch request (using an API call) and if that raises any errors, just stop the command there.
```python
import re

mentions = re.findall("<@!?([0-9]+)>", message.content)

try:
    user = await message.guild.get_member(mentions[0][2:-1]) or self.bot.fetch_user(mentions[0][2:-1])
except:
    return
```

We don't need an error check for list indexing on an empty list because the unscoped `except` section catches that for us.

Again, we take the first mention found in this list (although we could combine the final embed into a group of embeds or a paginator for each user) and then find the user associated with the ID in that mention.

### Small Oversight
I use a get-then-fetch for the user as a central point for an ID and a mention, but the mention is literally already given to you and the same with the ID, which was a bit of an oversight and definitely something I should have cut out, but I'll do it later. :trollface:

### Getting the Timezone Data
To create the embed with the timezone information for the message author and the person mentioned, we must query the database for timezone data twice: once for us and once for the person mentioned. However, instead of searching for us _first_, we'll search for us _second_, and the reason for that is because if they don't have timezone data, telling us what the time is becomes pretty pointless. If they don't have timezone data, we can stop the command there and not waste time trying to get our own timezone info.
```python
async with self.pool.acquire() as conn:
    req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (user.id,))
    their_timezone_data = await req.fetchone()

    if not their_timezone_data:
        return
```

If they _do_ end up having timezone data, we can then try to get our own.
```python
async with self.pool.acquire() as conn:
    ...
    req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (message.author.id,))
    your_timezone_data = await req.fetchone()

    if not your_timezone_data:
        return
```

### Creating the Finished Embed
Before the timezone data retrieval from the database, we can create an embed to start with.
```python
embed = discord.Embed(
    title = "Their Timezone",
    description = "Just to let you know:\n",
    color = discord.Color.dark_embed()
)
```
We end the embed's description with a new line character because we'll be adding onto it with each piece of data we retrieve, provided we receive both of them.

Upon receiving the new data, we can add it to the embed like this. Below is for the author's timezone info:
```python
your_tz = your_timezone_data['utc_diff']
your_datetime = dt.now() + td(hours = your_tz)

embed.description += f"- {user.mention}'s time is {utils.format_dt(your_datetime, style = 'f')} and their timezone is `UTC{f'+{your_tz}' if your_tz > 0 else your_tz}`\n"
```

We can then add two fields to the embed, one for mentioning the time difference and another for mentioning "extra information", which is basically how to set your own timezone.

```python
embed.add_field(
    name = "Time Difference",
    value = f"You are {abs(your_tz - their_tz)} hours ahead of {user.mention}." if your_tz - their_tz > 0 else f"{user.mention} is {abs(your_tz - their_tz)} hours ahead of you."
)
embed.add_field(
    name = "Extra Information",
    value = f"\nIf you want to set your timezone, use `/timezone set`.\nIf you want to remove your timezone, use `/timezone remove`."
)
```

Then, send a reply and return if any exceptions arise.
```python
try:
    await message.reply(embed = embed)
except:
    pass
```

We can use `pass` instead of `return` because it's the end of the command anyway.


## Step 2: Setting Timezones
Now that we have a way to measure channel activity, we need to add the main feature of the bot: displaying other user's timezones when they get mentioned.

Firstly, we need a new database table to hold our user IDs and the user's timezone, which we do as follows.
```sql
CREATE TABLE IF NOT EXISTS timezones (
    user_id INTEGER NOT NULL UNIQUE,
    utc_diff INTEGER NOT NULL DEFAULT 0
);
```

### User Experience
This table will have a unique user ID and the user's corresponding timezone. But asking people for their timezone feels like it will (and probably does) end up deprecating UX (user-experience), so for a more user-friendly experience, we can ask them the time instead, which is:
- easily accessible (look at the top of your screen, or turn your phone on)
- better well-known (I mean, who _doesn't_ know the time?)
- and, easy to write using the 24-hour format (HH:MM - no need for seconds)

### Slash commands or prefix commands?
We'll use slash commands for this, due to their (what I'll call) sectioned arguments. In prefix commands, all arguments (without quotation marks) are interpreted as only one "word", so think of it like the whole message content has been split by spaces. To get more than one word, you can either:
- a. use quotation marks
- b. use an asterisk and have every word after that grouped as one argument

However, in slash commands, you can have more than one word in an argument by standard. It's also quite UI-friendly, being a part of Discord itself, instead of sending messages. This is personally why I'll use slash commands for this.

The slash command is as follows.
```python
from discord import Interaction, app_commands
from discord.ext import commands

class Timezones(commands.Cog):
    ...
    
    timezone = app_commands.Group(name = 'timezone', description = 'A bunch of commands about timezones.')

    @timezone.command(name = 'set')
    async def set_timezone(self, interaction: Interaction, given_time: str):
        ...
```

To centralise our timezone commands, we can use an app commands group, which means our commands will be ran as `/timezone something`. For the `set` command, it gets run as `/timezone set <given_time>`.

But using arguments with a `_` in them doesn't sound very practical if we're caring about UX like I was mentioning earlier. Luckily for us, we can include a decorator that lets us rename an argument in code to a different name on the Discord side of things, which is what we can do to rename "given_time" to just "time".
```python
from discord import Interaction, app_commands
from discord.ext import commands

class Timezones(commands.Cog):
    ...
    
    timezone = app_commands.Group(name = 'timezone', description = 'A bunch of commands about timezones.')

    @timezone.command(name = 'set')
    @app_commands.rename(given_time = 'time')
    async def set_timezone(self, interaction: Interaction, given_time: str):
        ...
```

And for clarity's sake, we'll add a description for `given_time`.
```python
from discord import Interaction, app_commands
from discord.ext import commands

class Timezones(commands.Cog):
    ...
    
    timezone = app_commands.Group(name = 'timezone', description = 'A bunch of commands about timezones.')

    @timezone.command(name = 'set')
    @app_commands.rename(given_time = 'time')
    @app_commands.describe(given_time = 'The time for you now, given in HH:MM format.')
    async def set_timezone(self, interaction: Interaction, given_time: str):
        ...
```

### Time for Regular Expressions
To get the time in the `time` argument of our slash command, we can use regex. It's a simple `[0-9][0-9]:[0-9][0-9]` and works perfectly fine for obtaining a proper time.
```python
import re

time = re.findall('[0-9][0-9]:[0-9][0-9]')[0]
```
`re.findall(...)` returns a list of matches. We only want the first match, so we can index that list by using `[0]`.

However, a problem arises when there isn't a match at all. In this case, we would be indexing an empty list, which would raise an `IndexError` and stop the command from running entirely.

We can catch this exception using a `try-except` block around the indexing.
```python
try:
    time = re.findall('[0-9][0-9]:[0-9][0-9]')[0]
except IndexError:
    await interaction.response.send_message(
        "You've given an invalid time format! Use the format `HH:MM` when you run this command.",
        ephemeral = True
    )
    return
```
We try to match the given string with regex and then get the first match (in case they did something like `12:45:11`), and when that fails, we notify the user they gave an incorrect time format and stop the command there.

### "Hey mate, what's the time?"
Currently, users can input whatever time they feel like. `99:99` is as valid a time as `37:18`. We can split our regex match by the `:` character, which separates the string into the hours part and the minutes part.
```python
hours, minutes = time.split(':')
```

This is very easy. And then to check that the time is valid:
```python
if int(hours) not in range(24):
    await interaction.response.send_message(
        "You've given an invalid time format! Use the format `HH:MM` when you run this command.",
        ephemeral = True
    )
    return
```

We can take advantage of the fact that Python ranges typically start at 0 (when not specified) and end before the number given. This means we can do `range(24)`, which returns the numbers 0 to 23 (the only valid numbers for times - 24 becomes 0 again).

We need to call `int()` on the values because:
- a. they're still strings
- b. 00 is not a valid number

If the hours part _fails_ these checks, we can alert the user and stop the command there.

Next, we need to handle the minutes. Differing timezones means that the hours will be different, _not the minutes._ This is one way we can tell if somebody is telling the truth or not. We can check if the minutes given match up to the minutes at the time the command was run, like this:
```python
from datetime import datetime as dt

if int(minutes) != dt.now().minute:
    await interaction.response.send_message(
        "You've given an invalid time format! Use the format `HH:MM` when you run this command.",
        ephemeral = True
    )
    return
```

`dt.now()` gives us the current datetime (date and time) of right now (or at that point in time when the command was run). This `datetime.datetime` has an attribute called `minute` which gives us the minutes part of the datetime now. Since the minutes don't change, everywhere in the world will have the same minutes.

### More User Experience Ranting
Say you run the command and `dt.now().minute` ends up being 1 minute ago. This means the command would bounce, and you'd have to write it again, right? Well, we can change it from being exactly those minutes to being _approximately_ those minutes. Call it a 5-minute range, which we can check like this:
```python
mins_now = dt.now().minute

if not mins_now - 5 <= int(minutes) <= mins_now + 5:
    await interaction.response.send_message(
        "You've given an invalid time format! Use the format `HH:MM` when you run this command.",
        ephemeral = True
    )
    return
```

We store the minutes now as a variable to avoid multiple calls (and for cleanliness), then check if the minutes given are within 5 minutes before and 5 minutes after.

### I'm gonna cry. (Even More UX Ranting)
Turns out the 5-minute range _could_ carry over from say 12:58pm as the lower end and 13:06pm as the upper end, but this wouldn't be reflected in code as in code, the values would be from 58 to 68, which makes no sense. Because of this reason, I'm gonna revert those changes and keep it the way I had before.

### Confirmation Menu
When setting the timezone, we can watch out for any human mistakes with a confirmation menu. This is standard if you use `discord.py` but I'll explain it regardless.
```python
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
```

Basically, we have a view with two buttons: "Yes" in green, and "No" in red. They do exactly what you think they will do - one confirms the action; the other cancels it. When we confirm, we insert into the database a new record containing the person's user ID and UTC offset.


## Step 3: Removing Timezones
Now that you have your timezone, say you move across the world from Newfoundland, Canada to London, UK. You have now gone from UTC-6 to UTC+1, but the bot won't reflect those changes. This is Discord after all. You've probably already been doxxed before.

For this, we need a timezone removing command. And we can do exactly that.

### Removing Timezones in SQL
In SQL, we can remove timezones with the following transaction:
```sql
DELETE FROM messages;
```
And in Python, it's the same:
```python
async with self.pool.acquire() as conn:
    await conn.execute("DELETE FROM messages")
```

### Doing this in a command
```
        
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM timezones WHERE user_id = ?", (interaction.user.id,))
        
        await interaction.response.send_message(
            ephemeral = True, embed = discord.Embed(
                description = "Your timezone has been removed.",
                color = discord.Color.green()
            )
        )
```

We first check for a row in our database that has our user's timezone attached to them.
```python
from discord import app_commands, Interaction
from discord.ext import commands

class Timezones(commands.Cog):
    ...
    @timezone.command(name = 'remove', description = 'Remove your timezone.')
    async def remove_timezone(self, interaction: Interaction):
        async with self.pool.acquire() as conn:
            req = await conn.execute("SELECT * FROM timezones WHERE user_id = ?", (interaction.user.id,))
            row = await req.fetchone()
```

If they don't have one, notify the user and stop the command there.
```python
if not row:
    await interaction.response.send_message(
        ephemeral = True, embed = discord.Embed(
            description = "You don't have a timezone set.",
            color = discord.Color.red()
        )
    )
    return
```

If they _do_ have a timezone in the database, delete it and notify the user it was successful.
```python
    async with self.pool.acquire() as conn:
        ...
        await conn.execute("DELETE FROM timezones WHERE user_id = ?", (interaction.user.id,))
        
        await interaction.response.send_message(
            ephemeral = True, embed = discord.Embed(
                description = "Your timezone has been removed.",
                color = discord.Color.green()
            )
        )
```

## Step 4: Syncing Commands
For syncing commands, I'll use this sync command, made by me:
```python
# in main.py file
import traceback

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
```


## Conclusion
That's literally all the steps you need. Below are dependencies for if you want to host this bot yourself, including all the SQL table creation statements and all the libraries used in this gist.

This took me around 4 hours, and I'm glad you got all this way through my project. It means a lot to me that you got this far, and I hope you enjoy my future writings on future projects. (There's a few cooking up right now!)


## Dependencies

Before you use this bot, you need to run a few things.

First are the following SQL statements. These create the databases the bot is going to be using.
_Note: this bot runs using SQLite._

The first creates the `timezones` table:
```sql
CREATE TABLE IF NOT EXISTS timezones (
    user_id INTEGER NOT NULL UNIQUE,
    utc_diff INTEGER NOT NULL DEFAULT 0
);
```

The second creates the `guilds` table:
```sql
CREATE TABLE IF NOT EXISTS guilds (
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    PRIMARY KEY (user_id, guild_id)
);
```

The third creates the `messages` table, used for counting messages:
```sql
CREATE TABLE IF NOT EXISTS messages (
    guild_id INTEGER NOT NULL UNIQUE,
    channel_id INTEGER NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0
);
```

(The guilds table is necessary for performing lookups and paginating the results.)

Next, you need to install these libraries:
```
discord.py
asqlite
```
