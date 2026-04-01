import asyncio
import json
import os
from datetime import datetime, timezone
from urllib import error, parse, request

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

DATA_FILE = "data.json"
MANIFEST_STATE_FILE = "manifest_state.json"
EPIC_DEVICE_AUTH_FILE = "epic_device_auth.json"
COMMANDS_SYNCED = False
MANIFEST_POLL_TASK = None

EPIC_OAUTH_TOKEN_URL = (
    "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
)
EPIC_DEVICE_AUTH_URL = (
    "https://account-public-service-prod.ol.epicgames.com"
    "/account/api/public/account/{account_id}/deviceAuth"
)
EPIC_IOS_MANIFEST_URL = (
    "https://launcher-public-service-prod06.ol.epicgames.com"
    "/launcher/api/public/assets/v2/platform/IOS/namespace/fn/"
    "catalogItem/5cb97847cee34581afdbc445400e2f77/app/FortniteContentBuilds/"
    "label/Live"
)
EPIC_ANDROID_BASIC_TOKEN = (
    "basic "
    "MzRhMDJjZjhmNDQxNGEyYjk5YmQ0YzRiYTM2Zjg1M2E6"
    "ZGEwMmRmYzdiOTY4NGQ5Yzk0YzZiY2M2YTMwMjM2Yjk="
)
EPIC_USER_AGENT = "Fortnite/++Fortnite+Release-26.10-CL-27665530 Android/13"
MANIFEST_POLL_SECONDS = max(
    15, int(os.getenv("FORTNITE_MANIFEST_POLL_SECONDS", "60"))
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="^", intents=intents)


class EpicAPIError(Exception):
    pass


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_default_data():
    return {
        "protected_ids": [],
        "ban_channels": [],
        "allowed_users": [],
        "manifest_channels": {},
    }


def new_default_manifest_state():
    return {"fortnite_ios": None}


def read_json_file(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path, payload):
    with open(path, "w") as f:
        json.dump(payload, f, indent=4)


def normalize_data(data):
    base = new_default_data()
    for key in ("protected_ids", "ban_channels", "allowed_users"):
        value = data.get(key, [])
        if isinstance(value, list):
            base[key] = [str(item) for item in value]

    manifest_channels = data.get("manifest_channels", {})
    if isinstance(manifest_channels, dict):
        for guild_id, channel_id in manifest_channels.items():
            guild_id_str = str(guild_id)
            channel_id_str = str(channel_id)
            if guild_id_str.isdigit() and channel_id_str.isdigit():
                base["manifest_channels"][guild_id_str] = channel_id_str

    return base


def normalize_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return None

    build_version = str(snapshot.get("build_version", "")).strip()
    manifest_id = str(snapshot.get("manifest_id", "")).strip()
    file_hash = str(snapshot.get("file_hash", "")).strip()
    manifest_url = str(snapshot.get("manifest_url", "")).strip()
    checked_at = str(snapshot.get("checked_at", "")).strip() or utc_now_iso()

    if not build_version:
        return None

    return {
        "build_version": build_version,
        "manifest_id": manifest_id,
        "file_hash": file_hash,
        "manifest_url": manifest_url,
        "checked_at": checked_at,
    }


def normalize_manifest_state(data):
    base = new_default_manifest_state()
    if isinstance(data, dict):
        base["fortnite_ios"] = normalize_snapshot(data.get("fortnite_ios"))
    return base


def normalize_device_auth(data):
    if not isinstance(data, dict):
        return None

    account_id = str(data.get("account_id", "")).strip()
    device_id = str(data.get("device_id", "")).strip()
    secret = str(data.get("secret", "")).strip()

    if not account_id or not device_id or not secret:
        return None

    return {
        "account_id": account_id,
        "device_id": device_id,
        "secret": secret,
    }


def load_data():
    return normalize_data(read_json_file(DATA_FILE, new_default_data()))


def save_data(data):
    write_json_file(DATA_FILE, normalize_data(data))


def load_manifest_state():
    return normalize_manifest_state(
        read_json_file(MANIFEST_STATE_FILE, new_default_manifest_state())
    )


