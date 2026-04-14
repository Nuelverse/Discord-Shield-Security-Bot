"""
Webhook Protection — automatically deletes unauthorized webhooks.

Webhook protection is ON by default when a guild is set up.

Commands:
  /allow-webhook code:<2FA>  — Bot owner: temporarily disable protection for 30 minutes
                               to allow legitimate webhook creation.

The on_webhooks_update listener checks both the permanent DB flag and the
temporary disable window before deciding to delete a webhook.
"""

import discord
from discord.ext import commands, tasks
from discord.commands import Option
from datetime import datetime, timedelta
import time
import db_handler
import two_factor_helper
import permissions
import logger


class Webhooks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_temp_disables.start()

    def cog_unload(self):
        self.check_temp_disables.cancel()

    # ------------------------------------------------------------------
    # Background task: re-enable protection when 30-min window expires
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def check_temp_disables(self):
        for guild in self.bot.guilds:
            if not db_handler.check_guild(self.bot.CONN, guild.id):
                continue
            expires_str = db_handler.get_webhook_temp_disable(self.bot.CONN, guild.id)
            if expires_str is None:
                continue
            try:
                expires_at = datetime.fromisoformat(expires_str)
            except ValueError:
                db_handler.clear_webhook_temp_disable(self.bot.CONN, guild.id)
                continue
            if datetime.utcnow() >= expires_at:
                db_handler.clear_webhook_temp_disable(self.bot.CONN, guild.id)
                log_ch = logger.get_log_channel(self.bot, guild)
                embed = discord.Embed(
                    title="Webhook Protection Re-enabled",
                    description="The 30-minute webhook allow window has expired. Protection is active again.",
                    color=0x2ecc71,
                    timestamp=datetime.utcnow()
                )
                await logger.safe_send(log_ch, embed=embed)

    @check_temp_disables.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_log_embed(self, color: int, user, channel, action: str) -> discord.Embed:
        embed = discord.Embed(title="Webhook Event", color=color, timestamp=datetime.utcnow())
        embed.add_field(
            name="Created By",
            value=f"{user.name} ({user.id})" if user else "Unknown",
            inline=False
        )
        embed.add_field(name="Channel", value=channel.mention, inline=False)
        embed.add_field(name="Action", value=action, inline=False)
        embed.set_footer(text=f"Guild: {channel.guild.name}")
        return embed

    # ------------------------------------------------------------------
    # on_webhooks_update — core protection listener
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_webhooks_update")
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild

        if not db_handler.check_guild(self.bot.CONN, guild.id):
            return

        # Check if permanently disabled
        if not db_handler.check_webhook(self.bot.CONN, guild.id):
            return

        # Check if temporarily disabled (allow window active)
        expires_str = db_handler.get_webhook_temp_disable(self.bot.CONN, guild.id)
        if expires_str:
            try:
                if datetime.utcnow() < datetime.fromisoformat(expires_str):
                    log_ch = logger.get_log_channel(self.bot, guild)
                    await logger.safe_send(log_ch, embed=self._build_log_embed(
                        0x3498db, None, channel,
                        "Webhook created during allow window — allowed."
                    ))
                    return
            except ValueError:
                pass

        log_ch = logger.get_log_channel(self.bot, guild)

        try:
            webhooks = await channel.webhooks()
        except discord.Forbidden:
            await logger.safe_send(log_ch, embed=self._build_log_embed(
                0xe74c3c, None, channel,
                "Could not fetch webhooks — missing permissions."
            ))
            return

        if not webhooks:
            return

        recent = webhooks[-1]

        # Only process webhooks created within the last 120 seconds
        if recent.created_at.timestamp() < (time.time() - 120):
            return

        # Ignore channel follows (Discord-native, not user-created)
        if recent.type == discord.WebhookType.channel_follower:
            return

        # Allow verified-bot webhooks if the bypass is enabled
        if db_handler.check_verified_bots(self.bot.CONN, guild.id):
            if recent.user and recent.user.public_flags.verified_bot:
                await logger.safe_send(log_ch, embed=self._build_log_embed(
                    0x2ecc71, recent.user, channel,
                    "Verified bot webhook — allowed (bypass enabled)."
                ))
                return

        try:
            await recent.delete(reason="Webhook protection enabled.")
        except discord.Forbidden:
            await logger.safe_send(log_ch, embed=self._build_log_embed(
                0xe74c3c, recent.user if recent.user else None, channel,
                "Failed to delete webhook — missing permissions."
            ))
            return

        await logger.safe_send(log_ch, embed=self._build_log_embed(
            0xf1c40f,
            recent.user if recent.user else None,
            channel,
            f"Unauthorized webhook deleted (ID: {recent.id})."
        ))

    # ------------------------------------------------------------------
    # /allow-webhook  (bot owner + 2FA)
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.slash_command(
        name="allow-webhook",
        description="[Bot Owner] Temporarily disable webhook protection for 30 minutes. Requires 2FA."
    )
    async def allow_webhook(self, ctx: discord.ApplicationContext,
                            code: Option(int, "Your 6-digit 2FA code", required=True)):
        allowed, err = permissions.check(self.bot, ctx, 'bot_owner')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return

        ok, err2 = permissions.guild_required(self.bot, ctx)
        if not ok:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        expires_at = datetime.utcnow() + timedelta(minutes=30)
        db_handler.set_webhook_temp_disable(
            self.bot.CONN, ctx.guild.id, ctx.author.id, expires_at.isoformat()
        )

        await ctx.respond(
            f"Webhook protection suspended for **30 minutes** (until "
            f"<t:{int(expires_at.timestamp())}:t>). "
            "Add your webhook(s) now. Protection will resume automatically.",
            ephemeral=True
        )
        await logger.log_action(
            self.bot, ctx.guild, "Webhook Protection Temporarily Disabled", ctx.author,
            details={
                "Duration": "30 minutes",
                "Expires": f"<t:{int(expires_at.timestamp())}:f>",
            },
            level='warning'
        )


def setup(bot):
    bot.add_cog(Webhooks(bot))
