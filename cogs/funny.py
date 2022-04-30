import discord
from typing import Union
from discord.ext import commands
from tempfile import NamedTemporaryFile as create_temp
from utils.bot_vars import CancelView, twitter_rx, twitter_keys, handle, check, btn_check, escape_ansii, FFMPEG
from PIL import Image
import subprocess
import asyncio
import tweepy
import shlex
import io

# connect using the twitter keys in config
auth = tweepy.OAuthHandler(twitter_keys[0], twitter_keys[1])
auth.set_access_token(twitter_keys[2], twitter_keys[3])
api = tweepy.API(auth)

class ReplyView(discord.ui.View):
    def __init__(self, client, msg, reply_id):
        self.msg = msg
        self.client = client
        self.reply_id = reply_id
        super().__init__(timeout = None)

    @discord.ui.button(label="Reply", style=discord.ButtonStyle.primary, custom_id="replyview:reply")
    async def reply(self, button: discord.ui.Button, interaction: discord.Interaction):
        view = CancelView()
        view.children[0].label = "Cancel"
        view.children[0].style = discord.ButtonStyle.secondary

        await interaction.response.send_message("Send a message to use as the reply.", view = view, ephemeral = True)
        
        # get user input
        try:
            # wait for either a message or button press
            done, _ = await asyncio.wait([
                self.client.loop.create_task(self.client.wait_for('message', check=check(interaction), timeout=300)),
                self.client.loop.create_task(self.client.wait_for('interaction', check=btn_check(interaction), timeout=300))
            ], return_when=asyncio.FIRST_COMPLETED)
            
            for future in done:
                msg_or_interaction = future.result()

            # if a button press was received
            if isinstance(msg_or_interaction, discord.interactions.Interaction):
                if view.canceled: 
                    return await interaction.edit_original_message(content = "(canceled)", view = None)
            
            # if a message was received instead
            if isinstance(msg_or_interaction, discord.Message):
                message = msg_or_interaction
            else:
                # got unexpected response
                return await interaction.edit_original_message(content = "**Error:** got a weird response for some reason, please try again (or don't if you wanted to cancel)", view = None)
        except asyncio.TimeoutError:
            await interaction.edit_original_message(content = "**Error:** timed out", view = None)

        await message.delete()
        
        ctx = await self.client.get_context(message)
        status = message.content
        
        # same procedure as a reply command
        content_given = await funny(self.client).get_attachment(ctx, interaction)

        if content_given != False:
            media_ids = funny(self.client).get_media_ids(content_given)
        else:
            media_ids = None
        
        # send the reply
        new_status = api.update_status(status=status, media_ids=media_ids, in_reply_to_status_id=self.reply_id, auto_populate_reply_metadata=True)

        await interaction.edit_original_message(content = "Replied!", view = None)

        # reply to the original message containing the tweet
        new_msg = await self.msg.reply(f"{interaction.user.mention} replied:\nhttps://twitter.com/{handle}/status/{new_status.id}")

        view = ReplyView(self.client, new_msg, new_status.id)
        await new_msg.edit(view = view)

