"""
Core — 2FA registration, verification, and account recovery.

Commands:
  /create-2fa   — Generate QR code and backup codes (available to registered users,
                  server owners, and bot owner).
  /verify       — Confirm the TOTP pairing.
  /reset-user   — Bot owner or server owner: wipe a user's 2FA so they can re-register.

DM recovery:
  Users who lose their authenticator can DM the bot:
    recover <backup_code>
  This consumes one backup code and wipes the 2FA so /create-2fa can be run again.
"""

import os
import discord
from discord.ext import commands, tasks
from discord.commands import Option
import db_handler
import two_factor_helper
import permissions
import logger


class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.delete_pngs.start()

    def cog_unload(self):
        self.delete_pngs.cancel()

    # ------------------------------------------------------------------
    # Background task: purge QR code PNGs every minute
    # ------------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def delete_pngs(self):
        data_dir = './data/'
        if not os.path.isdir(data_dir):
            return
        for f in os.listdir(data_dir):
            if f.endswith('.png'):
                try:
                    os.remove(os.path.join(data_dir, f))
                except OSError:
                    pass

    @delete_pngs.before_loop
    async def before_delete_pngs(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # /create-2fa
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.slash_command(
        name="create-2fa",
        description="Set up 2FA for your account. Required before using your designated commands."
    )
    async def create_2fa(self, ctx: discord.ApplicationContext):
        if not permissions.can_setup_2fa(self.bot, ctx):
            await ctx.respond(
                "You are not registered in this server. "
                "Contact the server owner or bot owner to be added as an announcer or link manager.",
                ephemeral=True
            )
            return

        user_id = ctx.author.id

        if db_handler.check_user(self.bot.CONN, user_id):
            if db_handler.check_verified(self.bot.CONN, user_id) == 1:
                await ctx.respond(
                    "You already have 2FA set up. If you lost access to your authenticator, "
                    "DM the bot: `recover <backup_code>` (uses one backup code), "
                    "or ask an admin to run `/reset-user` for you.",
                    ephemeral=True
                )
            else:
                await ctx.respond(
                    "You have a pending 2FA setup. Run `/verify code:<6-digit-code>` to complete it.",
                    ephemeral=True
                )
            return

        png_path, secret = two_factor_helper.setup_and_get_path(ctx, self.bot.CONN)
        backup_codes = two_factor_helper.generate_backup_codes(self.bot.CONN, user_id)
        codes_block = "\n".join(backup_codes)

        await ctx.respond(
            "**2FA Setup — PolyMock Security Bot**\n\n"
            "1. Open **Authy** or **Google Authenticator** — never scan QR codes with Discord mobile.\n"
            "2. Scan the QR code below, or add manually as a **Time-based OTP** using this key:\n"
            f"```{secret}```\n"
            "3. Run `/verify code:<6-digit-code>` to confirm pairing.\n\n"
            "**Backup Codes — save these now, shown once:**\n"
            f"```{codes_block}```\n"
            "Each code is single-use. To use one: DM the bot `recover <code>`.\n\n"
            "This message will be deleted within a minute.",
            file=discord.File(png_path),
            ephemeral=True
        )

        await logger.log_action(
            self.bot, ctx.guild, "2FA Setup Initiated", ctx.author,
            details={"Status": "QR code generated, awaiting /verify"},
            level='info'
        )

    # ------------------------------------------------------------------
    # /verify
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.slash_command(description="Confirm your 2FA pairing with a 6-digit code.")
    async def verify(self, ctx: discord.ApplicationContext,
                     code: Option(int, "6-digit code from your authenticator app", required=True)):
        user_id = ctx.author.id

        if not db_handler.check_user(self.bot.CONN, user_id):
            await ctx.respond("Run `/create-2fa` first to start setup.", ephemeral=True)
            return

        if db_handler.check_verified(self.bot.CONN, user_id) == 1:
            await ctx.respond("Your 2FA is already verified.", ephemeral=True)
            return

        if two_factor_helper.verify_code(self.bot.CONN, user_id, code):
            db_handler.verify(self.bot.CONN, user_id)
            await ctx.respond(
                "2FA verified. You can now use all commands assigned to your role.",
                ephemeral=True
            )
            await logger.log_action(
                self.bot, ctx.guild, "2FA Verified", ctx.author,
                details={"Status": "TOTP pairing confirmed"},
                level='success'
            )
        else:
            await ctx.respond(
                "Incorrect code. Check your authenticator app (codes expire every 30 seconds) "
                "and try again.",
                ephemeral=True
            )

    # ------------------------------------------------------------------
    # /reset-user  (bot owner or server owner + 2FA)
    # ------------------------------------------------------------------

    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.slash_command(
        name="reset-user",
        description="[Owner] Reset a user's 2FA so they can re-register. Requires your 2FA code."
    )
    async def reset_user(self, ctx: discord.ApplicationContext,
                         member: Option(discord.Member, "Member to reset"),
                         code: Option(int, "Your 6-digit 2FA code", required=True)):
        allowed, err = permissions.check(self.bot, ctx, 'owner')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        if not db_handler.check_user(self.bot.CONN, member.id):
            await ctx.respond(f"{member.mention} has no 2FA account to reset.", ephemeral=True)
            return

        db_handler.delete_user(self.bot.CONN, member.id)
        await ctx.respond(
            f"{member.mention}'s 2FA has been reset. They must run `/create-2fa` again.",
            ephemeral=True
        )
        try:
            await member.send(
                f"Your 2FA for **{ctx.guild.name}** has been reset by {ctx.author}. "
                "Please run `/create-2fa` in the server to re-register."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        await logger.log_action(
            self.bot, ctx.guild, "2FA Reset", ctx.author,
            details={"Target": f"{member} ({member.id})", "Action": "2FA account deleted, re-registration required"},
            level='warning'
        )

    # ------------------------------------------------------------------
    # DM-based backup code recovery
    # ------------------------------------------------------------------

    @commands.Cog.listener("on_message")
    async def on_dm_recover(self, message: discord.Message):
        """
        Allows users to recover their 2FA via a backup code sent as a DM.
        Format: recover <backup_code>
        """
        if message.guild is not None or message.author.bot:
            return

        content = message.content.strip()
        if not content.lower().startswith("recover "):
            return

        parts = content.split(None, 1)
        if len(parts) != 2:
            await message.channel.send(
                "Format: `recover <backup_code>`\nExample: `recover 1234-5678`"
            )
            return

        backup_code = parts[1].strip()
        user_id = message.author.id

        if not db_handler.check_user(self.bot.CONN, user_id):
            await message.channel.send(
                "You do not have a 2FA account. No recovery needed."
            )
            return

        if not two_factor_helper.use_backup_code(self.bot.CONN, user_id, backup_code):
            await message.channel.send(
                "Invalid or already-used backup code. "
                "If you have no codes left, contact an admin to run `/reset-user` for you."
            )
            return

        db_handler.delete_user(self.bot.CONN, user_id)
        await message.channel.send(
            "Backup code accepted. Your 2FA has been reset.\n"
            "Go back to the server and run `/create-2fa` to pair a new authenticator."
        )


def setup(bot):
    bot.add_cog(Core(bot))
