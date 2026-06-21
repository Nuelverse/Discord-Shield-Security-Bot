"""
Name Filter — block users whose username or nickname matches configured patterns.

Commands (all under /name-filter):
  /name-filter add phrase <pattern>      Add a single phrase (substring) filter
  /name-filter add regex <pattern>       Add a single regex pattern filter
  /name-filter import phrase             Paste 50+ phrase filters at once via modal
  /name-filter import regex              Paste 50+ regex filters at once via modal
  /name-filter remove <id>               Remove a filter by its ID
  /name-filter list [page]               Browse all active filters, 10 per page
  /name-filter test <name>               Check if a name would be caught
  /name-filter set-action <action>       Configure what happens on a match (ban/kick/timeout)
  /name-filter cleanse                   Retroactively scan all current members

Triggers:
  - on_member_join       — username and display name checked immediately on join
  - on_member_update     — nickname changes checked in real time
  - on_user_update       — global username changes checked across all shared guilds

Exempt from filtering:
  - Bots
  - Bot master user (MASTER_USER_ID)
  - Trusted members (announcers) registered in the guild

Default action: ban. Configurable per guild via /name-filter set-action.
"""

import asyncio
import re
from datetime import timedelta

import discord
from discord.ext import commands
from discord.commands import Option

import db_handler
import logger
import permissions
import two_factor_helper


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match(filters: list, name: str):
    """
    Check `name` against every filter in the list.
    Returns (matched_filter_dict, name) on first match, or (None, None).
    Silently skips filters with broken regex rather than crashing.
    """
    for f in filters:
        try:
            if f['type'] == 'phrase':
                if f['pattern'].lower() in name.lower():
                    return f, name
            else:
                if re.search(f['pattern'], name):
                    return f, name
        except re.error:
            pass
    return None, None


def _is_exempt(bot, guild: discord.Guild, member_id: int) -> bool:
    """
    Return True if this member should be skipped by the name filter.
    Exempt: bot master, server owner, announcers, link managers.
    """
    if member_id == bot.master_user:
        return True
    if member_id == guild.owner_id:
        return True
    if db_handler.check_authorised(bot.CONN, (guild.id, member_id)):
        return True
    if db_handler.is_link_manager(bot.CONN, guild.id, member_id):
        return True
    return False


def _account_age_str(member: discord.Member) -> str:
    """Human-readable account age string."""
    now = discord.utils.utcnow()
    delta = now - member.created_at
    days = delta.days
    if days < 1:
        hours = delta.seconds // 3600
        return f"{hours} hour(s) old — **very new account**"
    if days < 7:
        return f"{days} day(s) old — **recently created**"
    if days < 30:
        return f"{days} days old"
    months = days // 30
    rem = days % 30
    return f"{months} month(s), {rem} day(s) old"


async def _take_action(
    bot,
    guild: discord.Guild,
    member: discord.Member,
    action: str,
    matched_filter: dict,
    matched_name: str,
    trigger: str,
):
    """
    Apply the configured action to the member and send a richly detailed
    log entry explaining exactly what happened and why.
    """
    filter_type_label = "Phrase (exact substring)" if matched_filter['type'] == 'phrase' else "Regex (pattern match)"

    # Build the audit-log reason string (appears in Discord's audit log)
    audit_reason = (
        f"[Name Filter] {trigger} — "
        f"[{matched_filter['type'].upper()}] `{matched_filter['pattern']}` "
        f"matched name: {matched_name!r}"
    )

    action_taken_label = "Unknown"
    action_level = 'critical'

    try:
        if action == 'kick':
            await member.kick(reason=audit_reason)
            action_taken_label = "Kicked from server"
            action_level = 'warning'
        elif action.startswith('timeout:'):
            hours = int(action.split(':', 1)[1])
            until = discord.utils.utcnow() + timedelta(hours=hours)
            await member.timeout(until, reason=audit_reason)
            action_taken_label = f"Timed out for {hours} hour(s)"
            action_level = 'warning'
        else:
            # Default: ban
            await member.ban(reason=audit_reason, delete_message_days=0)
            action_taken_label = "Permanently banned from server"
    except discord.Forbidden:
        action_taken_label = "Action FAILED — bot lacks permission (check role hierarchy)"
        action_level = 'error'
    except discord.HTTPException as exc:
        action_taken_label = f"Action FAILED — {exc}"
        action_level = 'error'

    # -----------------------------------------------------------------------
    # Send a descriptive log embed so moderators understand exactly what
    # happened, which rule was broken, and why the bot acted.
    # -----------------------------------------------------------------------
    await logger.log_action(
        bot,
        guild,
        f"Name Filter — {action_taken_label.split()[0].title()}ed",
        member,
        details={
            "Matched Name":    f"`{matched_name}`",
            "Name Type":       trigger,
            "Blocked Pattern": f"`{matched_filter['pattern']}`  (ID: {matched_filter['id']})",
            "Filter Type":     filter_type_label,
            "Action Taken":    action_taken_label,
            "Account Age":     _account_age_str(member),
            "Why":             (
                "This member's name matched a pattern your moderation team "
                "configured to block impersonators, fake support/staff accounts, "
                "scam bots, or other deceptive usernames. The filter triggered "
                f"automatically because `{matched_name}` satisfied the rule."
            ),
        },
        level=action_level,
    )


