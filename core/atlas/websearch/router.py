"""Query routing: Chinese queries go to the Chinese-native index first.

Western engines (Exa, Brave, Parallel, Tavily) index zhihu / weixin / bilibili / csdn poorly;
Bocha is built on a Chinese index. Atlas-own (no Hermes counterpart).
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WORDISH = re.compile(r"[A-Za-z0-9]+|[㐀-䶿一-鿿豈-﫿]")
# Hosts whose content lives mostly in the Chinese index even when the query is English.
_CN_HOSTS = ("zhihu.com", "weixin.qq.com", "mp.weixin.qq.com", "bilibili.com", "csdn.net", "douban.com",
             "weibo.com", "xiaohongshu.com", "juejin.cn", "cnblogs.com", "baidu.com", "163.com", "sohu.com",
             "qq.com", "jianshu.com", "gitee.com", "36kr.com", "sspai.com", ".cn")


def is_chinese_query(query: str, allowed_domains: list[str] | None = None) -> bool:
    """True when at least ~30% of the query's word units are CJK characters, or the caller
    restricted the search to Chinese sites."""
    for domain in allowed_domains or []:
        d = domain.strip().lower().lstrip("*.")
        if any(d == h.lstrip(".") or d.endswith(h if h.startswith(".") else "." + h) or d == h for h in _CN_HOSTS):
            return True
    units = _WORDISH.findall(query or "")
    if not units:
        return False
    cjk = sum(1 for u in units if _CJK.match(u))
    return cjk / len(units) >= 0.3
