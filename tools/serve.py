#!/usr/bin/env python3
"""TariffLens 数据层验证页的本地静态服务器。

关键：.gz 一律以 application/octet-stream 发送，**不带 Content-Encoding**。
这样浏览器 fetch 拿到的是原始 gzip 字节，必须由页面自己用
DecompressionStream('gzip') 解压 —— 与正式产品方案完全一致，
因此这个服务器本身就是方案可行性验证的一部分。

用法：  python3 serve.py [port]       默认 8771
"""
import http.server
import os
import socketserver
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8771


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def guess_type(self, path):
        if path.endswith(".gz"):
            return "application/octet-stream"
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        # 静音常规访问日志，只打印异常
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"serving {ROOT}")
        print(f"  http://127.0.0.1:{PORT}/verify.html")
        httpd.serve_forever()
