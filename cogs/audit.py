"""
Audit Log — logs deleted/edited messages and member bans to the guild log channel.

Events handled:
  on_message_delete  →  embed with author, channel, message ID, and content
  on_message_edit    →  embed with author, channel, before/after content diff, jump link
  on_member_ban      →  embed with banned user, responsible mod, and audit-log reason

Note: Discord only provides message content from its internal cache.
Messages sent before the bot started (or in large guilds where the cache
is evicted) will show "(not cached)" for the content.
"""

import asyncio

import discord
from discord.ext import commands
import db_handler


class AuditLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_log_ch(self, guild_id: int):
        log_id = db_handler.get_log_channel(self.bot.CONN, guild_id)
        return self.bot.get_channel(log_id) if log_id else None

    async def _safe_send(self, channel, **kwargs):
        if channel is None:
            return
        try:
            await channel.send(**kwargs)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ------------------------------------------------------------------
    # Deleted messages
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # Suppressed — link filter already logged this deletion specifically
        if message.id in self.bot.deleted_by_filter:
            self.bot.deleted_by_filter.discard(message.id)
            return
        if not db_handler.check_guild(self.bot.CONN, message.guild.id):
            return
        log_ch = self._get_log_ch(message.guild.id)
        if not log_ch:
            return

        embed = discord.Embed(title="Message Deleted", color=0xe74c3c)
        embed.add_field(
            name="Channel",
            value=f"{message.channel.mention} | `{message.channel.id}`",
            inline=False,
        )
        embed.add_field(name="Message ID", value=f"`{message.id}`", inline=True)
        embed.add_field(
            name="Author",
            value=f"{message.author.mention} | `{message.author.id}`",
            inline=False,
        )

        content = message.content or ""
        if content:
            # Truncate — Discord embed field cap is 1024 chars
            display = content[:950]
            if len(content) > 950:
                display += f"\n… ({len(content) - 950} chars truncated)"
            embed.add_field(name="Content", value=f"```{display}```", inline=False)
        else:
            embed.add_field(name="Content", value="*(empty or not cached)*", inline=False)

        if message.attachments:
            embed.add_field(
                name="Attachments",
                value="\n".join(a.filename for a in message.attachments),
                inline=False,
            )

        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Guild: {message.guild.name}")
        await self._safe_send(log_ch, embed=embed)

    # ------------------------------------------------------------------
    # Edited messages
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # Skip if only an embed was loaded (Discord auto-fetches OG tags)
        if before.content == after.content:
            return
        if after.author.bot or not after.guild:
            return
        # Yield briefly so the link filter can run its edit handler first.
        # If it catches the URL it will mark the ID; we skip to avoid double-logging.
        await asyncio.sleep(0.2)
        if after.id in self.bot.deleted_by_filter:
            # The delete event will clean up the set — don't discard here
            return
        if not db_handler.check_guild(self.bot.CONN, after.guild.id):
            return
        log_ch = self._get_log_ch(after.guild.id)
        if not log_ch:
            return

        embed = discord.Embed(title="Message Edited", color=0xf39c12)
        embed.add_field(
            name="Author",
            value=f"{after.author.mention} | `{after.author.id}`",
            inline=False,
        )
        embed.add_field(
            name="Channel",
            value=f"{after.channel.mention} | `{after.channel.id}`",
            inline=False,
        )

        before_text = (before.content or "*(empty)*")[:512]
        after_text = (after.content or "*(empty)*")[:512]
        embed.add_field(name="Before", value=f"```{before_text}```", inline=False)
        embed.add_field(name="After", value=f"```{after_text}```", inline=False)
        embed.add_field(
            name="Jump to Message",
            value=f"[Go to message]({after.jump_url})",
            inline=False,
        )

        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Message ID: {after.id}")
        await self._safe_send(log_ch, embed=embed)

    # ------------------------------------------------------------------
    # Member banned
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if not db_handler.check_guild(self.bot.CONN, guild.id):
            return
        log_ch = self._get_log_ch(guild.id)
        if not log_ch:
            return

        # Brief wait so Discord's audit log has time to populate
        await asyncio.sleep(1)

        moderator = "Unknown"
        reason    = "No reason provided"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    moderator = f"{entry.user.mention} | `{entry.user.id}`"
                    if entry.reason:
                        reason = entry.reason
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass

        # If the ban was issued by the bot itself (name filter / panic), skip —
        # those actions already produce their own detailed log entry.
        if moderator != "Unknown" and f"`{self.bot.user.id}`" in moderator:
            return

        embed = discord.Embed(title="Member Banned", color=0xe74c3c)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="Banned User",
            value=f"{user.mention} | `{user.id}`",
            inline=False,
        )
        embed.add_field(name="Username", value=str(user), inline=True)
        embed.add_field(name="Banned By", value=moderator, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Guild: {guild.name}")
        await self._safe_send(log_ch, embed=embed)


def setup(bot):
    bot.add_cog(AuditLog(bot))
