# Configuring the database
import sqlite3
# Used for deleting the file
import os

# Create the connection
conn = sqlite3.connect('timezones.sql')

# Create the "timezones" table
conn.execute("""
CREATE TABLE IF NOT EXISTS timezones (
    user_id INTEGER NOT NULL UNIQUE,
    utc_diff INTEGER NOT NULL DEFAULT 0
);
""")
conn.commit()

# Create the "messages table"
conn.execute("""
CREATE TABLE IF NOT EXISTS messages (
    guild_id INTEGER NOT NULL UNIQUE,
    channel_id INTEGER NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0
);
""")

# Create the "guilds" table - necessary for pagination.
conn.execute("""
CREATE TABLE IF NOT EXISTS guilds (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);
""")
conn.commit()

# Close the connection
conn.close()

# Delete this file
os.remove(__file__)