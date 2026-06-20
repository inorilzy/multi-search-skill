"""Zhihu-specific URL helpers."""
import urllib.parse


_ZHIHU_HOST_SUFFIX = ".zhihu.com"
_ZHIHU_HOSTS = {
    "zhihu.com",
    "www.zhihu.com",
    "zhuanlan.zhihu.com",
}

_BLOCK_MARKERS = (
    "你似乎来到了没有知识存在的荒原",
    "1 秒后自动跳转至知乎首页",
    "去往首页",
)

_LOGIN_WALL_MARKERS = (
    "打开知乎App",
    "登录/注册",
    "验证码登录",
    "其他方式登录",
)

_CONTENT_MARKERS = (
    "赞同了该",
    "人赞同",
    "赞同",
    "评论",
    "收藏",
    "发布于",
)


def is_zhihu_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in _ZHIHU_HOSTS or host.endswith(_ZHIHU_HOST_SUFFIX)


def is_zhihu_blocked_text(text: str) -> bool:
    content = (text or "").strip()
    if not content:
        return False
    if any(marker in content for marker in _BLOCK_MARKERS):
        return True
    has_substantial_content = len(content) >= 500 and any(marker in content for marker in _CONTENT_MARKERS)
    if has_substantial_content:
        return False
    return all(marker in content for marker in _LOGIN_WALL_MARKERS)
