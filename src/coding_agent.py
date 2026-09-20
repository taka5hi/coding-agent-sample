"""LangGraph 学習用: 簡易コーディングエージェント。

計画 -> 実装 -> 実行 -> (失敗なら) 振り返り -> 再実装 のループを持つ最小構成。
グラフ構造と各ノードの役割は nodes_and_graph.md を参照。
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, START, StateGraph

MAX_ITERATIONS = 3
llm = ChatAnthropic(model="claude-sonnet-4-5")  # 利用可能なモデル名に置き換えてください


# ---------- State ----------
class AgentState(TypedDict):
    task: str          # ユーザーの依頼
    plan: str          # 実装計画
    code: str          # 現在のコード
    test_output: str   # 実行結果（stdout + stderr）
    passed: bool       # 成功したか
    review: str        # reflect が出した改善方針
    iteration: int     # 試行回数
    result: str        # 最終出力


# ---------- Helpers ----------
def extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return m.group(1) if m else text


# ---------- Nodes ----------
def plan(state: AgentState) -> dict:
    res = llm.invoke(
        f"次のタスクを実装するための手順を、箇条書きで簡潔に立ててください。\n\n{state['task']}"
    )
    return {"plan": res.content, "iteration": 0, "review": ""}


def write_code(state: AgentState) -> dict:
    prompt = f"タスク:\n{state['task']}\n\n計画:\n{state['plan']}\n"
    if state["review"]:
        prompt += f"\n前回のコード:\n{state['code']}\n\n改善方針:\n{state['review']}\n"
    prompt += "\nassert によるテストを末尾に含む単一の Python ファイルを、コードブロックのみで出力してください。"
    res = llm.invoke(prompt)
    return {"code": extract_code(res.content), "iteration": state["iteration"] + 1}


def run_code(state: AgentState) -> dict:
    # 注意: 生成コードをそのまま実行します。慣れたら Docker 等のサンドボックスへ。
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "main.py"
        path.write_text(state["code"])
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True, text=True, timeout=30,
            )
            return {"passed": proc.returncode == 0, "test_output": proc.stdout + proc.stderr}
        except subprocess.TimeoutExpired:
            return {"passed": False, "test_output": "Timeout: 30秒以内に終了しませんでした"}


def reflect(state: AgentState) -> dict:
    res = llm.invoke(
        f"次のコードを実行したところ失敗しました。原因と修正方針を簡潔に述べてください。\n\n"
        f"コード:\n{state['code']}\n\n出力:\n{state['test_output']}"
    )
    return {"review": res.content}


def finalize(state: AgentState) -> dict:
    status = "成功" if state["passed"] else f"失敗（{state['iteration']}回試行）"
    return {"result": f"[{status}]\n\n{state['code']}\n\n--- 実行結果 ---\n{state['test_output']}"}


# ---------- Conditional edge ----------
def route(state: AgentState) -> Literal["reflect", "finalize"]:
    if state["passed"] or state["iteration"] >= MAX_ITERATIONS:
        return "finalize"
    return "reflect"


# ---------- Graph ----------
builder = StateGraph(AgentState)
builder.add_node("plan", plan)
builder.add_node("write_code", write_code)
builder.add_node("run_code", run_code)
builder.add_node("reflect", reflect)
builder.add_node("finalize", finalize)

builder.add_edge(START, "plan")
builder.add_edge("plan", "write_code")
builder.add_edge("write_code", "run_code")
builder.add_conditional_edges("run_code", route)
builder.add_edge("reflect", "write_code")
builder.add_edge("finalize", END)

graph = builder.compile()

if __name__ == "__main__":
    out = graph.invoke({"task": "フィボナッチ数列の第 n 項を返す関数 fib(n) を書いてください"})
    print(out["result"])
