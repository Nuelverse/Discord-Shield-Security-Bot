# SecurityBot — Discord Server Security Bot

A production-grade Discord security bot for communities that take their server's safety seriously. SecurityBot combines multi-factor authentication, advanced link scanning, automated name filtering, webhook protection, and full-server panic lockdown — all controlled through a strict 2FA-gated permission hierarchy.

Designed for one server per instance. Easy to self-host. Built with Python + py-cord.

---

## Why SecurityBot?

Most Discord bots treat security as an afterthought. SecurityBot was built security-first:

- **Every sensitive action requires a live 2FA code** — no exceptions.
- **Five-pass link scanner** that catches obfuscated, percent-encoded, markdown-split, and Unicode-spoofed URLs that other bots miss entirely.
- **Name filter** with regex and phrase matching — bans/kicks/timeouts impersonators and fake support accounts automatically on join.
- **Webhook protection** deletes unauthorized webhooks the moment they appear.
- **Panic mode** backs up your entire server's permissions, locks everything down in seconds, and restores from backup on command.
- **Full audit trail** — every state-changing action produces a structured log embed in your designated channel.

---

## Feature Overview

### 2FA Authentication System
- TOTP-based 2FA (compatible with Authy, Google Authenticator, any TOTP app)
- QR code generated on setup, auto-deleted from disk after 60 seconds
- 8 single-use backup codes (SHA-256 hashed — never stored in plaintext)
- DM-based backup code recovery without needing server access
- Per-user 2FA verification state tracked in database

### Permission Hierarchy
```
BOT OWNER (MASTER_USER_ID in .env)
  └── Full access to all commands including /panic and /setup-guild

SERVER OWNER (Discord guild.owner_id)
  └── Full per-server management, same as bot owner except /panic and /setup-guild

LINK MANAGER (added via /add-linkmanager)
  └── Manage the URL whitelist — requires 2FA to be set up and verified

ANNOUNCER (added via /add-announcer)
  └── Post announcements and manage embeds — requires 2FA verified

UNREGISTERED USER
  └── Cannot use any command
```

### Link Scanner — 5-Pass Detection Engine
Runs on every message and every edit. Handles the following evasion techniques:

| Technique | Example |
|---|---|
| Split URL across newlines | `ht\ntp://evil.com` |
| Blockquote-split URL | `> ht\n> tp\n> ://evil.com` |
| Markdown formatting in URL | `https*://*evil.com` |
| Extra/mixed slashes | `https:////\\\\evil.com` |
| Percent-encoded domain | `%68%74%74%70%73://evil.com` |
| Double-encoded domain | `%2568%2574...` |
| Unicode lookalike dots | `evil。com` → `evil.com` |
| Unicode lookalike slashes | `https:⁄⁄evil.com` |
| Unicode lookalike colons | `https：//evil.com` |
| Zero-width / invisible chars | `ev​il.com` |
| Angle bracket wrapping | `<https://evil.com>` |
| Markdown hyperlinks | `[click me](https://evil.com)` |
| Alternative protocols | `ftp://`, `discord://`, `javascript:`, `mailto:`, `tg://` |
| Mixed-case protocols | `dIsCoRd://`, `mAiLtO:` |
| Bare shortener domains | `discord.gg/xxx`, `t.me/xxx`, `bit.ly/xxx` |

Whitelist supports **domain-level** (allows all subdomains) and **exact URL** matching. Channels, categories, roles, and individual users can be fully exempted.

### Name Filter
Automatically acts on members whose username or nickname matches a configured pattern. Fires on join, nickname changes, and global username changes.

- **Phrase filters** — case-insensitive substring match (`support`, `admin`, `metamask`)
- **Regex filters** — full Python regex (`(?i)^mod`, `(?i) support$`)
- **Bulk import** — paste 50+ filters at once via Discord modal
- **Configurable action** — ban (default), kick, or timeout with custom hours
- **Retroactive cleanse** — scan all current members against active filters in one command
- Exempt: bot owner, server owner, announcers, link managers

### Webhook Protection
- Deletes any webhook created without going through the `/allow-webhook` command
- 30-minute temporary allow window when you need to add a legitimate webhook (CI/CD, etc.)
- Always-on by default when the server is set up
- Channel follower webhooks (Discord-native) are never deleted

### Panic Mode
Full server lockdown triggered by bot owner — accessible even via DM if kicked from the server.

**What it does:**
1. Backs up all role permissions and channel overwrites to database
2. Strips dangerous permissions (admin, manage roles, ban, kick, etc.) from all roles
3. Deletes all server webhooks
4. Cancels all scheduled events
5. Locks all channels (denies view + send to @everyone)
6. DMs the server owner
7. Full restore available via `/recover`

