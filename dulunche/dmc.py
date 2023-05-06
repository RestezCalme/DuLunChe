from datetime import datetime
import re, asyncio, aiohttp

__all__ = ["DanmakuClient"]

class DanmakuClient:
    def __init__(self, url, q, **kargs):
        self.__url = ""
        self.__site = None
        self.__usite = None
        self.__hs = None
        self.__ws = None
        self.__stop = False
        self.__dm_queue = q
        self.__link_status = True
        self.__extra_data = kargs
        if "http://" == url[:7] or "https://" == url[:8]:
            self.__url = url
        else:
            self.__url = "http://" + url
        self.__site = Bilibili
        self.__hs = aiohttp.ClientSession()

    async def init_ws(self):
        ws_url, reg_datas = await self.__site.get_ws_info(self.__url)
        self.__ws = await self.__hs.ws_connect(ws_url)
        for reg_data in reg_datas:
            if type(reg_data) == str:
                await self.__ws.send_str(reg_data)
            else:
                await self.__ws.send_bytes(reg_data)

    async def heartbeats(self):
        while self.__stop != True:
            # print('heartbeat')
            await asyncio.sleep(20)
            try:
                if type(self.__site.heartbeat) == str:
                    await self.__ws.send_str(self.__site.heartbeat)
                else:
                    await self.__ws.send_bytes(self.__site.heartbeat)
            except:
                pass

    async def fetch_danmaku(self):
        while self.__stop != True:
            async for msg in self.__ws:
                # self.__link_status = True
                ms = self.__site.decode_msg(msg.data)
                for m in ms:
                    if not m.get('time',0):
                        m['time'] = datetime.now()
                    await self.__dm_queue.put(m)
            if self.__stop != True:
                await asyncio.sleep(1)
                await self.init_ws()
                await asyncio.sleep(1)

    async def start(self):
        if self.__site != None:
            await self.init_ws()
            await asyncio.gather(
                self.heartbeats(),
                self.fetch_danmaku(),
            )
        else:
            await self.__usite.run(self.__url, self.__dm_queue, self.__hs, **self.__extra_data)

    async def stop(self):
        self.__stop = True
        if self.__site != None:
            await self.__hs.close()
        else:
            await self.__usite.stop()
            await self.__hs.close()

from datetime import datetime
import json, re, select, random, traceback
from struct import pack, unpack
import asyncio, aiohttp, zlib

class Bilibili:
    heartbeat = b"\x00\x00\x00\x1f\x00\x10\x00\x01\x00\x00\x00\x02\x00\x00\x00\x01\x5b\x6f\x62\x6a\x65\x63\x74\x20\x4f\x62\x6a\x65\x63\x74\x5d"

    async def get_ws_info(url):
        url = "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + url.split("/")[-1]
        reg_datas = []
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                room_json = json.loads(await resp.text())
                room_id = room_json["data"]["room_id"]
                data = json.dumps(
                    {"roomid": room_id, "uid": int(1e14 + 2e14 * random.random()), "protover": 2},
                    separators=(",", ":"),
                ).encode("ascii")
                data = (
                    pack(">i", len(data) + 16)
                    + b"\x00\x10\x00\x01"
                    + pack(">i", 7)
                    + pack(">i", 1)
                    + data
                )
                reg_datas.append(data)

        return "wss://broadcastlv.chat.bilibili.com/sub", reg_datas
    
    def decode_msg(data):
        dm_list_compressed = []
        dm_list = []
        ops = []
        msgs = []
        # print(data)
        while True:
            try:
                packetLen, headerLen, ver, op, seq = unpack("!IHHII", data[0:16])
            except Exception as e:
                break
            if len(data) < packetLen:
                break
            if ver == 1 or ver == 0:
                ops.append(op)
                dm_list.append(data[16:packetLen])
            elif ver == 2:
                dm_list_compressed.append(data[16:packetLen])
            if len(data) == packetLen:
                data = b""
                break
            else:
                data = data[packetLen:]

        for dm in dm_list_compressed:
            d = zlib.decompress(dm)
            while True:
                try:
                    packetLen, headerLen, ver, op, seq = unpack("!IHHII", d[0:16])
                except Exception as e:
                    break
                if len(d) < packetLen:
                    break
                ops.append(op)
                dm_list.append(d[16:packetLen])
                if len(d) == packetLen:
                    d = b""
                    break
                else:
                    d = d[packetLen:]

        for i, d in enumerate(dm_list):
            try:
                msg = {}
                if ops[i] == 5:
                    j = json.loads(d)
                    msg["msg_type"] = {
                        "SEND_GIFT": "gift",
                        "DANMU_MSG": "danmaku",
                        "WELCOME": "enter",
                        "NOTICE_MSG": "broadcast",
                    }.get(j.get("cmd"), "other")

                    if 'DANMU_MSG' in j.get('cmd'):
                        msg["msg_type"] = "danmaku"

                    if msg["msg_type"] == "danmaku":
                        msg["name"] = j.get("info", ["", "", ["", ""]])[2][1] or j.get(
                            "data", {}
                        ).get("uname", "")
                        msg["color"] = f"{j.get('info', [[0, 0, 0, 16777215]])[0][3]:06x}"
                        msg["content"] = j.get("info")[1]
                        try:
                            msg['time'] = datetime.fromtimestamp(j.get('info')[0][4]/1000)
                            if j.get('info')[13] != r'{}':
                                emoticon_info = j.get('info')[0][13]
                                msg["content"] = emoticon_info['emoticon_unique']
                                msg['msg_type'] = 'emoticon'
                        except:
                            pass
                        
                    elif msg["msg_type"] == "broadcast":
                        msg["type"] = j.get("msg_type", 0)
                        msg["roomid"] = j.get("real_roomid", 0)
                        msg["content"] = j.get("msg_common", "none")
                        msg["raw"] = j

                    msg["raw_data"] = j
                    
                else:
                    msg = {"name": "", "content": d, "msg_type": "other"}
                msgs.append(msg)
            except Exception as e:
                # traceback.print_exc()
                # print(e)
                pass

        return msgs