# HashFoxLabs Security Bot

A Discord security bot for a single server. Provides 2FA-gated command access, multi-pass link scanning with evasion bypass, webhook protection, panic lockdown, and structured audit logging.

---

## Table of Contents

- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Permission Hierarchy](#permission-hierarchy)
- [First-Time Server Setup](#first-time-server-setup)
- [2FA Onboarding Flow](#2fa-onboarding-flow)
- [Command Reference](#command-reference)
  - [2FA & Account](#2fa--account)
  - [Admin](#admin)
  - [Link Filter](#link-filter)
  - [Webhooks](#webhooks)
  - [Announcements](#announcements)
  - [Moderation](#moderation)
  - [Panic](#panic)
- [Link Scanner](#link-scanner)
- [Self-Recovery (Backup Codes)](#self-recovery-backup-codes)
- [Running Tests](#running-tests)

---

## Setup

**Requirements:** Python 3.10+

```bash
# 1. Clone / download the repo
git clone <your-private-repo-url>
cd hashfoxlabs-security-bot

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env (see below)
cp .env.example .env

# 5. Run
python bot.py
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_discord_bot_token_here
MASTER_USER_ID=your_discord_user_id_here
DEBUG_GUILD_ID=                          # Optional: speeds up slash command sync during dev
DATABASE_PATH=database.db                # Optional: override database file path
```

| Variable | Description |
|---|---|
| `BOT_TOKEN` | From the Discord Developer Portal → Your App → Bot |
| `MASTER_USER_ID` | Your Discord user ID — this account has full bot control |
| `DEBUG_GUILD_ID` | (Optional) Guild ID for instant slash command registration in development |
| `DATABASE_PATH` | (Optional) Path to the SQLite database file. Defaults to `database.db` in the project root |

> **Changing bot ownership:** Since `MASTER_USER_ID` is set in `.env`, you can transfer bot control to any user by updating this value without touching Discord application ownership.

---

## Permission Hierarchy

```
BOT OWNER (MASTER_USER_ID)
  └─ Full access to all commands, including /panic, /setup-guild, /toggle-linkfilter

SERVER OWNER (guild.owner_id)
  └─ Same as bot owner for server-scoped commands, except /panic and /setup-guild

LINK MANAGER (added via /add-linkmanager)
  └─ Can manage the link whitelist (/allow-link, /remove-link)
  └─ Requires 2FA to be set up and verified

ANNOUNCER (added via /add-announcer)
  └─ Can run /announce to get temporary channel access
  └─ Requires 2FA to be set up and verified

UNREGISTERED USER
  └─ Cannot run any command
```

**Key rules:**
- No user can run any command unless they are at minimum a link manager or announcer.
- All security-sensitive commands require a valid 2FA code at execution time.
- Bot owner and server owner must add team members; team members cannot self-register.

---

## First-Time Server Setup

1. **Bot owner** runs `/setup-guild` with a log channel, announcement channel, and 2FA code.
2. Bot owner adds team members:
   - `/add-linkmanager` for link whitelist managers
   - `/add-announcer` for announcement posters
3. Each added team member runs `/create-2fa` → scans QR code → runs `/verify`.
4. Team members are now operational.

---

## 2FA Onboarding Flow

```
Admin runs /add-linkmanager or /add-announcer
  → New member DMs the bot: they're notified to run /create-2fa
  → Member runs /create-2fa in the server
      → Bot replies ephemerally with QR code PNG + backup codes (shown once)
      → Member scans QR in Authy / Google Authenticator
  → Member runs /verify code:<6-digit-totp>
      → 2FA confirmed, member can now use their assigned commands
```

> **Important:** Scan the QR code with an authenticator app like **Authy** or **Google Authenticator** — never with Discord mobile's camera, which opens links instead of scanning for TOTP.

---

## Command Reference

### 2FA & Account

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/create-2fa` | Registered users, server owner, bot owner | No (first-time setup) | Generates QR code + 8 backup codes. Shows secret key for manual entry. |
| `/verify code` | Anyone with a pending 2FA setup | N/A | Confirms TOTP pairing with a 6-digit code from authenticator. |
| `/reset-user member code` | Server owner, bot owner | Yes | Wipes a user's 2FA so they can re-register. DMs the reset user. |

---

### Admin

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/setup-guild log_channel announcement_channel code` | Bot owner only | Yes | One-time server initialization. Sets log channel and initial announcement channel. Webhook protection is ON by default. |
| `/add-announcer member code` | Server owner, bot owner | Yes | Adds a user to the announcers list. DMs them with setup instructions. |
| `/remove-announcer member code` | Server owner, bot owner | Yes | Removes announce permissions from a user. |
| `/add-linkmanager member code` | Server owner, bot owner | Yes | Adds a user to the link managers list. DMs them with setup instructions. |
| `/remove-linkmanager member code` | Server owner, bot owner | Yes | Removes link manager permissions from a user. |
| `/add-channel channel code` | Server owner, bot owner | Yes | Add a channel to the announcement channels list. |
| `/remove-channel channel code` | Server owner, bot owner | Yes | Remove a channel from the announcement channels list. |
| `/set-logs channel code` | Server owner, bot owner | Yes | Change the bot's log channel. |
| `/change-timeout seconds code` | Bot owner only | Yes | Set the announcement permission window duration (30–3600 seconds, default 300). |
| `/list option` | Any registered user | No | List a specific config: `announcers`, `link-managers`, `whitelist`, `channels`, `exempt`. Shows 2FA status per user. |
| `/list-all` | Server owner, bot owner | No | Full server config embed: all managers, announcers, channels, filter state, webhook state, timeouts. |

---

### Link Filter

The link filter scans every message and edit in the server. When a link is detected and not on the whitelist, the message is deleted and the event is logged.

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/allow-link type` | Link managers, server owner, bot owner | Yes (in modal) | Opens a modal. Enter up to 10 URLs (one per line). `type=domain` whitelists the entire domain + subdomains. `type=specific` whitelists the exact URL. 2FA code is entered in the modal. |
| `/remove-link url code` | Link managers, server owner, bot owner | Yes | Remove a URL from the whitelist. |
| `/toggle-linkfilter code` | Bot owner only | Yes | Enable or disable the link filter globally for this server. |
| `/add-whitelist-linkfilter entity_type target code` | Server owner, bot owner | Yes | Exempt a channel, role, user, or category from link scanning. `entity_type`: `channel`, `role`, `user`, `category`. |
| `/remove-whitelist-linkfilter entity_type target code` | Server owner, bot owner | Yes | Remove a link filter exemption. |

**Link Scanner passes** (runs on every message + edit):
1. Standard HTTP/HTTPS URLs and bare shortener domains
2. Angle-bracket wrapped links `<https://...>`
3. Markdown hyperlinks `[text](url)`
4. Full deep scan — catches split URLs, obfuscated Unicode, percent-encoded domains, markdown formatting injected into URLs
5. Non-HTTP protocol detection (`ftp://`, `discord://`, `javascript:`, `mailto:`, etc.)

---

### Webhooks

Webhook protection is always enabled by default. The bot deletes any webhook created without going through the `/allow-webhook` window.

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/allow-webhook code` | Bot owner only | Yes | Opens a 30-minute window during which new webhooks are allowed. Protection automatically re-enables after the window expires. |

> To add a legitimate webhook (e.g., for a CI/CD integration), run `/allow-webhook`, create the webhook within 30 minutes, and protection resumes automatically.

---

### Announcements

`/announce` grants the announcer direct Discord channel permissions to post for a limited time window, then locks them out automatically when the timer expires.

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/announce channel code` | Announcers, server owner, bot owner | Yes (inline) | Verifies 2FA, then grants `send_messages`, `embed_links`, `attach_files`, and `mention_everyone` in the selected channel for the configured timeout. Permissions are automatically revoked when the timer expires. Channel must be registered in the announcement channels list. |

**Important notes:**
- The link filter still applies during the window. Any links to be included in the announcement must be whitelisted first via `/allow-link`.
- If `/announce` is run again before the timer expires, the timer resets for a fresh full window.
- All grant and revocation events are logged with a full timestamp to the audit log.

---

### Moderation

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/role member role` | Server owner, bot owner | No | Toggle a role on/off for a member. |
| `/bulk-role` | Server owner, bot owner | No | Opens a modal to apply a role to multiple users at once (paste user IDs). |
| `/new-role name color` | Server owner, bot owner | No | Create a new role. `color` is an optional hex value (e.g. `#FF5733`). |
| `/rename-channel channel new_name` | Server owner, bot owner | No | Rename a channel. Protects log and announcement channels from accidental rename. |
| `/toggle-channel channel role` | Server owner, bot owner | No | Toggle a role's access to a channel on/off. |
| `/sync-channels category` | Server owner, bot owner | No | Sync all channels in a category to the category's permissions. |
| `/restrict-channel member action channel` | Server owner, bot owner | No | Restrict a member to a single channel. Denies view access in all categories, then allows it in the target channel. `action`: `add` or `remove`. |
| `/lock-threads channel` | Server owner, bot owner | No | Lock all active and archived threads in a channel (or server-wide if no channel specified). |
| `/export` | Server owner, bot owner | No | Export all server members and their roles as a CSV file attachment. |
| `/export-category category` | Server owner, bot owner | No | Export message history from all text channels in a category as a ZIP of CSVs. |
| `/list-overrides` | Server owner, bot owner | No | List all channels that have user-specific permission overrides. |

---

### Panic

Panic mode locks down the entire server by removing dangerous permissions from all roles and locking all channels. It backs up the current state so it can be restored.

| Command | Who Can Use | 2FA Required | Description |
|---|---|---|---|
| `/panic` | Bot owner only | Yes (in modal) | Opens a confirmation modal. Requires typing `CONFIRM LOCKDOWN` and entering your 2FA code. Strips dangerous permissions from all roles, deletes all webhooks, and locks all channels. |
| `/recover code` | Bot owner only | Yes | Restores all role permissions and channel permissions from the panic backup. |

**DM trigger:** The bot owner can also DM the bot `panic <guild_id> <2fa_code>` to activate panic mode without a slash command — useful if server commands are inaccessible.

---

## Link Scanner

The scanner handles the following obfuscation/evasion techniques:

| Technique | Example |
|---|---|
| Split URL across newlines | `ht\ntp://evil.com` |
| Blockquote-split URL | `> ht\n> tp\n> ://evil.com` |
| Markdown formatting in URL | `https*://*evil.com`, `**https://**evil.com` |
| Extra/mixed slashes | `https:////\\\\evil.com` |
| Percent-encoded domain | `%68%74%74%70%73://evil.com` |
| Double-encoded domain | `%2568%2574...` |
| Unicode lookalike dots | `evil。com` → `evil.com` |
| Unicode lookalike slashes | `https:⁄⁄evil.com` |
| Unicode lookalike colons | `https：//evil.com` |
| Zero-width / invisible chars | `ev\u200bil.com` |
| Angle bracket wrapping | `<https://evil.com>` |
| Markdown hyperlinks | `[click me](https://evil.com)` |
| Alternative protocols | `ftp://`, `discord://`, `javascript:`, `mailto:`, `tg://` |
| Mixed-case protocols | `dIsCoRd://`, `mAiLtO:` |
| Bare shortener domains | `discord.gg/xxx`, `t.me/xxx`, `bit.ly/xxx` |

---

## Self-Recovery (Backup Codes)

When you run `/create-2fa`, you receive 8 single-use backup codes in `XXXX-XXXX` format. **Save them immediately** — they are shown once and hashed in the database.

**If you lose access to your authenticator:**

1. DM the bot: `recover 1234-5678`
2. The bot consumes the backup code and resets your 2FA.
3. Go to the server and run `/create-2fa` again.

If you have no backup codes left, ask the server owner or bot owner to run `/reset-user` for you.