Requires: 2FA code + typing `CONFIRM LOCKDOWN` in a modal. No accidental triggers.

### Embed Builder
Send, edit, and delete rich embeds as the bot from within Discord — no dashboard needed.

- Modal-based builder with live preview before posting
- Forum channel support (creates a new thread)
- All embeds tracked in database for future edit/delete
- Supports title, description, custom color, footer, image URL
- 2FA required for all write operations

### Moderation Toolkit
- Role management — toggle, bulk apply, create
- Channel permission management — toggle access, sync category, restrict to single channel
- Thread locking — lock all threads in a channel or server-wide
- Member and role CSV export
- **Permission export** — full colour-coded Excel snapshot of every role's permissions at server level, per category, and per channel
- Channel permission override audit

### Audit Logging
Structured embed logs posted to your configured log channel for every security event:
- Message deletions by link filter (with full message content)
- Link whitelist changes
- Webhook activity
- 2FA events (setup, verify, reset)
- Name filter triggers (includes matched name, pattern, account age, action taken)
- Panic and recover events
- All admin changes (announcers, link managers, channels, timeouts)

---

## Setup

**Requirements:** Python 3.10+ · A Discord bot application with Message Content intent enabled

```bash
# 1. Clone / download the repo
git clone https://github.com/Nuelverse/Discord-Shield-Security-Bot
cd Discord-Shield-Security-Bot

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your values (see below)

# 5. Run
python bot.py
```

---

## Environment Variables

```env
BOT_TOKEN=your_discord_bot_token_here
MASTER_USER_ID=your_discord_user_id_here
DEBUG_GUILD_ID=                    # Optional: instant slash command sync during dev
DATABASE_PATH=database.db          # Optional: override the database file path
```

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Discord Developer Portal → Your App → Bot → Token |
| `MASTER_USER_ID` | Yes | Your Discord user ID — this account has full bot control |
| `DEBUG_GUILD_ID` | No | Guild ID for instant slash command registration during development |
| `DATABASE_PATH` | No | Path to the SQLite database file. Defaults to `database.db` |

> **Changing ownership:** `MASTER_USER_ID` is read from `.env` at startup. Transfer bot control to any Discord user by changing this value — no Discord application ownership transfer needed.

### Discord Developer Portal Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a new application, navigate to **Bot**
3. Enable **Message Content Intent**, **Server Members Intent**, **Presence Intent**
4. Copy the bot token → paste into `.env` as `BOT_TOKEN`
5. Under **OAuth2 → URL Generator**, select scopes: `bot`, `applications.commands`
6. Required bot permissions: `Administrator` (or at minimum: Manage Roles, Manage Channels, Ban Members, Kick Members, Manage Webhooks, Manage Threads, View Audit Log, Read/Send Messages, Embed Links, Attach Files, Manage Messages)

---

## First-Time Server Setup

1. Invite the bot to your server using the OAuth2 URL from the Developer Portal.
2. The **bot owner** (your `MASTER_USER_ID` account) runs `/create-2fa` → scans the QR code → runs `/verify`.
3. Bot owner runs `/setup-guild log_channel:<#channel> announcement_channel:<#channel> code:<2fa>`.
4. Add team members:
   - `/add-linkmanager member:<@user> code:<2fa>` — for link whitelist managers
   - `/add-announcer member:<@user> code:<2fa>` — for announcement posters
5. Each new team member runs `/create-2fa` → scans QR → runs `/verify`.
6. Enable the link filter: `/toggle-linkfilter code:<2fa>`
7. Whitelist any domains your server legitimately uses: `/allow-link type:domain`

---

## 2FA Onboarding Flow

```
Admin runs /add-linkmanager or /add-announcer
  → New member is DM'd with instructions
  → Member runs /create-2fa in the server
      → Bot responds ephemerally with QR code PNG + 8 backup codes (shown once)
      → Member scans QR in Authy / Google Authenticator
  → Member runs /verify code:<6-digit-totp>
      → 2FA confirmed — member can now use their assigned commands
```

> Scan QR codes with an authenticator app — **never** with Discord mobile's built-in camera (it opens links instead of reading TOTP).

---

## Command Reference

