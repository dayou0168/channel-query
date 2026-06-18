#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地批量查询工具：
1. 根据 WPPChat 账号调用后台 /api/im/imUserInfo/list 查注册来源 sms_phone
2. 将注册来源标准化为来源编号
3. 在渠道表的“来源编号”列查找，并返回其左侧的渠道编码

默认启动本地 HTTP 服务；后台登录成功后会把 token 保存到本机，供 Telegram 机器人读取。
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import html
import io
import ipaddress
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


BACKEND_BASE_URL = os.environ.get("WPPCHAT_BACKEND_URL", "https://zhheew.bw009.com")
BACKEND_LIST_PATH = "/api/im/imUserInfo/list"
DEFAULT_SHEET_URL = os.environ.get("CHANNEL_QUERY_SHEET_URL", "")

GOOGLE_OAUTH_STATE: dict[str, dict[str, Any]] = {}
GOOGLE_OAUTH_TOKEN: dict[str, Any] = {}
BACKEND_SESSION_TOKEN = ""
SECURE_STORE_ENTROPY = b"channel-query-secure-store-v1"
MASTER_KEY_ENV = "CHANNEL_QUERY_MASTER_KEY"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CHANNEL_QUERY_DATA_DIR", str(APP_DIR))).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = (APP_DIR / DATA_DIR).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DRAFT_FILE = DATA_DIR / ".channel_query_draft.json"
BACKEND_TOKEN_FILE = DATA_DIR / ".backend_token.enc"
LEGACY_BACKEND_TOKEN_FILE = DATA_DIR / ".backend_token"
LEGACY_BACKEND_DPAPI_TOKEN_FILE = DATA_DIR / ".backend_token.dpapi"
BACKEND_LOGIN_FILE = DATA_DIR / ".backend_login.enc"
GOOGLE_OAUTH_TOKEN_FILE = DATA_DIR / ".google_oauth_token.enc"
LEGACY_GOOGLE_OAUTH_DPAPI_TOKEN_FILE = DATA_DIR / ".google_oauth_token.dpapi"


