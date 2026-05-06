"""
GitHub OAuth 認證模組
支援直接在瀏覽器中登入 GitHub，無需使用 gh CLI
"""

import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import threading
import httpx
from typing import Optional


class GitHubOAuth:
    """GitHub OAuth 認證處理器"""
    
    # GitHub OAuth App 設定
    # 注意：這些是公開的 OAuth App 憑證，僅用於本地開發
    CLIENT_ID = "Iv1.b507a08c87ecfe98"  # 你需要在 GitHub 註冊一個 OAuth App 來獲取
    REDIRECT_URI = "http://localhost:8765/callback"
    SCOPES = "repo read:org copilot"  # 需要的權限範圍
    
    def __init__(self):
        self.auth_code: Optional[str] = None
        self.expected_state: Optional[str] = None
        self.state_mismatch: bool = False
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        # Allow the polling loop to wait on a real condition instead of sleeping.
        self._completed = threading.Event()
        
    class CallbackHandler(BaseHTTPRequestHandler):
        """處理 OAuth 回調的 HTTP 伺服器"""
        
        oauth_instance = None  # 將由外部設定
        
        def do_GET(self):
            """處理 GET 請求"""
            # 解析 URL
            parsed_path = urlparse(self.path)
            
            if parsed_path.path == '/callback':
                # 解析查詢參數
                params = parse_qs(parsed_path.query)
                
                if 'code' in params:
                    # CSRF protection: state must echo the value we sent.
                    received_state = params.get('state', [None])[0]
                    expected_state = self.oauth_instance.expected_state
                    if expected_state is not None and received_state != expected_state:
                        self.oauth_instance.state_mismatch = True
                        self.send_response(400)
                        self.send_header('Content-type', 'text/plain; charset=utf-8')
                        self.end_headers()
                        self.wfile.write("OAuth state mismatch — possible CSRF; request rejected.".encode("utf-8"))
                        self.oauth_instance._completed.set()
                        return
                    # 成功獲取授權碼
                    self.oauth_instance.auth_code = params['code'][0]
                    self.oauth_instance._completed.set()
                    
                    # 返回成功頁面
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    
                    success_html = """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <title>認證成功</title>
                        <style>
                            body {
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                                display: flex;
                                justify-content: center;
                                align-items: center;
                                height: 100vh;
                                margin: 0;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            }
                            .container {
                                background: white;
                                padding: 40px;
                                border-radius: 10px;
                                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                                text-align: center;
                            }
                            h1 {
                                color: #28a745;
                                margin-bottom: 20px;
                            }
                            p {
                                color: #666;
                                font-size: 16px;
                            }
                            .checkmark {
                                font-size: 60px;
                                color: #28a745;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="checkmark">✓</div>
                            <h1>認證成功！</h1>
                            <p>你已經成功登入 GitHub。</p>
                            <p>現在可以關閉此視窗，返回應用程式繼續操作。</p>
                        </div>
                    </body>
                    </html>
                    """
                    self.wfile.write(success_html.encode('utf-8'))
                    
                elif 'error' in params:
                    # Mark completion so the waiting loop unblocks.
                    self.oauth_instance._completed.set()
                    # 認證失敗
                    error = params['error'][0]
                    error_description = params.get('error_description', ['Unknown error'])[0]
                    
                    self.send_response(400)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    
                    error_html = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <meta charset="utf-8">
                        <title>認證失敗</title>
                        <style>
                            body {{
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                                display: flex;
                                justify-content: center;
                                align-items: center;
                                height: 100vh;
                                margin: 0;
                                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                            }}
                            .container {{
                                background: white;
                                padding: 40px;
                                border-radius: 10px;
                                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                                text-align: center;
                            }}
                            h1 {{
                                color: #dc3545;
                                margin-bottom: 20px;
                            }}
                            p {{
                                color: #666;
                                font-size: 16px;
                            }}
                            .error-icon {{
                                font-size: 60px;
                                color: #dc3545;
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="error-icon">✗</div>
                            <h1>認證失敗</h1>
                            <p>錯誤：{error}</p>
                            <p>{error_description}</p>
                            <p>請關閉此視窗並重試。</p>
                        </div>
                    </body>
                    </html>
                    """
                    self.wfile.write(error_html.encode('utf-8'))
            else:
                # 未知路徑
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            """靜默日誌輸出"""
            pass
    
    def start_oauth_flow(self) -> Optional[str]:
        """
        啟動 OAuth 認證流程
        
        Returns:
            GitHub access token，如果認證失敗則返回 None
        """
        # 生成隨機 state 用於防止 CSRF 攻擊
        state = secrets.token_urlsafe(32)
        self.expected_state = state
        self.state_mismatch = False
        self._completed.clear()

        # 啟動本地伺服器
        try:
            self.server = HTTPServer(('localhost', 8765), self.CallbackHandler)
            self.CallbackHandler.oauth_instance = self
            
            # 在背景執行緒中啟動伺服器
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            
            print("✓ 本地回調伺服器已啟動 (http://localhost:8765)")
            
        except OSError as e:
            print(f"✗ 無法啟動本地伺服器：{e}")
            print("  請確保 8765 端口未被佔用")
            return None
        
        # 構建 OAuth 授權 URL
        auth_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={self.CLIENT_ID}"
            f"&redirect_uri={self.REDIRECT_URI}"
            f"&scope={self.SCOPES.replace(' ', '%20')}"
            f"&state={state}"
        )
        
        print("\n🔐 正在打開瀏覽器進行 GitHub 認證...")
        print(f"   如果瀏覽器未自動打開，請手動訪問：")
        print(f"   {auth_url}\n")
        
        # 在瀏覽器中打開授權 URL
        webbrowser.open(auth_url)
        
        # 等待接收授權碼（最多等待 5 分鐘）
        print("⏳ 等待認證完成...")
        # Wait on the completion event with a 5-minute deadline; this avoids
        # creating a fresh threading.Event() each iteration just to sleep.
        self._completed.wait(timeout=300)

        # 停止伺服器
        if self.server:
            self.server.shutdown()
            self.server = None

        if self.state_mismatch:
            print("✗ 偵測到 OAuth state 不符（可能是 CSRF），拒絕授權碼")
            return None

        if not self.auth_code:
            print("✗ 認證超時（5 分鐘內未完成）")
            return None
        
        print("✓ 已接收授權碼")
        
        # 使用授權碼換取 access token
        return self._exchange_code_for_token(self.auth_code)
    
    def _exchange_code_for_token(self, code: str) -> Optional[str]:
        """
        使用授權碼換取 access token
        
        Args:
            code: 授權碼
            
        Returns:
            Access token，如果交換失敗則返回 None
        """
        print("🔄 正在換取 access token...")
        
        # 注意：這需要 OAuth App 的 client_secret
        # 對於公開的桌面應用，應該使用 Device Flow 而不是標準的 OAuth Flow
        # 這裡為了簡化，先展示標準流程
        # 實際部署時建議使用 GitHub Device Flow
        
        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={
                        "Accept": "application/json",
                    },
                    data={
                        "client_id": self.CLIENT_ID,
                        "client_secret": "",  # 需要你的 client_secret
                        "code": code,
                        "redirect_uri": self.REDIRECT_URI,
                    },
                    timeout=30.0,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "access_token" in data:
                        print("✓ 成功獲取 access token")
                        return data["access_token"]
                    else:
                        print(f"✗ 無法獲取 token：{data}")
                        return None
                else:
                    print(f"✗ 請求失敗：{response.status_code}")
                    return None
                    
        except Exception as e:
            print(f"✗ 換取 token 時發生錯誤：{e}")
            return None


class GitHubDeviceFlow:
    """
    GitHub Device Flow 認證（推薦用於桌面應用）
    不需要 client_secret，更安全
    """
    
    CLIENT_ID = "Iv1.b507a08c87ecfe98"  # GitHub OAuth App Client ID
    
    def start_device_flow(self) -> Optional[str]:
        """
        啟動 Device Flow 認證
        
        Returns:
            GitHub access token，如果認證失敗則返回 None
        """
        print("\n🔐 正在啟動 GitHub 裝置認證流程...")
        
        try:
            with httpx.Client() as client:
                # 步驟 1：請求裝置碼和使用者碼
                response = client.post(
                    "https://github.com/login/device/code",
                    headers={
                        "Accept": "application/json",
                    },
                    data={
                        "client_id": self.CLIENT_ID,
                        "scope": "repo read:org copilot",
                    },
                    timeout=30.0,
                )
                
                if response.status_code != 200:
                    print(f"✗ 無法獲取裝置碼：{response.status_code}")
                    return None
                
                device_data = response.json()
                device_code = device_data["device_code"]
                user_code = device_data["user_code"]
                verification_uri = device_data["verification_uri"]
                expires_in = device_data["expires_in"]
                interval = device_data.get("interval", 5)
                
                print(f"\n📱 請在瀏覽器中訪問：{verification_uri}")
                print(f"   並輸入代碼：{user_code}")
                print(f"   (代碼將在 {expires_in} 秒後過期)\n")
                
                # 自動打開瀏覽器
                webbrowser.open(verification_uri)
                
                # 步驟 2：輪詢檢查使用者是否完成授權
                print("⏳ 等待授權完成...")
                
                import time
                start_time = time.time()
                
                while time.time() - start_time < expires_in:
                    time.sleep(interval)
                    
                    # 檢查授權狀態
                    poll_response = client.post(
                        "https://github.com/login/oauth/access_token",
                        headers={
                            "Accept": "application/json",
                        },
                        data={
                            "client_id": self.CLIENT_ID,
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                        timeout=30.0,
                    )
                    
                    if poll_response.status_code == 200:
                        token_data = poll_response.json()
                        
                        if "access_token" in token_data:
                            print("✓ 認證成功！")
                            return token_data["access_token"]
                        elif token_data.get("error") == "authorization_pending":
                            # 使用者尚未完成授權，繼續等待
                            print(".", end="", flush=True)
                            continue
                        elif token_data.get("error") == "slow_down":
                            # 輪詢太快，增加等待時間
                            interval += 5
                            continue
                        elif token_data.get("error") in ["expired_token", "access_denied"]:
                            # 授權過期或被拒絕
                            print(f"\n✗ 認證失敗：{token_data.get('error_description', token_data.get('error'))}")
                            return None
                    
                print("\n✗ 認證超時")
                return None
                
        except Exception as e:
            print(f"✗ 認證過程中發生錯誤：{e}")
            return None


def authenticate_github(use_device_flow: bool = True) -> Optional[str]:
    """
    便利函數：啟動 GitHub 認證流程
    
    Args:
        use_device_flow: 是否使用 Device Flow（推薦）。False 則使用標準 OAuth Flow
        
    Returns:
        GitHub access token，如果認證失敗則返回 None
    """
    if use_device_flow:
        flow = GitHubDeviceFlow()
        return flow.start_device_flow()
    else:
        oauth = GitHubOAuth()
        return oauth.start_oauth_flow()


if __name__ == "__main__":
    # 測試
    print("GitHub 認證測試")
    print("=" * 50)
    
    # 使用 Device Flow（推薦）
    token = authenticate_github(use_device_flow=True)
    
    if token:
        print(f"\n✓ 成功獲取 token：{token[:20]}...")
    else:
        print("\n✗ 認證失敗")
