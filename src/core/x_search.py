"""
meshctx x_search — X/Twitter 搜索
对标: OpenClaw x_search
"""
import os, json, urllib.request, urllib.parse

def x_search(query: str, count: int = 10, result_type: str = "recent",
             bearer_token: str = None) -> dict:
    """搜索 X/Twitter 帖子
    
    Args:
        query: 搜索词
        count: 结果数 (max 100)
        result_type: recent | popular | mixed
        bearer_token: X API Bearer Token (默认从 X_BEARER_TOKEN 环境变量读取)
    """
    token = bearer_token or os.environ.get("X_BEARER_TOKEN", "")
    if not token:
        return {"ok": False, "error": "X_BEARER_TOKEN not set. Get one at https://developer.x.com"}
    
    try:
        params = urllib.parse.urlencode({
            "query": query, "max_results": min(count, 100),
            "tweet.fields": "created_at,author_id,public_metrics",
            "expansions": "author_id",
            "user.fields": "name,username"
        })
        url = f"https://api.twitter.com/2/tweets/search/recent?{params}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "meshctx/1.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        
        tweets = []
        users = {u["id"]: u for u in (data.get("includes", {}).get("users", []))}
        for t in data.get("data", []):
            author = users.get(t["author_id"], {})
            tweets.append({
                "id": t["id"],
                "text": t["text"],
                "author": author.get("username", "unknown"),
                "author_name": author.get("name", ""),
                "created_at": t.get("created_at", ""),
                "likes": t.get("public_metrics", {}).get("like_count", 0),
                "retweets": t.get("public_metrics", {}).get("retweet_count", 0),
                "url": f"https://x.com/{author.get('username','i')}/status/{t['id']}"
            })
        return {"ok": True, "query": query, "count": len(tweets), "tweets": tweets}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def x_user_tweets(username: str, count: int = 10) -> dict:
    """获取用户最近推文"""
    token = os.environ.get("X_BEARER_TOKEN", "")
    if not token:
        return {"ok": False, "error": "X_BEARER_TOKEN not set"}
    try:
        # 先获取用户ID
        url = f"https://api.twitter.com/2/users/by/username/{username}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            user = json.loads(resp.read())
        uid = user["data"]["id"]
        
        # 获取推文
        url2 = f"https://api.twitter.com/2/users/{uid}/tweets?max_results={min(count,100)}&tweet.fields=created_at,public_metrics"
        req2 = urllib.request.Request(url2, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req2, timeout=10) as resp:
            data = json.loads(resp.read())
        
        tweets = [{"id": t["id"], "text": t["text"], "created_at": t.get("created_at"),
                   "likes": t.get("public_metrics",{}).get("like_count",0),
                   "url": f"https://x.com/{username}/status/{t['id']}"}
                  for t in data.get("data", [])]
        return {"ok": True, "username": username, "count": len(tweets), "tweets": tweets}
    except Exception as e:
        return {"ok": False, "error": str(e)}