### 2FA & Account

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/create-2fa` | Registered users, owners | No | Generate QR code + 8 backup codes. Shows secret key for manual entry. |
| `/verify code` | Anyone with pending setup | N/A | Confirm TOTP pairing with a 6-digit code. |
| `/reset-user member code` | Server owner, bot owner | Yes | Wipe a user's 2FA for re-registration. DMs the reset user. |

### Admin

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/setup-guild log_channel announcement_channel code` | Bot owner | Yes | One-time server initialization. |
| `/add-announcer member code` | Server owner, bot owner | Yes | Add a user to announcers. DMs them setup instructions. |
| `/remove-announcer member code` | Server owner, bot owner | Yes | Remove announce permissions. |
| `/add-linkmanager member code` | Server owner, bot owner | Yes | Add a user to link managers. DMs them setup instructions. |
| `/remove-linkmanager member code` | Server owner, bot owner | Yes | Remove link manager permissions. |
| `/add-channel channel code` | Server owner, bot owner | Yes | Add a channel to the announcement channels list. |
| `/remove-channel channel code` | Server owner, bot owner | Yes | Remove a channel from the announcement channels list. |
| `/set-logs channel code` | Server owner, bot owner | Yes | Change the log channel. |
| `/change-timeout seconds code` | Bot owner | Yes | Set announcement permission window duration (30–3600s, default 300). |
| `/list option` | Any registered user | No | List a config group: `announcers`, `link-managers`, `whitelist`, `channels`, `exempt`. |
| `/list-all` | Server owner, bot owner | No | Full server config overview in one embed. |

### Link Filter

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/allow-link type` | Link managers, owners | Yes (in modal) | Whitelist up to 10 domains or URLs at once. `domain` covers all subdomains. |
| `/remove-link url code` | Link managers, owners | Yes | Remove a URL from the whitelist. |
| `/toggle-linkfilter code` | Bot owner | Yes | Enable or disable link scanning for this server. |
| `/add-whitelist-linkfilter entity_type target code` | Server owner, bot owner | Yes | Exempt a channel, category, role, or user from link scanning. |
| `/remove-whitelist-linkfilter entity_type target code` | Server owner, bot owner | Yes | Remove a link filter exemption. |

### Webhooks

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/allow-webhook code` | Bot owner | Yes | Open a 30-minute window for adding a legitimate webhook. Protection auto-re-enables after. |

### Announcements

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/announce channel code` | Announcers, owners | Yes | Grant temporary channel access (send, embed, attach, mention @everyone). Auto-revoked when timer expires. |

### Embeds

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/embed send channel code` | Announcers, owners | Yes | Build and post an embed via modal with live preview. |
| `/embed edit message_id channel code` | Announcers, owners | Yes | Edit a previously sent embed. Pre-filled modal with current content. |
| `/embed delete message_id channel code` | Announcers, owners | Yes | Delete a bot embed and remove its database record. |
| `/embed list [channel]` | Any registered user | No | List 10 most recent bot embeds (optionally filtered by channel). |

### Name Filter

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/name-filter add phrase pattern code` | Announcers, owners | Yes | Add a single case-insensitive phrase filter. |
| `/name-filter add regex pattern code` | Announcers, owners | Yes | Add a regex filter. Validates syntax before saving. |
| `/name-filter import phrase code` | Announcers, owners | Yes | Paste 50+ phrase filters at once via modal. |
| `/name-filter import regex code` | Announcers, owners | Yes | Paste 50+ regex filters at once. Invalid patterns reported and skipped. |
| `/name-filter remove filter_id code` | Announcers, owners | Yes | Remove a filter by its ID. |
| `/name-filter list` | Announcers, owners | No | Post all active filters to the log channel (regex first, then phrase). |
| `/name-filter test name` | Announcers, owners | No | Check if a name would be caught and which filter would match it. |
| `/name-filter set-action action code [timeout_hours]` | Announcers, owners | Yes | Set match action: `ban`, `kick`, or `timeout` (1–672 hours). |
| `/name-filter cleanse code` | Announcers, owners | Yes | Retroactively scan all current members. 5-minute guild cooldown. |

### Moderation

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/role member role` | Server owner, bot owner | No | Toggle a role on/off for a member. |
| `/bulk-role` | Server owner, bot owner | No | Apply a role to multiple users at once (paste user IDs in modal). |
| `/new-role name [color]` | Server owner, bot owner | No | Create a new role. `color` is an optional hex value. |
| `/rename-channel channel new_name` | Server owner, bot owner | No | Rename a channel. Protects log and announcement channels. |
| `/toggle-channel channel role` | Server owner, bot owner | No | Toggle a role's access to a channel on/off. |
| `/sync-channels category` | Server owner, bot owner | No | Sync all channels in a category to category permissions. |
| `/restrict-channel member action channel` | Server owner, bot owner | No | Restrict a member to one channel. `action`: `add` or `remove`. |
| `/lock-threads [channel]` | Server owner, bot owner | No | Lock all active and archived threads in a channel or server-wide. |
| `/export` | Server owner, bot owner | Yes | Export all server members and their roles as a CSV file. |
| `/export-category category` | Server owner, bot owner | Yes | Export message history from all text channels in a category as a ZIP of CSVs. |
| `/export-permissions` | Server owner, bot owner | Yes | Export every role's permissions to a colour-coded `.xlsx` file — server level on Sheet 1, category overrides on Sheet 2, channel overrides on Sheet 3. Green = allowed, red = denied. |
| `/list-overrides` | Server owner, bot owner | Yes | List all channels with user-specific permission overrides. |

