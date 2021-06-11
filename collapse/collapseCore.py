# -*- coding: utf-8 -*-

import json
from time import sleep, time
import tweepy
import tweepy.error
import sys
from datetime import datetime
import subprocess
import os
import os.path
import hashlib
import string
import shelve
from html.parser import HTMLParser
from collapse.expandurl import ExpandURL, make_result
from babel.dates import format_timedelta
from threading import Thread, Lock
import random
import logging
from collapse.namespacedBrain import NamespacedBrain
from collapse.imagegetter import ImageGetter
import requests
import requests.exceptions
import re
import textwrap
import traceback

class Collapse(object):
    """Core bot functionality, mostly separate from the IRC functionality
    
    Attributes:
        brain (Brain): Brain instance
        brain_lock (Lock): The lock used during writes to the brain
        collapse_api (tweepy.API): Tweepy instance
        collapse_auth (tweepy.OAuthHandler): Tweepy auth object
        expand_urls (bool): Whether we should expand shorturls
        expandedURLs (dict): The dict of expanded urls so we don't spam HTTP requests
        expandURL (ExpandURL): ExpandURL instance
        image_getter (ImageGetter): ImageGetter instance
        insults (list): a list of colorful adjectives 
        me (object): tweepy me()
        settings (dict): a dict of settings retrieved from the conf file
        status_callbacks (list): A list of callbacks to execute
        twitter_timeout (int): timeout used for twitter actions
    """
    
    def __init__(self, settings):
        """constructor
        
        Args:
            settings (dict): a dict of settings from the conf file
        """
        self.brain_lock = Lock()
        insult_data = json.load(
            open(os.path.join(os.path.dirname(__file__), 'insults.json'), 'r'))
        if 'insults' in insult_data:
            self.insults = insult_data['insults']
        self.brain = NamespacedBrain()
        self.settings = settings
        self.collapse_auth = tweepy.OAuthHandler(
            settings['consumer_key'],
            settings['consumer_secret']
            )

        self.twitter_timeout = int(settings['twitter_timeout']) if 'twitter_timeout' in settings else 5
        self.collapse_api = None
        self._start_twitter()
        self.status_callbacks = []
        self.expand_urls = 'expand_urls' in self.settings and \
            self.settings['expand_urls']
        self.image_getter = ImageGetter()
        self.expandURL = ExpandURL()
        self.expandedURLs = {}

    def _start_twitter(self):
        try:
            self.lock()
            if 'collapse_access_token_key' in self.brain:
                self.collapse_auth.set_access_token(
                    self.brain['collapse_access_token_key'],
                    self.brain['collapse_access_token_secret']
                    )
                self.unlock()
            else:
                auth_url = self.collapse_auth.get_authorization_url()
                print("Visit this URL and enter the code here when presented.")
                print(auth_url)
                code = eval(input("> "))
                access_token = self.collapse_auth.get_access_token(str(code))
                self.brain['collapse_access_token_key'] = access_token[0]
                self.brain['collapse_access_token_secret'] = access_token[1]
                self.unlock()
            self.collapse_api = tweepy.API(self.collapse_auth, timeout=self.twitter_timeout)
            self.me = self.collapse_api.me()
        except tweepy.error.TweepError as e:
            logging.exception(e)

    def lock(self):
        return self.brain_lock.acquire()

    def unlock(self):
        return self.brain_lock.release()

    def handle_status_callbacks(self, status):
        """Summary
        
        Args:
            status (object): A tweet object
        
        Returns:
            None: None
        """
        self.lock()
        futures = self.get_url_futures(status._json['full_text'])

        key = 'twitter_user_%s_last_id' % status.user.screen_name.lower()
        self.brain[key] = status.id
        self.unlock()
        if status.user.screen_name == self.me.screen_name:
            return
        for cb in self.status_callbacks:
            if status.user.screen_name != 'JuffoPager':
                cb(self.ircify(status.user.screen_name, status._json['full_text']),
                    futures)#, emoji=u'🐦')

    def register_status_callback(self, func):
        """Summary
        
        Args:
            func (callable): a function to use as a callback
        """
        self.status_callbacks.append(func)

    def stop_tweepy(self):
        pass

    def _brain_filter(self, key_prefix):
        """Returns a subset dict of stuff from the brain
        
        Args:
            key_prefix (str): what to filter one
        
        Returns:
            dict: what you want
        """
        keys_filtered = [k for k in self.brain if k[:len(key_prefix)] == key_prefix]
        return dict([(k, self.brain[k]) for k in keys_filtered])

    def get_url_futures(self, text):
        """open requests for all the urls from the text
        
        Args:
            text (str): The body of text to open requests for
        
        Returns:
            list: list of futures
        """
        futures = []
        parts = text.split(' ')
        for part in parts:
            part = ''.join([x for x in part if x in string.printable])
            if part.startswith('https://') or part.startswith('http://'):
                brainkey = 'expanded_' + self._hexurl(part)
                if brainkey not in self.brain:
                    futures.append(self.expandURL.expand(part))
        return futures

    def expand_text_urls(self, text, futures):
        """Expands short URLs in text if necessary
        
        Args:
            text (str): the text
            futures (list): a list of requests futures
        
        Returns:
            str: The text with expanded URLs
        """
        expanded = {}
        parts = text.split(' ')        
        def get_expanded(result):
            if result['status'] and result['end_url'] != result['start_url']:
                unwww = lambda x: x.replace('www.', '')
                shorturl_domain_name = result['start_url'] + ' (' + \
                    unwww(result['end_domain_name']) + ')'
                end_url = result['end_url']
                max_length = 70
                # if it's too long, keep the short url and
                # append the domain name.
                if len(end_url) < max_length:
                    expanded[result['start_url']] = end_url
                elif len(result['start_url']) < max_length - len(shorturl_domain_name):
                    # if the shorter url is really shorter, append
                    # the domain name.
                    expanded[result['start_url']] = shorturl_domain_name            
        for future in futures:
            result = future.finish()
            get_expanded(result)      
        for part in parts:
            part = ''.join([x for x in part if x in string.printable])
            if (part.startswith('https://') or part.startswith('http://')) and \
                part not in expanded:
                key = 'expanded_' + self._hexurl(part)
                if key in self.brain:
                    get_expanded(make_result(part, self.brain[key]))
        for src_url in expanded:
            text = text.replace(src_url, expanded[src_url])
        return text

    def _hexurl(self, url):
        """sha1 a URL
        
        Args:
            url (str): the url
        
        Returns:
            str: the sha1 hash of a URL
        """
        h = hashlib.sha1()
        h.update(url)
        return h.hexdigest()

    def handle_command(self, sender, message):
        """Handles a command from a user
        
        Args:
            sender (str): the nick of the sender
            message (str): the message used as a command
        
        Returns:
            list: a list of lines to send back
        
        Raises:
            e: the passed exception
        """
        cmds = message.split(' ')
        cmd = cmds.pop(0)
        arg_message = ' '.join(cmds)
        if self.nick_ignored(sender):
            return

        # I'm sorry about this.
        try:
            if cmd == 'twit':
                return self.twit(arg_message)
            elif cmd == 'untwit':
                target_id = None
                if arg_message != '':
                    target_id = int(arg_message)
                return self.untwit(target_id)
            elif cmd == 'quote' and len(cmds) > 0:
                extra = ' '.join(cmds[1:])
                nick = cmds[0]
                if not self.nick_ignored(nick) and sender != nick:
                    return self.quote(nick, extra)
            elif cmd == 'reply' and len(cmds) > 1:
                handle_or_id = cmds[0]
                return self.reply(handle_or_id, arg_message)
            elif cmd == 'twitter' and len(cmds) == 1 and cmds[0] == 'help':
                return self.syntax()
            elif cmd == 'insult':
                return self.insult()
            elif cmd == 'corn':
                return self.corn()
            elif cmd == 'unicorn':
                return ['RIP ⚰️']
            elif cmd == 'bicorn':
                return self.corn(num=2)
            elif cmd == 'ｃｏｒｎ':
                return self.corn(pop=True)
            elif cmd == 'ｕｎｉｃｏｒｎ':
                return self.corn(num=1, pop=True)
            elif cmd == 'man' and len(cmds) > 0 and cmds[0] == 'the':
                return self.battlestations()
            salute = self.salute(message)
            if salute is not None:
                return salute

            if self.is_owner(sender):
                # admin commands
                self._log('admin command')
                if cmd == 'status':
                    return self.status()
                elif cmd == 'set':
                    if cmds[0] == 'twitter':
                        self._start_twitter()
                        return ['restarting twitter']
                elif cmd == 'ignore' and len(cmds) > 0:
                    return self.ignore(cmds[0])
                elif cmd == 'unignore' and len(cmds) > 0:
                    return self.unignore(cmds[0])
                elif cmd == 'ignored' and 'ignore_nicks' in self.settings:
                    return [self.settings['ignore_nicks']]

            # handle reposted urls
            urls = self._get_urls(message)
            if urls:
                return self.url(urls, author=sender)

            filterer = re.compile(r"[^a-z ]+", re.IGNORECASE)
            message_filtered = filterer.sub(" ", message)

        except Exception as e:
            logging.exception(e)
            self.unlock()
            raise e

    def is_owner(self, sender):
        """is the nick the owner?
        
        Args:
            sender (str): who is it
        
        Returns:
            bool: yep
        """
        return 'owner' in self.settings and sender == self.settings['owner']

    def _get_urls(self, text):
        urls = []
        parts = text.split(' ')
        for part in parts:
            part = ''.join([x for x in part if x in string.printable])
            if part.startswith('https://') or part.startswith('http://') and \
                part not in self.settings['banned_urls']:
                urls.append(part)
        return urls

    def nick_ignored(self, nick):
        """is this nick ignored?
        
        Args:
            nick (str): you know it
        
        Returns:
            bool: yep
        """
        if 'ignore_nicks' not in self.settings:
            return False
        lowered = self.settings['ignore_nicks'].lower()
        return nick.lower() in lowered

    def ignore(self, nick):
        """ignore someone
        
        Args:
            nick (str): the user
        
        Returns:
            list: a list of lines to send back
        """
        if self.nick_ignored(nick):
            print('no')
            return ['This nick is already ignored.']
        mut = self.settings['ignore_nicks'].split(' ')
        mut.append(nick)
        self.settings['ignore_nicks'] = ' '.join(mut)
        return ['✋']

    def unignore(self, nick):
        """unignore someone
        
        Args:
            nick (str): yep
        
        Returns:
            list: a list of lines
        """
        if not self.nick_ignored(nick):
            return ['This nick is not ignored.']
        self.settings['ignore_nicks'] = \
            ' '.join([n for n in self.settings['ignore_nicks'].split(' ') if n != nick])
        return ['🤚']

    def ircify(self, screen_name, text, futures=[]):
        """Turn a tweet's screen name and text into something more presentable
           for IRC.
        
        Args:
            screen_name (str): tweeter
            text (str): tweet
            futures (list, optional): list of request futures
        
        Returns:
            list: list of str
        """
        prefix = '@' + screen_name + ': '
        bprefix = ' ' * len(prefix)
        maxwidth = 192 
        chunksize = maxwidth - len(prefix) + 1
        if self.expand_urls:
            text = self.expand_text_urls(text, futures)
        inlines = text.split("\n")
        lines = []
        _HTMLParser = HTMLParser()
        for ind, line in enumerate(inlines):
            new_line = []
            clean = _HTMLParser.unescape(line)
            if type(clean) != str:
                clean = clean.encode('utf-8')
            clean = clean.replace("\n", "")
            subparts = clean.split(' ')
            parts = []
            # first, break up words
            for part in subparts:
                while len(part) > chunksize:
                    parts.append(part[:chunksize])
                    part = part[chunksize:]
                parts.append(part)
            # then, break up lines
            for part in parts:
                if len(' '.join(new_line) + part) > chunksize:
                    lines.append(' '.join(new_line))
                    new_line = []
                new_line.append(part)
            if len(new_line) > 0:
                lines.append(' '.join(new_line))
        outlines = []
        for i, line in enumerate(lines):
            pref = prefix if i == 0 else bprefix
            outlines.append(pref + line) 
        return outlines

    def _log_error(self, t):
        """you can figure this one out
        
        Args:
            t (str): oops
        
        Returns:
            None: I think facility.write returns None
        """
        return self._log(t, facility=sys.stderr)

    def _log(self, t, facility=sys.stdout):
        """_log
        
        Args:
            t (whatever): anything
            facility (idk, optional): idk
        """
        facility.write(str(t) + "\n")

    def insult(self):
        """get an insult
        
        Returns:
            list: list of str
        """
        return [random.choice(self.insults).capitalize() + '.']

    def corn(self, pop=False, num=3):
        """corn
        
        Args:
            pop (bool, optional): is it popcorn
            num (int, optional): how many
        
        Returns:
            list: list of str
        """
        return ['🌽' * num] if not pop else ['🍿' * num]

    def battlestations(self):
        """battlestations
        
        Returns:
            list: battlestations
        """
        return ['BATTLESTATIONS!']

    def salute(self, message):
        """salute the troops
        
        Args:
            message (str): the message
        
        Returns:
            list: list of str
        """
        parts = message.split(' ')
        rank_present = False
        rank = ''
        action = 'salutes'
        for part in parts:
            # get it on the second pass
            if rank_present:
                return ['/me %s %s %s' % (action, rank.title(), part.title())]
            # sets bool for the next loop
            if part == 'general' or part == 'major' or part == 'private' or part == 'colonel' or part == 'seaman':
                rank_present = True
                rank = part
        return None

    def quote(self, nick, extra):
        """quotes someone to twitter
        
        Args:
            nick (str): the user
            extra (str): extra stuff to add
        
        Returns:
            str: return str
        """
        self.lock()
        k = 'said_%s' % nick
        if not self.nick_ignored(nick) and k in self.brain:
            out = [self.brain[k]]
            out.append(extra)
            try:
                self.collapse_api.update_status(status=' '.join(out))
            except tweepy.TweepError as e:
                self.unlock()
                return str(e.message[0]['message'])
            self.unlock()
            return "%s has been quoted to Twitter." % nick
        self.unlock()
        return "Nothing found for %s" % nick

    def twit(self, message):
        """tweet something
        
        Args:
            message (str): the thing to send
        
        Returns:
            bool: yes
        """
        try:
            media_payload = self.image_getter.get_images(message)
            media_ids = [self.collapse_api.media_upload(i).media_id_string for i in media_payload[1]]
            self.collapse_api.update_status(status=media_payload[0], media_ids=media_ids)
        except tweepy.TweepError as e:
            logging.exception(e)
            return e.message
        return True

    def untwit(self, id=None):
        """delete a tweet
        
        Args:
            id (None, optional): delete this tweet, or the last tweet
        
        Returns:
            str: status of result
        """
        try:
            if id is not None:
                self.collapse_api.destroy_status(id=id)
                return "Destroyed status " + str(id)
            else:
                self.me = self.collapse_api.me()
                self.collapse_api.destroy_status(id=self.me.status.id)
                return "Destroyed status " + str(self.me.status.id) + ": " + \
                    self.me.status.text[:15] + '...'
        except tweepy.TweepError as e:
            return e.message

    def syntax(self):
        """help
        
        Returns:
            list of str: help
        """
        return [
            'Syntax:',
            '    twit $$$$ - Send a tweet',
            '    reply :):) $$$$$ - Replies to :):) with $$$$$ on twitter '
                'using the last status pasted to channel',
            '    untwit - Delete the last tweet',
            '    untwit 123123123 - Deletes tweet ID 123123123',
            '    /quit - Enters admin mode for douglbutt'
        ]

    def reply(self, handle_or_id, text):
        """reply to a tweet
        
        Args:
            handle_or_id (str): what do yo uthink
            text (str): the message
        
        Returns:
            str: yep
        """
        if handle_or_id.startswith('@'):
            self.lock()
            key = str('twitter_user_%s_last_id' % handle_or_id[1:]).lower()
            if key in self.brain:
                last_id = self.brain[key]
                self.unlock()
            else:
                self.unlock()
                return 'I don\'t see any recent tweets for that user to ' \
                    'reply to.'
        else:
            try:
                last_id = int(handle_or_id)
                text = text[len(handle_or_id):].strip()
            except ValueError:
                # not a real reply
                self._log("Returning because this is a bogus command.")
                return

        media_payload = self.image_getter.get_images(text)
        media_ids = [self.collapse_api.media_upload(i).media_id_string for i in media_payload[1]]
        self.collapse_api.update_status(status=media_payload[0], media_ids=media_ids,
            in_reply_to_status_id=last_id)

    def expand_twitter_urls(self, status):
        """expand twitter short turls
        
        Args:
            status (str): the tweet
        
        Returns:
            str: the tweet with expanded urls
        """
        print('expanding status')
        text = status._json['full_text']
        if hasattr(status, 'entities'):
            for url in status.entities['urls']:
                print('url', url)
                text = text.replace(url['url'], url['expanded_url'])
        if hasattr(status, 'extended_entities'):
            print('extended entities')
            for media in status.extended_entities['media']:
                text = text.replace(media['url'], media['expanded_url'])
        print('returning', text)
        return text

    def render_html(self, content):
        """Convert HTML body to IRCable body
        
        Args:
            content (str): stuff
        
        Returns:
            str: stuff
        """
        return re.sub(r'<[^>]+>', '',
            content.replace('</p>', '\n').replace('<br />', '\n')).strip()

    def process_toot(self, toot_url):
        """process mastodon posts for IRC
        
        Args:
            toot_url (str): url to toot
        
        Returns:
            str: the ircable body
        """
        messages=[]
        tootkey = 'toot_' +  self._hexurl(toot_url)
        parts = toot_url.split('/')
        toot_user = None
        if len(parts) < 3:
            return messages
        for part in parts:
            if len(part) > 0 and part[0] == '@':
                toot_user = part[1:]
        toot_domain = parts[2]
        if tootkey in self.brain:
            messages.extend(self.brain[tootkey])
        else:
            if toot_url[-5:] != '.json':
                toot_url += '.json'
            try:
                r = requests.get(toot_url)
                try:
                    resp = r.json()
                    content = self.render_html(resp['content'])
                    add_urls = []
                    for item in resp['attachment']:
                        add_urls.append(item['url'])
                    add_urls_rendered = ''
                    if (len(content) > 0 and content[-1] != '\n' and content[-1] != ' '):
                        add_urls_rendered = ' '
                    add_urls_rendered += ' '.join(add_urls)
                    content += add_urls_rendered
                    content = content.replace('\-', '-')
                    formatted = self.ircify('%s' % toot_user,
                            content) #, emoji=u'🐘')
                    self.brain[tootkey] = formatted
                    messages.extend(formatted)
                except KeyError as e:
                    print(e)
                    return messages
                except ValueError as e:
                    print(e)
                    return messages
            except requests.exceptions.RequestException as e:
                print(e)
                return messages
        return messages

    def process_tweet(self, tweet_id, via=None):
        """process tweet for IRC
        
        Args:
            tweet_id (int): id of tweet
            via (None, optional): not used
        
        Returns:
            list: list of str
        """
        print('processing tweet id', tweet_id)
        messages=[]
        tweetkey = 'tweet_' + str(tweet_id)
        if tweetkey in self.brain:
            print('tweet in brain')
            messages.extend(self.brain[tweetkey])
        else:
            try:
                status = self.collapse_api.get_status(id=tweet_id, tweet_mode='extended')
                user_key = 'twitter_user_%s_last_id' % \
                    status.user.screen_name.lower()
                self.brain[user_key] = status.id
                expanded_tweet = self.expand_twitter_urls(status)
                formatted = self.ircify(status.user.screen_name,
                        expanded_tweet)#, emoji=u'🐦')
                self.brain[tweetkey] = formatted
                messages.extend(formatted)
            except tweepy.TweepError as e:
                messages.append(str(e.message[0]['message']))
        return messages

    def _is_number(self, stronk):
        """idk why I use this
        
        Args:
            stronk (whatever): Description
        
        Returns:
            bool: yep
        """
        try:
            int(stronk)
            return True
        except ValueError:
            return False

    def url(self, urls, author=None):
        """process urls
        
        Args:
            urls (list): list of str
            author (None, optional): the person that posted the url
        
        Returns:
            list: list of str
        """
        self.lock()
        messages = []
        for url in urls:
            hexed = self._hexurl(url)
            key = 'urls_' + hexed
            first_author_key = 'firstpost_' + hexed
            parts = url.split('/')
            if len(parts) > 2 and parts[2].endswith('twitter.com'):
                for i, part in enumerate(parts):
                    if part in ('status', 'statuses'):
                        tweet_id = parts[i + 1]
                        if len(author) == 1:
                            messages.extend(['go to hell'])
                        else:
                            messages.extend(self.process_tweet(tweet_id, via=author))

            if len(parts) > 2 and self._is_number(parts[-1]) and parts[-2][0] == '@':
                if len(author) == 1:
                    messages.extend(['go to hell'])
                else:
                    messages.extend(self.process_toot(url))

            current_time = time()
            if key in self.brain:
                orig_date = self.brain[key]
                if (current_time - orig_date) > 120.0:
                    delta = datetime.now() - datetime.fromtimestamp(orig_date)
                    if author != self.brain[first_author_key]:
                        messages.append(
                            "Thanks for posting %s's link again. (%s ago)" % \
                                (self.brain[first_author_key],
                                    format_timedelta(delta, locale='en_US')))
                    else:
                        messages.append("You posted this %s ago, %s." % \
                            (format_timedelta(delta, locale='en_US'),
                                random.choice(self.insults)))
            elif len(author) > 1:
                self.brain[key] = int(time())
                self.brain[first_author_key] = author
        self.unlock()
        return messages

    def said(self, nick, message):
        """record the last thing someone said for quoting
        
        Args:
            nick (str): user
            message (str): the message
        """
        self.lock()
        self.brain['said_' + nick] = message
        self.unlock()
