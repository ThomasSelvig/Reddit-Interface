import random, string, asyncio, aiohttp, time, json
from bs4 import BeautifulSoup
from colr import color
from faker import Faker
from aiohttp_socks import ProxyType, ProxyConnector, ChainProxyConnector
from pyperclip import copy
from hashlib import sha256
from base64 import b64decode

# from keys import KEYS  # API-Keys stored away from strangers
KEYS = {
	"clientkey": input("anti-captcha.com API key: ").strip(),
	"reddit-sitekey": "6LeTnxkTAAAAAN9QEuDZRpn90WwKk_R1TRW_g-JC",  # last updated in this code: 8 / 4 / 2020
	"passwordSuffix": "" # password structure of created account: sha256(un + passwordSuffix)
}

'''
Aliases:
	"s": "session" (a browser session)
	"r": "request response"

Problems and potential solutions

	google recaptcha sometimes denies proxies (like TOR)
		use residential proxies
			rent residential IPs online
			break into someone's wifi and hide a raspberry pi in close proximity to be used as a proxy

	reddit only accepts registration with some delay between (7 min)
		use lots of proxies lmao

	reddit updated their recaptcha sitekey every once in a while
		update it manually by finding it at "https://www.reddit.com/register/" and replacing "sitekey" in KEYS
		todo: add auto-updating sitekey

	[SOLVED] sometimes faker gives a user agent for mobile devices, causing the CSRF to not be returned with request
		fixed by using internet explorer, which isn't on mobile

	[SOLVED] reddit actions require a header "authentication": derived from d2_token cookie
		this is set when you GET "https://www.reddit.com/"
		result is different when you're logged in (different privileges, such as upvoting)
		base64 decode a part of this cookie to get authentication header

	fix bad PEP8 D:

'''


class GetUser:
	async def getCSRF(s, suburl):
		async with s.get("https://www.reddit.com/"+suburl+"/") as r:
			try:
				token = BeautifulSoup(await r.text(), "html.parser").find("input", {"name": "csrf_token"})["value"]
			except:
				print(r.status)
				print((await r.text())[:100])
				copy(await r.text())

			return token

	async def getCaptchaSolution(s):
		url = "https://api.anti-captcha.com"

		data = {
			"clientKey": KEYS["clientkey"],
			"task": {
				"type": "NoCaptchaTaskProxyless",
				"websiteURL": "https://www.reddit.com/register",
				"websiteKey": KEYS["reddit-sitekey"]
			}
		}
		# use "s" to contact anti-captcha.com and send "key"
		async with s.post(url + "/createTask",
			data=json.dumps(data)) as r:
			
			task = json.loads(await r.text())
			if task["errorId"] != 0:
				return task, None

		# wait until task is reported complete
		completed = False
		await asyncio.sleep(10)
		data = {
			"clientKey": KEYS["clientkey"],
			"taskId": task["taskId"]
		}
		while not completed:
			async with s.post(url + "/getTaskResult",
				data=json.dumps(data)) as r:
				
				result = json.loads(await r.text())
				if result["status"] == "ready":
					# got the captcha result!
					return None, result["solution"]["gRecaptchaResponse"]

				await asyncio.sleep(2) # check for results every 2 seconds

	async def getAuth(s):
		cookies = s.cookie_jar.filter_cookies("https://reddit.com")
		# this is really fucky but reddit requires the "authorization" header to do stuff like voting
		authorization = "Bearer " + json.loads(b64decode("ey" + cookies["d2_token"].value.split(".ey")[-1]))["accessToken"]
		return authorization

	# directly returns User object
	async def genRedditUser():
		# get browser session without using context manager so that it stays alive in the User object
		s = aiohttp.ClientSession(headers={"User-Agent": Faker().internet_explorer()}, cookie_jar=aiohttp.CookieJar())

		# get cross site request forgery token
		csrf = await GetUser.getCSRF(s, "register")

		# get captcha
		error, captcha = await GetUser.getCaptchaSolution(s)
		assert error == None, "Failed: " + str(error)
		#print("Recaptcha solution:\n" + color(captcha, "salmon"))
			
		# get user credentials according to format
		charSet = string.ascii_lowercase + string.ascii_uppercase + string.digits + "-_"
		un = "".join([random.choice(charSet) for i in range(20)])
			
		data = {
			"username": un,
			"email": f"{un}@gmail.com",
			"password": sha256((un+KEYS["passwordSuffix"]).encode()).hexdigest(),
			"csrf_token": csrf,
			"g-recaptcha-response": captcha,
			"dest": "https://www.reddit.com"
		}

		# register account
		async with s.post("https://www.reddit.com/register", 
			data=data, headers={"Referer": "https://www.reddit.com/register/"}) as r:

			if r.status == 200 and not "<html" in (await r.text()):
				# successfully registered account
				print(color(un, "green"), "registered")
				accounts.append(un)
				return User(s, un, await GetUser.getAuth(s))
			else:
				# registration failed
				print(color(un, "red"), "failed")
				print(r.status)
				print((await r.text())[:100])
				copy(await r.text())
				return None

	# directly returns User object
	async def loginRedditUser(un, pw=None):
		s = aiohttp.ClientSession(headers={"User-Agent": Faker().internet_explorer()}, cookie_jar=aiohttp.CookieJar())

		async with s.post("https://www.reddit.com/login", 
			headers={
				"Referer": "https://www.reddit.com/login/"
			},
			data={
				"csrf_token": await GetUser.getCSRF(s, "login"),
				"otp": "",
				"password": pw if pw else sha256((un+KEYS["passwordSuffix"]).encode()).hexdigest(),
				"dest": "https://www.reddit.com",
				"username": un
			}) as r:

			if r.status == 200 and (await r.text())[0] == "{":
				print(color(f"{un} logged in", "green"))
			else:
				print(color(f"{un} failed to log in", "red"))

		async with s.get("https://www.reddit.com/") as r:
			pass # this is here to get the d2_token

		return User(s, un, await GetUser.getAuth(s))


