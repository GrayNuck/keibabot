import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View
import requests
from bs4 import BeautifulSoup
import re
import json
import os
from keep_alive import keep_alive  # サーバーを叩き起こす機能

# --- 設定 ---
TOP_JOCKEYS = ["ルメール", "川田", "武豊", "戸崎圭", "坂井", "横山武", "松山", "レーン", "モレイラ", "デムーロ"]
PLACE_CODES = {"01":"札幌", "02":"函館", "03":"福島", "04":"新潟", "05":"東京", "06":"中山", "07":"中京", "08":"京都", "09":"阪神", "10":"小倉"}
COURSE_FEATURES = {
    "東京": "直線の長さ: 525.9m (長い) | 坂: だらだらとした坂 | 傾向: 瞬発力勝負、差し有利",
    "中山": "直線の長さ: 310m (短い) | 坂: ゴール前に急坂 | 傾向: パワーが必要、先行有利",
    "京都": "直線の長さ: 404m (平坦) | 坂: 3コーナーに坂(淀の坂) | 傾向: 下り坂で加速、スピード重視",
    "阪神": "直線の長さ: 474m (普通) | 坂: ゴール前に急坂 | 傾向: タフな馬が強い",
    "中京": "直線の長さ: 412m (普通) | 坂: 直線に急坂 | 傾向: 差しが決まりやすいタフなコース",
    "新潟": "直線の長さ: 659m (日本最長) | 坂: ほぼ平坦 | 傾向: とにかく長い直線、追い込みが決まる",
    "福島": "直線の長さ: 292m (短い) | 坂: 起伏が激しい | 傾向: 小回り、逃げ・先行有利",
    "小倉": "直線の長さ: 293m (短い) | 坂: 平坦 | 傾向: スピード勝負、逃げ有利",
    "札幌": "直線の長さ: 266m (短い) | 坂: 平坦(洋芝) | 傾向: コーナーが大きく緩やか",
    "函館": "直線の長さ: 262m (日本最短) | 坂: 起伏あり(洋芝) | 傾向: 逃げ切りやすい"
}

BALANCE_FILE = "balance.json"

# --- Bot設定 ---
class KeibaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Logged in as {self.user}")

bot = KeibaBot()

# --- 収支管理 ---
def load_data():
    if not os.path.exists(BALANCE_FILE): return {}
    try:
        with open(BALANCE_FILE, "r") as f: return json.load(f)
    except: return {}

def save_data(data):
    with open(BALANCE_FILE, "w") as f: json.dump(data, f)

def update_balance(uid, amt):
    d = load_data(); uid=str(uid)
    d[uid] = d.get(uid, 0) + amt
    save_data(d)
    return d[uid]

def set_balance(uid, amt):
    d = load_data(); uid=str(uid)
    d[uid] = amt
    save_data(d)
    return amt

# --- ロジック ---
def get_todays_race_list():
    try:
        res = requests.get("https://race.netkeiba.com/top/race_list.html", headers={"User-Agent": "Mozilla/5.0"})
        res.encoding = 'EUC-JP'
        soup = BeautifulSoup(res.text, 'lxml')
        opts = []
        for track in soup.find_all('dl', class_='RaceList_DataList'):
            t_name = track.find('p', class_='RaceList_DataTitle').text.strip().split()[1]
            for item in track.find_all('li', class_='RaceList_Item'):
                num = item.find('div', class_='RaceList_ItemNum').text.strip()
                name = item.find('span', class_='ItemTitle').text.strip() or "レース"
                link = item.find('a')
                if link and 'race_id=' in link.get('href'):
                    rid = re.search(r'race_id=(\d+)', link.get('href')).group(1)
                    opts.append(discord.SelectOption(label=f"{t_name}{num} {name}"[:25], value=rid))
        return opts
    except: return []

def get_netkeiba_data(rid):
    try:
        res = requests.get(f"https://race.netkeiba.com/race/shutuba.html?race_id={rid}", headers={"User-Agent": "Mozilla/5.0"})
        res.encoding = 'EUC-JP'
        soup = BeautifulSoup(res.text, 'lxml')
        name = soup.find('div', class_='RaceName').text.strip()
        cond = "良"
        dtl = soup.find('div', class_='RaceData01').text
        if "不良" in dtl: cond="不良"
        elif "重" in dtl: cond="重"
        elif "稍重" in dtl: cond="稍重"
        place = PLACE_CODES.get(rid[4:6], "不明")
        horses = []
        for r in soup.find_all('tr', class_='HorseList'):
            try:
                hname = r.find('span', class_='HorseName').text.strip()
                waku = r.find('td', class_=lambda x: x and 'Waku' in x).text.strip()
                jock = r.find('td', class_='Jockey').text.strip()
                pop = int(r.find('td', class_='Popular').text.strip())
                odds = float(r.find('td', class_='Odds').text.strip())
                wc = 0
                wm = re.search(r'\(([\+\-]?\d+)\)', r.find('td', class_='Weight').text.strip())
                if wm: wc = int(wm.group(1))
                horses.append({"name":hname, "waku":waku, "jockey":jock, "pop":pop, "odds":odds, "wc":wc})
            except: continue
        return {"name":name, "place":place, "cond":cond, "horses":horses, "feat":COURSE_FEATURES.get(place,"")}
    except: return None

