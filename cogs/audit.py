"""
Audit Log — logs ALL deleted and edited messages to the guild log channel.

Events handled:
  on_message_delete  →  embed with author, channel, message ID, and content
  on_message_edit    →  embed with author, channel, before/after content diff, jump link

Note: Discord only provides message content from its internal cache.
Messages sent before the bot started (or in large guilds where the cache
is evicted) will show "(not cached)" for the content.
"""

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


def setup(bot):
    bot.add_cog(AuditLog(bot))
