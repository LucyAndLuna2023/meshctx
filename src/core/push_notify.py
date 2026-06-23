"""
meshctx PushNotification — 推送通知到桌面/手机
对标: Claude Code PushNotification
支持: Desktop (notify-send/terminal-notifier), Telegram, Webhook
"""
import os, subprocess, json, urllib.request

def push_notify(title: str, body: str = "", urgency: str = "normal",
                platform: str = "auto") -> str:
    """发送推送通知"""
    platform = platform.lower()
    
    # Desktop notification
    if platform in ("auto", "desktop"):
        # Linux: notify-send
        try:
            subprocess.run(["notify-send", "-u", urgency, title, body], 
                          timeout=5, capture_output=True)
            return f"Desktop notification sent: {title}"
        except FileNotFoundError:
            pass
        # macOS: terminal-notifier
        try:
            subprocess.run(["terminal-notifier", "-title", title, "-message", body],
                          timeout=5, capture_output=True)
            return f"Desktop notification sent: {title}"
        except FileNotFoundError:
            pass
        # Windows: PowerShell toast
        try:
            subprocess.run(["powershell", "-Command",
                f"Add-Type -AssemblyName System.Windows.Forms; "  
                f"$n = New-Object System.Windows.Forms.NotifyIcon; "
                f"$n.Icon = [System.Drawing.SystemIcons]::Information; "
                f"$n.BalloonTipTitle = '{title}'; "
                f"$n.BalloonTipText = '{body}'; "
                f"$n.Visible = $true; $n.ShowBalloonTip(5000)"],
                timeout=10, capture_output=True)
            return f"Windows notification sent: {title}"
        except:
            pass
    
    # Telegram
    if platform in ("auto", "telegram"):
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            try:
                text = f"<b>{title}</b>\n{body}" if body else title
                data = json.dumps({"chat_id": chat_id, "text": text, 
                    "parse_mode": "HTML"}).encode()
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                req = urllib.request.Request(url, data=data,
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10)
                return f"Telegram notification sent: {title}"
            except:
                pass
    
    # Fallback: print to console
    print(f"\n{'='*50}\n🔔 {title}\n{body}\n{'='*50}")
    return f"Console notification: {title}"

def push_notify_on_completion(task_name: str):
    """任务完成时发送通知（别名）"""
    return push_notify("✅ Task Complete", task_name)