def calc_predict(data):
    res = []
    for h in data['horses']:
        sc = 0; r = []
        if h['odds'] < 2.5: sc-=5; r.append("過剰人気")
        elif 3<=h['odds']<=20: sc+=15; r.append("妙味")
        if any(j in h['jockey'] for j in TOP_JOCKEYS): sc+=10; r.append("騎手")
        if abs(h['wc'])>=10: sc-=10; r.append(f"体重{h['wc']}")
        if data['cond'] in ["重","不良"]:
            if h['pop']>=5: sc+=5; r.append("道悪穴")
            if int(h['waku'])>=7: sc+=3
        p = data['place']
        w = int(h['waku'])
        if p in ["東京","新潟"] and w>=7: sc+=5; r.append("外枠")
        elif p in ["中山","小倉","福島"] and w<=2: sc+=10; r.append("内枠")
        elif p=="京都" and w==1: sc+=8
        
        h['score'] = sc
        h['reasons'] = ",".join(r) if r else "-"
        res.append(h)
    return sorted(res, key=lambda x:x['score'], reverse=True)

def calc_alloc(horses, budget):
    targets = [h for h in horses if h['odds']>0]
    if not targets: return []
    inv = sum(1/h['odds'] for h in targets)
    allocs = []
    for h in targets:
        bet = round((budget*(1/h['odds'])/inv)/100)*100 or 100
        allocs.append({"name":h['name'], "odds":h['odds'], "bet":bet, "ret":int(bet*h['odds'])})
    return allocs

# --- コマンド ---
class RaceSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="レースを選択...", options=opts[:25])
    async def callback(self, itr):
        await run_pred(itr, self.values[0], 1000)

async def run_pred(itr, rid, bud):
    await itr.response.defer()
    d = get_netkeiba_data(rid)
    if not d: return await itr.followup.send("エラー")
    res = calc_predict(d)
    plan = calc_alloc(res[:3], bud)
    em = "☔" if d['cond'] in ["重","不良"] else "☀️"
    embed = discord.Embed(title=f"{d['name']}", description=f"{d['place']} {em}{d['cond']} | 予算{bud}円", color=0xD4AF37)
    if d['cond'] in ["重","不良"]: embed.add_field(name="注意", value="荒れる可能性大", inline=False)
    txt = ""
    tot = 0
    for p in plan:
        prof = p['ret']-bud
        txt += f"**{p['name']}** ({p['odds']})\n└ {p['bet']}円 -> {p['ret']} ({prof:+})\n"
        tot += p['bet']
    embed.add_field(name="推奨買い目", value=txt, inline=False)
    embed.add_field(name="操作", value=f"`/record -{tot}`", inline=False)
    await itr.followup.send(embed=embed)

@bot.tree.command(name="today", description="レース選択")
async def today(itr: discord.Interaction):
    await itr.response.defer()
    opts = get_todays_race_list()
    if opts: await itr.followup.send("選択:", view=View().add_item(RaceSelect(opts)))
    else: await itr.followup.send("開催なし")

@bot.tree.command(name="predict", description="詳細予想")
async def predict(itr: discord.Interaction, race_id: str, budget: int=1000):
    await run_pred(itr, race_id, budget)

@bot.tree.command(name="balance", description="収支")
async def balance(itr: discord.Interaction):
    v = get_user_balance(itr.user.id)
    await itr.response.send_message(f"収支: {v:,}円")

@bot.tree.command(name="record", description="記録")
async def record(itr: discord.Interaction, amount: int):
    v = update_balance(itr.user.id, amount)
    await itr.response.send_message(f"更新: {v:,}円")

@bot.tree.command(name="fix_balance", description="修正")
async def fix_balance(itr: discord.Interaction, amount: int):
    set_balance(itr.user.id, amount)
    await itr.response.send_message(f"修正完了: {amount:,}円")

def get_user_balance(uid):
    return load_data().get(str(uid), 0)

# サーバー起動
keep_alive()
# 鍵はサーバー側で設定するので、ここではこう書く
bot.run(os.getenv('DISCORD_TOKEN'))
