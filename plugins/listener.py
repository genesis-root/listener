from disco.bot import Plugin
from disco.bot.command import CommandError
from disco.voice.client import VoiceException

import opuslib.api
import opuslib.api.decoder
import opuslib.api.ctl


class Listener:
    def __init__(self, client):
        self.client = client
        self.is_recording = False
        # TODO: prevent collisions
        self.ofile = None
        self.dec = opuslib.api.decoder.create_state(48000, 2)

class ListenerPlugin(Plugin):

    def load(self, ctx):
        super(ListenerPlugin, self).load(ctx)
        self.guild_listeners = {}

    @Plugin.command('join')
    def on_join(self, event):
        user_state = event.guild.get_member(event.author).get_voice_state()
        if not user_state:
            return event.msg.reply('You must be in a voice channel to use that command.')
        listener = self.guild_listeners.get(event.guild.id)
        if listener:
            if listener.client.channel.id == event.channel.channel_id:
                return event.msg.reply("I'm already in that voice channel.")
            else:
                listener.client.disconnect()
                del(self.guild_listeners[event.guild.id])

        try:
            client = user_state.channel.connect()
        except VoiceException as e:
            return event.msg.reply('Failed to connect to voice: `{}`'.format(e))
        self.guild_listeners[event.guild.id] = Listener(client)
        # Seems that bot needs to have sent some amount of audio before it is able to record
        client.send_frame(bytes(0))

    @Plugin.command('leave')
    def on_leave(self, event):
        listener = self.guild_listeners.get(event.guild.id)
        if not listener:
            return event.msg.reply("I'm already not in any voice channel on this server.")
        else:
            listener.client.disconnect()
            if listener.ofile:
                listener.ofile.close()
            del(self.guild_listeners[event.guild.id])


    @Plugin.command('record')
    def on_record(self, event):
        listener = self.guild_listeners.get(event.guild.id)
        if not listener:
            return event.msg.reply("I'm not in any voice channel on this server.")
        if listener.is_recording:
            return event.msg.reply("I'm already recording.")
        listener.ofile = open("out.raw", 'wb')
        listener.is_recording = True

        user = event.guild.get_member(event.author)
        event.msg.reply("Recording: {}".format(user))

    @Plugin.command('stop')
    def on_stop(self, event):
        listener = self.guild_listeners.get(event.guild.id)
        if not listener:
            return event.msg.reply("I'm not in any voice channel on this server.")
        if not listener.is_recording:
            return event.msg.reply("I'm not recoding at the moment.")
        listener.ofile.close()
        listener.is_recording = False
        event.msg.reply("Stopped recording.")

    @Plugin.listen('VoiceData')
    def on_voice_data(self, event):
        listener = self.guild_listeners.get(event.client.guild().id)
        if listener.is_recording:
            user = event.client.guild().get_member(event.user_id)
            print("VOICE DATA from {}, type: {}, rtp: {}, nonce: {}, len(event.data): {}".format(user, event.payload_type, event.rtp, event.nonce, len(event.data)))
            frame_size = int((48000) * len(event.data))
            pcm = opuslib.api.decoder.decode(listener.dec, event.data, len(event.data), frame_size, 0)
            listener.ofile.write(pcm)
