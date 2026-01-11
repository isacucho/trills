import discord
from discord.ext import commands
import json
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='^', intents=intents)

OWNER_ID = 1137978737573503007
DATA_FILE = 'data.json'

default_data = {
    'protected_ids': [str(OWNER_ID)],
    'ban_channels': [],
    'allowed_users': [str(OWNER_ID)],
    'banned_users': []
}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return default_data

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@bot.event
async def on_ready():
    print(f'{bot.user} is ready')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="sending scammers to a far away land rn // ^about for help"))

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    data = load_data()
    
    if str(message.channel.id) in data['ban_channels']:
        if str(message.author.id) in data['protected_ids']:
            return await bot.process_commands(message)
        
        try:
            await message.author.ban(reason=f'instabanned due to typing in a monitored channel', delete_message_days=0)
            await message.delete()
            if str(message.author.id) not in data['banned_users']:
                data['banned_users'].append(str(message.author.id))
                save_data(data)
        except:
            pass
        return
    
    await bot.process_commands(message)

@bot.command()
async def add(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users'] or str(ctx.author.id) not in data['protected_ids']:
        return
    if str(user_id) not in data['protected_ids']:
        data['protected_ids'].append(str(user_id))
        save_data(data)
        await ctx.send(f'added {user_id} to protected list!')
    else:
        await ctx.send(f'{user_id} is already protected LOL')

@bot.command()
async def remove(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users'] or str(ctx.author.id) not in data['protected_ids']:
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't unprotect yourself!")
    if user_id == OWNER_ID:
        return await ctx.send('error: could not remove {user_id}')
    if str(user_id) in data['protected_ids']:
        data['protected_ids'].remove(str(user_id))
        save_data(data)
        await ctx.send(f'removed {user_id} from protected list!')
    else:
        await ctx.send(f'{user_id} isn\'t even in the protected list!')

@bot.command()
async def toggle(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users'] or str(ctx.author.id) not in data['protected_ids']:
        return
    if user_id == OWNER_ID:
        return await ctx.send('error: could not toggle {user_id}')
    if str(user_id) in data['protected_ids']:
        data['protected_ids'].remove(str(user_id))
        await ctx.send(f'removed {user_id} from protected list!')
    else:
        data['protected_ids'].append(str(user_id))
        await ctx.send(f'added {user_id} to protected list!')
    save_data(data)

@bot.command()
async def ban(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't ban yourself!")
    if str(user_id) in data['protected_ids']:
        return await ctx.send('can\'t ban a protected user LOL')
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.ban(user, reason='manually banned')
        if str(user_id) not in data['banned_users']:
            data['banned_users'].append(str(user_id))
            save_data(data)
        await ctx.send(f'successfully banned {user_id}!')
    except:
        await ctx.send('error: failed to ban user')

@bot.command()
async def unban(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        if str(user_id) in data['banned_users']:
            data['banned_users'].remove(str(user_id))
            save_data(data)
        await ctx.send(f'successfully unbanned {user_id}!')
    except:
        await ctx.send('error: failed to unban user')

@bot.command()
async def kick(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't kick yourself!")
    if str(user_id) in data['protected_ids']:
        return await ctx.send('can\'t kick a protected user LOL')
    try:
        member = ctx.guild.get_member(user_id)
        if member is None:
            return await ctx.send('user not found in this server!')
        await member.kick(reason='manually kicked')
        await ctx.send(f'successfully kicked {user_id}!')
    except:
        await ctx.send('error: failed to kick user')

@bot.command()
async def instaban(ctx, channel_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    if str(channel_id) not in data['ban_channels']:
        data['ban_channels'].append(str(channel_id))
        save_data(data)
        await ctx.send(f'enabled instant ban-on-type for channel {channel_id}!')
    else:
        await ctx.send(f'the channel {channel_id} already has instant ban-on-type enabled!')

@bot.command()
async def uninstaban(ctx, channel_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    if str(channel_id) in data['ban_channels']:
        data['ban_channels'].remove(str(channel_id))
        save_data(data)
        await ctx.send(f'disabled instant ban-on-type for channel {channel_id}!')
    else:
        await ctx.send(f'the channel {channel_id} doesn\'t even have instant ban-on-type enabled LOL')

@bot.command()
async def access(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users'] or str(ctx.author.id) not in data['protected_ids']:
        return
    if str(user_id) not in data['allowed_users']:
        data['allowed_users'].append(str(user_id))
        save_data(data)
        await ctx.send(f'granted access to {user_id}! they can now use my commands :P')
    else:
        await ctx.send(f'{user_id} already has access to my commands!')

@bot.command()
async def revoke(ctx, user_id: int):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users'] or str(ctx.author.id) not in data['protected_ids']:
        return
    if user_id == ctx.author.id:
        return await ctx.send("you can't revoke your own access!")
    if user_id == OWNER_ID:
        return await ctx.send("error: could not remove owner's access")
    if str(user_id) in data['allowed_users']:
        data['allowed_users'].remove(str(user_id))
        save_data(data)
        await ctx.send(f"revoked {user_id}'s access!")
    else:
        await ctx.send(f"{user_id} doesn't even have access!")

@bot.command()
async def echo(ctx, *, message):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    await ctx.send(message)

@bot.command()
async def listprotected(ctx):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    protected = ', '.join(data['protected_ids']) if data['protected_ids'] else 'None'
    await ctx.send(f'protected user IDs: {protected}')

@bot.command()
async def listchannels(ctx):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    channels = ', '.join(data['ban_channels']) if data['ban_channels'] else 'None'
    await ctx.send(f'ban-on-type channels: {channels}')

@bot.command()
async def listaccess(ctx):
    data = load_data()
    if str(ctx.author.id) not in data['allowed_users']:
        return
    access_list = ', '.join(data['allowed_users']) if data['allowed_users'] else 'None'
    await ctx.send(f'allowed users: {access_list}')

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
- typing in instant-ban channels results in an *immediate* ban (unless protected)
- both protection AND access are needed to grant/revoke others protection/access
"""
    await ctx.send(help_text)

@bot.command()
async def cleardata(ctx):
    if ctx.author.id != OWNER_ID:
        return
    with open(DATA_FILE, 'w') as f:
        json.dump(default_data, f, indent=4)
    await ctx.send('reset all data to default!')

from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if TOKEN:
    bot.run(TOKEN)
