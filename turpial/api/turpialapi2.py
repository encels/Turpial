# -*- coding: utf-8 -*-

# Modelo base basado en hilos para el Turpial
#
# Author: Wil Alvarez (aka Satanas)
# Dic 22, 2009

import time
import Queue
import logging
import threading
import traceback

from turpial.api import oauth
from turpial.api.oauth_client import TurpialAuthClient
from turpial.api.twitter_globals import *
from turpial.api.turpialhttp import *


class TurpialAPI(threading.Thread):
    def __init__(self, isthread=True):
        threading.Thread.__init__(self)
        
        self.isthread = isthread
        self.setDaemon(False)
        self.log = logging.getLogger('API')
        self.queue = Queue.Queue()
        self.exit = False
        '''
        # OAuth stuffs
        self.client = None
        self.consumer = None
        self.is_oauth = False
        self.token = None
        self.signature_method_hmac_sha1 = None
        '''
        
        self.http = TurpialHTTP()
        #self.format = 'json'
        #self.username = None
        #self.password = None
        self.profile = None
        self.tweets = []
        self.replies = []
        self.directs = []
        self.favorites = []
        self.muted_users = []
        self.friends = []
        self.friendsloaded = False
        self.conversation = []
        
        self.to_fav = []
        self.to_unfav = []
        self.to_del = []
        self.log.debug('Iniciado')
        
    def execute(self, args, callback):
        if args.has_key('oauth'):
            self.http.oauth(args, callback)
        elif args.has_key('mute'):
            rtn = self.__handle_muted()
        else:
            rtn = self.http.request(args, callback)
            if args.has_key('post-process'):
                rtn = args['post-process'](rtn)
        
        return rtn
    
    def __register(self, args, callback):
        if self.isthread:
            self.queue.put((args, callback))
        else:
            self.execute(args, callback)
        
    def __del_tweet_from(self, tweets, id):
        item = None
        for twt in tweets:
            if id == twt['id']:
                item = twt
                break
        if item: tweets.remove(item)
        return tweets
        
    def __change_tweet_from(self, tweets, id, key, value):
        index = None
        for twt in tweets:
            if id == twt['id']:
                index = tweets.index(twt)
                break
        if index: tweets[index][key] = value
        return tweets
        
    def __handle_oauth(self, args, callback):
        pass
            
    def __handle_tweets(self, tweet, args):
        if tweet is None: return False
        
        if args.has_key('add'):
            exist = False
            for twt in self.tweets:
                if tweet['id'] == twt['id']: exist = True
            
            if not exist: self.tweets.insert(0, tweet)
        elif args.has_key('del'):
            self.tweets = self.__del_tweet_from(self.tweets, tweet['id'])
            self.favorites = self.__del_tweet_from(self.favorites, tweet['id'])
            self.directs = self.__del_tweet_from(self.favorites, tweet['id'])
            
        return True
        
    def __handle_retweets(self, tweet):
        if tweet is None: return False
        self.tweets = self.__change_tweet_from(self.tweets, tweet['id'], 
            'retweeted_status', tweet['retweeted_status'])
        self.replies = self.__change_tweet_from(self.replies, tweet['id'], 
            'retweeted_status', tweet['retweeted_status'])
        self.favorites = self.__change_tweet_from(self.favorites, tweet['id'], 
            'retweeted_status', tweet['retweeted_status'])
        
        return True
        
    def __handle_muted(self):
        if len(self.muted_users) == 0: return self.tweets
        
        tweets = []
        for twt in self.tweets:
            if twt['user']['screen_name'] not in self.muted_users:
               tweets.append(twt)
               
        return tweets
        
    def __handle_favorites(self, tweet, fav):
        if tweet is None: return False
        
        if fav:
            tweet['favorited'] = True
            self.favorites.insert(0, tweet)
            self.to_fav.remove(str(tweet['id']))
        else:
            self.favorites = self.__del_tweet_from(self.favorites, tweet['id'])
            self.to_unfav.remove(str(tweet['id']))
            
        self.tweets = self.__change_tweet_from(self.tweets, tweet['id'], 'favorited', fav)
        self.replies = self.__change_tweet_from(self.replies, tweet['id'], 'favorited', fav)
        
        return True
        
    def __handle_friends(self, rtn, done_callback, cursor):
        if rtn is None:
            self.log.debug('Error descargando amigos, intentando de nuevo')
            self.get_friends(done_callback, cursor)
        else:
            for p in rtn['users']:
                self.friends.append(p)
            
            if rtn['next_cursor'] > 0:
                self.get_friends(done_callback, rtn['next_cursor'])
            else:
                self.friendsloaded = True
                done_callback(self.friends)
                
    def __handle_conversation(self, rtn, done_callback):
        if rtn is None:
            self.log.debug(u'Error descargando conversación')
            done_callback(rtn)
        else:
            self.conversation.append(rtn)
            
            if rtn['in_reply_to_status_id']:
                self.get_conversation(str(rtn['in_reply_to_status_id']), done_callback, False)
            else:
                done_callback(self.conversation)
        
    def __handle_follow(self, user, follow):
        if follow:
            exist = False
            for u in self.friends:
                if user['id'] == u['id']: exist = True
            
            if not exist: 
                self.friends.insert(0, user)
                self.profile['friends_count'] += 1
        else:
            item = None
            for u in self.friends:
                if user['id'] == u['id']:
                    item = u
                    break
            if item: 
                self.friends.remove(item)
                self.profile['friends_count'] -= 1
            
    def is_friend(self, user):
        for f in self.friends:
            if user == f['screen_name']: return True
        return False
        
    def is_fav(self, tweet_id):
        for twt in self.tweets:
            if tweet_id == str(twt['id']): return twt['favorited']
        for twt in self.replies:
            if tweet_id == str(twt['id']): return twt['favorited']
        for twt in self.favorites:
            if tweet_id == str(twt['id']): return twt['favorited']

        
    def auth(self, username, password, callback):
        self.log.debug('Iniciando autenticacion basica')
        #self.username = username
        #self.password = password
        self.http.set_credentials(username, password)
        self.__register({'uri': 'http://twitter.com/account/verify_credentials', 'login':True}, callback)
        
    def start_oauth(self, auth, show_pin_callback, done_callback):
        self.log.debug('Iniciando OAuth')
        self.__register({'cmd': 'start', 'oauth':True, 'auth': auth, 'done':done_callback}, show_pin_callback)
        
    def authorize_oauth_token(self, pin, callback):
        self.log.debug('Solicitando autenticacion del token')
        self.__register({'cmd': 'authorize', 'oauth':True, 'pin': pin}, callback)
        
    def update_rate_limits(self, callback):
        self.__register({'uri': 'http://twitter.com/account/rate_limit_status'}, callback)
        
    def update_timeline(self, callback, count=20):
        self.log.debug('Descargando Timeline')
        args = {'count': count}
        self.__register({'uri': 'http://api.twitter.com/1/statuses/home_timeline', 'args': args, 'timeline': True}, callback)
        
    def update_replies(self, callback, count=20):
        self.log.debug('Descargando Replies')
        args = {'count': count}
        self.__register({'uri': 'http://twitter.com/statuses/mentions','args': args,  'replies': True}, callback)
        
    def update_directs(self, callback, count=20):
        self.log.debug('Descargando Directs')
        args = {'count': count}
        self.__register({'uri': 'http://twitter.com/direct_messages', 'args': args, 'directs': True}, callback)
        
    def update_favorites(self, callback):
        self.log.debug('Descargando Favorites')
        self.__register({'uri': 'http://twitter.com/favorites', 'favorites': True}, callback)
        
    def update_status(self, text, in_reply_id, callback):
        if in_reply_id:
            args = {'status': text, 'in_reply_to_status_id': in_reply_id}
        else:
            args = {'status': text}
        self.log.debug(u'Nuevo tweet: %s' % text)
        self.__register({'uri': 'http://twitter.com/statuses/update', 'args': args, 'tweet':True, 'add': True}, callback)
        
    def destroy_status(self, tweet_id, callback):
        self.log.debug('Destruyendo tweet: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/statuses/destroy', 'id': tweet_id, 'args': '', 'tweet':True, 'del': True}, callback)
        
    def retweet(self, tweet_id, callback):
        self.log.debug('Retweet: %s' % tweet_id)
        self.__register({'uri': 'http://api.twitter.com/1/statuses/retweet',  'id':tweet_id, 'rt':True, 'args': ''}, callback)
        
    def set_favorite(self, tweet_id, callback):
        self.to_fav.append(tweet_id)
        self.log.debug('Marcando como favorito tweet: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/favorites/create', 'id':tweet_id, 'fav': True, 'args': ''}, callback)
        
    def unset_favorite(self, tweet_id, callback):
        self.to_unfav.append(tweet_id)
        self.log.debug('Desmarcando como favorito tweet: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/favorites/destroy', 'id':tweet_id, 'fav': False, 'args': ''}, callback)
    
    def search_topic(self, query, callback):
        args = {'q': query, 'rpp': 50}
        self.log.debug('Buscando tweets: %s' % query)
        self.__register({'uri': 'http://search.twitter.com/search', 'args': args}, callback)
        
    def update_profile(self, name, url, bio, location, callback):
        args = {'name': name, 'url': url, 'location': location, 'description': bio}
        self.log.debug('Actualizando perfil')
        self.__register({'uri': 'http://twitter.com/account/update_profile', 'args': args}, callback)
        
    def get_friends(self, callback, cursor=-1):
        args = {'cursor': cursor}
        self.log.debug('Descargando Lista de Amigos')
        self.__register({'uri': 'http://twitter.com/statuses/friends', 'args': args,
            'done': callback, 'friends': True}, self.__handle_friends)
        
    def follow(self, user, callback):
        args = {'screen_name': user}
        self.log.debug('Siguiendo a: %s' % user)
        self.__register({'uri': 'http://twitter.com/friendships/create', 'args': args, 'follow': True}, callback)
        
    def unfollow(self, user, callback):
        args = {'screen_name': user}
        self.log.debug('Dejando de seguir a: %s' % user)
        self.__register({'uri': 'http://twitter.com/friendships/destroy', 'args': args, 'follow': False}, callback)
        
    def mute(self, arg, callback):
        if type(arg).__name__=='list':
            self.log.debug('Actualizando usuarios silenciados')
            self.muted_users = arg
        else:
            if arg not in self.friends:
                self.log.debug('No se silencia a %s porque no es tu amigo' % arg)
            elif arg not in self.muted_users: 
                self.log.debug('Silenciando a %s' % arg)
                self.muted_users.append(arg)
        self.__register({'mute': True}, callback)
        
    def in_reply_to(self, tweet_id, callback):
        self.log.debug('Buscando respuesta: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/statuses/show', 'id': tweet_id}, callback)
        
    def get_conversation(self, tweet_id, callback, first=True):
        if first: 
            self.conversation = []
            self.log.debug(u'Obteniendo conversación:')
        self.log.debug('--Tweet: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/statuses/show', 'id': tweet_id, 
            'done': callback, 'conversation': True}, self.__handle_conversation)
        
    def destroy_direct(self, tweet_id, callback):
        self.log.debug('Destruyendo directo: %s' % tweet_id)
        self.__register({'uri': 'http://twitter.com/direct_messages/destroy', 'id': tweet_id, 'args': '', 'direct':True, 'del': True}, callback)
        
    def end_session(self):
        self.__register({'uri': 'http://twitter.com/account/end_session', 'args': '', 'exit': True}, None)
        
    def quit(self):
        self.exit = True
        
    def run(self):
        while not self.exit:
            time.sleep(0.3)
            try:
                req = self.queue.get(False)
            except Queue.Empty:
                continue
            
            (args, callback) = req
            
            rtn = None
            
            if args.has_key('login'): 
                self.profile = rtn
                
            if args.has_key('timeline'):
                if rtn: self.tweets = rtn
            elif args.has_key('replies'):
                if rtn: self.replies = rtn
            elif args.has_key('directs'):
                if rtn: self.directs = rtn
            elif args.has_key('favorites'):
                if rtn: self.favorites = rtn
                callback(self.tweets, self.replies, self.favorites)
                continue
                
            if args.has_key('tweet'):
                done = self.__handle_tweets(rtn, args)
                if done: rtn = self.__handle_muted()
                if args.has_key('del'):
                    callback(rtn, self.favorites)
                    continue
            
            if args.has_key('direct'):
                if args.has_key('del'):
                    callback(rtn, self.favorites)
                    continue
            
            if args.has_key('rt'):
                done = self.__handle_retweets(rtn)
                if done: 
                    rtn = self.__handle_muted()
                    callback(rtn, self.replies, self.favorites)
                else:
                    callback(None, None, None)
                continue
                
            if args.has_key('fav'):
                done = self.__handle_favorites(rtn, args['fav'])
                callback(self.tweets, self.replies, self.favorites)
                #if done: 
                #    callback(self.tweets, self.replies, self.favorites)
                #else:
                #    callback(None,None,None)
                continue
                
            if args.has_key('friends'):
                callback(rtn, args['done'], args['args']['cursor'])
                continue
                
            if args.has_key('conversation'):
                callback(rtn, args['done'])
                continue
                
            if args.has_key('follow'):
                self.__handle_follow(rtn, args['follow'])
                callback(self.friends, self.profile, rtn, args['follow'])
                continue
                
            if args.has_key('exit'):
                self.exit = True
            else:
                callback(rtn)
            
        self.log.debug('Terminado')
        return
