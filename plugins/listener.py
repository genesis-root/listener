import io
import queue
import wave

from disco.bot import Plugin, Config
from disco.bot.command import CommandError
from disco.voice.client import VoiceException
import opuslib
import speech_recognition as sr

class PCM2WAVStream:
    def __init__(self):
        self.buffer = io.BytesIO()
        self.wav = wave.open(self.buffer, 'wb')
        self.wav.setparams((2, 2, 48000, 0, 'NONE', 'NONE'))

    def write(self, pcm):
        self.wav.writeframes(pcm)

    def seek(self, n):
        self.buffer.seek(n)

    def read(self, n=None):
        if not n:
            return self.buffer.read()
        else:
            return self.buffer.read(n)

    def dump(self, fname):
        self.buffer.seek(0)
        with open(str(fname) + ".wav", "wb") as ofile:
            ofile.write(self.buffer.read())

    def close(self):
        self.wav.close()
        self.buffer.close()

class ListenerPluginDefaultConfig(Config):
    wit_api_key = ""

class Listener:
    def __init__(self, client):
        self.client = client
        self.is_recording = False
        # TODO: prevent collisions
        self.user_ofiles = {}
        self.dec = opuslib.Decoder(48000, 2)
        self.wqueue = queue.Queue()

@Plugin.with_config(ListenerPluginDefaultConfig)
class ListenerPlugin(Plugin):
    def load(self, ctx):
        super(ListenerPlugin, self).load(ctx)
        self.wit_api_key = self.config.get('wit_api_key')
        self.guild_listeners = {}
        self.rec = sr.Recognizer()

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
            for (uid, f) in listener.user_ofiles.items():
                f.close()
            listener.user_ofiles = {}
            del(self.guild_listeners[event.guild.id])


    @Plugin.command('record')
    def on_record(self, event):
        listener = self.guild_listeners.get(event.guild.id)
        if not listener:
            return event.msg.reply("I'm not in any voice channel on this server.")
        if listener.is_recording:
            return event.msg.reply("I'm already recording.")
        listener.is_recording = True

        user = event.guild.get_member(event.author)
        event.msg.reply("Recording: {}".format(user))
        while(listener.is_recording):
            user_id, pcm = listener.wqueue.get()
            if user_id:
                if user_id not in listener.user_ofiles:
                    # listener.user_ofiles[user_id] = open(str(user_id) + ".raw", 'wb')
                    listener.user_ofiles[user_id] = PCM2WAVStream()
                listener.user_ofiles[user_id].write(pcm)
                #listener.user_ofiles[user_id].flush()
        event.msg.reply("Stopped recording, transcribing...")
        for (uid, f) in listener.user_ofiles.items():
            audio = None
            f.seek(0)
            with sr.AudioFile(f) as source:
                audio = self.rec.record(source)  # read the entire audio file
                if audio:
                    text = ""
                    try:
                        text = self.rec.recognize_wit(audio, key=self.wit_api_key)
                    except sr.UnknownValueError:
                        print("WIT.ai could not understand audio")
                    except sr.RequestError as e:
                        print("Could not request results from WIT.ai; {0}".format(e))
            if not text:
                event.msg.reply("Could not tell what {} said".format(user))
            else:
                event.msg.reply("{} said: {}".format(user, text))
            f.dump(uid)
            f.close()
        listener.user_ofiles = {}

    @Plugin.command('stop')
    def on_stop(self, event):
        listener = self.guild_listeners.get(event.guild.id)
        if not listener:
            return event.msg.reply("I'm not in any voice channel on this server.")
        if not listener.is_recording:
            return event.msg.reply("I'm not recoding at the moment.")
        listener.is_recording = False
        listener.wqueue.put((None, bytes(0))) # need to trigger last queue read iteration

    @Plugin.listen('VoiceData')
    def on_voice_data(self, event):
        listener = self.guild_listeners.get(event.client.guild().id)
        if listener.is_recording:
            user = event.client.guild().get_member(event.user_id)
            print("VOICE DATA from {}, type: {}, rtp: {}, nonce: {}, len(event.data): {}".format(user, event.payload_type, event.rtp, event.nonce, len(event.data)))
            frame_size = int((48000) * len(event.data))
            pcm = listener.dec.decode( event.data, frame_size)
            listener.wqueue.put((event.user_id, pcm))