class funny(commands.Cog):
    def __init__(self, client):
        self.client = client
    
    async def cog_check(self, ctx):
        # check if command is sent from funny museum
        if ctx.guild.id != 783166876784001075:
            await ctx.send("**Error:** that command only works in funny museum")
        else:
            return True
    
    async def get_attachment(self, ctx: commands.Context, interaction: discord.Interaction = None):
        """ Get the attachment to use for the tweet """
        # switch to the replied message if it's there
        if ctx.message.attachments:
            msg = ctx.message
        elif ctx.message.reference:
            msg = ctx.message.reference.resolved
        else:
            return False
        
        count = 0
        att_bytes = []

        if not msg.attachments:
            return False
        else:
            for att in msg.attachments:
                if count == 4:
                    break

                if "image" in att.content_type:
                    # if the content is animated, only one can be posted
                    if any(att.content_type == x for x in ["image/gif", "image/apng"]):
                        return ["gif", io.BytesIO(await att.read())]

                    att_bytes.append(io.BytesIO(await att.read()))
                    count += 1
                    continue
                
                if att.filename.lower().endswith("mov"):
                    # convert mov to mp4
                    with create_temp(suffix=".mov") as temp_mov, create_temp(suffix=".mp4") as temp_mp4:
                        if not interaction:
                            processing = await ctx.send(f"{self.client.loading} Processing...")
                        else:
                            processing = await interaction.edit_original_message(content = f"{self.client.loading} Processing...", view = None)

                        temp_mov.write(await att.read())
                        command = shlex.split(f'{FFMPEG} -i {temp_mov.name} -qscale 0 {temp_mp4.name}')
                        
                        p = subprocess.Popen(command)
                        p.wait()

                        # if there was an error running the ffmpeg command
                        if p.returncode != 0:
                            if not interaction:
                                await processing.edit("**Error:** there was an issue converting from mov to mp4")
                            else:
                                processing = await interaction.edit_original_message(content = "**Error:** there was an issue converting from mov to mp4")

                            return False
                        else:
                            return ["video", io.BytesIO(temp_mp4.read())]

                return ["video", io.BytesIO(await att.read())]

            return ["image", att_bytes]
    
    async def get_attachment_obj(self, ctx: commands.Context):
        """ For just getting the attachment only """
        # switch to the replied message if it's there
        if ctx.message.attachments:
            msg = ctx.message
        elif ctx.message.reference:
            msg = ctx.message.reference.resolved
        else:
            return False
        
        if not msg.attachments:
            return False
        else:
            return msg.attachments[0]
        
    def get_media_ids(self, content):
        """ Uploads the given content to twitter and gets the returned media id """
        media_ids = []
        result = content[0]
        media = content[1]

        # chooses between either uploading multiple images or just one video/gif
        if result == "image":
            for image in media:
                # create temporary file to store image data in
                with create_temp(suffix='.png') as temp:
                    # convert image into png in case of filetype conflicts
                    im = Image.open(image)
                    im.convert('RGBA')
                    im.save(temp.name, format='PNG')

                    res = api.media_upload(temp.name)
                    media_ids.append(res.media_id)
        else:
            # store media data in a temporary file
            with create_temp() as temp:
                temp.write(media.getvalue())
                res = api.chunked_upload(temp.name, media_category=f"tweet_{result}")
                media_ids.append(res.media_id)

        return media_ids

    def get_reaction_role(self, emoji: discord.PartialEmoji, guild: discord.Guild):
        if emoji.name == "1️⃣":
            # selected "he/him"
            role = guild.get_role(820126482684313620)
        if emoji.name == "2️⃣":
            # selected "she/her"
            role = guild.get_role(820126584442322984)
        if emoji.name == "3️⃣":
            # selected "they/them"
            role = guild.get_role(820126629945933874)

        return role

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event: discord.RawReactionActionEvent):
        # check if the message being reacted to is the one from funny museum
        if event.message_id == 820147742382751785:
            guild: discord.Guild = self.client.get_guild(event.guild_id)

            # get the corresponding role from the reaction
            role = self.get_reaction_role(event.emoji, guild)
            await event.member.add_roles(role)
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, event: discord.RawReactionActionEvent):
        # check if the message being reacted to is the one from funny museum
        if event.message_id == 820147742382751785:
            guild: discord.Guild = self.client.get_guild(event.guild_id)
            
            # get the corresponding role from the reaction
            role = self.get_reaction_role(event.emoji, guild)

            member = guild.get_member(event.user_id)
            await member.remove_roles(role)

    @commands.command()
    async def tweet(self, ctx: commands.Context, *, status: str = None):
        """ Tweets any message from discord """
        content_given = await self.get_attachment(ctx)

        # gets the media ids to use if an attachment is found
        if content_given != False:
            media_ids = self.get_media_ids(content_given)
        else:
            if status is None:
                raise commands.BadArgument()

            media_ids = None
        
        # sends the tweet
        try:
            new_status = api.update_status(status=status, media_ids=media_ids)
        except Exception as e:
            return await ctx.send(f"**Error:** could not send tweet (full error: ||{escape_ansii(e)}||)")
        
        # tweet sent! so cool
        msg = await ctx.send(f"{self.client.ok} **Tweet sent:**\nhttps://twitter.com/{handle}/status/{new_status.id}")

        view = ReplyView(self.client, msg, new_status.id)
        await msg.edit(view = view)

    @commands.command()
    async def reply(self, ctx: commands.Context, reply_to: Union[str, int] = None, *, status: str = None):
        """ Replies to a given tweet """
        is_chain = False

        # checks if the user wants to reply to a tweet that is in a different message
        if ctx.message.reference and not twitter_rx.match(reply_to):
            # .reply hello there
            #          ^ this is not intended to be used as the reply id, so add it to the existing status
            status = f"{reply_to} {status}" if status else reply_to
            reply_to = ctx.message.reference.resolved.content
            is_chain = True
        
        # if nothing is given at all
        if reply_to is None:
            raise commands.BadArgument()
        
        # if reply_to is not numeric, treat it as a url
        if not reply_to.isnumeric():
            # except if it's "latest", then use the latest tweet
            if reply_to == "latest":
                reply_id = api.user_timeline(screen_name = handle, count = 1)[0].id
            else:
                url = twitter_rx.search(reply_to)
                
                if url is None:
                    return await ctx.send("**Error:** could not find tweet url/id")
                
                reply_id = int(url.group(2))
        else:
            # if an id is given
            reply_id = int(reply_to)

        content_given = await self.get_attachment(ctx)

        # check for attachments and create media ids
        if content_given != False:
            media_ids = self.get_media_ids(content_given)
        else:
            if status is None:
                return commands.BadArgument()

            media_ids = None
        
        # send the reply
        try:
            new_status = api.update_status(status=status, media_ids=media_ids, in_reply_to_status_id=reply_id, auto_populate_reply_metadata=True)
        except tweepy.NotFound:
            return await ctx.send("**Error:** could not find tweet from the given url/id")
        except Exception as e:
            return await ctx.send(f"**Error:** could not send tweet (full error: ||{escape_ansii(e)}||)")
        
        if not is_chain:
            replied_to = api.get_status(reply_id)
            msg = await ctx.send(f"{self.client.ok} **Reply sent:**\nhttps://twitter.com/{replied_to.user.screen_name}/status/{replied_to.id}\nhttps://twitter.com/{handle}/status/{new_status.id}")
        else:
            await ctx.message.delete()
            await ctx.message.reference.resolved.reply(f"{ctx.author.mention} replied:\nhttps://twitter.com/{handle}/status/{new_status.id}")

        view = ReplyView(self.client, msg, new_status.id)
        await msg.edit(view = view)
        
    @commands.command(aliases=['pf'])
    async def profile(self, ctx: commands.Context, kind: str = None):
        """ Changes the twitter account's profile picture/banner """
        if kind is None:
            raise commands.BadArgument()

        att = await self.get_attachment_obj(ctx)

        if att is False:
            embed = self.error_create("no image attachment was found")
            return await ctx.send(embed = embed)

        # if an image is given
        if "image" in att.content_type and any(att.content_type != x for x in ["image/gif", "image/apng"]):
            processing = await ctx.send(f"{self.client.loading} Resizing image...")

            img = Image.open(io.BytesIO(await att.read()))

            try:
                with create_temp(suffix=".png") as temp:
                    # resize into a square for pfp
                    if any(kind == x for x in ["p", "picture"]):
                        kind = "picture"

                        img = img.convert('RGBA').resize((512, 512))

                        img.save(temp.name, format="PNG")
                        api.update_profile_image(filename=temp.name)

                    # resize into a rectangle for banner
                    elif any(kind == x for x in ["b", "banner"]):
                        kind = "banner"

                        img = img.convert('RGBA').resize((1500, 500))

                        img.save(temp.name, format="PNG")
                        api.update_profile_banner(filename=temp.name)

                    else:
                        await processing.delete()
                        raise commands.BadArgument()
            except Exception as e:
                await processing.delete()
                return await ctx.send(f"**Error:** could not set profile {kind} (full error: ||{escape_ansii(e)}||)")

            await processing.delete()
            
            # it worked
            await ctx.send(f"{self.client.ok} **The profile {kind} has been set:**\nhttps://twitter.com/{handle}")
        else:
            return await ctx.send("**Error:** attachment is not an image")

def setup(bot):
    bot.add_cog(funny(bot))