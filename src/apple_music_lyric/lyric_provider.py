import httpx
import json
import binascii
import re
import asyncio
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from typing import Optional, Dict

class LyricProvider:
    def __init__(self):
        self.linuxapi_key = b"rFgB&h#%2?^eDg:Q"
        self.anonymous_token = "bf8bfeabb1aa84f9c8c3906c04a04fb864322804c83f5d607e91a04eae463c9436bd1a17ec353cf780b396507a3f7464e8a60f4bbc019437993166e004087dd32d1490298caf655c2353e58daa0bc13cc7d5c198250968580b12c1b8817e3f5c807e650dd04abd3fb8130b7ae43fcc5b"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36",
            "Cookie": f"MUSIC_A={self.anonymous_token}",
            "Referer": "https://music.163.com"
        }
        self.netease_client = httpx.AsyncClient(headers=self.headers)
        self.qq_client = httpx.AsyncClient(headers={
            "Referer": "https://y.qq.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
        })

    def _encrypt_linuxapi(self, text: str) -> str:
        cipher = AES.new(self.linuxapi_key, AES.MODE_ECB)
        padded_text = pad(text.encode('utf-8'), AES.block_size)
        encrypted = cipher.encrypt(padded_text)
        return binascii.hexlify(encrypted).decode('utf-8').upper()

    def _prepare_data(self, method: str, url: str, params: dict) -> dict:
        text = json.dumps({
            "method": method,
            "url": url,
            "params": params
        })
        return {"eparams": self._encrypt_linuxapi(text)}

    def _clean_keyword(self, keyword: str) -> str:
        if not keyword:
            return ""
        cleaned = keyword.split(' — ')[0].strip()
        cleaned = cleaned.replace("'", "").replace("·", "").replace("$", "").replace("&", "")
        cleaned = re.sub(r'\s+[-—]\s+(Single|EP).*?$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\(.*?\)|\[.*?\]|\{.*?\}|（.*?）', '', cleaned)
        return cleaned.strip()

    async def _search_netease(self, query: str, limit: int = 10) -> list:
        data = self._prepare_data("POST", "https://music.163.com/api/search/get", {"s": query, "type": 1, "limit": limit, "offset": 0})
        try:
            response = await self.netease_client.post("https://music.163.com/api/linux/forward", data=data, timeout=5.0)
            response.raise_for_status()
            songs = response.json().get("result", {}).get("songs", [])
            for s in songs:
                s['id'] = f"netease:{s['id']}"
                if 'album' in s:
                    s['album']['name'] = "[网易] " + s['album'].get('name', '')
            return songs
        except Exception as e:
            print(f"Netease search error: {e}")
            return []

    async def _search_qq(self, query: str, limit: int = 10) -> list:
        url = "http://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        params = {"format": "json", "n": limit, "p": 1, "w": query, "cr": 1, "g_tk": 5381}
        try:
            res = await self.qq_client.get(url, params=params, timeout=5.0)
            res.raise_for_status()
            text = res.text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match: return []
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
                
            songs = data.get("data", {}).get("song", {}).get("list", [])
            results = []
            for s in songs:
                results.append({
                    "id": f"qq:{s.get('songmid')}",
                    "name": s.get("songname"),
                    "artists": [{"name": a.get("name", "")} for a in s.get("singer", [])],
                    "album": {"name": "[QQ] " + s.get("albumname", "")},
                    "duration": s.get("interval", 0) * 1000
                })
            return results
        except Exception as e:
            print("QQ search error:", e)
            return []

    async def search_songs_list(self, query: str, limit: int = 10) -> dict:
        netease_task = asyncio.create_task(self._search_netease(query, limit))
        qq_task = asyncio.create_task(self._search_qq(query, limit))
        res = await asyncio.gather(netease_task, qq_task, return_exceptions=True)
        
        n_res = res[0]
        q_res = res[1]
        netease_res = n_res if isinstance(n_res, list) else []
        qq_res = q_res if isinstance(q_res, list) else []
        
        return {
            "netease": netease_res,
            "qq": qq_res
        }

    async def search_song(self, title: str, artist: str) -> Optional[str]:
        clean_title = self._clean_keyword(title)
        clean_artist = self._clean_keyword(artist)
        query = f"{clean_title} {clean_artist}".strip()
        
        res = await self.search_songs_list(query, 10)
        
        n_res, q_res = res.get("netease", []), res.get("qq", [])
        if not n_res and not q_res:
            if clean_artist:
                return await self.search_song(title, "")
            return None
        
        if n_res: return n_res[0].get("id")
        return q_res[0].get("id")

    async def get_lyric(self, song_id: str) -> Dict[str, str]:
        if song_id.startswith("qq:"):
            return await self._get_qq_lyric(song_id[3:])
            
        nid = song_id[8:] if song_id.startswith("netease:") else song_id
        
        data = self._prepare_data(
            "POST",
            "https://music.163.com/api/song/lyric?lv=-1&kv=-1&tv=-1",
            {"id": nid}
        )
        try:
            response = await self.netease_client.post(
                "https://music.163.com/api/linux/forward",
                data=data,
                timeout=5.0
            )
            response.raise_for_status()
            res_json = response.json()
            
            lrc = res_json.get("lrc", {}).get("lyric", "")
            tlyric = res_json.get("tlyric", {}).get("lyric", "")
            
            return {
                "lrc": lrc,
                "tlyric": tlyric
            }
        except Exception as e:
            print(f"Lyric fetch error (Netease): {e}")
            return {"lrc": "", "tlyric": ""}

    async def _get_qq_lyric(self, songmid: str) -> Dict[str, str]:
        url = "http://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
        params = {"songmid": songmid, "g_tk": 5381, "format": "json"}
        try:
            res = await self.qq_client.get(url, params=params, timeout=5.0)
            res.raise_for_status()
            text = res.text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if not match: return {"lrc": "", "tlyric": ""}
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {"lrc": "", "tlyric": ""}
                
            b64lyric = data.get("lyric", "")
            b64tlyric = data.get("trans", "")
            
            lrc = base64.b64decode(b64lyric).decode('utf-8') if b64lyric else ""
            tlyric = base64.b64decode(b64tlyric).decode('utf-8') if b64tlyric else ""
            return {"lrc": lrc, "tlyric": tlyric}
        except Exception as e:
            print("Lyric fetch error (QQ):", e)
            return {"lrc": "", "tlyric": ""}

    async def fetch_lyrics_for_song(self, title: str, artist: str) -> Dict[str, str]:
        print(f"Searching lyrics for: {title} - {artist}")
        song_id = await self.search_song(title, artist)
        if not song_id:
            print("Song not found on any provider.")
            return {"lrc": "", "tlyric": ""}
        
        print(f"Found song ID: {song_id}, fetching lyrics...")
        return await self.get_lyric(song_id)

    async def close(self):
        await self.netease_client.aclose()
        await self.qq_client.aclose()
