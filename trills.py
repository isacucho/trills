import json
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="^", intents=intents)

DATA_FILE = "data.json"
COMMANDS_SYNCED = False


def new_default_data():
    return {
        "protected_ids": [],
        "ban_channels": [],
        "allowed_users": [],
    }


def normalize_data(data):
    base = new_default_data()
    for key in base:
        value = data.get(key, [])
        if isinstance(value, list):
            base[key] = [str(item) for item in value]
    return base


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return normalize_data(json.load(f))
        except (json.JSONDecodeError, OSError):
            return new_default_data()
    return new_default_data()


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(normalize_data(data), f, indent=4)


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


async def respond(interaction, message):
    if interaction.response.is_done():
        await interaction.followup.send(message)
    else:
        await interaction.response.send_message(message)


async def ensure_guild_context(interaction):
    if interaction.guild is None:
        await respond(interaction, "this command can only be used in a server.")
        return False
    return True


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
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
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
`/about` - shows this message!

**Notes:**
- only users with access can use commands
- server owners always have full access
- users with Discord Administrator permission can also fully manage commands
- typing in instant-ban channels results in an *immediate* ban (unless protected)
- non-owners need both protection AND access to grant/revoke others protection/access
"""
    await respond(interaction, help_text)


@bot.tree.command(name="cleardata", description="Reset all bot data to defaults")
async def cleardata(interaction: discord.Interaction):
    if not await ensure_guild_context(interaction):
        return
    if not is_guild_owner(interaction):
        return
    with open(DATA_FILE, "w") as f:
        json.dump(new_default_data(), f, indent=4)
    await respond(interaction, "reset all data to default!")


load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
