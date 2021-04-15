import json
import asyncio
import tweepy
from exts.db import DB
from random import randrange
import logging


class Tracker:
    def __init__(self, queue):
        self.config = json.load(open('twitter_config.json'))
        self.queue = queue
        self.loop = asyncio.new_event_loop()
        self.log = logging.getLogger(' Tracker ').info
        self.count = 200

    def start(self):
        self.db = DB()
        self.loop.run_until_complete(self.main())

    async def main(self):
        self.log('Setting up Apps ...')
        await self.setup_apis()
        self.log("Followings tracker is ready!")
        while True:
            all_users = self.db.get_all_users()
            if len(all_users) == 0:
                self.log("No users in the database!")
                await asyncio.sleep(10)
                continue
            self.log(f'Got {len(all_users)} users from database')
            for user in all_users:
                self.log(f'Target user : {user["username"]}')
                if not user['tracked']:
                    self.log(f'{user["username"]} is not tracked yet!')
                    await self.track_user(user)
                    continue
                self.log(f'{user["username"]} is already tracked!')
                new_followings = await self.check_for_new_followings(user)
                for user_id in new_followings:
                    message = await self.create_message_for_tg(user_id, user["username"])
                    self.queue.put(message)
            await asyncio.sleep(self.get_wait_time(len(all_users)))

    def get_wait_time(self, number_of_users):
        if number_of_users <= 5:
            return 240
        elif number_of_users > 5 and number_of_users <= 10:
            return 180
        elif number_of_users > 10:
            return 120

    async def create_message_for_tg(self, following_id, follower_username):
        api = next(self.random_api)
        user = api.get_user(user_id=following_id)
        username = user._json["screen_name"]
        profile_url = f'https://twitter.com/{username}'
        follower_profile_url = f'https://twitter.com/{follower_username}'
        message = f'[{follower_username}]({follower_profile_url}) just started to follow [{username}]({profile_url}).'
        self.log(f'Prepared message for TG : {message}')
        return message

    async def check_for_new_followings(self, user):
        self.log(f'Checking for new followings for {user["username"]}')
        cur = user["cursor"]
        self.log(f'Latest cursor is : {cur}')
        api = next(self.random_api)
        try:
            results = api.friends(user["username"],
                                  cursor=cur, count=self.count)
        except tweepy.error.RateLimitError:
            self.log('Hit rate limit on API, switching to next App.')
            await asyncio.sleep(3)
            return await self.check_for_new_followings(user)
        friends = results[0]
        followings_list = list()
        for friend in friends:
            followings_list.append(friend._json["id"])

        def filter_followings(user_id):
            if user_id in user["followings_list"]:
                return False
            return True

        if results[1][1] != 0:
            new_cur = results[1][1]
            self.db.update_cursor(user["user_id"], new_cur)
        new_followings = list(filter(filter_followings, followings_list))
        self.log(
            f'Got {len(new_followings)} new followings for {user["username"]}')
        if len(new_followings) != 0:
            self.log(f'Adding new followings to db.')
            self.db.extend_users_followings_list(
                user["user_id"], new_followings)
        return new_followings

    def get_random_api(self):
        while True:
            total = len(self.authenticated_apps)
            if total == 1:
                index = 0
            else:
                index = randrange(0, total-1)
            yield self.authenticated_apps[index]

    async def track_user(self, user):
        self.log(f'Starting to track {user["username"]}')
        username = user["username"]
        cur = -1
        followings_list = list()
        api = next(self.random_api)
        while True:
            try:
                results = api.friends(username,
                                      cursor=cur, count=self.count)
            except tweepy.error.RateLimitError:
                self.log('Hit rate limit on API, switching to next App.')
                await asyncio.sleep(3)
                api = next(self.random_api)
                continue
            friends = results[0]
            for friend in friends:
                followings_list.append(friend._json["id"])
            if results[1][1] == 0:
                break
            cur = results[1][1]
        self.log(
            f'Got {len(followings_list)} total following for {user["username"]}')
        self.db.update_cursor(user["user_id"], cur)
        self.db.extend_users_followings_list(user["user_id"], followings_list)
        self.db.set_user_tracked(user["user_id"])

    async def setup_apis(self):
        creds = list(self.config.get("TWITTER_APPS_CREDS"))
        self.authenticated_apps = []
        for cred in creds:
            API_KEY = cred.get("APP_API_KEY")
            API_KEY_SECRET = cred.get("APP_API_KEY_SECRET")
            ACCESS_TOKEN = cred.get("APP_ACCESS_TOKEN")
            ACCESS_TOKEN_SECRET = cred.get("APP_ACCESS_TOKEN_SECRET")
            auth = tweepy.OAuthHandler(API_KEY, API_KEY_SECRET)
            auth.set_access_token(ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
            api = tweepy.API(auth, wait_on_rate_limit=True,
                             wait_on_rate_limit_notify=True)
            self.authenticated_apps.append(api)
        self.random_api = self.get_random_api()