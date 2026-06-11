"""Replay a persisted Session 8 run, one node at a time.

Stdin-driven. Reads `state/sessions/<sid>/` and walks its NodeState
records in completion order. For each node prints a fixed block, then
waits for the user to advance.

Usage:
    uv run python replay.py <session_id>

Keys:
    enter   advance to next node
    p       expand the full rendered prompt that was sent to the gateway
    o       expand the full AgentResult.output JSON
    q       quit
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from persistence import SessionStore, list_sessions
from schemas import NodeState


def _print_block(i: int, n: int, st: NodeState, session_id: str = "") -> None:
    r = st.result
    skill = st.skill
    elapsed = f"{r.elapsed_s:.1f}s" if r and r.elapsed_s else "—"
    provider = (r.provider if r and r.provider else "—")
    retries = st.retries
    tools = ""
    
    if skill == "browser" and st.status == "complete" and r and r.output:
        out = r.output
        path = out.get("path", "—")
        goal = out.get("goal", "—")
        turns = out.get("turns", 0)
        
        print()
        print("=" * 80)
        print(" BROWSER AGENT REPLAY REPORT")
        print("=" * 80)
        print(f"Original User Goal: {goal}")
        print("-" * 80)
        
        # 2. Planner DAG
        print("Planner DAG Linkage:")
        preds_list = []
        succs_list = []
        try:
            from persistence import SessionStore
            store = SessionStore(session_id)
            g = store.read_graph()
            if g and st.node_id in g.nodes:
                preds_list = [g.nodes[p].get("skill", "?") for p in g.predecessors(st.node_id)]
                succs_list = [g.nodes[s].get("skill", "?") for s in g.successors(st.node_id)]
        except Exception:
            pass
        if not preds_list:
            preds_list = ["planner"]
        if not succs_list:
            succs_list = ["distiller", "formatter"]
        
        print(f"  {' + '.join(preds_list)} ──> Browser (Current) ──> {' + '.join(succs_list)}")
        print("-" * 80)
        
        # 3. Browser Path Chosen
        print(f"Browser Path Chosen: {path.upper()}")
        print("-" * 80)
        
        # 4. Browser Actions
        print("Executed Browser Actions:")
        actions = out.get("actions", [])
        if actions:
            for act_turn in actions:
                t = act_turn.get("turn", 0)
                outcome = act_turn.get("outcome", "ok")
                for a in act_turn.get("actions", []):
                    desc = a.get("type", "")
                    if a.get("mark") is not None:
                        desc += f"(mark={a.get('mark')})"
                    if a.get("value") is not None:
                        desc += f"(val={a.get('value')})"
                    print(f"  [Turn {t}] {desc} ──> {outcome}")
        else:
            print("  (No interactive actions executed)")
        print("-" * 80)
        
        # 5. Screenshots
        print("Screenshots Captured (Timeline):")
        screenshots = out.get("screenshots", [])
        if screenshots:
            for idx, scr in enumerate(screenshots, 1):
                print(f"  [{idx}] {scr}")
        else:
            print("  (No screenshots captured)")
        print("-" * 80)
        
        # 6. Page State Logs
        print("Page State Logs:")
        page_states = out.get("page_states", [])
        if page_states:
            for state in page_states:
                print(f"  [Turn {state.get('turn')}]")
                print(f"    URL:   {state.get('url')}")
                print(f"    Title: {state.get('title')}")
                print(f"    Path:  {state.get('path')}")
        else:
            print("  (No page states logged)")
        print("-" * 80)
        
        # 7. Extracted Data
        ext_data = out.get("extracted_data", {})
        print("Extracted Data (Structured JSON):")
        print(json.dumps({k: v for k, v in ext_data.items() if k != "comparison_table"}, indent=2, ensure_ascii=False))
        print("-" * 80)
        
        # 8. Final Comparison Table
        print("Final Comparison Table:")
        comp_table = ext_data.get("comparison_table", "")
        if comp_table:
            print(comp_table)
        else:
            print("  (No comparison table generated)")
        print("-" * 80)
        
        # 9. Cost Summary
        print("Cost & Performance Summary:")
        cost_sum = ext_data.get("cost_summary", {})
        if cost_sum:
            print(f"  Chosen Path:     {cost_sum.get('path', path)}")
            print(f"  Total Turns:     {cost_sum.get('turns', turns)}")
            print(f"  Input Tokens:    {cost_sum.get('input_tokens', 0)}")
            print(f"  Output Tokens:   {cost_sum.get('output_tokens', 0)}")
            print(f"  Estimated Cost:  ${cost_sum.get('cost', 0.0):.6f}")
            print(f"  Wall Clock Time: {cost_sum.get('wall_clock_time', 0.0):.2f}s")
        else:
            print(f"  Chosen Path:     {path}")
            print(f"  Total Turns:     {turns}")
            print(f"  Estimated Cost:  ${getattr(r, 'cost', 0.0):.6f}")
            print(f"  Wall Clock Time: {getattr(r, 'elapsed_s', 0.0):.2f}s")
        print("=" * 80)
        return

    print()
    print(f"node {i} / {n}")
    print(f"  agent      {skill}")
    print(f"  status     {st.status}")
    print(f"  elapsed    {elapsed}")
    print(f"  provider   {provider}")
    print(f"  retries    {retries}")
    print(f"  inputs     {', '.join(st.inputs) or '(none)'}")
    if tools:
        print(f"  tools      {tools}")
    if r and r.error:
        print(f"  error      {r.error[:240]}")
    if r and r.output:
        try:
            out_preview = json.dumps(r.output, ensure_ascii=False)
        except (TypeError, ValueError):
            out_preview = str(r.output)
        if len(out_preview) > 500:
            out_preview = out_preview[:500] + "…"
        print(f"  output     {out_preview}")


def _expand_prompt(st: NodeState) -> None:
    print()
    print("─" * 78)
    print(st.prompt_sent or "(no prompt captured)")
    print("─" * 78)


def _expand_output(st: NodeState) -> None:
    print()
    print("─" * 78)
    if st.result and st.result.output:
        print(json.dumps(st.result.output, indent=2, ensure_ascii=False))
    else:
        print("(no output)")
    print("─" * 78)


def replay(session_id: str) -> int:
    store = SessionStore(session_id)
    states = store.read_all_nodes()
    if not states:
        print(f"replay: no nodes under state/sessions/{session_id}/", file=sys.stderr)
        return 2

    query = store.read_query() or ""
    print(f"session  {session_id}")
    print(f"query    {query[:200]}")
    print(f"nodes    {len(states)}")
    print()
    print("press enter to advance, p to expand prompt, o to expand output, q to quit")

    i = 0
    while i < len(states):
        st = states[i]
        _print_block(i + 1, len(states), st, session_id)
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if cmd == "q":
            return 0
        if cmd == "p":
            _expand_prompt(st)
            continue
        if cmd == "o":
            _expand_output(st)
            continue
        i += 1
    print("\n(end of session)")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("replay: no sessions under state/sessions/", file=sys.stderr)
            return 2
        print("available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nusage: uv run python replay.py <session_id>")
        return 0
    return replay(args[0])


if __name__ == "__main__":
    sys.exit(main())
