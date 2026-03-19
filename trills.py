import json
import os

import discord
from discord.ext import commands


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="^", intents=intents)

DATA_FILE = "data.json"


def new_default_data():
    return {
        "protected_ids": [],
        "ban_channels": [],
        "allowed_users": [],
        "banned_users": [],
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


def is_guild_owner(ctx):
    return ctx.guild is not None and ctx.author.id == ctx.guild.owner_id


def has_discord_admin(ctx):
    return ctx.guild is not None and ctx.author.guild_permissions.administrator


def has_access(ctx, data):
    return (
        is_guild_owner(ctx)
        or has_discord_admin(ctx)
        or str(ctx.author.id) in data["allowed_users"]
    )


def has_admin_power(ctx, data):
    user_id = str(ctx.author.id)
    return is_guild_owner(ctx) or has_discord_admin(ctx) or (
        user_id in data["allowed_users"] and user_id in data["protected_ids"]
    )


def is_protected_user(ctx, user_id, data):
    return (
        ctx.guild is not None and user_id == ctx.guild.owner_id
    ) or str(user_id) in data["protected_ids"]


async def ensure_guild_context(ctx):
    if ctx.guild is None:
        await ctx.send("this command can only be used in a server.")
        return False
    return True


@bot.event
async def on_ready():
    print(f"{bot.user} is ready")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="sending scammers to a far away land rn // ^about for help",
        )
    )


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    data = load_data()

    if str(message.channel.id) in data["ban_channels"]:
        if (
            message.author.id == message.guild.owner_id
            or str(message.author.id) in data["protected_ids"]
        ):
            return await bot.process_commands(message)

        try:
            await message.author.ban(
                reason="instabanned due to typing in a monitored channel",
                delete_message_days=0,
            )
            await message.delete()
            if str(message.author.id) not in data["banned_users"]:
                data["banned_users"].append(str(message.author.id))
                save_data(data)
        except Exception:
            pass
        return

    await bot.process_commands(message)


