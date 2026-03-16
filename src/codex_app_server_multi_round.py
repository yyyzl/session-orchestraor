#!/usr/bin/env python3
"""通过 Codex App Server 自动进行 5 轮“数字+1”对话。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class JsonRpcAppServerClient:
    """最小可用 JSON-RPC 客户端，仅覆盖本任务需要的请求/通知。"""

    def __init__(self, command: Optional[List[str]] = None, cwd: Optional[str] = None) -> None:
        self.command = command or [resolve_codex_binary(), "app-server", "--listen", "stdio://"]
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen[str]] = None
        self.msg_queue: Queue[Dict[str, Any]] = Queue()
        self.backlog: List[Dict[str, Any]] = []
        self.request_id = 0

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None

        threading.Thread(
            target=self._read_stream,
            args=(self.proc.stdout, "STDOUT"),
            daemon=True,
        ).start()
        threading.Thread(
            target=self._read_stream,
            args=(self.proc.stderr, "STDERR"),
            daemon=True,
        ).start()

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def _read_stream(self, pipe: Any, stream_name: str) -> None:
        for raw_line in iter(pipe.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    self.msg_queue.put(payload)
            except json.JSONDecodeError:
                print(f"[{stream_name}/RAW] {line}", file=sys.stderr)

    def _next_request_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> int:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("app-server 尚未启动")
        req_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        self.proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return req_id

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Dict[str, Any]:
        req_id = self.send_request(method, params)
        msg = self._wait_for(
            lambda m: m.get("id") == req_id and ("result" in m or "error" in m),
            timeout=timeout,
        )
        if "error" in msg:
            raise RuntimeError(f"请求 {method} 失败: {msg['error']}")
        return msg.get("result", {})

    def wait_notification(
        self,
        method: str,
        timeout: float = 120.0,
        thread_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        def _match(msg: Dict[str, Any]) -> bool:
            if msg.get("method") != method:
                return False
            params = msg.get("params", {}) or {}
            if thread_id and params.get("threadId") != thread_id:
                return False
            if turn_id and params.get("turn", {}).get("id") != turn_id and params.get("turnId") != turn_id:
                return False
            return True

        return self._wait_for(_match, timeout=timeout)

    def _pop_backlog(self, predicate: Callable[[Dict[str, Any]], bool]) -> Optional[Dict[str, Any]]:
        for idx, msg in enumerate(self.backlog):
            if predicate(msg):
                return self.backlog.pop(idx)
        return None

    def _wait_for(self, predicate: Callable[[Dict[str, Any]], bool], timeout: float) -> Dict[str, Any]:
        deadline = time.time() + timeout
        while True:
            cached = self._pop_backlog(predicate)
            if cached is not None:
                return cached

            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError("等待 JSON-RPC 消息超时")

            try:
                msg = self.msg_queue.get(timeout=remain)
            except Empty as exc:
                raise TimeoutError("等待 JSON-RPC 消息超时") from exc

            if predicate(msg):
                return msg
            self.backlog.append(msg)

    def wait_turn_result_text(self, thread_id: str, turn_id: str, timeout: float = 300.0) -> str:
        """等待 turn 完成并提取文本输出，优先 item/completed，其次 delta 拼接。"""

        deadline = time.time() + timeout
        delta_parts: List[str] = []
        item_completed_text: Optional[str] = None
        turn_completed = False

        while True:
            remain = deadline - time.time()
            if remain <= 0:
                raise TimeoutError(f"等待 turn 输出超时: {turn_id}")

            try:
                msg = self.msg_queue.get(timeout=remain)
            except Empty as exc:
                raise TimeoutError(f"等待 turn 输出超时: {turn_id}") from exc

            # JSON-RPC response 需要保留给 request() 处理
            if "id" in msg and ("result" in msg or "error" in msg):
                self.backlog.append(msg)
                continue

            method = msg.get("method")
            params = msg.get("params", {}) or {}
            msg_thread_id = params.get("threadId")
            msg_turn_id = params.get("turnId") or params.get("turn", {}).get("id")

            if msg_thread_id != thread_id:
                continue

            if method == "item/agentMessage/delta" and msg_turn_id == turn_id:
                delta_parts.append(str(params.get("delta", "")))
                continue

            if method == "item/completed" and msg_turn_id == turn_id:
                item = params.get("item", {}) or {}
                if item.get("type") == "agentMessage":
                    item_completed_text = str(item.get("text", "")).strip()
                continue

            if method == "error" and msg_turn_id == turn_id:
                err_obj = params.get("error", {})
                raise RuntimeError(f"turn 执行失败: {err_obj}")

            if method == "turn/completed" and msg_turn_id == turn_id:
                turn_completed = True
                if item_completed_text:
                    return item_completed_text
                merged = "".join(delta_parts).strip()
                if merged:
                    return merged
                # 某些实现中 completed 会早于 item/completed，稍等补齐
                grace_deadline = time.time() + 5
                while time.time() < grace_deadline:
                    grace_remain = max(0.1, grace_deadline - time.time())
                    try:
                        follow = self.msg_queue.get(timeout=grace_remain)
                    except Empty:
                        break

                    if "id" in follow and ("result" in follow or "error" in follow):
                        self.backlog.append(follow)
                        continue

                    f_method = follow.get("method")
                    f_params = follow.get("params", {}) or {}
                    f_thread_id = f_params.get("threadId")
                    f_turn_id = f_params.get("turnId") or f_params.get("turn", {}).get("id")
                    if f_thread_id != thread_id or f_turn_id != turn_id:
                        continue

                    if f_method == "item/completed":
                        item = f_params.get("item", {}) or {}
                        if item.get("type") == "agentMessage":
                            txt = str(item.get("text", "")).strip()
                            if txt:
                                return txt
                    if f_method == "item/agentMessage/delta":
                        delta_parts.append(str(f_params.get("delta", "")))

                final_merged = "".join(delta_parts).strip()
                if final_merged:
                    return final_merged
                raise RuntimeError(f"turn {turn_id} 已完成，但未捕获到文本输出")

            # 若已经 completed，但期间还收到相关 delta，尽量拼接
            if turn_completed and method == "item/agentMessage/delta" and msg_turn_id == turn_id:
                delta_parts.append(str(params.get("delta", "")))


def select_model(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """优先选择 5.3 Codex；不可用时回退到最接近的 Codex。"""

    if not models:
        raise ValueError("model/list 返回为空")

    def score(m: Dict[str, Any]) -> int:
        text = " ".join(
            [
                str(m.get("id", "")),
                str(m.get("model", "")),
                str(m.get("displayName", "")),
                str(m.get("description", "")),
            ]
        ).lower()

        s = 0
        if "gpt-5.3-codex" in text:
            s += 3000
        if "5.3" in text and "codex" in text:
            s += 2000
        if "codex" in text:
            s += 600
        if "gpt-5" in text or " 5 " in text:
            s += 200
        if m.get("isDefault"):
            s += 50
        return s

    ranked = sorted(models, key=score, reverse=True)
    if score(ranked[0]) <= 0:
        defaults = [m for m in models if m.get("isDefault")]
        return defaults[0] if defaults else models[0]
    return ranked[0]


def resolve_codex_binary(user_specified: Optional[str] = None) -> str:
    """解析 codex 可执行文件路径，优先 Windows 下更稳定的 codex.cmd。"""

    if user_specified:
        return user_specified

    for name in ("codex.cmd", "codex.exe", "codex"):
        found = shutil.which(name)
        if found:
            return found

    appdata = os.environ.get("APPDATA")
    if appdata:
        npm_dir = Path(appdata) / "npm"
        for name in ("codex.cmd", "codex.exe", "codex"):
            candidate = npm_dir / name
            if candidate.exists():
                return str(candidate)

    raise FileNotFoundError("未找到 codex 可执行文件，请用 --codex-bin 显式传入路径")


def parse_first_int(text: str) -> Optional[int]:
    match = re.search(r"[-+]?\d+", text)
    if not match:
        return None
    return int(match.group(0))


def extract_latest_agent_text(thread_read_result: Dict[str, Any], turn_id: str) -> str:
    turns = thread_read_result.get("thread", {}).get("turns", [])
    target_turn = None
    for turn in turns:
        if turn.get("id") == turn_id:
            target_turn = turn
            break

    if target_turn is None:
        raise ValueError(f"未找到 turn: {turn_id}")

    items = target_turn.get("items", [])
    for item in reversed(items):
        if item.get("type") == "agentMessage":
            return str(item.get("text", "")).strip()

    raise ValueError(f"turn {turn_id} 未找到 agentMessage")


def wait_turn_finished(
    client: JsonRpcAppServerClient,
    thread_id: str,
    turn_id: str,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """通过轮询 thread/read 等待指定 turn 完成，避免依赖通知流。"""

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            thread_read = client.request(
                "thread/read",
                {
                    "threadId": thread_id,
                    "includeTurns": True,
                },
                timeout=30,
            )
        except RuntimeError as exc:
            err_text = str(exc)
            if "not materialized yet" in err_text and "includeTurns" in err_text:
                time.sleep(1)
                continue
            raise
        turns = thread_read.get("thread", {}).get("turns", [])
        target_turn = None
        for turn in turns:
            if turn.get("id") == turn_id:
                target_turn = turn
                break

        if target_turn is not None:
            status = target_turn.get("status")
            if status == "completed":
                return thread_read
            if status in ("failed", "interrupted"):
                raise RuntimeError(f"turn 状态异常: {status}")

        time.sleep(1)

    raise TimeoutError(f"等待 turn 完成超时: {turn_id}")


def run_five_rounds(rounds: int = 5, start_number: int = 1, codex_bin: Optional[str] = None) -> Dict[str, Any]:
    client = JsonRpcAppServerClient(
        command=[resolve_codex_binary(codex_bin), "app-server", "--listen", "stdio://"]
    )
    client.start()

    try:
        client.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-app-server-multi-round",
                    "title": "Codex App Server Multi Round Test",
                    "version": "1.0.0",
                },
                "capabilities": None,
            },
            timeout=30,
        )

        models_resp = client.request(
            "model/list",
            {
                "limit": 200,
                "includeHidden": True,
            },
            timeout=30,
        )
        models = models_resp.get("data", [])
        selected_model = select_model(models)

        thread_resp = client.request(
            "thread/start",
            {
                "model": selected_model.get("id"),
                "baseInstructions": "你是一个数字加一机器人。收到用户输入后，只输出输入数字+1后的数字本身，不要输出任何解释或额外文本。",
                "developerInstructions": "对每次输入，返回输入数字+1。输出只能是一个整数。",
                "experimentalRawEvents": False,
                "persistExtendedHistory": False,
            },
            timeout=30,
        )
        thread_id = thread_resp.get("thread", {}).get("id")
        if not thread_id:
            raise RuntimeError("thread/start 未返回 thread.id")

        results: List[Dict[str, Any]] = []
        current_number = start_number

        for round_index in range(1, rounds + 1):
            turn_resp = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [
                        {
                            "type": "text",
                            "text": (
                                "你是数字加一机器人。"
                                "请把我给的数字加1，只输出一个整数，不要解释。"
                                f"输入数字：{current_number}"
                            ),
                            "text_elements": [],
                        }
                    ],
                },
                timeout=30,
            )

            turn_id = turn_resp.get("turn", {}).get("id")
            if not turn_id:
                raise RuntimeError("turn/start 未返回 turn.id")

            assistant_text = client.wait_turn_result_text(
                thread_id=thread_id,
                turn_id=turn_id,
                timeout=300,
            )

            results.append(
                {
                    "round": round_index,
                    "user_input": current_number,
                    "assistant_output": assistant_text,
                }
            )

            parsed = parse_first_int(assistant_text)
            if parsed is None:
                raise RuntimeError(f"第 {round_index} 轮返回无法解析为数字: {assistant_text}")
            current_number = parsed

        return {
            "model_id": selected_model.get("id"),
            "model_display_name": selected_model.get("displayName"),
            "thread_id": thread_id,
            "results": results,
        }
    finally:
        client.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex App Server 5轮数字+1自动交互")
    parser.add_argument("--rounds", type=int, default=5, help="对话轮数，默认 5")
    parser.add_argument("--start", type=int, default=1, help="起始数字，默认 1")
    parser.add_argument("--codex-bin", type=str, default=None, help="可选：codex 可执行文件路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    result = run_five_rounds(rounds=args.rounds, start_number=args.start, codex_bin=args.codex_bin)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"模型: {result['model_display_name']} ({result['model_id']})")
    print(f"线程: {result['thread_id']}")
    print("5轮结果:")
    for item in result["results"]:
        print(f"  第{item['round']}轮: 你发 {item['user_input']} -> 回 {item['assistant_output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