def generate_master_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def get_fernet_cipher() -> Any | None:
    key = os.environ.get(MASTER_KEY_ENV, "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode("ascii"))


def dpapi_transform(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("安全加密存储当前仅支持 Windows DPAPI。")
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def make_blob(value: bytes) -> tuple[DataBlob, Any]:
        buffer = ctypes.create_string_buffer(value)
        return DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt_func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    crypt_func.argtypes = [
        ctypes.POINTER(DataBlob),
        wintypes.LPCWSTR if protect else ctypes.c_void_p,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt_func.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    input_blob, input_buffer = make_blob(data)
    entropy_blob, entropy_buffer = make_blob(SECURE_STORE_ENTROPY)
    output_blob = DataBlob()
    description = None if protect else None
    ok = crypt_func(
        ctypes.byref(input_blob),
        description,
        ctypes.byref(entropy_blob),
        None,
        None,
        0x1,
        ctypes.byref(output_blob),
    )
    _ = input_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))


def secure_write_text(path: Path, text: str) -> None:
    cipher = get_fernet_cipher()
    if cipher:
        encrypted = cipher.encrypt(text.encode("utf-8")).decode("ascii")
        path.write_text("fernet:" + encrypted, encoding="ascii")
        return
    if os.name == "nt":
        encrypted = dpapi_transform(text.encode("utf-8"), protect=True)
        path.write_text("dpapi:" + base64.b64encode(encrypted).decode("ascii"), encoding="ascii")
        return
    raise RuntimeError(f"Linux服务器需要先设置 {MASTER_KEY_ENV}。")


def secure_read_text(path: Path) -> str:
    text = path.read_text(encoding="ascii").strip()
    if text.startswith("fernet:"):
        cipher = get_fernet_cipher()
        if not cipher:
            raise RuntimeError(f"缺少 {MASTER_KEY_ENV}，无法解密服务器 token。")
        return cipher.decrypt(text.removeprefix("fernet:").encode("ascii")).decode("utf-8")
    if text.startswith("dpapi:"):
        encrypted = base64.b64decode(text.removeprefix("dpapi:"))
        return dpapi_transform(encrypted, protect=False).decode("utf-8")
    encrypted = base64.b64decode(text)
    return dpapi_transform(encrypted, protect=False).decode("utf-8")


def read_saved_backend_token() -> str:
    for token_path in (BACKEND_TOKEN_FILE, LEGACY_BACKEND_DPAPI_TOKEN_FILE):
        if not token_path.exists():
            continue
        try:
            token = secure_read_text(token_path).strip()
            if token and token_path != BACKEND_TOKEN_FILE:
                try:
                    secure_write_text(BACKEND_TOKEN_FILE, token)
                    token_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if token:
                return token
        except Exception:
            continue
    if LEGACY_BACKEND_TOKEN_FILE.exists():
        try:
            token = LEGACY_BACKEND_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                secure_write_text(BACKEND_TOKEN_FILE, token)
                LEGACY_BACKEND_TOKEN_FILE.unlink(missing_ok=True)
                return token
        except Exception:
            return ""
    return ""


def save_backend_token(token: str) -> bool:
    try:
        secure_write_text(BACKEND_TOKEN_FILE, token)
        LEGACY_BACKEND_TOKEN_FILE.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def normalize_totp_secret(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("otpauth://"):
        parsed = urllib.parse.urlparse(text)
        query = urllib.parse.parse_qs(parsed.query)
        text = (query.get("secret") or [""])[0]
    return re.sub(r"[\s-]+", "", text).upper()


def generate_totp(secret: str, when: int | None = None) -> str:
    normalized = normalize_totp_secret(secret)
    if not normalized:
        raise RuntimeError("缺少Google Authenticator密钥，无法自动生成验证码。")
    padding_len = (-len(normalized)) % 8
    try:
        key = base64.b32decode((normalized + "=" * padding_len).encode("ascii"), casefold=True)
    except Exception as exc:
        raise RuntimeError("Google Authenticator密钥格式不正确。") from exc
    counter = int((when or time.time()) // 30)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def save_backend_login_config(backend_base: str, username: str, password: str, totp_secret: str) -> bool:
    if not username or not password or not totp_secret:
        return False
    data = {
        "backend_base": normalize_backend_base(backend_base),
        "username": username,
        "password": password,
        "totp_secret": normalize_totp_secret(totp_secret),
        "saved_at": int(time.time()),
    }
    try:
        secure_write_text(BACKEND_LOGIN_FILE, json.dumps(data, ensure_ascii=False))
        return True
    except Exception:
        return False


def load_backend_login_config() -> dict[str, str]:
    if not BACKEND_LOGIN_FILE.exists():
        return {}
    try:
        data = json.loads(secure_read_text(BACKEND_LOGIN_FILE))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    required = ("backend_base", "username", "password", "totp_secret")
    if not all(data.get(key) for key in required):
        return {}
    return {key: str(data.get(key) or "") for key in required}


def load_form_draft() -> dict[str, str]:
    if not DRAFT_FILE.exists():
        return {}
    try:
        raw = json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "accounts",
        "sheetUrl",
        "sheetCsv",
        "backendBase",
        "backendUsername",
        "backendToken",
        "serviceAccountFile",
        "oauthClientFile",
    }
    return {key: str(value) for key, value in raw.items() if key in allowed and value is not None}


def json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>渠道查询</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d8dee6;
      --text: #17202a;
      --muted: #637083;
      --accent: #1677ff;
      --accent-strong: #0958d9;
      --ok: #147a3f;
      --warn: #a15c00;
      --bad: #b42318;
      --shadow: 0 8px 24px rgba(22, 34, 51, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 22px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 5;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .status {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--muted);
    }
    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 430px) 1fr;
      gap: 16px;
      padding: 16px;
      max-width: 1500px;
      width: 100%;
      margin: 0 auto;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .left {
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - 88px);
      overflow: auto;
    }
    .section {
      padding: 14px;
      border-bottom: 1px solid var(--line);
    }
    .section:last-child { border-bottom: 0; }
    .section h2 {
      margin: 0 0 10px;
      font-size: 14px;
      font-weight: 650;
    }
    label {
      display: block;
      margin: 10px 0 6px;
      color: var(--muted);
      font-size: 13px;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      color: var(--text);
      background: #fff;
      outline: none;
    }
    input:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.13);
    }
    textarea {
      min-height: 150px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      line-height: 1.45;
    }
    .csv-input { min-height: 110px; }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > * { flex: 1; }
    .row .fit { flex: 0 0 auto; }
    button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 12px;
      background: #fff;
      color: var(--text);
      font: inherit;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      white-space: nowrap;
    }
    button.primary {
      color: #fff;
      border-color: var(--accent);
      background: var(--accent);
    }
    button.primary:hover { background: var(--accent-strong); }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.6;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 12px;
    }
    .actions button.primary {
      grid-column: span 2;
    }
    .message {
      margin-top: 10px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfd;
      color: var(--muted);
      min-height: 40px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .message.error {
      color: var(--bad);
      border-color: #f1b8b4;
      background: #fff6f5;
    }
    .message.ok {
      color: var(--ok);
      border-color: #9bd7b4;
      background: #f4fbf7;
    }
    details {
      margin-top: 12px;
      border: 1px dashed var(--line);
      border-radius: 6px;
      padding: 8px 10px 10px;
      background: #fbfcfd;
    }
    summary {
      cursor: pointer;
      color: var(--muted);
      font-size: 13px;
      user-select: none;
    }
    .results {
      min-height: calc(100vh - 88px);
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .toolbar {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .toolbar h2 {
      margin: 0;
      font-size: 14px;
    }
    .toolbar .right {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .table-wrap {
      overflow: auto;
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
      text-align: left;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f9fafb;
      font-weight: 650;
      color: #26313f;
    }
    td {
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 13px;
    }
    tr.missing td { color: var(--bad); }
    tr.found td.channel { color: var(--ok); font-weight: 650; }
    .empty {
      padding: 28px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 900px) {
      header { padding: 0 14px; }
      main {
        grid-template-columns: 1fr;
        padding: 10px;
      }
      .left, .results {
        max-height: none;
        min-height: auto;
      }
      .toolbar {
        align-items: flex-start;
        flex-direction: column;
      }
      .toolbar .right {
        justify-content: flex-start;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <h1>渠道查询</h1>
      <div class="status"><span id="statusDot" class="dot"></span><span id="statusText">待查询</span></div>
    </header>
    <main>
      <aside class="panel left">
        <div class="section">
          <h2>WPPChat账号</h2>
          <textarea id="accounts" placeholder="每行一个账号，也支持逗号、空格分隔"></textarea>
          <div class="actions">
            <button id="loadSample" type="button">填入示例</button>
            <button id="clearAccounts" type="button">清空账号</button>
          </div>
        </div>
        <div class="section">
          <h2>渠道表</h2>
          <label for="sheetUrl">Google表格链接</label>
          <div class="row">
            <input id="sheetUrl" value="__DEFAULT_SHEET_URL__" />
            <button id="openSheet" class="fit" type="button">打开表格</button>
          </div>
          <label for="csvFile">上传CSV</label>
          <input id="csvFile" type="file" accept=".csv,text/csv" />
          <label for="sheetCsv">粘贴CSV内容</label>
          <textarea id="sheetCsv" class="csv-input" placeholder="需要包含“来源编号”列，渠道编码在它左侧"></textarea>
          <details>
            <summary>高级：私有表格自动读取</summary>
            <label for="serviceAccountFile">服务账号JSON路径</label>
            <input id="serviceAccountFile" placeholder="以后自动读取私有表格时再配置" />
            <label for="oauthClientFile">Google OAuth客户端JSON路径</label>
            <input id="oauthClientFile" placeholder="以后做完整Google登录授权时再配置" />
            <div class="actions">
              <button id="loginGoogle" type="button">授权Google</button>
              <button id="checkGoogle" type="button">检测Google</button>
            </div>
          </details>
        </div>
        <div class="section">
          <h2>后台连接</h2>
          <label for="backendBase">后台地址</label>
          <div class="row">
            <input id="backendBase" value="__BACKEND_BASE_URL__" />
            <button id="openBackend" class="fit" type="button">打开后台</button>
          </div>
          <label for="backendUsername">后台用户名</label>
          <input id="backendUsername" placeholder="后台登录用户名" autocomplete="username" />
          <label for="backendPassword">后台密码</label>
          <input id="backendPassword" type="password" placeholder="后台登录密码" autocomplete="current-password" />
          <label for="backendCaptcha">谷歌验证码</label>
          <input id="backendCaptcha" placeholder="Google Authenticator 6位验证码" inputmode="numeric" />
          <label for="backendTotpSecret">自动续登录密钥</label>
          <input id="backendTotpSecret" type="password" placeholder="Google Authenticator绑定密钥，不是6位验证码" autocomplete="off" />
          <details>
            <summary>高级：手动填写后台 x-token</summary>
            <label for="backendToken">x-token</label>
            <input id="backendToken" type="password" placeholder="一般不用填，软件会优先自动读取当前Chrome登录态" />
          </details>
          <div class="actions">
            <button id="loginBackend" type="button">登录后台</button>
            <button id="checkToken" type="button">检测登录态</button>
            <button id="query" class="primary" type="button">开始查询</button>
          </div>
          <div id="message" class="message">先跑通逻辑：打开后台并登录；打开Google表格，下载CSV后上传或粘贴。高级授权后面再接。</div>
        </div>
      </aside>
      <section class="panel results">
        <div class="toolbar">
          <h2 id="resultTitle">结果</h2>
          <div class="right">
            <button id="copyCsv" type="button" disabled>复制CSV</button>
            <button id="downloadCsv" type="button" disabled>下载CSV</button>
          </div>
        </div>
        <div class="table-wrap">
          <div id="empty" class="empty">暂无结果</div>
          <table id="table" hidden>
            <thead>
              <tr>
                <th>WPPChat账号</th>
                <th>注册IP</th>
                <th>注册省份</th>
                <th>注册来源</th>
                <th>渠道编码</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
      </section>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const FORM_DRAFT = __FORM_DRAFT_JSON__;
    let lastRows = [];

    function parseAccounts(text) {
      return [...new Set(text.split(/[\s,，;；]+/).map(s => s.trim()).filter(Boolean))];
    }

    function setMessage(text, type = "") {
      const el = $("message");
      el.textContent = text;
      el.className = "message" + (type ? " " + type : "");
    }

    function setStatus(text, type = "") {
      $("statusText").textContent = text;
      $("statusDot").className = "dot" + (type ? " " + type : "");
    }

    function restoreDraft() {
      let count = 0;
      for (const [id, value] of Object.entries(FORM_DRAFT || {})) {
        const el = $(id);
        if (el && value) {
          el.value = value;
          count += 1;
        }
      }
      if (count) {
        setMessage("已恢复上次导入的账号和CSV。重启后请重新登录后台。", "ok");
      }
    }

    restoreDraft();

    function toCsv(rows) {
      const headers = ["WPPChat账号", "注册IP", "注册省份", "注册来源", "渠道编码", "状态"];
      const escapeCell = (v) => {
        const s = String(v ?? "");
        return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      return [headers, ...rows.map(r => [
        r.account,
        r.register_ip || "",
        r.register_province || "",
        r.source || "",
        r.channel_code,
        r.status,
      ])]
        .map(row => row.map(escapeCell).join(","))
        .join("\n");
    }

    function render(rows) {
      lastRows = rows;
      $("empty").hidden = rows.length > 0;
      $("table").hidden = rows.length === 0;
      $("copyCsv").disabled = rows.length === 0;
      $("downloadCsv").disabled = rows.length === 0;
      $("resultTitle").textContent = rows.length ? `结果（${rows.length}）` : "结果";
      $("tbody").innerHTML = rows.map(r => {
        const cls = r.channel_code === "未查到" ? "missing" : "found";
        return `<tr class="${cls}">
          <td>${escapeHtml(r.account)}</td>
          <td>${escapeHtml(r.register_ip || "")}</td>
          <td>${escapeHtml(r.register_province || "")}</td>
          <td>${escapeHtml(r.source || "")}</td>
          <td class="channel">${escapeHtml(r.channel_code)}</td>
          <td>${escapeHtml(r.status)}</td>
        </tr>`;
      }).join("");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[ch]));
    }

    async function api(path, body) {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      return data;
    }

    $("csvFile").addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      $("sheetCsv").value = await file.text();
      setMessage(`已载入CSV：${file.name}`, "ok");
    });

    $("openSheet").addEventListener("click", () => {
      const url = $("sheetUrl").value.trim();
      if (url) window.open(url, "_blank", "noopener");
    });

    $("openBackend").addEventListener("click", () => {
      const url = $("backendBase").value.trim();
      if (url) window.open(url, "_blank", "noopener");
    });

    $("loadSample").addEventListener("click", () => {
      $("accounts").value = "abc915915\nbvcxzsdfgh\nnot-exists-demo";
    });

    $("clearAccounts").addEventListener("click", () => {
      $("accounts").value = "";
      render([]);
      setStatus("待查询");
      setMessage("已清空账号。");
    });

    $("checkToken").addEventListener("click", async () => {
      setStatus("检测中", "warn");
      setMessage("正在检测后台登录态...");
      try {
        const data = await api("/api/check-token", {
          backendBase: $("backendBase").value.trim(),
          backendToken: $("backendToken").value.trim(),
        });
        setStatus("可连接", "ok");
        setMessage(`后台连接正常。token来源：${data.tokenSource}。`, "ok");
      } catch (err) {
        setStatus("不可用", "warn");
        setMessage(err.message, "error");
      }
    });

    $("loginBackend").addEventListener("click", async () => {
      setStatus("登录中", "warn");
      setMessage("正在登录后台...");
      try {
        const data = await api("/api/backend-login", {
          backendBase: $("backendBase").value.trim(),
          username: $("backendUsername").value.trim(),
          password: $("backendPassword").value,
          captcha: $("backendCaptcha").value.trim(),
          totpSecret: $("backendTotpSecret").value.trim(),
        });
        $("backendPassword").value = "";
        $("backendCaptcha").value = "";
        $("backendTotpSecret").value = "";
        setStatus("后台已登录", "ok");
        const savedText = data.savedToken ? "已加密保存给Telegram机器人使用" : "但未能保存给Telegram机器人使用";
        const autoText = data.savedLogin ? "自动续登录已开启" : "未保存自动续登录信息";
        setMessage(`后台登录成功：${data.loginName || "已获取token"}，${savedText}，${autoText}。`, data.savedToken ? "ok" : "warn");
      } catch (err) {
        setStatus("登录失败", "warn");
        setMessage(err.message, "error");
      }
    });

    $("loginGoogle").addEventListener("click", () => {
      const clientFile = $("oauthClientFile").value.trim();
      if (!clientFile) {
        setMessage("请先填写 Google OAuth 客户端 JSON 路径。", "error");
        return;
      }
      const url = `/auth/google?clientFile=${encodeURIComponent(clientFile)}`;
      window.location.href = url;
    });

    $("checkGoogle").addEventListener("click", async () => {
      setMessage("正在检测 Google 登录状态...");
      try {
        const data = await api("/api/google-status", {});
        setMessage(data.loggedIn ? `Google已登录：${data.email || "已授权"}` : "Google尚未登录。", data.loggedIn ? "ok" : "");
      } catch (err) {
        setMessage(err.message, "error");
      }
    });

    $("query").addEventListener("click", async () => {
      const accounts = parseAccounts($("accounts").value);
      if (!accounts.length) {
        setMessage("请先输入WPPChat账号。", "error");
        return;
      }
      $("query").disabled = true;
      setStatus("查询中", "warn");
      setMessage(`正在查询 ${accounts.length} 个账号...`);
      try {
        const data = await api("/api/query", {
          accounts,
          backendBase: $("backendBase").value.trim(),
          backendToken: $("backendToken").value.trim(),
          sheetUrl: $("sheetUrl").value.trim(),
          sheetCsv: $("sheetCsv").value,
          serviceAccountFile: $("serviceAccountFile").value.trim(),
        });
        render(data.results);
        setStatus("完成", "ok");
        setMessage(`完成：${data.summary.found} 个查到，${data.summary.missing} 个未查到。渠道表来源：${data.sheetSource}。后台登录：${data.tokenSource}。`, "ok");
      } catch (err) {
        setStatus("失败", "warn");
        setMessage(err.message, "error");
      } finally {
        $("query").disabled = false;
      }
    });

    $("copyCsv").addEventListener("click", async () => {
      await navigator.clipboard.writeText(toCsv(lastRows));
      setMessage("结果CSV已复制。", "ok");
    });

    $("downloadCsv").addEventListener("click", () => {
      const blob = new Blob(["\ufeff" + toCsv(lastRows)], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `渠道查询_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
  </script>
</body>
</html>""".replace("__DEFAULT_SHEET_URL__", html.escape(DEFAULT_SHEET_URL)).replace(
    "__BACKEND_BASE_URL__", html.escape(BACKEND_BASE_URL)
).replace(
    "__FORM_DRAFT_JSON__", json_for_script(load_form_draft())
)


def normalize_source(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return ""
    if "://" in text:
        parsed = urllib.parse.urlparse(text)
        host = parsed.hostname or ""
        return host.split(".")[0].strip()
    if "/" in text:
        parsed = urllib.parse.urlparse("https://" + text)
        if parsed.hostname:
            return parsed.hostname.split(".")[0].strip()
    if "." in text:
        return text.split(".")[0].strip()
    return text


def parse_accounts(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = "\n".join(str(item) for item in value)
    else:
        raw = str(value or "")
    items = [item.strip() for item in re.split(r"[\s,，;；]+", raw) if item.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def google_sheet_to_csv_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
    if not match:
        return url
    sheet_id = match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    gid = (query.get("gid") or [""])[0]
    if not gid and parsed.fragment:
        frag = urllib.parse.parse_qs(parsed.fragment)
        gid = (frag.get("gid") or [""])[0]
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        export_url += f"&gid={urllib.parse.quote(gid)}"
    return export_url


def parse_sheet_url(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(url or "")
    match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
    if not match:
        raise RuntimeError("Google表格链接格式不正确。")
    sheet_id = match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    gid = (query.get("gid") or [""])[0]
    if not gid and parsed.fragment:
        frag = urllib.parse.parse_qs(parsed.fragment)
        gid = (frag.get("gid") or [""])[0]
    return sheet_id, gid or "0"


def fetch_url_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 channel-query/1.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("Google表格未公开，无法直接读取。请上传CSV，或把表格共享为“知道链接的人可查看”。")
        raise RuntimeError(f"读取表格失败：HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"读取表格失败：{exc.reason}") from exc


def sniff_csv(text: str) -> csv.Dialect:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample)
    except csv.Error:
        return csv.excel


def read_delimited_rows(text: str) -> list[list[str]]:
    candidates: list[list[list[str]]] = []
    for delimiter in (",", "\t", ";", "，"):
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        candidates.append(rows)
        if any("来源编号" in [cell.strip() for cell in row] for row in rows[:30]):
            return rows
    rows = list(csv.reader(io.StringIO(text), dialect=sniff_csv(text)))
    candidates.append(rows)
    return max(candidates, key=lambda item: max((len(row) for row in item[:30]), default=0))


def build_channel_map(csv_text: str) -> dict[str, str]:
    if not csv_text.strip():
        raise RuntimeError("渠道表为空。")
    text = csv_text.lstrip("\ufeff")
    rows = read_delimited_rows(text)
    header_index = -1
    source_col = -1
    for idx, row in enumerate(rows[:30]):
        normalized = [cell.strip() for cell in row]
        if "来源编号" in normalized:
            header_index = idx
            source_col = normalized.index("来源编号")
            break
    if header_index < 0 or source_col < 0:
        raise RuntimeError("渠道表中未找到“来源编号”列。")
    if source_col == 0:
        raise RuntimeError("“来源编号”左侧没有渠道编码列。")
    channel_col = source_col - 1
    mapping: dict[str, str] = {}
    for row in rows[header_index + 1 :]:
        if len(row) <= source_col:
            continue
        source_id = normalize_source(row[source_col])
        if not source_id:
            continue
        channel = row[channel_col].strip() if len(row) > channel_col else ""
        if channel:
            mapping[source_id] = channel
    if not mapping:
        raise RuntimeError("渠道表中没有可用的来源编号映射。")
    return mapping


def build_channel_map_from_rows(rows: list[list[Any]]) -> dict[str, str]:
    header_index = -1
    source_col = -1
    for idx, row in enumerate(rows[:30]):
        normalized = [str(cell).strip() for cell in row]
        if "来源编号" in normalized:
            header_index = idx
            source_col = normalized.index("来源编号")
            break
    if header_index < 0 or source_col < 0:
        raise RuntimeError("渠道表中未找到“来源编号”列。")
    if source_col == 0:
        raise RuntimeError("“来源编号”左侧没有渠道编码列。")
    channel_col = source_col - 1
    mapping: dict[str, str] = {}
    for row in rows[header_index + 1 :]:
        if len(row) <= source_col:
            continue
        source_id = normalize_source(row[source_col])
        if not source_id:
            continue
        channel = str(row[channel_col]).strip() if len(row) > channel_col else ""
        if channel:
            mapping[source_id] = channel
    if not mapping:
        raise RuntimeError("渠道表中没有可用的来源编号映射。")
    return mapping


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def get_service_account_access_token(credentials_file: str) -> str:
    path = Path(credentials_file).expanduser()
    if not path.exists():
        raise RuntimeError(f"服务账号JSON不存在：{path}")
    info = json.loads(path.read_text(encoding="utf-8"))
    private_key = serialization.load_pem_private_key(info["private_key"].encode("utf-8"), password=None)
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": info["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
        "aud": info.get("token_uri") or "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    )
    signature = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    assertion = signing_input + "." + b64url(signature)
    payload = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        claims["aud"],
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"服务账号授权失败：HTTP {exc.code} {body}") from exc
    token = data.get("access_token")
    if not token:
        raise RuntimeError("服务账号授权失败：未返回 access_token。")
    return token


def google_api_get_json(url: str, token: str, auth_label: str = "Google账号") -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in (401, 403):
            if auth_label == "服务账号":
                raise RuntimeError("服务账号无权读取表格。请把表格共享给服务账号 client_email，权限选查看者。")
            raise RuntimeError("Google授权账号无权读取表格或授权已过期。请确认授权的Google账号有表格查看权限，并重新授权Google。")
        raise RuntimeError(f"读取 Google Sheets API 失败：HTTP {exc.code} {body}") from exc


def google_api_get_json_oauth(url: str) -> dict[str, Any]:
    return google_api_get_json(url, get_google_oauth_access_token(), "Google账号")


def load_sheet_values_with_token(sheet_url: str, token: str, auth_label: str = "Google账号") -> list[list[Any]]:
    sheet_id, gid = parse_sheet_url(sheet_url)
    meta_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(sheet_id)}"
        "?fields=sheets.properties(sheetId,title)"
    )
    meta = google_api_get_json(meta_url, token, auth_label)
    title = ""
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties", {})
        if str(props.get("sheetId")) == str(gid):
            title = props.get("title", "")
            break
    if not title:
        sheets = meta.get("sheets") or []
        if sheets:
            title = sheets[0].get("properties", {}).get("title", "")
    if not title:
        raise RuntimeError("无法识别 Google 表格工作表名称。")
    encoded_range = urllib.parse.quote(f"'{title}'", safe="")
    values_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{urllib.parse.quote(sheet_id)}"
        f"/values/{encoded_range}?majorDimension=ROWS"
    )
    values = google_api_get_json(values_url, token, auth_label)
    return values.get("values") or []


def load_sheet_with_service_account(sheet_url: str, credentials_file: str) -> list[list[Any]]:
    token = get_service_account_access_token(credentials_file)
    return load_sheet_values_with_token(sheet_url, token, "服务账号")


def load_sheet_with_google_oauth(sheet_url: str) -> list[list[Any]]:
    return load_sheet_values_with_token(sheet_url, get_google_oauth_access_token(), "Google账号")


def load_saved_google_oauth_token() -> bool:
    if GOOGLE_OAUTH_TOKEN.get("refresh_token") or GOOGLE_OAUTH_TOKEN.get("access_token"):
        return True
    token_text = ""
    token_path_used: Path | None = None
    for token_path in (GOOGLE_OAUTH_TOKEN_FILE, LEGACY_GOOGLE_OAUTH_DPAPI_TOKEN_FILE):
        if not token_path.exists():
            continue
        try:
            token_text = secure_read_text(token_path)
            token_path_used = token_path
            break
        except Exception:
            continue
    if not token_text:
        return False
    try:
        raw = json.loads(token_text)
    except Exception:
        return False
    if not isinstance(raw, dict) or not raw.get("client"):
        return False
    GOOGLE_OAUTH_TOKEN.clear()
    GOOGLE_OAUTH_TOKEN.update(raw)
    if token_path_used and token_path_used != GOOGLE_OAUTH_TOKEN_FILE:
        try:
            save_google_oauth_token()
            token_path_used.unlink(missing_ok=True)
        except Exception:
            pass
    return True


def save_google_oauth_token() -> bool:
    if not GOOGLE_OAUTH_TOKEN.get("refresh_token") and not GOOGLE_OAUTH_TOKEN.get("access_token"):
        return False
    try:
        secure_write_text(GOOGLE_OAUTH_TOKEN_FILE, json.dumps(GOOGLE_OAUTH_TOKEN, ensure_ascii=False))
        return True
    except Exception:
        return False


def load_oauth_client(client_file: str) -> dict[str, Any]:
    path = Path(client_file).expanduser()
    if not path.exists():
        raise RuntimeError(f"OAuth客户端JSON不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    client = data.get("installed") or data.get("web") or data
    if not client.get("client_id"):
        raise RuntimeError("OAuth客户端JSON中未找到 client_id。")
    if not client.get("token_uri"):
        client["token_uri"] = "https://oauth2.googleapis.com/token"
    if not client.get("auth_uri"):
        client["auth_uri"] = "https://accounts.google.com/o/oauth2/v2/auth"
    return client


def make_google_auth_url(client_file: str, redirect_uri: str) -> str:
    client = load_oauth_client(client_file)
    state = b64url(os.urandom(24))
    GOOGLE_OAUTH_STATE[state] = {"client": client, "redirect_uri": redirect_uri}
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/spreadsheets.readonly openid email",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return client["auth_uri"] + "?" + urllib.parse.urlencode(params)


def exchange_google_code(code: str, state: str) -> dict[str, Any]:
    pending = GOOGLE_OAUTH_STATE.pop(state, None)
    if not pending:
        raise RuntimeError("Google登录状态已失效，请重新登录。")
    client = pending["client"]
    previous_refresh_token = ""
    if load_saved_google_oauth_token():
        previous_refresh_token = str(GOOGLE_OAUTH_TOKEN.get("refresh_token") or "")
    payload = {
        "code": code,
        "client_id": client["client_id"],
        "redirect_uri": pending["redirect_uri"],
        "grant_type": "authorization_code",
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]
    token_data = post_form_json(client["token_uri"], payload, "Google授权换取token失败")
    GOOGLE_OAUTH_TOKEN.clear()
    GOOGLE_OAUTH_TOKEN.update(
        {
            "client": client,
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token") or previous_refresh_token,
            "expires_at": int(time.time()) + int(token_data.get("expires_in") or 3600) - 60,
            "id_token": token_data.get("id_token"),
        }
    )
    if not GOOGLE_OAUTH_TOKEN.get("access_token"):
        raise RuntimeError("Google登录失败：未返回 access_token。")
    save_google_oauth_token()
    return GOOGLE_OAUTH_TOKEN


def post_form_json(url: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{label}：HTTP {exc.code} {body}") from exc


def get_google_oauth_access_token() -> str:
    load_saved_google_oauth_token()
    if not GOOGLE_OAUTH_TOKEN.get("access_token"):
        raise RuntimeError("Google尚未登录。请先点击“登录Google”。")
    if int(GOOGLE_OAUTH_TOKEN.get("expires_at") or 0) > int(time.time()) + 30:
        return str(GOOGLE_OAUTH_TOKEN["access_token"])
    refresh_token = GOOGLE_OAUTH_TOKEN.get("refresh_token")
    client = GOOGLE_OAUTH_TOKEN.get("client") or {}
    if not refresh_token:
        raise RuntimeError("Google授权已过期，请重新登录。")
    payload = {
        "client_id": client["client_id"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]
    token_data = post_form_json(client["token_uri"], payload, "刷新Google token失败")
    GOOGLE_OAUTH_TOKEN["access_token"] = token_data.get("access_token")
    GOOGLE_OAUTH_TOKEN["expires_at"] = int(time.time()) + int(token_data.get("expires_in") or 3600) - 60
    save_google_oauth_token()
    return str(GOOGLE_OAUTH_TOKEN["access_token"])


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def google_status() -> dict[str, Any]:
    load_saved_google_oauth_token()
    if not GOOGLE_OAUTH_TOKEN.get("access_token"):
        return {"loggedIn": False}
    payload = decode_jwt_payload(str(GOOGLE_OAUTH_TOKEN.get("id_token") or ""))
    return {
        "loggedIn": True,
        "email": payload.get("email", ""),
        "expiresAt": GOOGLE_OAUTH_TOKEN.get("expires_at"),
    }


def success_page(message: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google登录成功</title>
<style>
body{{font:14px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f6f7f9;margin:0;display:grid;place-items:center;min-height:100vh;color:#17202a}}
.box{{background:#fff;border:1px solid #d8dee6;border-radius:8px;padding:24px;max-width:520px;box-shadow:0 8px 24px rgba(22,34,51,.08)}}
a{{color:#1677ff}}
</style>
<div class="box">
  <h1>登录完成</h1>
  <p>{message}</p>
  <p><a href="/">返回渠道查询工具</a></p>
</div>
</html>"""


def error_page(message: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>操作失败</title>
<style>
body{{font:14px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#fff6f5;margin:0;display:grid;place-items:center;min-height:100vh;color:#17202a}}
.box{{background:#fff;border:1px solid #f1b8b4;border-radius:8px;padding:24px;max-width:680px;box-shadow:0 8px 24px rgba(22,34,51,.08)}}
code{{white-space:pre-wrap;color:#b42318}}
a{{color:#1677ff}}
</style>
<div class="box">
  <h1>操作失败</h1>
  <code>{html.escape(message)}</code>
  <p><a href="/">返回渠道查询工具</a></p>
</div>
</html>"""


def extract_token_from_chrome() -> str:
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Default" / "Local Storage" / "leveldb",
                Path(local_app_data) / "Microsoft" / "Edge" / "User Data" / "Default" / "Local Storage" / "leveldb",
            ]
        )
    for leveldb_dir in candidates:
        token = extract_token_from_leveldb(leveldb_dir)
        if token:
            return token
    raise RuntimeError("未找到后台登录态。请保持Chrome已登录后台，或手动填写 x-token。")


def extract_token_from_leveldb(leveldb_dir: Path) -> str:
    if not leveldb_dir.exists():
        return ""
    needles = [b"zhheew.bw009.com", "zhheew.bw009.com".encode("utf-16le")]
    files = [p for p in leveldb_dir.iterdir() if p.is_file() and p.name != "LOCK"]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not any(needle in data for needle in needles):
            continue
        for needle in needles:
            start = 0
            while True:
                index = data.find(needle, start)
                if index < 0:
                    break
                start = index + 1
                chunk = data[max(0, index - 20000) : min(len(data), index + 80000)]
                token = extract_token_from_chunk(chunk)
                if token:
                    return token
    return ""


def extract_token_from_chunk(chunk: bytes) -> str:
    patterns = [
        r'"token"\s*:\s*"([^"\\]+)"',
        r"token[^A-Za-z0-9_]{1,8}([A-Za-z0-9_\-\.]{40,})",
    ]
    for encoding in ("utf-8", "utf-16le", "latin1"):
        text = chunk.decode(encoding, errors="ignore").replace("\x00", "")
        if "zhheew" not in text.lower() and "token" not in text:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                token = match.group(1)
                if len(token) >= 40:
                    return token
    return ""


def get_backend_token(explicit_token: str | None) -> tuple[str, str]:
    global BACKEND_SESSION_TOKEN
    if explicit_token:
        return explicit_token.strip(), "手动输入"
    if BACKEND_SESSION_TOKEN:
        return BACKEND_SESSION_TOKEN, "软件后台登录"
    env_token = os.environ.get("WPPCHAT_X_TOKEN", "").strip()
    if env_token:
        return env_token, "环境变量"
    token = read_saved_backend_token()
    if token:
        return token, "本地加密token"
    return extract_token_from_chrome(), "Chrome登录态"


def normalize_backend_base(value: str | None) -> str:
    text = (value or BACKEND_BASE_URL).strip()
    if not text:
        text = BACKEND_BASE_URL
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"后台地址格式不正确：{value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def backend_headers(backend_base: str, token: str | None = None, referer_path: str = "/#/login") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": backend_base,
        "Referer": backend_base + referer_path,
        "User-Agent": "Mozilla/5.0 channel-query/1.0",
    }
    if token:
        headers["x-token"] = token
    return headers


def request_backend_login(backend_base: str, username: str, password: str, captcha: str) -> tuple[str, str]:
    payload = {"username": username, "password": password, "captcha": captcha}
    request = urllib.request.Request(
        backend_base + "/api/login",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=backend_headers(backend_base),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"后台登录失败：HTTP {exc.code} {body_text}。当前后台域名：{backend_base}") from exc
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(
            f"后台登录失败：{data.get('msg') or data.get('message') or data.get('code')}。当前后台域名：{backend_base}"
        )
    data_payload = data.get("data")
    token = data.get("token") or ""
    login_name = data.get("login_name") or ""
    if isinstance(data_payload, dict):
        token = token or data_payload.get("token") or ""
        login_name = login_name or data_payload.get("login_name") or ""
    elif isinstance(data_payload, str):
        token = token or data_payload
    if not token:
        raise RuntimeError("后台登录成功但未返回 token。")
    return str(token), str(login_name or "")


def backend_login(body: dict[str, Any]) -> dict[str, Any]:
    global BACKEND_SESSION_TOKEN
    backend_base = normalize_backend_base(body.get("backendBase"))
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    captcha = str(body.get("captcha") or "").strip()
    totp_secret = str(body.get("totpSecret") or "").strip()
    if not captcha and totp_secret:
        captcha = generate_totp(totp_secret)
    if not username or not password or not captcha:
        raise RuntimeError("请填写后台用户名、密码和谷歌验证码。")
    token, login_name = request_backend_login(backend_base, username, password, captcha)
    BACKEND_SESSION_TOKEN = str(token)
    saved_token = save_backend_token(BACKEND_SESSION_TOKEN)
    saved_login = save_backend_login_config(backend_base, username, password, totp_secret) if totp_secret else False
    return {
        "loginName": login_name,
        "tokenLength": len(BACKEND_SESSION_TOKEN),
        "savedToken": saved_token,
        "savedLogin": saved_login,
    }


def extract_backend_rows(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    page = data.get("data") or {}
    total = page.get("total") if isinstance(page, dict) else None
    rows = page.get("data") if isinstance(page, dict) else page
    if not isinstance(rows, list):
        return [], total
    return [row for row in rows if isinstance(row, dict)], total


def account_match_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def pick_backend_row(account: str, rows: list[dict[str, Any]], total: int | None, allow_single_fallback: bool) -> dict[str, Any] | None:
    target = account_match_key(account)
    for row in rows:
        if account_match_key(row.get("username")) == target:
            return row
    if allow_single_fallback and len(rows) == 1 and (total in (None, 1)):
        return rows[0]
    return None


def is_backend_auth_expired_error(exc: Exception) -> bool:
    text = str(exc)
    return "授权已过期" in text or "HTTP 401" in text


def refresh_backend_token(backend_base: str | None = None) -> str:
    global BACKEND_SESSION_TOKEN
    config = load_backend_login_config()
    if not config:
        raise RuntimeError("后台授权已过期，且未保存自动续登录信息。请在网页工具里填写自动续登录密钥并重新登录后台。")
    base = normalize_backend_base(backend_base or config["backend_base"])
    captcha = generate_totp(config["totp_secret"])
    token, _ = request_backend_login(base, config["username"], config["password"], captcha)
    BACKEND_SESSION_TOKEN = token
    if not save_backend_token(token):
        raise RuntimeError("后台已自动重新登录，但新token未能加密保存。请检查服务器加密密钥和目录权限。")
    return token


def post_backend_list(base: str, token: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    request = urllib.request.Request(
        base + BACKEND_LIST_PATH,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=backend_headers(base, token, "/#/im/imUserInfo"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"后台查询失败：HTTP {exc.code} {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"后台查询失败：{exc.reason}") from exc
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"后台返回错误：{data.get('msg') or data.get('message') or data.get('code')}")
    return extract_backend_rows(data)


def post_backend_list_auto_refresh(base: str, token: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    effective_token = BACKEND_SESSION_TOKEN or token
    try:
        return post_backend_list(base, effective_token, payload)
    except RuntimeError as exc:
        if not is_backend_auth_expired_error(exc):
            raise
        new_token = refresh_backend_token(base)
        return post_backend_list(base, new_token, payload)


def call_backend_user(account: str, token: str, backend_base: str) -> dict[str, Any] | None:
    base = normalize_backend_base(backend_base)
    account = str(account or "").strip()
    payloads = [
        {"page": 1, "page_size": 50, "username": account, "is_like": 1, "is_reply": -1},
        {"page": 1, "page_size": 50, "username": account, "is_like": 2, "is_reply": -1},
        {"page": 1, "page_size": 50, "username": account, "is_like": 1},
        {"page": 1, "page_size": 50, "username": account},
    ]
    seen_payloads: set[str] = set()
    for payload in payloads:
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if key in seen_payloads:
            continue
        seen_payloads.add(key)
        rows, total = post_backend_list_auto_refresh(base, token, payload)
        if not rows:
            continue
        row = pick_backend_row(account, rows, total, allow_single_fallback=True)
        if row:
            return row
    return None


def is_same_ip(row: dict[str, Any], ip: str) -> bool:
    return first_backend_value(row, "address", "register_ip", "ip") == ip


def call_backend_users_by_ip(ip: str, token: str, backend_base: str, max_results: int = 500) -> list[dict[str, Any]]:
    try:
        normalized_ip = str(ipaddress.ip_address(str(ip).strip()))
    except ValueError as exc:
        raise RuntimeError(f"IP地址格式不正确：{ip}") from exc

    base = normalize_backend_base(backend_base)
    page_size = 100
    query_modes = [2, 1]
    for is_like in query_modes:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while len(results) < max_results:
            payload = {
                "page": page,
                "page_size": page_size,
                "address": normalized_ip,
                "is_like": is_like,
                "is_reply": -1,
            }
            rows, total = post_backend_list_auto_refresh(base, token, payload)
            if not rows:
                break
            for row in rows:
                if not is_same_ip(row, normalized_ip):
                    continue
                key = str(row.get("user_id") or row.get("username") or len(results))
                if key in seen:
                    continue
                seen.add(key)
                results.append(row)
                if len(results) >= max_results:
                    break
            if total is not None and page * page_size >= int(total):
                break
            if len(rows) < page_size:
                break
            page += 1
        if results:
            return results
    return []


def load_channel_map(sheet_url: str, sheet_csv: str, service_account_file: str = "") -> tuple[dict[str, str], str]:
    if sheet_csv and sheet_csv.strip():
        return build_channel_map(sheet_csv), "CSV"
    if service_account_file:
        return build_channel_map_from_rows(load_sheet_with_service_account(sheet_url, service_account_file)), "服务账号"
    if GOOGLE_OAUTH_TOKEN.get("access_token") or load_saved_google_oauth_token():
        return build_channel_map_from_rows(load_sheet_with_google_oauth(sheet_url)), "Google登录"
    csv_url = google_sheet_to_csv_url(sheet_url)
    if not csv_url:
        raise RuntimeError("请提供Google表格链接，或上传/粘贴CSV。")
    return build_channel_map(fetch_url_text(csv_url)), "Google表格"


def first_backend_value(row: dict[str, Any] | None, *keys: str) -> str:
    if not row:
        return ""
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def format_backend_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{10,13}", text):
        timestamp = int(text)
        if timestamp > 9_999_999_999:
            timestamp = timestamp // 1000
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except (OverflowError, OSError, ValueError):
            return text
    return text


def query_accounts(body: dict[str, Any]) -> dict[str, Any]:
    accounts = parse_accounts(body.get("accounts"))
    if not accounts:
        raise RuntimeError("没有可查询的WPPChat账号。")
    channel_map, sheet_source = load_channel_map(
        body.get("sheetUrl") or DEFAULT_SHEET_URL,
        body.get("sheetCsv") or "",
        body.get("serviceAccountFile") or "",
    )
    token, token_source = get_backend_token(body.get("backendToken"))
    backend_base = body.get("backendBase") or BACKEND_BASE_URL

    results = []
    for account in accounts:
        row = call_backend_user(account, token, backend_base)
        source = row.get("sms_phone", "") if row else ""
        source_id = normalize_source(source)
        register_ip = first_backend_value(row, "address", "register_ip", "ip")
        register_province = first_backend_value(row, "font_rgb", "province", "register_province", "province_name", "city")
        register_time = format_backend_time(first_backend_value(row, "register_time", "created", "create_time"))
        channel_code = channel_map.get(source_id, "未查到") if source_id else "未查到"
        if not row:
            status = "后台未查到账号"
        elif not source_id:
            status = "注册来源为空"
        elif channel_code == "未查到":
            status = "渠道表未匹配"
        else:
            status = "已匹配"
        results.append(
            {
                "account": account,
                "register_ip": register_ip,
                "register_province": register_province,
                "register_time": register_time,
                "source": source,
                "source_id": source_id,
                "channel_code": channel_code,
                "status": status,
            }
        )
        time.sleep(0.05)

    found = sum(1 for item in results if item["channel_code"] != "未查到")
    return {
        "results": results,
        "sheetSource": sheet_source,
        "tokenSource": token_source,
        "summary": {"total": len(results), "found": found, "missing": len(results) - found},
    }


def check_token(body: dict[str, Any]) -> dict[str, Any]:
    token, token_source = get_backend_token(body.get("backendToken"))
    backend_base = normalize_backend_base(body.get("backendBase"))
    request = urllib.request.Request(
        backend_base + BACKEND_LIST_PATH,
        data=json.dumps({"page": 1, "page_size": 1}, ensure_ascii=False).encode("utf-8"),
        headers=backend_headers(backend_base, token, "/#/im/imUserInfo"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"后台连接失败：HTTP {exc.code}") from exc
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"后台连接失败：{data.get('msg') or data.get('message') or data.get('code')}")
    return {"tokenSource": token_source}


class Handler(BaseHTTPRequestHandler):
    server_version = "ChannelQuery/1.0"

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
            return
        if self.path.startswith("/auth/google"):
            self.handle_google_auth()
            return
        if self.path.startswith("/oauth2callback"):
            self.handle_google_callback()
            return
        self.send_json({"ok": False, "error": "Not found"}, 404)

    def do_POST(self) -> None:
        try:
            body = self.read_json()
            if self.path == "/api/query":
                self.send_json({"ok": True, **query_accounts(body)})
                return
            if self.path == "/api/check-token":
                self.send_json({"ok": True, **check_token(body)})
                return
            if self.path == "/api/backend-login":
                self.send_json({"ok": True, **backend_login(body)})
                return
            if self.path == "/api/google-status":
                self.send_json({"ok": True, **google_status()})
                return
            self.send_json({"ok": False, "error": "Not found"}, 404)
        except Exception as exc:
            if os.environ.get("CHANNEL_QUERY_DEBUG"):
                traceback.print_exc()
            self.send_json({"ok": False, "error": str(exc)}, 400)

    def handle_google_auth(self) -> None:
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            client_file = (query.get("clientFile") or [""])[0]
            if not client_file:
                raise RuntimeError("缺少 OAuth 客户端 JSON 路径。")
            auth_url = make_google_auth_url(client_file, self.redirect_uri())
            self.send_response(302)
            self.send_header("Location", auth_url)
            self.end_headers()
        except Exception as exc:
            self.send_text(error_page(str(exc)), "text/html; charset=utf-8")

    def handle_google_callback(self) -> None:
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("error"):
                raise RuntimeError((query.get("error_description") or query.get("error") or ["Google登录失败"])[0])
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            if not code or not state:
                raise RuntimeError("Google回调缺少 code 或 state。")
            exchange_google_code(code, state)
            email = google_status().get("email") or "已授权"
            saved_text = "已加密保存给Telegram机器人使用" if GOOGLE_OAUTH_TOKEN_FILE.exists() else "但未能保存给Telegram机器人使用"
            self.send_text(success_page(f"Google登录成功：{html.escape(email)}，{saved_text}"), "text/html; charset=utf-8")
        except Exception as exc:
            self.send_text(error_page(str(exc)), "text/html; charset=utf-8")

    def redirect_uri(self) -> str:
        host = self.headers.get("Host")
        if not host:
            address, port = self.server.server_address[:2]
            host = f"{address}:{port}"
        return f"http://{host}/oauth2callback"

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def send_text(self, text: str, content_type: str) -> None:
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="WPPChat 渠道批量查询工具")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--generate-master-key", action="store_true", help="生成 Linux 服务器加密 token 用的主密钥")
    args = parser.parse_args()

    if args.generate_master_key:
        print(generate_master_key())
        return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"渠道查询工具已启动：http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