@bot.command()
async def add(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_admin_power(ctx, data):
        return
    if str(user_id) not in data["protected_ids"]:
        data["protected_ids"].append(str(user_id))
        save_data(data)
        await ctx.send(f"added {user_id} to protected list!")
    else:
        await ctx.send(f"{user_id} is already protected LOL")


@bot.command()
async def remove(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_admin_power(ctx, data):
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't unprotect yourself!")
    if user_id == ctx.guild.owner_id:
        return await ctx.send("error: could not remove {user_id}")
    if str(user_id) in data["protected_ids"]:
        data["protected_ids"].remove(str(user_id))
        save_data(data)
        await ctx.send(f"removed {user_id} from protected list!")
    else:
        await ctx.send(f"{user_id} isn't even in the protected list!")


@bot.command()
async def toggle(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_admin_power(ctx, data):
        return
    if user_id == ctx.guild.owner_id:
        return await ctx.send("error: could not toggle {user_id}")
    if str(user_id) in data["protected_ids"]:
        data["protected_ids"].remove(str(user_id))
        await ctx.send(f"removed {user_id} from protected list!")
    else:
        data["protected_ids"].append(str(user_id))
        await ctx.send(f"added {user_id} to protected list!")
    save_data(data)


@bot.command()
async def ban(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_access(ctx, data):
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't ban yourself!")
    if is_protected_user(ctx, user_id, data):
        return await ctx.send("can't ban a protected user LOL")
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.ban(user, reason="manually banned")
        if str(user_id) not in data["banned_users"]:
            data["banned_users"].append(str(user_id))
            save_data(data)
        await ctx.send(f"successfully banned {user_id}!")
    except Exception:
        await ctx.send("error: failed to ban user")


@bot.command()
async def unban(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_access(ctx, data):
        return
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        if str(user_id) in data["banned_users"]:
            data["banned_users"].remove(str(user_id))
            save_data(data)
        await ctx.send(f"successfully unbanned {user_id}!")
    except Exception:
        await ctx.send("error: failed to unban user")


@bot.command()
async def kick(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_access(ctx, data):
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't kick yourself!")
    if is_protected_user(ctx, user_id, data):
        return await ctx.send("can't kick a protected user LOL")
    try:
        member = ctx.guild.get_member(user_id)
        if member is None:
            return await ctx.send("user not found in this server!")
        await member.kick(reason="manually kicked")
        await ctx.send(f"successfully kicked {user_id}!")
    except Exception:
        await ctx.send("error: failed to kick user")


@bot.command()
async def instaban(ctx, channel_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_access(ctx, data):
        return
    if str(channel_id) not in data["ban_channels"]:
        data["ban_channels"].append(str(channel_id))
        save_data(data)
        await ctx.send(f"enabled instant ban-on-type for channel {channel_id}!")
    else:
        await ctx.send(
            f"the channel {channel_id} already has instant ban-on-type enabled!"
        )


@bot.command()
async def uninstaban(ctx, channel_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_access(ctx, data):
        return
    if str(channel_id) in data["ban_channels"]:
        data["ban_channels"].remove(str(channel_id))
        save_data(data)
        await ctx.send(f"disabled instant ban-on-type for channel {channel_id}!")
    else:
        await ctx.send(
            f"the channel {channel_id} doesn't even have instant ban-on-type enabled LOL"
        )


@bot.command()
async def access(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_admin_power(ctx, data):
        return
    if str(user_id) not in data["allowed_users"]:
        data["allowed_users"].append(str(user_id))
        save_data(data)
        await ctx.send(f"granted access to {user_id}! they can now use my commands :P")
    else:
        await ctx.send(f"{user_id} already has access to my commands!")


@bot.command()
async def revoke(ctx, user_id: int):
    if not await ensure_guild_context(ctx):
        return
    data = load_data()
    if not has_admin_power(ctx, data):
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't revoke your own access!")
    if user_id == ctx.guild.owner_id:
        return await ctx.send("error: could not remove owner's access")
    if str(user_id) in data["allowed_users"]:
        data["allowed_users"].remove(str(user_id))
        save_data(data)
        await ctx.send(f"revoked {user_id}'s access!")
    else:
        await ctx.send(f"{user_id} doesn't even have access!")


@bot.command()
async def echo(ctx, *, message):
    data = load_data()
    if not has_access(ctx, data):
        return
    await ctx.send(message)


@bot.command()
async def listprotected(ctx):
    data = load_data()
    if not has_access(ctx, data):
        return
    protected = ", ".join(data["protected_ids"]) if data["protected_ids"] else "None"
    await ctx.send(f"protected user IDs: {protected}")


@bot.command()
async def listchannels(ctx):
    data = load_data()
    if not has_access(ctx, data):
        return
    channels = ", ".join(data["ban_channels"]) if data["ban_channels"] else "None"
    await ctx.send(f"ban-on-type channels: {channels}")


@bot.command()
async def listaccess(ctx):
    data = load_data()
    if not has_access(ctx, data):
        return
    access_list = ", ".join(data["allowed_users"]) if data["allowed_users"] else "None"
    await ctx.send(f"allowed users: {access_list}")


@bot.command()
async def about(ctx):
    help_text = """
*hey! i'm Trills, a multi-use bot made to protect servers from being bothered by dirty scammers, here are a few of my commands:*
`^add <user_id>` - add a user to protected list, not letting me ban them
`^remove <user_id>` - remove a user from protected list, enabling me to ban them
`^toggle <user_id>` - toggles a user's protected status
`^ban <user_id>` - manually ban a user
`^unban <user_id>` - unban a user
`^kick <user_id>` - kick a user
`^instaban <channel_id>` - enable instant ban on message sent in a channel
`^uninstaban <channel_id>` - disable instant ban on message sent in a channel
`^access <user_id>` - give a user the ability to use my commands
`^revoke <user_id>` - take away a user's command access
`^echo <message>` - make me echo anything you type
`^listprotected` - lists all protected user IDs
`^listchannels` - lists all channels that instantly ban when a message is sent
`^listaccess` - lists all users with command access
`^about` - shows this message!

**Notes:**
- only users with access can use commands
- server owners always have full access
- users with Discord Administrator permission can also fully manage commands
- typing in instant-ban channels results in an *immediate* ban (unless protected)
- non-owners need both protection AND access to grant/revoke others protection/access
"""
    await ctx.send(help_text)


@bot.command()
async def cleardata(ctx):
    if not await ensure_guild_context(ctx):
        return
    if not is_guild_owner(ctx):
        return
    with open(DATA_FILE, "w") as f:
        json.dump(new_default_data(), f, indent=4)
    await ctx.send("reset all data to default!")


from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
