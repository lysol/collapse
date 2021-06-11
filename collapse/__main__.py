# -*- coding: utf-8 -*-
import irc
import irc.buffer
irc.buffer.DecodingLineBuffer.errors = 'replace'
import irc.bot
import irc.client
from optparse import OptionParser
import configparser
import queue
import random
import threading
import os, sys
import io
import string
from unidecode import unidecode
import collapse.collapseCore as collapseCore
try:
    import inotify.adapters
    INOTIFY_PRESENT = True
except AttributeError:
    INOTIFY_PRESENT = False


class CollapseReactor(irc.client.Reactor):

    def __init__(self, *args, **kwargs):
        self.process_callbacks = []
        irc.client.Reactor.__init__(self, *args, **kwargs)

    def add_process_callback(self, cb):
        self.process_callbacks.append(cb)

    def process_once(self, timeout=0):
        irc.client.Reactor.process_once(self, timeout=timeout)
        for cb in self.process_callbacks:
            cb(self)


class CollapseBot(irc.bot.SingleServerIRCBot):

    """The main IRC bot
    
    Attributes:
        callbacks (dict): a dict of callbacks
        channel (str): the primary channel name
        collapse (Collapse): The collapseCore singleton
        collapse_thread (Thread): the main thread
        debug (bool): Should we print stuff out
        inotify (Inotify): Inotify
        inotify_generator (event_gen): event_gen
        log (dict): internal log of channels
        queue (Queue): Timed events ran in the background
        reactor_class (CollapseReactor): internal irc lib stuff
        scheduled (bool): Make sure the queue is always depleting
        settings (dict): settings from conf file
        threads (list): list of Threads
        useThreads (bool): use a thread?
    """
    
    reactor_class = CollapseReactor
    queue = queue.Queue()
    threads = []
    callbacks = {}

    def __init__(self, settings):
        if 'port' not in settings:
            port = 6667
        else:
            port = settings['port']

        self.settings = settings
        self.useThreads = 'use_threads' not in settings or \
            settings['use_threads']

        irc.bot.SingleServerIRCBot.__init__(self, [(settings['server'], port)],
            settings['nick'], settings['user'])

        self.channel = settings['channel']
        self.scheduled = False
        self.schedule_cycle(0)
        self.log = {}
        if 'debug' in settings:
            print("debug mode on")
            self.debug = True

        self._collapse_lock = threading.Lock()
        self._initialize_collapse()

        if INOTIFY_PRESENT:
            inotify_dir = '/tmp/%s' % settings['nick']
            reply_dir = '/tmp/%s_replies' % settings['nick']
            if not os.path.exists(inotify_dir):
                os.mkdir(inotify_dir)
            if not os.path.exists(reply_dir):
                os.mkdir(reply_dir)

            print("Initializing inotify")
            self.inotify = inotify.adapters.Inotify()
            self.inotify.add_watch(inotify_dir)
            self.inotify.add_watch(reply_dir)
            self.inotify_generator = self.inotify.event_gen()
            self._run_inotify()

    def _initialize_collapse(self):
        def _c():
            self._collapse_lock.acquire()
            self.collapse = collapseCore.Collapse(self.settings)
            self.collapse.register_status_callback(self._handle_status_reply)
            self._collapse_lock.release()
        self.collapse_thread = threading.Thread(target=_c)
        self.collapse_thread.start()

    def _handle_status_reply(self, replies):
        self._handle_messages(self.connection, self.channel, replies)

    def _handle_callback(self, func, tid, args, **kwargs):
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            result = e
        self.queue.put((tid, result))
        if not self.scheduled:
            self.schedule_cycle()

    def _create_thread(self, target, func, args=[], kwargs={}):
        tid = random.randint(0, 65535)
        self.threads.append(threading.Thread(target=target,
            args=[func, tid, args], kwargs=kwargs))
        self.threads[-1].start()
        return tid

    def say(self, connection, target, message):
        """say something on irc
        
        Args:
            connection (TYPE): connection
            target (str): the place we're saying it
            message (str): the message
        """
        self._handle_messages(connection, target, message)

    def set_callback(self, c, reply_to, func, args=[], kwargs={}):
        """execute some stuff async
        
        Args:
            c (TYPE): Description
            reply_to (TYPE): Description
            func (TYPE): Description
            args (list, optional): Description
            kwargs (dict, optional): Description
        """
        if self.useThreads:
            tid = self._create_thread(self._handle_callback, func, args, kwargs)
            self.callbacks[tid] = lambda replies: self._handle_messages(c, reply_to, replies)
        else:
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                result = e
            self._handle_messages(c, reply_to, result)
            if not self.scheduled:
                self.schedule_cycle()

    def _run_inotify(self):
        """looks for files from the streaming connection that twitter no longer supports,
           so this doesn't work anymore anyway
        """
        try:    
            event = next(self.inotify_generator)
            if event is not None:
                (_, type_names, path, filename) = event
                fullpath = '%s/%s' % (path, filename)
                if 'IN_CLOSE_WRITE' in type_names and os.path.exists(fullpath):
                    o = io.open(fullpath, mode="r", encoding="utf-8")
                    contents = o.read().split('\n')
                    o.close()
                    os.unlink(fullpath)
                    if '_replies' not in fullpath:
                        self._handle_messages(self.connection, self.channel,
                            contents)
                    else:
                        # actual reply from twitter. filename is the id
                        self._handle_messages(self.connection,
                            self.channel, self.collapse.process_tweet(filename))

        except UnicodeDecodeError as e:
            print(e)
        self.connection.reactor.scheduler.execute_after(0.5,
            self._run_inotify)

    def _timed_events(self):
        """Process timed events in plugins, and thread callbacks."""
        # print 'Processing events'
        try:
            result = self.queue.get(False)
            while len(result) > 0 and result[0] in list(self.callbacks.keys()):
                # print 'queue contents' + repr(result)
                self.callbacks[result[0]](result[1])
                del(self.callbacks[result[0]])
        except queue.Empty:
            self.scheduled = False
            # print 'Queue emptied.'
            return
        self.schedule_cycle()

    def schedule_cycle(self, delay=0.001):
        """fire off the timed events
        
        Args:
            delay (float, optional): how long to wait
        """
        self.connection.reactor.scheduler.execute_after(delay,
            self._timed_events)
        self.scheduled = True

    def _log(self, channel, nick, message):
        """logs message from users
        
        Args:
            channel (str): the channel we're in
            nick (str): the sender
            message (str): the message
        """
        if channel:
            if channel not in self.log:
                self.log[channel] = {}
            if nick not in self.log[channel]:
                self.log[channel][nick] = []
            self.log[channel][nick].append(message)
            while len(self.log[channel][nick]) > 100:
                self.log[channel][nick].pop(0)
        else:
            if nick not in self.log:
                self.log[nick] = []
            self.log[nick].append(message)
            while len(self.log[nick]) > 100:
                self.log[nick].pop(0)

    def on_nicknameinuse(self, c, e):
        """event handler for nickname in use
        
        Args:
            c (TYPE): conn
            e (TYPE): context
        """
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        if self.debug:
            print(e.arguments[0])
        if 'pass' in self.settings:
            c.privmsg('nickserv', 'identify ' + self.settings['pass'])
        if 'key' in self.settings:
            c.join(self.channel, self.settings['key'])
        else:
            c.join(self.channel)

    def on_privmsg(self, c, e):
        if self.debug:
            print("%s\t%s" % (e.source, e.arguments[0]))
        self._command_check(c, e, e.source.nick)
        self._log(None, e.source.nick, e.arguments[0])

    def on_notice(self, c, e):
        if self.debug:
            print("%s: %s" % (e.source, e.arguments[0]))

    def on_join(self, c, e):
        if self.debug:
            print("Joined %s" % e.target)
        if e.target not in self.log:
            self.log[e.target] = {}

    def on_part(self, c, e):
        if self.debug:
            print("Parted %s" % e.target)

    def on_kick(self, c, e):
        if self.debug:
            print("%s kicked from %s by %s" % (e.arguments[0], e.target,
                e.source))

    def on_pubmsg(self, c, e):
        if self.debug:
            try:
                print("%s %s\t%s" % (e.target, e.source, e.arguments[0]))
            except UnicodeEncodeError:
                print("oops some unicode", end=' ')
        if not self.collapse.nick_ignored(e.source.nick):
            self._command_check(c, e, e.target)
            def _noop(func, tid, args, **kwargs):
                pass
            self._create_thread(_noop, self._log,
                [e.target, e.source.nick, e.arguments[0]])

    def _handle_messages(self, c, reply_to, replies):
        """main message handler for bot
        
        Args:
            c (object): connection
            reply_to (str): the sender
            replies (TYPE): messages
        """
        if type(replies) != list:
            replies = [replies]
        replies = [line for line in replies if type(line) in (str, str) and \
            line is not None and line.strip() != '']
        for reply in replies:
            if type(reply) == str:
                try:
                    reply = str(reply.encode('utf-8'))
                except UnicodeDecodeError as e:
                    if 'owner' in self.settings:
                        c.privmsg(reply_to,
                            '%s: I am bad at computers' % \
                            self.settings['owner'])
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    print((exc_type, fname, exc_tb.tb_lineno))
                    print(e)
            if type(reply) == str:
                if len(reply) > 256:
                    # kinda just give up if the line is too long
                    reply = reply[:256] + '🌽🌽🌽'
                if reply[:3] == '/me':
                    c.action(reply_to, reply[4:])
                else:
                    c.privmsg(reply_to, reply)
            elif type(reply) == type(Exception):
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print((exc_type, fname, exc_tb.tb_lineno))
                print(e)
            elif reply is not None:
                print(repr(reply))

    def _wait_for_all_threads(self):
        """wait
        """
        for thread in self.threads:
            thread.join()

    def _command_check(self, c, e, reply_to):
        """Process commands that have corresponding methods.
        
        Args:
            c (TYPE): connection
            e (TYPE): context
            reply_to (str): sender/channel
        """
        sender = e.source.nick
        reply_to = e.target
        arg = e.arguments[0]
        # check for command prefix
        if self.settings['prefix'] != '':
            prefixlen = len(self.settings['prefix'])
            prefixmatch = arg[:prefixlen] == self.settings['prefix']
            if prefixmatch:
                arg = arg[prefixlen:]
        else:
            prefixmatch = True

        cmds = arg.split(' ')
        self.set_callback(c, reply_to, self.collapse.said, args=[e.source.nick, arg])
        self.set_callback(c, reply_to, self.collapse.handle_command, args=[sender, arg, reply_to])

    def stop_tweepy(self):
        """kill tweepy
        """
        self._collapse_lock.acquire()
        self.collapse.stop_tweepy()
        self._collapse_lock.release()


def load_settings(filename):
    """load settings from file
    
    Args:
        filename (str): path to file
    
    Returns:
        dict: dict of settings
    """
    settings = {'prefix': ''}
    config = configparser.ConfigParser()
    config.read(filename)
    for option in config.options("bot"):
        if option in ['expand_urls', 'use_threads']:
            settings[option] = config.getboolean('bot', option)
        else:
            settings[option] = config.get("bot", option)

    if 'banned_urls' not in settings:
        settings['banned_urls'] = []
    settings['filename'] = filename
    return settings

def main():
    """main entrypoint
    """
    parser = OptionParser()

    (options, args) = parser.parse_args()

    if len(args) != 1:
        print("Usage: bot.py configfile")
        exit(1)

    settings = load_settings(args[0])

    bot = CollapseBot(settings)
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop_tweepy()

if __name__ == "__main__":
    main()