class User:
	DOWNVOTE = -1
	UPVOTE = 1

	def __init__(self, s, un, auth):
		self.s = s
		self.un = un
		self.auth = auth

	async def vote(self, id, value):
		params = {
			"redditWebClient": "desktop2x",
			"app": "desktop2x-client-production",
			"raw_json": 1,
			"gilding_detail": 1
		}
		data = {
			"id": id,
			"dir": value,
			"api_type": "json"
		}
		headers = {
			"Authorization": self.auth
		}

		async with self.s.post("https://oauth.reddit.com/api/vote", params=params, data=data, headers=headers) as r:
			print(succ := r.status in range(200, 250))
			return succ

	# For testing: check if (userSession is logged in) or (userSession is logged in as provided username)
	async def isLoggedIn(userSession, un=None):
		if un:
			newurl = f"https://www.reddit.com/user/{un}/saved.json"
		else:
			async with userSession.get("https://www.reddit.com/user/me") as r:
				usertag = r.headers["location"]
				newurl = f"https://www.reddit.com{usertag}saved.json"

		async with userSession.get(newurl) as r:
			return r.status == 200

	async def getHistory(self, un):
		history = []
		after = None
		while True:
			async with self.s.get(f"https://www.reddit.com/user/{un}/.json" + (f"?after={after}" if after else "")) as r:
				data = await r.json()
				history += [i["data"] for i in data["data"]["children"]]
				
				if (after := data["data"]["after"]) == None:
					break

		return history



async def main():

	user = await GetUser.loginRedditUser("username", "password")
	history = await user.getHistory("kianoe")
	
	# upvote every post in this user's history that you can vote on
	_ = await asyncio.gather(*[user.vote(post["name"], User.UPVOTE) for post in history if not post["archived"]])

	# close the http session
	await user.s.close()


if __name__ == '__main__':
	accounts = []  # list of registered UNs

	print(color("Init process\n".rjust(50)*3, fore="white", back="black"))
	asyncio.run(main())
	print(color("\nPython 3.8 aiohttp doesn't work well, the EOF crash that's about to happen is normal behaviour\nExpecting crash, brace for impact".rjust(50)*3, fore="black", back="white"))