### Panic

| Command | Access | 2FA | Description |
|---|---|---|---|
| `/panic` | Bot owner | Yes (modal) | Open confirmation modal. Requires typing `CONFIRM LOCKDOWN` + 2FA code. Locks down entire server. |
| `/recover code` | Bot owner | Yes | Restore all role permissions and channel overwrites from panic backup. |

**DM trigger:** If you can't access the server, DM the bot: `panic <guild_id> <2fa_code> CONFIRM LOCKDOWN`

---

## Self-Recovery (Backup Codes)

When you run `/create-2fa`, 8 single-use backup codes are generated in `XXXX-XXXX` format. **Save them immediately** — they are shown once and stored only as SHA-256 hashes.

**If you lose access to your authenticator app:**

1. DM the bot: `recover 1234-5678`
2. The bot consumes the backup code and resets your 2FA.
3. Go to the server and run `/create-2fa` again.

If you have no backup codes left, ask the server owner or bot owner to run `/reset-user`.

---

## Customization

### Brand Color
The default embed color is Discord blurple (`#5865F2`). To change it:

Edit [cogs/embeds.py](cogs/embeds.py) line 32:
```python
BRAND_COLOR = 0x5865F2  # Change to your hex color, e.g. 0xFF5733
```

### 2FA App Name
The name shown in authenticator apps is set in [two_factor_helper.py](two_factor_helper.py):
```python
uri = pyotp.totp.TOTP(secret).provisioning_uri(
    name="Security Bot",       # Shown as the account label
    issuer_name="SecurityBot"  # Shown as the issuer
)
```

### Dangerous Permissions (Panic Mode)
Configure which permissions are stripped during panic in [config.json](config.json) under `"panic" → "dangerous_permissions"`.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

---

## Tech Stack

- **Runtime:** Python 3.10+
- **Discord library:** [py-cord](https://github.com/Pycord-Development/pycord) (slash commands, modals, views)
- **Database:** SQLite with WAL mode + parameterized queries throughout (no SQL injection)
- **2FA:** [pyotp](https://github.com/pyauth/pyotp) (TOTP, RFC 6238 compliant)
- **QR codes:** [pyqrcode](https://github.com/mnooner256/pyqrcode) + pypng
- **Config:** python-dotenv
- **Excel export:** [openpyxl](https://openpyxl.readthedocs.io/) (permission audit workbooks)

---

## Security Notes

- All sensitive commands require a valid TOTP code verified at execution time — no session-based auth.
- Backup codes are SHA-256 hashed before storage and deleted on use (single-use).
- QR code PNGs are written to disk and auto-deleted within 60 seconds by a background task.
- The SQLite database uses foreign key constraints, WAL mode, and parameterized queries throughout.
- The link scanner runs 5 detection passes. Within the deep-scan pass, percent-decoding is applied iteratively (up to 3 decode iterations) to catch double-encoded URLs.

---

## Deployment

This bot is free to use and open source under the MIT license.  
For custom deployment, configuration, or integration into your Web3 project's Discord server, reach out to the author.

---

## License

[MIT License](LICENSE) — use it, fork it, build on it. Credit stays in the source.

---

## Built By

<div align="center">

### [Nuelverse](https://github.com/Nuelverse)
**Web3 Builder · Community Manager · Aspiring Blockchain Developer**

[![GitHub](https://img.shields.io/badge/GitHub-Nuelverse-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Nuelverse)
[![X](https://img.shields.io/badge/X-@nuelverse-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/nuelverse)
[![Discord](https://img.shields.io/badge/Discord-nuelverse-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/users/1039501090917457950)
[![Email](https://img.shields.io/badge/Email-nuelverse%40proton.me-6D4AFF?style=for-the-badge&logo=protonmail&logoColor=white)](mailto:nuelverse@proton.me)
  
*If this bot protects your server, consider reaching out.*

</div>
