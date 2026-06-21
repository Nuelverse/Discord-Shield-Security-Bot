import asyncio
import discord
from discord.ext import commands
import json
import os
from dotenv import load_dotenv
import db_handler

# py-cord calls asyncio.get_event_loop() at init time, which raises on Python 3.10+
# when no loop exists yet. Create one explicitly before instantiating the bot.
asyncio.set_event_loop(asyncio.new_event_loop())

load_dotenv()

with open('./config.json', 'r') as f:
    config = json.load(f)

COGS = [
    'cogs.core',           # 2FA setup, verify, reset-user
    'cogs.link_filter',    # Link scanning + allow-link, remove-link, toggle-linkfilter
    'cogs.webhooks',       # Webhook protection + allow-webhook
    'cogs.panic',          # /panic, /recover, DM trigger
    'cogs.announcements',  # /announce
    'cogs.admin',          # add/remove managers, setup-guild, list, set-logs
    'cogs.moderation',     # role, bulk-role, export, channel utilities
    'cogs.audit',          # Message deletion/edit logging
    'cogs.embeds',         # /embed send, edit, delete, list
    'cogs.name_filter',    # /name-filter add, import, remove, list, test, set-action, cleanse
]


class SecurityBot(discord.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        intents.webhooks = True
        intents.scheduled_events = True
        intents.messages = True
        intents.message_content = True  # Privileged — must be enabled in Dev Portal
        debug_guild = int(os.getenv('DEBUG_GUILD_ID', 0)) or None
        super().__init__(intents=intents, debug_guilds=[debug_guild] if debug_guild else None)
        self.config = config
        self.master_user = int(os.getenv('MASTER_USER_ID'))
        self.CONN = None
        self.deleted_by_filter = set()  # message IDs deleted by link filter — suppresses audit double-log

    async def on_ready(self):
        # Ensure the data directory exists for QR code PNGs
        os.makedirs('./data', exist_ok=True)

        self.CONN = db_handler.startup_db()
        if self.CONN is None:
            print("FATAL: Could not connect to database. Shutting down.")
            await self.close()
            return
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f'Guilds: {len(self.guilds)}')
        print(f'Master User ID: {self.master_user}')
        print('----------------------------------')


bot = SecurityBot()

for cog in COGS:
    bot.load_extension(cog)


@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(
            f"This command is on cooldown. Try again in **{error.retry_after:.0f}s**.",
            ephemeral=True
        )
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.respond("I am missing permissions to do that.", ephemeral=True)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.respond("You do not have permission to use this command.", ephemeral=True)
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.respond("This command can only be used in a server.", ephemeral=True)
    else:
        print(f"[ERROR] Unhandled error in /{ctx.command}: {type(error).__name__}: {error}")
        try:
            await ctx.respond("An unexpected error occurred. Please try again.", ephemeral=True)
        except Exception:  # nosec B110 — ctx may be expired; silently drop
            pass


if __name__ == '__main__':
    token = os.getenv('BOT_TOKEN')
    if not token:
        print("FATAL: BOT_TOKEN not set in .env")
    else:
        import time
        delay = 10
        for attempt in range(1, 6):
            try:
                bot.run(token)
                break
            except discord.errors.HTTPException as e:
                if e.status == 429:
                    print(f"[WARN] Rate limited by Discord on startup (attempt {attempt}/5). Retrying in {delay}s...")
                    time.sleep(delay)
                    delay = min(delay * 2, 300)
                else:
                    raise