def save_manifest_state(state):
    write_json_file(MANIFEST_STATE_FILE, normalize_manifest_state(state))


def load_device_auth():
    return normalize_device_auth(read_json_file(EPIC_DEVICE_AUTH_FILE, {}))


def save_device_auth(device_auth):
    write_json_file(EPIC_DEVICE_AUTH_FILE, normalize_device_auth(device_auth) or {})


def is_guild_owner(interaction):
    return (
        interaction.guild is not None
        and interaction.user.id == interaction.guild.owner_id
    )


def has_discord_admin(interaction):
    member = interaction.user
    return (
        interaction.guild is not None
        and isinstance(member, discord.Member)
        and member.guild_permissions.administrator
    )


def has_access(interaction, data):
    return (
        is_guild_owner(interaction)
        or has_discord_admin(interaction)
        or str(interaction.user.id) in data["allowed_users"]
    )


def has_admin_power(interaction, data):
    user_id = str(interaction.user.id)
    return is_guild_owner(interaction) or has_discord_admin(interaction) or (
        user_id in data["allowed_users"] and user_id in data["protected_ids"]
    )


def is_protected_user(interaction, user_id, data):
    return (
        interaction.guild is not None and user_id == interaction.guild.owner_id
    ) or str(user_id) in data["protected_ids"]


def parse_user_id(raw_value):
    cleaned = raw_value.strip()
    if cleaned.startswith("<@") and cleaned.endswith(">"):
        cleaned = cleaned[2:-1].lstrip("!")
    if cleaned.isdigit():
        return int(cleaned)
    return None


async def respond(interaction, message, ephemeral=False, embed=None):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral, embed=embed)
    else:
        await interaction.response.send_message(
            message, ephemeral=ephemeral, embed=embed
        )


async def ensure_guild_context(interaction):
    if interaction.guild is None:
        await respond(interaction, "this command can only be used in a server.")
        return False
    return True


