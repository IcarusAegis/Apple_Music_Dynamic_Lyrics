import re
from typing import List, Dict

class LyricLine:
    def __init__(self, time_ms: int, text: str):
        self.time_ms = time_ms
        self.text = text
        self.translation = ""

    def __repr__(self):
        return f"[{self.time_ms}ms] {self.text} (trans: {self.translation})"

class LyricParser:
    def __init__(self):
        # Matches [mm:ss.xx] or [mm:ss.xxx]
        self.time_pattern = re.compile(r'\[(\d{2,}):(\d{2}(?:\.\d{2,3})?)\]')
        
    def _parse_time_to_ms(self, match: re.Match) -> int:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return int((minutes * 60 + seconds) * 1000)

    def parse(self, lrc: str, tlyric: str = "") -> List[LyricLine]:
        """Parse original and translated lyrics, merging them by time."""
        if not lrc:
            return []

        lines = self._parse_single_lrc(lrc)
        
        if tlyric:
            trans_lines = self._parse_single_lrc(tlyric)
            # Create a dictionary for quick translation lookup by time
            trans_dict = {tl.time_ms: tl.text for tl in trans_lines}
            
            # Match translations to original lines
            # Note: Sometimes time tags are not perfectly identical (e.g. 1ms off)
            # but usually they are exact match in Netease API
            for line in lines:
                if line.time_ms in trans_dict:
                    line.translation = trans_dict[line.time_ms]
                else:
                    # fuzzy match within 100ms
                    for t_time, t_text in trans_dict.items():
                        if abs(t_time - line.time_ms) <= 100:
                            line.translation = t_text
                            break

        return lines

    def _parse_single_lrc(self, lrc: str) -> List[LyricLine]:
        results = []
        for raw_line in lrc.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Some lines might have multiple time tags: [00:12.00][00:15.00] hello
            matches = list(self.time_pattern.finditer(raw_line))
            if not matches:
                continue
            
            # The actual text is after the last time tag
            last_match = matches[-1]
            text = raw_line[last_match.end():].strip()
            
            # Ignore lines that are just meta info like [00:00.00] 作词: xxx
            if text.startswith("作词") or text.startswith("作曲") or text.startswith("编曲"):
                # But keep it if it's considered a lyric line, usually we want to see it
                pass

            for match in matches:
                time_ms = self._parse_time_to_ms(match)
                results.append(LyricLine(time_ms, text))
                
        # Sort by time
        results.sort(key=lambda x: x.time_ms)
        return results

# Test block
if __name__ == "__main__":
    parser = LyricParser()
    test_lrc = """
[00:00.000] 作词 : 五月天 阿信
[00:01.000] 作曲 : 王力宏
[00:20.860]这厢是 梦梅恋上画中的仙
[00:23.990]那厢是 丽娘为爱消香殒碎
"""
    test_tlyric = """
[00:20.86]This is Mengmei falling in love with a fairy in the painting
[00:23.99]That is Liniang dying for love
"""
    parsed = parser.parse(test_lrc, test_tlyric)
    for p in parsed:
        print(p)
