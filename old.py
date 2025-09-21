import argparse
import json
import re
import time
import requests
import logging
from playwright.sync_api import sync_playwright
import threading
from dulunche.biliapi import BiliLiveAPI

def get_live_status(room_id, cookies):
    url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/122.0.0.0 Safari/537.36",
        "Referer": f"https://live.bilibili.com/{room_id}",
        "Origin":  "https://live.bilibili.com",
    }
    r = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["data"]["live_status"]

def start_live_watch(room_id, cookies):
    """
    开播后启动无头浏览器观看，直到下播。
    期间每分钟统计一次观看时长，但日志每10分钟输出一次，
    并在下播时输出最终总结。
    """
    def run():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # 导入 cookies
            cookie_list = []
            for k, v in cookies.items():
                cookie_list.append({
                    "name": k,
                    "value": v,
                    "domain": ".bilibili.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax"
                })
            context.add_cookies(cookie_list)

            page = context.new_page()
            page.goto(f"https://live.bilibili.com/{room_id}")

            watch_minutes = 0
            try:
                while True:
                    time.sleep(60)   # 每分钟循环一次
                    watch_minutes += 1
                    intimacy = min((watch_minutes // 5) * 6, 30)  # 每5分钟+6, 上限30

                    # ✅ 日志每10分钟输出一次
                    if watch_minutes % 10 == 0:
                        logging.info(f"已观看 {watch_minutes} 分钟，亲密度≈ {intimacy}")

                    # 检查是否下播
                    try:
                        status = get_live_status(room_id, cookies)
                        if status != 1:
                            # 下播时输出最终总结
                            final_intimacy = min((watch_minutes // 5) * 6, 30)
                            logging.info(f"检测到下播，结束观看任务。"
                                         f"总共观看 {watch_minutes} 分钟，亲密度≈ {final_intimacy}")
                            break
                    except Exception as e:
                        logging.error(f"检测下播状态失败: {e}")
                        continue
            finally:
                browser.close()

    # 后台线程运行，不阻塞主逻辑
    t = threading.Thread(target=run, daemon=True)
    t.start()

def read_text(fpath,mode):
    text = []

    if '独轮车' in mode:
        with open(fpath,'r',encoding='utf-8') as f:
            text_list = f.readlines()
            for t in text_list:
                t = t.strip()
                # t = re.sub(r"[\n,，.。～！、;；]",' ',t)
                if len(t) > 0 and not t.startswith('//'):
                    text.append(t[:30])
                if t == '//':
                    break
    else:
        with open(fpath,'r',encoding='utf-8') as f:
            text_list = f.readlines()
            for line in text_list:
                line = line.strip()
                if line == '//':
                    break
                str_list = re.split(r"[,，.。～！、;；]",line)
                str_list = [s for s in str_list if s and len(s.strip())>0]
                p = 0
                while p < len(str_list):
                    t = str_list[p]
                    if len(t) < 10:
                        while p < len(str_list)-1 and len(t+' '+str_list[p+1]) < 25:
                            t += ' '+str_list[p+1]
                            p += 1
                        text.append(t)
                        p += 1
                    elif len(t) > 30:
                        if len(t) < 60:
                            t0 = t[:len(t)//2]
                            t1 = t[len(t)//2:]
                        else:
                            t0 = t[0:30]
                            t1 = t[30:60]
                        text.append(t0)
                        text.append(t1)
                        p += 1
                    else:
                        text.append(t)
                        p += 1
    return text

def get_mode(fpath):
    with open(fpath,'r',encoding='utf-8') as f:
        text_list = f.readlines()
        sen_max = max([len(x) for x in text_list])
        if sen_max > 40:
            mode = '说书'
        else:
            mode = '独轮车'
    return mode 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("danmu.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cookies',type=str,default='./cookies.json')
    parser.add_argument('-r','--rid',type=str,default='14709735')
    parser.add_argument('-t','--txt',type=str,default='./text.txt')
    parser.add_argument('-i','--interval',type=float,default=15)
    parser.add_argument('--mode',choices=['auto','shuoshu','dulunche'],default='auto')
    args = parser.parse_args()

    if args.mode == 'auto':
        args.mode = get_mode(args.txt)
    mode = '独轮车' if args.mode == 'dulunche' else '说书'
    text = read_text(args.txt,mode=args.mode)

    with open(args.cookies, encoding='utf8') as f:
        cookies = json.load(f)
        cookies = {it['name']:it['value'] for it in cookies['cookie_info']['cookies']}
    bapi = BiliLiveAPI(cookies=cookies)
    login_info = bapi.get_user_info(args.rid)

    logging.info("等待直播间开播...")
    while True:
        try:
            # ✅ 这里把 cookies 传进去
            if get_live_status(args.rid, cookies) == 1:
                logging.info("直播已开播，开始发送弹幕")
                start_live_watch(args.rid, cookies)
                break
        except Exception as e:
            logging.info("获取房间状态失败：", e)
        time.sleep(30)

    if login_info['code'] != 0:
        input('未登录，请使用biliuprs进行登录：https://github.com/biliup/biliup-rs')
        exit(1)
    else:
        data = login_info['data']
        medal_info = data.get('medal', {})
        if medal_info.get('is_weared'):
            curr = medal_info.get('curr_weared_v2') or medal_info.get('curr_weared')
            if curr:
                medal_name = curr.get('medal_name') or curr.get('name', '')
                level = curr.get('level', '')
                logging.info(f"正在使用账号 {data['info']['uname']} 独轮车，佩戴 {medal_name} {level}级 牌子.")
            else:
                logging.info(f"正在使用账号 {data['info']['uname']} 独轮车，未戴牌子.")
        else:
            logging.info(f"正在使用账号 {data['info']['uname']} 独轮车，未戴牌子.")


    
    dm_cnt = 0
    kill_cnt = 0
    
    while True:
        # 每次循环先检测直播状态
        try:
            status = get_live_status(args.rid, cookies)
        except Exception as e:
            logging.error(f"获取直播状态失败: {e}")
            time.sleep(30)
            continue

        # 如果没开播 -> 等待直到开播
        if status != 1:
            logging.info("检测到直播未开播，进入等待...")
            while True:
                time.sleep(30)
                try:
                    status = get_live_status(args.rid, cookies)
                    if status == 1:
                        logging.info("检测到直播重新开播，继续发送弹幕。")
                        break
                except Exception as e:
                    logging.error(f"获取直播状态失败: {e}")
                    continue

        # -------- 弹幕发送逻辑 --------
        CHECK_EVERY = 5  # 每发送多少条检测一次直播状态，可自行调整
        sent_since_check = 0
        for word_cnt, txt in enumerate(text):
            # 周期性检查直播状态
            if CHECK_EVERY and sent_since_check >= CHECK_EVERY:
                try:
                    if get_live_status(args.rid, cookies) != 1:
                        logging.warning("周期性检查：检测到直播已下播，中断当前弹幕循环。")
                        break
                except Exception as e:
                    logging.error("周期性检查直播状态失败: %s", e)
                    # 不中断，继续发送
                sent_since_check = 0

            try:
                bapi.send_danmu(args.rid, txt)
                dm_cnt += 1
                sent_since_check += 1
                print(f"已发送弹幕 {dm_cnt} 条: {txt}")  
                time.sleep(args.interval)
            except Exception as e:
                logging.error(f"发送失败: {e}")
                kill_cnt += 1
                if kill_cnt > 3:
                    logging.critical("连续失败过多，停止脚本。")
                    exit(1)