def _json_request(url, *, method="GET", headers=None, data=None):
    encoded_data = None
    final_headers = headers or {}
    if data is not None:
        encoded_data = parse.urlencode(data).encode("utf-8")

    req = request.Request(
        url=url,
        method=method,
        headers=final_headers,
        data=encoded_data,
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8")
            if not payload:
                return {}
            return json.loads(payload)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise EpicAPIError(f"http {exc.code}: {detail or exc.reason}") from exc
    except error.URLError as exc:
        raise EpicAPIError(str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise EpicAPIError("invalid json response from epic") from exc


def _epic_headers(access_token=None, *, basic_auth=False, form=False):
    headers = {"User-Agent": EPIC_USER_AGENT, "Accept": "application/json"}
    if basic_auth:
        headers["Authorization"] = EPIC_ANDROID_BASIC_TOKEN
    if access_token:
        headers["Authorization"] = f"bearer {access_token}"
    if form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return headers


def _exchange_code_for_access_token(exchange_code):
    payload = {
        "grant_type": "exchange_code",
        "exchange_code": exchange_code.strip(),
        "token_type": "eg1",
    }
    return _json_request(
        EPIC_OAUTH_TOKEN_URL,
        method="POST",
        headers=_epic_headers(basic_auth=True, form=True),
        data=payload,
    )


def _create_device_auth(access_token, account_id):
    return _json_request(
        EPIC_DEVICE_AUTH_URL.format(account_id=account_id),
        method="POST",
        headers=_epic_headers(access_token=access_token),
    )


def _login_with_device_auth(device_auth):
    payload = {
        "grant_type": "device_auth",
        "account_id": device_auth["account_id"],
        "device_id": device_auth["device_id"],
        "secret": device_auth["secret"],
        "token_type": "eg1",
    }
    return _json_request(
        EPIC_OAUTH_TOKEN_URL,
        method="POST",
        headers=_epic_headers(basic_auth=True, form=True),
        data=payload,
    )


def _fetch_fortnite_ios_manifest_sync():
    device_auth = load_device_auth()
    if not device_auth:
        raise EpicAPIError("epic device auth is not configured")

    auth = _login_with_device_auth(device_auth)
    access_token = auth.get("access_token")
    if not access_token:
        raise EpicAPIError("epic login succeeded without an access token")

    payload = _json_request(
        EPIC_IOS_MANIFEST_URL,
        headers=_epic_headers(access_token=access_token),
    )
    elements = payload.get("elements") or []
    if not elements:
        raise EpicAPIError("manifest response did not include any elements")

    first = elements[0]
    manifests = first.get("manifests") or []
    manifest_url = ""
    if manifests and isinstance(manifests[0], dict):
        manifest_url = str(manifests[0].get("uri", "")).strip()

    manifest_name = manifest_url.rsplit("/", 1)[-1] if manifest_url else ""
    manifest_id = manifest_name[:-9] if manifest_name.endswith(".manifest") else manifest_name

    hash_value = first.get("hash", "")
    if isinstance(hash_value, dict):
        hash_value = (
            hash_value.get("hash")
            or hash_value.get("value")
            or hash_value.get("hexDigest")
            or ""
        )

    return normalize_snapshot(
        {
            "build_version": first.get("buildVersion", ""),
            "manifest_id": manifest_id,
            "file_hash": hash_value,
            "manifest_url": manifest_url,
            "checked_at": utc_now_iso(),
        }
    )


async def bootstrap_epic_device_auth(exchange_code):
    def _bootstrap():
        login = _exchange_code_for_access_token(exchange_code)
        access_token = login.get("access_token")
        account_id = login.get("account_id")
        if not access_token or not account_id:
            raise EpicAPIError("epic exchange code login did not return account data")

        created = _create_device_auth(access_token, account_id)
        return normalize_device_auth(
            {
                "account_id": created.get("accountId") or account_id,
                "device_id": created.get("deviceId"),
                "secret": created.get("secret"),
            }
        )

    device_auth = await asyncio.to_thread(_bootstrap)
    if not device_auth:
        raise EpicAPIError("failed to create epic device auth")
    save_device_auth(device_auth)
    return device_auth


async def fetch_fortnite_ios_manifest():
    snapshot = await asyncio.to_thread(_fetch_fortnite_ios_manifest_sync)
    if not snapshot:
        raise EpicAPIError("manifest snapshot was empty")
    return snapshot


def create_manifest_embed(snapshot, title="Fortnite iOS Update"):
    embed = discord.Embed(title=title, color=discord.Color.blue())
    embed.add_field(
        name="Build Version",
        value=snapshot.get("build_version", "Unknown"),
        inline=False,
    )
    embed.add_field(
        name="Manifest ID",
        value=snapshot.get("manifest_id", "Unknown"),
        inline=False,
    )
    embed.add_field(
        name="File Hash",
        value=snapshot.get("file_hash", "Unknown"),
        inline=False,
    )

    manifest_url = snapshot.get("manifest_url", "")
    if manifest_url:
        embed.add_field(name="Manifest URL", value=manifest_url, inline=False)

    checked_at = snapshot.get("checked_at", "")
    if checked_at:
        embed.set_footer(text=f"Checked {checked_at}")

    return embed


async def announce_manifest_update(snapshot):
    data = load_data()
    for guild_id, channel_id in data["manifest_channels"].items():
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        if not isinstance(channel, discord.abc.Messageable):
            continue

        try:
            await channel.send(embed=create_manifest_embed(snapshot))
        except discord.HTTPException:
            continue


async def check_fortnite_manifest_updates():
    if not load_device_auth():
        return

    current_snapshot = await fetch_fortnite_ios_manifest()
    state = load_manifest_state()
    previous_snapshot = state.get("fortnite_ios")

    if previous_snapshot is None:
        state["fortnite_ios"] = current_snapshot
        save_manifest_state(state)
        print("seeded fortnite ios manifest state")
        return

    if previous_snapshot.get("build_version") == current_snapshot.get("build_version"):
        return

    state["fortnite_ios"] = current_snapshot
    save_manifest_state(state)
    print(
        "fortnite ios manifest update detected:",
        previous_snapshot.get("build_version"),
        "->",
        current_snapshot.get("build_version"),
    )
    await announce_manifest_update(current_snapshot)


async def manifest_poll_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_fortnite_manifest_updates()
        except EpicAPIError as exc:
            print(f"manifest poll failed: {exc}")
        except Exception as exc:
            print(f"unexpected manifest poll failure: {exc}")
        await asyncio.sleep(MANIFEST_POLL_SECONDS)


def ensure_manifest_poll_task():
    global MANIFEST_POLL_TASK
    if MANIFEST_POLL_TASK is None or MANIFEST_POLL_TASK.done():
        MANIFEST_POLL_TASK = asyncio.create_task(manifest_poll_loop())


@bot.event
async def on_ready():
    global COMMANDS_SYNCED
    print(f"{bot.user} is ready")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="sending scammers to a far away land rn // /about for help",
        )
    )
    if not COMMANDS_SYNCED:
        synced = await bot.tree.sync()
        COMMANDS_SYNCED = True
        print(f"synced {len(synced)} slash commands")
    ensure_manifest_poll_task()


