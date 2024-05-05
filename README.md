# Timezones Bot

I made a bot to track your timezones and alert users who ping you about their time and timezone (if they have set one) compared to yours.

## How it works

Below, I go through my entire process of creating this bot. From start to finish.
I hope you enjoy your read! :D

## Step 1: Listening for Messages
Using the power of `on_message` listeners, we can measure how active a channel's chat is. As a baseline, I have chosen to use 20 messages per minute (1 message every 3 seconds) as a benchmark for an active chat. We first start with a task loop and an `on_message` listener to count the number of messages in a minute:
```python
class Timezones(...):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        ...
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
class Timezones(...):
    def __init__(self, bot):
        self.bot = bot
        self.pool = bot.pool
        ...
        self.messages_per_minute = 0

    @commands.Cog.listener('on_message')
    async def message_counter(self, message):
        if not message.guild:
            return
        
        self.messages_per_minute += 1
```

The `guild` attribute of our message object can either be in two types: a `Guild` instance or a `NoneType`. We can check for this `NoneType` with an `if not ...` check, and by returning if it's true, any private messages do not pass this first layer and get kicked out immediately.

However, messages in guilds pass this check, and of course, all messages in all channels in all guilds is **not** what we want to happen. So to counter this, we need to centralise the scope of our search, and we can do this with an SQL table. So for this, we can create a `messages` table to count all messages in all channes in all servers and measure activity that way.
```sql
CREATE TABLE IF NOT EXISTS messages (
    guild_id INTEGER NOT NULL UNIQUE,
    channel_id INTEGER NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0
);
```

As you can see, we have a `guild_id` column for a guild ID, a `channel_id` column for a channel ID and a count to represent the number of messages sent in that channel. This is a lot more reliable than the scope of our previous search.


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

The guilds table is necessary for performing lookups and paginating the results.