# ---------------------------------------------------------------------------
# Bulk import modal
# ---------------------------------------------------------------------------

class BulkImportModal(discord.ui.Modal):
    def __init__(self, bot, guild_id: int, guild: discord.Guild, actor, filter_type: str):
        super().__init__(title=f"Import {filter_type.title()} Filters")
        self.bot         = bot
        self.guild_id    = guild_id
        self.guild       = guild
        self.actor       = actor
        self.filter_type = filter_type

        if filter_type == 'phrase':
            hint = "support\nmetamask\nofficial\nadmin\ncustomer service\nverification"
        else:
            hint = "(?i)metamask\n(?i)^admin\n(?i) support$\n(?i)official\n(?i)^mod"

        self.add_item(discord.ui.InputText(
            label=f"{filter_type.title()} filters — one per line",
            style=discord.InputTextStyle.paragraph,
            placeholder=hint,
            required=True,
            max_length=4000,
        ))

    async def callback(self, interaction: discord.Interaction):
        raw      = self.children[0].value
        patterns = [line.strip() for line in raw.splitlines() if line.strip()]

        if not patterns:
            await interaction.response.send_message("No patterns found in input.", ephemeral=True)
            return

        added           = 0
        skipped_dup     = 0
        skipped_invalid = 0
        bad_patterns    = []

        for pattern in patterns:
            # Validate regex before inserting
            if self.filter_type == 'regex':
                try:
                    re.compile(pattern)
                except re.error as exc:
                    skipped_invalid += 1
                    bad_patterns.append(f"`{pattern[:50]}` — {exc}")
                    continue

            ok = db_handler.insert_name_filter(
                self.bot.CONN, self.guild_id, self.filter_type, pattern, interaction.user.id
            )
            if ok:
                added += 1
            else:
                skipped_dup += 1

        # Build feedback message
        lines = [f"**{added}** {self.filter_type} filter(s) added successfully."]
        if skipped_dup:
            lines.append(f"**{skipped_dup}** skipped — already exist in this server.")
        if skipped_invalid:
            lines.append(f"**{skipped_invalid}** skipped — invalid regex syntax:")
            for bp in bad_patterns[:5]:
                lines.append(f"  • {bp}")
            if len(bad_patterns) > 5:
                lines.append(f"  … and {len(bad_patterns) - 5} more.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        if added > 0:
            await logger.log_action(
                self.bot, self.guild,
                "Name Filters Bulk Imported",
                self.actor,
                details={
                    "Filter Type": self.filter_type.title(),
                    "Added":       str(added),
                    "Duplicates":  str(skipped_dup),
                    "Invalid":     str(skipped_invalid),
                },
                level='info',
            )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class NameFilter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    nf        = discord.SlashCommandGroup("name-filter",  "Manage name-based security filters")
    nf_add    = nf.create_subgroup("add",    "Add a single filter")
    nf_import = nf.create_subgroup("import", "Bulk import filters via modal")

    # ------------------------------------------------------------------
    # /name-filter add phrase
    # ------------------------------------------------------------------

    @nf_add.command(
        name="phrase",
        description="Add a single phrase filter. Blocks any name containing this text (case-insensitive).",
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def add_phrase(
        self,
        ctx: discord.ApplicationContext,
        pattern: Option(str, "Keyword or phrase to block", required=True),
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        ok = db_handler.insert_name_filter(self.bot.CONN, ctx.guild.id, 'phrase', pattern, ctx.author.id)
        if not ok:
            await ctx.respond(f"Phrase filter `{pattern}` already exists.", ephemeral=True)
            return
        await ctx.respond(f"Phrase filter added: `{pattern}`", ephemeral=True)
        await logger.log_action(
            self.bot, ctx.guild, "Name Filter Added", ctx.author,
            details={"Type": "Phrase", "Pattern": f"`{pattern}`"},
            level='info',
        )

    # ------------------------------------------------------------------
    # /name-filter add regex
    # ------------------------------------------------------------------

    @nf_add.command(
        name="regex",
        description="Add a regex pattern filter. Use (?i) prefix for case-insensitive matching.",
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def add_regex(
        self,
        ctx: discord.ApplicationContext,
        pattern: Option(str, "Regex pattern (Python re syntax)", required=True),
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        try:
            re.compile(pattern)
        except re.error as exc:
            await ctx.respond(f"Invalid regex pattern: `{exc}`", ephemeral=True)
            return

        ok = db_handler.insert_name_filter(self.bot.CONN, ctx.guild.id, 'regex', pattern, ctx.author.id)
        if not ok:
            await ctx.respond(f"Regex filter `{pattern}` already exists.", ephemeral=True)
            return
        await ctx.respond(f"Regex filter added: `{pattern}`", ephemeral=True)
        await logger.log_action(
            self.bot, ctx.guild, "Name Filter Added", ctx.author,
            details={"Type": "Regex", "Pattern": f"`{pattern}`"},
            level='info',
        )

    # ------------------------------------------------------------------
    # /name-filter import phrase
    # ------------------------------------------------------------------

    @nf_import.command(
        name="phrase",
        description="Open a modal and paste up to 100+ phrase filters at once — one per line. Requires 2FA.",
    )
    async def import_phrase(
        self,
        ctx: discord.ApplicationContext,
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return
        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return
        await ctx.send_modal(
            BulkImportModal(self.bot, ctx.guild.id, ctx.guild, ctx.author, 'phrase')
        )

    # ------------------------------------------------------------------
    # /name-filter import regex
    # ------------------------------------------------------------------

    @nf_import.command(
        name="regex",
        description="Open a modal and paste up to 100+ regex filters at once — one per line. Requires 2FA.",
    )
    async def import_regex(
        self,
        ctx: discord.ApplicationContext,
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return
        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return
        await ctx.send_modal(
            BulkImportModal(self.bot, ctx.guild.id, ctx.guild, ctx.author, 'regex')
        )

    # ------------------------------------------------------------------
    # /name-filter remove
    # ------------------------------------------------------------------

    @nf.command(
        name="remove",
        description="Remove a filter by its ID. Find IDs with /name-filter list. Requires 2FA.",
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def remove_filter(
        self,
        ctx: discord.ApplicationContext,
        filter_id: Option(int, "Filter ID shown in /name-filter list", required=True),
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        # Fetch before deleting so we can log the pattern
        filters = db_handler.get_name_filters(self.bot.CONN, ctx.guild.id)
        target  = next((f for f in filters if f['id'] == filter_id), None)

        removed = db_handler.delete_name_filter(self.bot.CONN, ctx.guild.id, filter_id)
        if not removed:
            await ctx.respond(
                f"No filter with ID `{filter_id}` found in this server. "
                "Use `/name-filter list` to see valid IDs.",
                ephemeral=True,
            )
            return

        pattern_info = f"`{target['pattern']}`" if target else f"ID {filter_id}"
        await ctx.respond(f"Filter removed: {pattern_info}", ephemeral=True)
        await logger.log_action(
            self.bot, ctx.guild, "Name Filter Removed", ctx.author,
            details={
                "Filter ID": str(filter_id),
                "Pattern":   f"`{target['pattern']}`" if target else "—",
                "Type":      target['type'].title() if target else "—",
            },
            level='warning',
        )

    # ------------------------------------------------------------------
    # /name-filter list
    # ------------------------------------------------------------------

    @nf.command(
        name="list",
        description="Post all active name filters to the log channel (regex first, then phrase).",
    )
    async def list_filters(
        self,
        ctx: discord.ApplicationContext,
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        filters = db_handler.get_name_filters(self.bot.CONN, ctx.guild.id)
        if not filters:
            await ctx.respond(
                "No name filters configured yet.\n"
                "Use `/name-filter add phrase` or `/name-filter import phrase` to get started.",
                ephemeral=True,
            )
            return

        log_ch = logger.get_log_channel(self.bot, ctx.guild)
        if not log_ch:
            await ctx.respond("No log channel configured. Run `/set-logs` first.", ephemeral=True)
            return

        action = db_handler.get_name_filter_action(self.bot.CONN, ctx.guild.id)
        if action.startswith('timeout:'):
            hours        = action.split(':', 1)[1]
            action_label = f"Timeout ({hours}h)"
        else:
            action_label = action.title()

        regex_filters  = [f for f in filters if f['type'] == 'regex']
        phrase_filters = [f for f in filters if f['type'] == 'phrase']

        async def send_block(header: str, items: list):
            """Send items as one or more copyable code blocks, splitting at 1800 chars."""
            lines = [f['pattern'] for f in items]
            chunks = []
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > 1800:
                    chunks.append(current)
                    current = line
                else:
                    current = f"{current}\n{line}" if current else line
            if current:
                chunks.append(current)

            first = True
            for chunk in chunks:
                title_part = header if first else f"{header} (cont.)"
                await log_ch.send(f"**{title_part}**\n```\n{chunk}\n```")
                first = False

        # Summary header embed
        summary = discord.Embed(
            title=f"Name Filter List — {ctx.guild.name}",
            description=(
                f"**{len(filters)}** filter(s) active • "
                f"**{len(regex_filters)}** regex • "
                f"**{len(phrase_filters)}** phrase\n"
                f"Action on match: **{action_label}**\n"
                f"Requested by {ctx.author.mention}"
            ),
            color=0x5865F2,
            timestamp=discord.utils.utcnow(),
        )
        await log_ch.send(embed=summary)

        if regex_filters:
            await send_block(f"REGEX FILTERS ({len(regex_filters)})", regex_filters)
        if phrase_filters:
            await send_block(f"PHRASE FILTERS ({len(phrase_filters)})", phrase_filters)

        await ctx.respond(
            f"Filter list posted to {log_ch.mention} — "
            f"**{len(regex_filters)}** regex, **{len(phrase_filters)}** phrase.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /name-filter test
    # ------------------------------------------------------------------

    @nf.command(
        name="test",
        description="Check whether a specific name would be caught by any active filter.",
    )
    async def test_filter(
        self,
        ctx: discord.ApplicationContext,
        name: Option(str, "The username or nickname to test", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        filters = db_handler.get_name_filters(self.bot.CONN, ctx.guild.id)
        if not filters:
            await ctx.respond("No filters configured — nothing to test against.", ephemeral=True)
            return

        matched_filter, _ = _match(filters, name)
        if matched_filter:
            ftype = "Phrase" if matched_filter['type'] == 'phrase' else "Regex"
            await ctx.respond(
                f"**Match found** for `{name}`\n"
                f"Filter `#{matched_filter['id']}` [{ftype}]: `{matched_filter['pattern']}`\n"
                f"This name **would be actioned** if a real member used it.",
                ephemeral=True,
            )
        else:
            await ctx.respond(
                f"**No match** — `{name}` passes all {len(filters)} active filter(s).",
                ephemeral=True,
            )

    # ------------------------------------------------------------------
    # /name-filter set-action
    # ------------------------------------------------------------------

    @nf.command(
        name="set-action",
        description="Configure what the bot does when a name filter is triggered. Requires 2FA.",
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def set_action(
        self,
        ctx: discord.ApplicationContext,
        action: Option(
            str,
            "Action to take on a match",
            choices=['ban', 'kick', 'timeout'],
            required=True,
        ),
        code: Option(int, "Your 6-digit 2FA code", required=True),
        timeout_hours: Option(
            int,
            "Hours to timeout for (only applies when action=timeout, default 24)",
            required=False,
            default=24,
            min_value=1,
            max_value=672,
        ),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        stored = f"timeout:{timeout_hours}" if action == 'timeout' else action
        db_handler.set_name_filter_action(self.bot.CONN, ctx.guild.id, stored)

        label = f"Timeout ({timeout_hours}h)" if action == 'timeout' else action.title()
        await ctx.respond(
            f"Name filter action updated to **{label}**.\n"
            f"All future filter matches will result in: **{label}**.",
            ephemeral=True,
        )
        await logger.log_action(
            self.bot, ctx.guild, "Name Filter Action Changed", ctx.author,
            details={"New Action": label},
            level='info',
        )

    # ------------------------------------------------------------------
    # /name-filter cleanse
    # ------------------------------------------------------------------

    @nf.command(
        name="cleanse",
        description="Scan every current member against all active filters and action matches. Requires 2FA.",
    )
    @commands.cooldown(1, 300, commands.BucketType.guild)
    async def cleanse(
        self,
        ctx: discord.ApplicationContext,
        code: Option(int, "Your 6-digit 2FA code", required=True),
    ):
        allowed, err = permissions.check(self.bot, ctx, 'announcer')
        if not allowed:
            await ctx.respond(err, ephemeral=True)
            return
        ok2, err2 = permissions.guild_required(self.bot, ctx)
        if not ok2:
            await ctx.respond(err2, ephemeral=True)
            return

        if not two_factor_helper.verify_code(self.bot.CONN, ctx.author.id, code):
            await ctx.respond("Incorrect 2FA code.", ephemeral=True)
            return

        filters = db_handler.get_name_filters(self.bot.CONN, ctx.guild.id)
        if not filters:
            await ctx.respond(
                "No filters configured. Add some with `/name-filter add` or `/name-filter import` first.",
                ephemeral=True,
            )
            return

        await ctx.defer(ephemeral=True)

        action   = db_handler.get_name_filter_action(self.bot.CONN, ctx.guild.id)
        actioned = 0
        failed   = 0
        skipped  = 0

        for member in list(ctx.guild.members):
            if member.bot:
                continue
            if _is_exempt(self.bot, ctx.guild, member.id):
                skipped += 1
                continue

            # Check username first, then nickname
            matched_filter, matched_name = _match(filters, member.name)
            trigger = "Cleanse scan — username"

            if not matched_filter and member.nick:
                matched_filter, matched_name = _match(filters, member.nick)
                trigger = "Cleanse scan — nickname"

            if matched_filter:
                try:
                    await _take_action(
                        self.bot, ctx.guild, member, action,
                        matched_filter, matched_name, trigger,
                    )
                    actioned += 1
                except Exception:
                    failed += 1
                # Brief pause between actions to avoid Discord rate limiting
                await asyncio.sleep(0.75)

        if action.startswith('timeout:'):
            hours        = action.split(':', 1)[1]
            action_label = f"Timeout ({hours}h)"
        else:
            action_label = action.title()

        await ctx.followup.send(
            f"**Cleanse complete.**\n"
            f"**{actioned}** member(s) actioned ({action_label}) • "
            f"**{skipped}** exempt • "
            f"**{failed}** failed\n"
            f"Filters checked: **{len(filters)}** • "
            f"Full details logged to your log channel.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # Event: member joins
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        if not db_handler.check_guild(self.bot.CONN, guild.id):
            return
        if _is_exempt(self.bot, guild, member.id):
            return

        filters = db_handler.get_name_filters(self.bot.CONN, guild.id)
        if not filters:
            return

        # Check username
        matched_filter, matched_name = _match(filters, member.name)
        trigger = "Joined server — username"

        # Also check display name if it differs (e.g. global display name set)
        if not matched_filter and member.display_name != member.name:
            matched_filter, matched_name = _match(filters, member.display_name)
            trigger = "Joined server — display name"

        if matched_filter:
            action = db_handler.get_name_filter_action(self.bot.CONN, guild.id)
            await _take_action(self.bot, guild, member, action, matched_filter, matched_name, trigger)

    # ------------------------------------------------------------------
    # Event: nickname change within the server
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        # Only care about nickname changes
        if before.nick == after.nick:
            return
        # Nickname was removed — not a threat
        if not after.nick:
            return

        guild = after.guild
        if not db_handler.check_guild(self.bot.CONN, guild.id):
            return
        if _is_exempt(self.bot, guild, after.id):
            return

        filters = db_handler.get_name_filters(self.bot.CONN, guild.id)
        if not filters:
            return

        matched_filter, matched_name = _match(filters, after.nick)
        if matched_filter:
            action = db_handler.get_name_filter_action(self.bot.CONN, guild.id)
            await _take_action(
                self.bot, guild, after, action,
                matched_filter, matched_name, "Changed their server nickname",
            )

    # ------------------------------------------------------------------
    # Event: global username change
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        # Only care about name changes
        if before.name == after.name:
            return

        # Check the new username against every guild the bot shares with this user
        for guild in self.bot.guilds:
            if not db_handler.check_guild(self.bot.CONN, guild.id):
                continue
            member = guild.get_member(after.id)
            if not member or member.bot:
                continue
            if _is_exempt(self.bot, guild, member.id):
                continue

            filters = db_handler.get_name_filters(self.bot.CONN, guild.id)
            if not filters:
                continue

            matched_filter, matched_name = _match(filters, after.name)
            if matched_filter:
                action = db_handler.get_name_filter_action(self.bot.CONN, guild.id)
                await _take_action(
                    self.bot, guild, member, action,
                    matched_filter, matched_name, "Changed their global Discord username",
                )


def setup(bot):
    bot.add_cog(NameFilter(bot))