@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    data = load_data()

    if str(message.channel.id) in data["ban_channels"]:
        if (
            message.author.id == message.guild.owner_id
            or str(message.author.id) in data["protected_ids"]
        ):
            return

        try:
            await message.author.ban(
                reason="instabanned due to typing in a monitored channel",
                delete_message_days=0,
            )
            await message.delete()
        except Exception:
            pass


@bot.tree.command(name="add", description="Add a user to protected list")
@app_commands.describe(user_id="User ID or mention to protect")
async def add(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if str(target_id) not in data["protected_ids"]:
        data["protected_ids"].append(str(target_id))
        save_data(data)
        await respond(interaction, f"added {target_id} to protected list!")
    else:
        await respond(interaction, f"{target_id} is already protected LOL")


@bot.tree.command(name="remove", description="Remove a user from protected list")
@app_commands.describe(user_id="User ID or mention to unprotect")
async def remove(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if target_id == interaction.user.id:
        return await respond(interaction, "you can't unprotect yourself!")
    if target_id == interaction.guild.owner_id:
        return await respond(interaction, f"error: could not remove {target_id}")
    if str(target_id) in data["protected_ids"]:
        data["protected_ids"].remove(str(target_id))
        save_data(data)
        await respond(interaction, f"removed {target_id} from protected list!")
    else:
        await respond(interaction, f"{target_id} isn't even in the protected list!")


@bot.tree.command(name="toggle", description="Toggle a user's protected status")
@app_commands.describe(user_id="User ID or mention to toggle protection for")
async def toggle(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if target_id == interaction.guild.owner_id:
        return await respond(interaction, f"error: could not toggle {target_id}")
    if str(target_id) in data["protected_ids"]:
        data["protected_ids"].remove(str(target_id))
        await respond(interaction, f"removed {target_id} from protected list!")
    else:
        data["protected_ids"].append(str(target_id))
        await respond(interaction, f"added {target_id} to protected list!")
    save_data(data)


@bot.tree.command(name="ban", description="Ban a user by user ID")
@app_commands.describe(user_id="User ID or mention to ban")
async def ban(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if target_id == interaction.user.id:
        return await respond(interaction, "you can't ban yourself!")
    if is_protected_user(interaction, target_id, data):
        return await respond(interaction, "can't ban a protected user LOL")
    try:
        user = await bot.fetch_user(target_id)
        await interaction.guild.ban(user, reason="manually banned")
        await respond(interaction, f"successfully banned {target_id}!")
    except Exception:
        await respond(interaction, "error: failed to ban user")


@bot.tree.command(name="unban", description="Unban a user by user ID")
@app_commands.describe(user_id="User ID or mention to unban")
async def unban(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    try:
        user = await bot.fetch_user(target_id)
        await interaction.guild.unban(user)
        await respond(interaction, f"successfully unbanned {target_id}!")
    except Exception:
        await respond(interaction, "error: failed to unban user")


@bot.tree.command(name="kick", description="Kick a user by user ID")
@app_commands.describe(user_id="User ID or mention to kick")
async def kick(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if target_id == interaction.user.id:
        return await respond(interaction, "you can't kick yourself!")
    if is_protected_user(interaction, target_id, data):
        return await respond(interaction, "can't kick a protected user LOL")
    try:
        member = interaction.guild.get_member(target_id)
        if member is None:
            return await respond(interaction, "user not found in this server!")
        await member.kick(reason="manually kicked")
        await respond(interaction, f"successfully kicked {target_id}!")
    except Exception:
        await respond(interaction, "error: failed to kick user")


@bot.tree.command(name="instaban", description="Enable instant ban in a channel")
@app_commands.describe(channel="Channel to monitor")
async def instaban(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    if str(channel.id) not in data["ban_channels"]:
        data["ban_channels"].append(str(channel.id))
        save_data(data)
        await respond(
            interaction, f"enabled instant ban-on-type for channel {channel.mention}!"
        )
    else:
        await respond(
            interaction,
            f"the channel {channel.mention} already has instant ban-on-type enabled!",
        )


async def uninstaban_channel_autocomplete(
    interaction: discord.Interaction, current: str
):
    if interaction.guild is None:
        return []

    data = load_data()
    current_lower = current.lower()
    choices = []

    for channel_id in data["ban_channels"]:
        channel = interaction.guild.get_channel(int(channel_id))
        if channel is None:
            label = f"deleted-channel ({channel_id})"
        else:
            label = f"#{channel.name} ({channel_id})"

        if current_lower and current_lower not in label.lower():
            continue

        choices.append(app_commands.Choice(name=label[:100], value=channel_id))
        if len(choices) >= 25:
            break

    return choices


@bot.tree.command(name="uninstaban", description="Disable instant ban in a channel")
@app_commands.describe(channel_id="Enabled channel to stop monitoring")
@app_commands.autocomplete(channel_id=uninstaban_channel_autocomplete)
async def uninstaban(interaction: discord.Interaction, channel_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    if channel_id in data["ban_channels"]:
        data["ban_channels"].remove(channel_id)
        save_data(data)
        channel = interaction.guild.get_channel(int(channel_id))
        channel_ref = channel.mention if channel else channel_id
        await respond(
            interaction, f"disabled instant ban-on-type for channel {channel_ref}!"
        )
    else:
        channel = (
            interaction.guild.get_channel(int(channel_id))
            if channel_id.isdigit()
            else None
        )
        channel_ref = channel.mention if channel else channel_id
        await respond(
            interaction,
            f"the channel {channel_ref} doesn't even have instant ban-on-type enabled LOL",
        )


@bot.tree.command(name="access", description="Grant command access to a user ID")
@app_commands.describe(user_id="User ID or mention to grant access")
async def access(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if str(target_id) not in data["allowed_users"]:
        data["allowed_users"].append(str(target_id))
        save_data(data)
        await respond(
            interaction, f"granted access to {target_id}! they can now use my commands :P"
        )
    else:
        await respond(interaction, f"{target_id} already has access to my commands!")


@bot.tree.command(name="revoke", description="Revoke command access from a user ID")
@app_commands.describe(user_id="User ID or mention to revoke access from")
async def revoke(interaction: discord.Interaction, user_id: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return
    target_id = parse_user_id(user_id)
    if target_id is None:
        return await respond(interaction, "please provide a valid user ID or mention.")
    if target_id == interaction.user.id:
        return await respond(interaction, "you can't revoke your own access!")
    if target_id == interaction.guild.owner_id:
        return await respond(interaction, "error: could not remove owner's access")
    if str(target_id) in data["allowed_users"]:
        data["allowed_users"].remove(str(target_id))
        save_data(data)
        await respond(interaction, f"revoked {target_id}'s access!")
    else:
        await respond(interaction, f"{target_id} doesn't even have access!")


@bot.tree.command(name="echo", description="Make the bot repeat your message")
@app_commands.describe(message="Message to echo")
async def echo(interaction: discord.Interaction, message: str):
    data = load_data()
    if not has_access(interaction, data):
        return
    await respond(interaction, message)


@bot.tree.command(name="listprotected", description="List all protected user IDs")
async def listprotected(interaction: discord.Interaction):
    data = load_data()
    if not has_access(interaction, data):
        return
    protected = ", ".join(data["protected_ids"]) if data["protected_ids"] else "None"
    await respond(interaction, f"protected user IDs: {protected}")


@bot.tree.command(name="listchannels", description="List all instant-ban channels")
async def listchannels(interaction: discord.Interaction):
    data = load_data()
    if not has_access(interaction, data):
        return
    channels = ", ".join(data["ban_channels"]) if data["ban_channels"] else "None"
    await respond(interaction, f"ban-on-type channels: {channels}")


@bot.tree.command(name="listaccess", description="List all users with command access")
async def listaccess(interaction: discord.Interaction):
    data = load_data()
    if not has_access(interaction, data):
        return
    access_list = ", ".join(data["allowed_users"]) if data["allowed_users"] else "None"
    await respond(interaction, f"allowed users: {access_list}")


@bot.tree.command(name="listbans", description="List currently banned users in this server")
async def listbans(interaction: discord.Interaction):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return
    try:
        entries = [entry async for entry in interaction.guild.bans(limit=100)]
    except Exception:
        return await respond(interaction, "error: failed to fetch server ban list")

    if not entries:
        return await respond(interaction, "no users are currently banned in this server.")

    lines = [f"{entry.user} ({entry.user.id})" for entry in entries]
    header = f"server bans ({len(entries)} shown):\n"
    body = "\n".join(lines)
    message = f"{header}{body}"
    if len(message) > 1900:
        message = f"{header}" + "\n".join(lines[:40])
    await respond(interaction, message)


@bot.tree.command(name="manifest_ios", description="Fetch the current Fortnite iOS manifest")
async def manifest_ios(interaction: discord.Interaction):
    data = load_data()
    if not has_access(interaction, data):
        return

    if not load_device_auth():
        return await respond(
            interaction,
            "epic auth isn't configured yet. use `/epicauth <exchange_code>` first.",
            ephemeral=True,
        )

    await interaction.response.defer(thinking=True)
    try:
        snapshot = await fetch_fortnite_ios_manifest()
    except EpicAPIError as exc:
        return await interaction.followup.send(
            f"error: failed to fetch the fortnite ios manifest ({exc})"
        )

    await interaction.followup.send(
        embed=create_manifest_embed(snapshot, title="Current Fortnite iOS Manifest")
    )


@bot.tree.command(
    name="manifest_channel",
    description="Set the channel for automatic Fortnite iOS manifest updates",
)
@app_commands.describe(channel="Channel to receive Fortnite iOS manifest updates")
async def manifest_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return

    data["manifest_channels"][str(interaction.guild.id)] = str(channel.id)
    save_data(data)
    await respond(
        interaction,
        f"fortnite ios manifest updates will now post in {channel.mention}!",
    )


@bot.tree.command(
    name="manifest_disable",
    description="Disable automatic Fortnite iOS manifest updates in this server",
)
async def manifest_disable(interaction: discord.Interaction):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return

    removed = data["manifest_channels"].pop(str(interaction.guild.id), None)
    save_data(data)
    if removed:
        await respond(interaction, "disabled fortnite ios manifest updates here!")
    else:
        await respond(interaction, "this server doesn't have manifest updates enabled.")


@bot.tree.command(
    name="manifest_status",
    description="Show the configured Fortnite iOS manifest channel and last seen build",
)
async def manifest_status(interaction: discord.Interaction):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_access(interaction, data):
        return

    configured_channel_id = data["manifest_channels"].get(str(interaction.guild.id))
    configured_channel = (
        interaction.guild.get_channel(int(configured_channel_id))
        if configured_channel_id
        else None
    )
    channel_text = (
        configured_channel.mention
        if configured_channel is not None
        else configured_channel_id or "not configured"
    )

    state = load_manifest_state()
    snapshot = state.get("fortnite_ios")
    if snapshot is None:
        details = "no ios manifest has been stored yet."
    else:
        details = (
            f"last build: {snapshot['build_version']}\n"
            f"manifest id: {snapshot.get('manifest_id', 'Unknown')}\n"
            f"file hash: {snapshot.get('file_hash', 'Unknown')}\n"
            f"checked at: {snapshot.get('checked_at', 'Unknown')}"
        )

    await respond(
        interaction,
        f"manifest channel: {channel_text}\n{details}",
    )


@bot.tree.command(
    name="epicauth",
    description="Create and store Epic device auth using an exchange code",
)
@app_commands.describe(exchange_code="Epic exchange code used to bootstrap device auth")
async def epicauth(interaction: discord.Interaction, exchange_code: str):
    if not await ensure_guild_context(interaction):
        return
    data = load_data()
    if not has_admin_power(interaction, data):
        return

    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        await bootstrap_epic_device_auth(exchange_code)
    except EpicAPIError as exc:
        return await interaction.followup.send(
            f"error: failed to store epic device auth ({exc})", ephemeral=True
        )

    await interaction.followup.send(
        "stored epic device auth successfully. manifest polling is now enabled.",
        ephemeral=True,
    )


@bot.tree.command(
    name="epicauthstatus",
    description="Show whether Epic device auth is configured for manifest polling",
)
async def epicauthstatus(interaction: discord.Interaction):
    data = load_data()
    if not has_access(interaction, data):
        return

    device_auth = load_device_auth()
    if device_auth:
        masked_account = device_auth["account_id"][:8]
        await respond(
            interaction,
            f"epic auth is configured for account `{masked_account}...`.",
            ephemeral=True,
        )
    else:
        await respond(
            interaction,
            "epic auth is not configured yet. use `/epicauth <exchange_code>`.",
            ephemeral=True,
        )


@bot.tree.command(name="about", description="Show help and command information")
async def about(interaction: discord.Interaction):
    help_text = """
*hey! i'm Trills, a multi-use bot made to protect servers from being bothered by dirty scammers, here are a few of my commands:*
`/add <user_id>` - add a user to protected list, not letting me ban them
`/remove <user_id>` - remove a user from protected list, enabling me to ban them
`/toggle <user_id>` - toggles a user's protected status
`/ban <user_id>` - manually ban a user
`/unban <user_id>` - unban a user
`/kick <user_id>` - kick a user
`/instaban <channel>` - enable instant ban on message sent in a channel
`/uninstaban <channel>` - disable instant ban on message sent in a channel
`/access <user_id>` - give a user the ability to use my commands
`/revoke <user_id>` - take away a user's command access
`/echo <message>` - make me echo anything you type
`/listprotected` - lists all protected user IDs
`/listchannels` - lists all channels that instantly ban when a message is sent
`/listaccess` - lists all users with command access
`/listbans` - lists currently banned users in this server
`/manifest_ios` - fetch the current Fortnite iOS manifest live
`/manifest_channel <channel>` - set where automatic Fortnite iOS manifest updates post
`/manifest_disable` - disable automatic Fortnite iOS manifest posts in this server
`/manifest_status` - show the configured manifest channel and last seen iOS build
`/epicauth <exchange_code>` - bootstrap Epic device auth for manifest polling
`/epicauthstatus` - show whether Epic auth is configured
`/about` - shows this message!

**Notes:**
- only users with access can use commands
- server owners always have full access
- users with Discord Administrator permission can also fully manage commands
- typing in instant-ban channels results in an *immediate* ban (unless protected)
- non-owners need both protection AND access to grant/revoke others protection/access
- fortnite ios manifest polling checks automatically in the background once epic auth is configured
"""
    await respond(interaction, help_text)


@bot.tree.command(name="cleardata", description="Reset all bot data to defaults")
async def cleardata(interaction: discord.Interaction):
    if not await ensure_guild_context(interaction):
        return
    if not is_guild_owner(interaction):
        return
    write_json_file(DATA_FILE, new_default_data())
    await respond(interaction, "reset all data to default!")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
