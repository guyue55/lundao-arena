#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论道台 (Lundao Arena) — 对局记账与出档工具

职责边界：本脚本只管「记账 + 出档」，不产生任何发言内容。
发言由宿主 agent 调度真实角色（subagent / 本人扮演）产出，逐条写入对局文件。

用法：
  python3 arena.py init   --spec spec.json [--dir <对局目录>]
  python3 arena.py turn   --dir <对局目录> --round 3 --speaker A --text-file 3a.txt \
                          --score A:2,B:1 --verdict "A占上风" [--note "..."]
  python3 arena.py status --dir <对局目录>
  python3 arena.py brief  --dir <对局目录> [--round N] [--out 文件]
  python3 arena.py render --dir <对局目录> [--html]
  python3 arena.py check  --dir <对局目录> [--strict-evidence]

对局文件：<对局目录>/arena.json（唯一真相源，可断点续跑）
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

STATE = "arena.json"
VALID_MODES = ("duel", "roundtable", "camp")
VALID_RULESETS = ("historical", "adversarial", "truthseeking", "persuasion", "creative")

# 证据标签（借鉴 xiaoba-dev/debate 的 [verified]/[reasoned]/[to-verify]，
# 再加一档「存疑」用来收编硬圆被拆穿的派）。出档时挂在发言后面。
EVIDENCE_LEVELS = ("verified", "reasoned", "to-verify", "speculative")
EVIDENCE_LABELS = {
    "verified": "已核", "reasoned": "推理", "to-verify": "待核", "speculative": "存疑",
}
EVIDENCE_ALIASES = {
    "v": "verified", "verified": "verified", "已核": "verified", "核实": "verified",
    "r": "reasoned", "reasoned": "reasoned", "推理": "reasoned", "推论": "reasoned",
    "t": "to-verify", "to-verify": "to-verify", "待核": "to-verify", "未核": "to-verify",
    "s": "speculative", "speculative": "speculative", "存疑": "speculative", "编派": "speculative",
}

# 匿名席位牌：brief 视图用，绝不让真名漏出去。
SEAT_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def norm_evidence(value: str) -> str:
    """把 --evidence 的各种写法收敛到四档；空串返回空串（不强制打标）。"""
    v = (value or "").strip().strip("[]").strip()
    if not v:
        return ""
    key = v.lower()
    if key not in EVIDENCE_ALIASES:
        die(f"--evidence 只认 {list(EVIDENCE_LEVELS)}（或对应中文），收到 {value!r}")
    return EVIDENCE_ALIASES[key]


# ---------------------------------------------------------------- 基础读写

def die(msg: str, code: int = 1):
    print(f"[arena] 错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def load(dirpath: str) -> dict:
    p = os.path.join(dirpath, STATE)
    if not os.path.exists(p):
        die(f"{p} 不存在。先跑 init。")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save(dirpath: str, data: dict):
    p = os.path.join(dirpath, STATE)
    data["updated_at"] = now_iso()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 计分

def parse_score(raw: str, known_ids: list[str]) -> dict:
    """'A:2,B:1' -> {'A': 2, 'B': 1}"""
    out = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            die(f"分数片段格式应为 角色:分值，收到 {part!r}")
        k, v = part.split(":", 1)
        k = k.strip()
        if k not in known_ids:
            die(f"未知角色 id {k!r}，本局角色：{', '.join(known_ids)}")
        try:
            out[k] = float(v)
        except ValueError:
            die(f"分值必须是数字，收到 {v!r}")
    return out


RUBRIC_DIMS = ("接招", "新据", "自洽", "认账")


def parse_rubric(raw: str, known_ids: list[str]) -> dict:
    """'A:接2,据2,洽2,认1;B:接1,据1,洽2,认2' -> {'A': {'接招':2,...}, 'B': {...}}

    四维固定顺序：接招 / 新据 / 自洽 / 认账，各 0-2 分。
    """
    if not raw.strip():
        return {}
    out = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            die(f"评分项格式应为 'A:接2,据2,洽2,认1'，收到 {chunk!r}")
        who, rest = chunk.split(":", 1)
        who = who.strip()
        if who not in known_ids:
            die(f"评分项里的角色 {who!r} 不在 {known_ids}")
        vals = [v.strip() for v in rest.replace("，", ",").split(",") if v.strip()]
        if len(vals) != len(RUBRIC_DIMS):
            die(f"{who} 的四项评分必须齐四项（接招/新据/自洽/认账），收到 {vals}")
        d = {}
        for dim, tok in zip(RUBRIC_DIMS, vals):
            num = "".join(ch for ch in tok if ch.isdigit())
            if not num:
                die(f"{who} 的 {dim} 评分读不出数字：{tok!r}")
            n = int(num)
            if not 0 <= n <= 2:
                die(f"{who} 的 {dim} 评分必须在 0-2 之间，收到 {n}")
            d[dim] = n
        out[who] = d
    return out


def totals(data: dict) -> dict:
    t = {r["id"]: 0.0 for r in data["roles"]}
    for turn in data.get("turns", []):
        for k, v in (turn.get("score") or {}).items():
            t[k] = t.get(k, 0.0) + float(v)
    return t


def round_wins(data: dict) -> dict:
    w = {r["id"]: 0 for r in data["roles"]}
    for turn in data.get("turns", []):
        s = turn.get("score") or {}
        if not s:
            continue
        top = max(s.values())
        leaders = [k for k, v in s.items() if v == top]
        if len(leaders) == 1:
            w[leaders[0]] = w.get(leaders[0], 0) + 1
    return w


def camp_totals(data: dict) -> dict:
    """{'魏': {'score': 12, 'wins': 2}}"""
    t = totals(data)
    w = round_wins(data)
    out = {}
    for cname, members in (data.get("camp") or {}).items():
        out[cname] = {
            "score": sum(t.get(m, 0.0) for m in members),
            "wins": sum(w.get(m, 0) for m in members),
        }
    return out


def fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


# ---------------------------------------------------------------- init

def cmd_init(args):
    if not os.path.exists(args.spec):
        die(f"找不到 spec 文件：{args.spec}")
    try:
        with open(args.spec, "r", encoding="utf-8") as f:
            spec = json.load(f)
    except json.JSONDecodeError as e:
        die(f"spec 不是合法 JSON：{args.spec} 第 {e.lineno} 行 {e.msg}")

    for k in ("title", "mode", "roles"):
        if not spec.get(k):
            die(f"spec 缺少必填字段 {k}")

    mode = spec["mode"]
    if mode not in VALID_MODES:
        die(f"mode 必须是 {VALID_MODES} 之一，收到 {mode!r}")

    ruleset = spec.get("ruleset", "adversarial")
    if ruleset not in VALID_RULESETS:
        die(f"ruleset 必须是 {VALID_RULESETS} 之一，收到 {ruleset!r}")

    roles = spec["roles"]
    ids = [r.get("id") for r in roles]
    if None in ids:
        die("每个 role 必须有 id")
    if len(set(ids)) != len(ids):
        die(f"角色 id 重复：{ids}")
    for r in roles:
        if not r.get("name"):
            die(f"角色 {r['id']} 缺少 name")

    camp = spec.get("camp")
    if mode == "camp":
        if not camp or not isinstance(camp, dict) or len(camp) < 2:
            die("camp 模式必须在 spec.camp 里写明阵营，形如 {\"魏\": [\"A\"], \"蜀\": [\"C\"]}")
        flat = [i for members in camp.values() for i in members]
        if sorted(flat) != sorted(ids):
            die(f"spec.camp 必须不重不漏地覆盖全部角色 id。camp={flat} roles={ids}")
    elif camp:
        die("camp 字段只用于 mode=camp。")

    turn_order = spec.get("turn_order") or ids
    if sorted(turn_order) != sorted(ids):
        die(f"spec.turn_order 必须不重不漏地覆盖全部角色 id。"
            f"turn_order={turn_order} roles={ids}——漏了谁，谁就永远轮不到说话")

    rounds = int(spec.get("rounds_total") or 8)
    if rounds < 1:
        die("rounds_total 至少为 1")

    dirpath = args.dir or spec.get("dir") or slug(spec["title"])
    os.makedirs(dirpath, exist_ok=True)
    state_path = os.path.join(dirpath, STATE)
    if os.path.exists(state_path) and not args.force:
        die(f"{state_path} 已存在。要覆盖请加 --force（会抹掉已有回合）。")

    data = {
        "schema": "lundao-arena/v1",
        "title": spec["title"],
        "mode": mode,
        "ruleset": ruleset,
        "rounds_total": rounds,
        "turn_order": spec.get("turn_order") or [r["id"] for r in roles],
        "roles": roles,
        "judge": spec.get("judge") or {},
        "premise": spec.get("premise") or "",
        "constraints": spec.get("constraints") or [],
        "camp": camp or {},
        "scoring": spec.get("scoring") or {"kind": "rubric3", "per_round_total": 3},
        "turns": [],
        "status": "running",
        "legacy": bool(spec.get("legacy")),
        "created_at": now_iso(),
    }
    save(dirpath, data)
    print(f"[arena] 已建局：{dirpath}/{STATE}")
    print(f"[arena] {data['title']} — {mode} / {ruleset} / {rounds} 回合 / {len(roles)} 角色")


def slug(s: str) -> str:
    keep = [c for c in s if c.isalnum() or c in "-_ "] [:40]
    out = "".join(keep).strip().replace(" ", "-")
    if not out:
        out = "arena-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    return out


# ---------------------------------------------------------------- turn

def cmd_turn(args):
    data = load(args.dir)
    ids = [r["id"] for r in data["roles"]]

    if args.speaker not in ids:
        die(f"speaker 必须是 {ids} 之一，收到 {args.speaker!r}")

    order_ids = data.get("turn_order") or ids
    if args.speaker not in order_ids:
        die(f"speaker {args.speaker} 不在 turn_order {order_ids} 里——"
            f"轮转表漏了这个角色，补 spec 的 turn_order 再记")
    if int(args.round) < 1:
        die("--round 从 1 开始")
    if int(args.round) > int(data.get("rounds_total") or 0):
        die(f"--round {args.round} 超出赛程 {data.get('rounds_total')} 回合；"
            f"要加长赛程，改 spec 的 rounds_total 重建局，别在账上跳号")

    res0 = data.get("result")
    if res0 and args.round != res0["round"]:
        # --force 只认「终局那一回合」这一目标：既能重记它把旧终局作废、接着往下打，
        # 又不能让终局之后凭空多出一段账，也不能绕过终局去改更早的回合
        # （改了更早的回合，result 清空、status 回 running，而终局那一条还挂在账上）。
        die(f"本局已在第 {res0['round']} 回合终局（{res0.get('loser')} {res0.get('label')}），"
            f"记不了第 {args.round} 回合——--force 只能重记终局那一回合。"
            f"要接着打，先 --force 重记第 {res0['round']} 回合把旧终局作废，再记后面的。")
    if res0 and not args.force:
        die(f"本局已在第 {res0['round']} 回合终局（{res0.get('loser')} {res0.get('label')}）。"
            f"要改终局那一回合，请加 --force（旧终局会作废、可以接着往下打）。")

    exists = [t for t in data["turns"] if t["round"] == args.round and t["speaker"] == args.speaker]
    if exists and not args.force:
        die(f"第 {args.round} 回合 {args.speaker} 已记录。要覆盖请加 --force。")

    text = ""
    if args.text_file:
        if not os.path.exists(args.text_file):
            die(f"找不到发言文件：{args.text_file}")
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    elif args.text:
        text = args.text.strip()
    if not text:
        die("发言正文为空：用 --text-file 或 --text 提供。")

    score = parse_score(args.score or "", ids)
    rubric = parse_rubric(getattr(args, "rubric", "") or "", ids)
    pivot = (getattr(args, "pivot", "") or "").strip()
    evidence = norm_evidence(getattr(args, "evidence", "") or "")
    concedes = (getattr(args, "concede", "") or "").strip()
    ko = (getattr(args, "ko", "") or "").strip()
    if concedes and ko:
        die("--concede 与 --ko 只能二选一：一次只结一个终局")
    if concedes:
        if concedes not in ids:
            die(f"--concede 必须是 {ids} 之一，收到 {concedes!r}")
        if concedes != args.speaker:
            die(f"认输要记在认输者自己那一回合（本回合发言是 {args.speaker}，"
                f"--concede 给的是 {concedes}）")
    if ko:
        if ko not in ids:
            die(f"--ko 必须是 {ids} 之一，收到 {ko!r}")
        if ko == args.speaker:
            die("--ko 指的是被击穿的人，不能是自己")

    per_total = data.get("scoring", {}).get("per_round_total")
    # 合法合计：正常 3 分；2:0（明显压制）与 1:1（势均）是 2 分，都是规则内的形态。
    allowed = data.get("scoring", {}).get("allowed_totals") or ([per_total, 2] if per_total else [])
    if (score and per_total and data.get("mode") == "duel"
            and abs(sum(score.values()) - float(per_total)) > 1e-9):
        if sum(score.values()) not in [float(x) for x in allowed]:
            print(f"[arena] 警告：本回合分值合计 {sum(score.values()):g}，"
                  f"规则写明每回合 {per_total} 分（2:0 与 1:1 为 2 分，属规则内）", file=sys.stderr)

    order = data.get("turn_order") or ids
    prev = data["turns"][-1] if data["turns"] else None
    if prev and prev["round"] == args.round:
        idx = order.index(prev["speaker"])
        expect = order[(idx + 1) % len(order)]
        if args.speaker != expect and not args.force:
            print(f"[arena] 警告：上一发言是 {prev['speaker']}，按轮转顺序本应轮到 "
                  f"{expect}，实际记录 {args.speaker}（照记）。", file=sys.stderr)

    if exists:
        data["turns"].remove(exists[0])

    data["turns"].append({
        "round": int(args.round),
        "speaker": args.speaker,
        "text": text,
        "score": score,
        "verdict": args.verdict or "",
        "note": args.note or "",
        "pivot": pivot,
        "rubric": rubric,
        "evidence": evidence,
        "blind": bool(getattr(args, "blind", False)),
        "concede": concedes,
        "ko": ko,
        "at": now_iso(),
    })
    data["turns"].sort(key=lambda t: (t["round"], order.index(t["speaker"])))

    if concedes or ko:
        loser = concedes or ko
        others = [i for i in ids if i != loser]
        data["result"] = {
            "round": int(args.round),
            "loser": loser,
            "winner": others[0] if len(others) == 1 else None,
            "reason": "concede" if concedes else "ko",
            "label": "认输" if concedes else "要害被击穿",
            "note": args.note or "",
        }
        data["status"] = "finished"
    else:
        res = data.get("result")
        if res and int(args.round) <= int(res.get("round") or 0):
            # 重记了终局那一回合（或更早），旧终局失效
            data.pop("result", None)
            data["status"] = "running"
        done = len({t["round"] for t in data["turns"]})
        if done >= data["rounds_total"]:
            data["status"] = "finished"
    save(args.dir, data)
    print(f"[arena] 已记：第 {args.round} 回合 · {args.speaker} · "
          f"{len(text)} 字 · 比分 {args.verdict or '—'}")
    res = data.get("result")
    if res:
        wname = {r["id"]: r["name"] for r in data["roles"]}.get(res.get("winner") or "", "—")
        print(f"[arena] 终局：第 {res['round']} 回合 · "
              f"{ {r['id']: r['name'] for r in data['roles']}.get(res['loser'], res['loser']) } "
              f"{res['label']}"
              + (f"，{wname} 胜" if res.get("winner") else "")
              + " —— 局已结")


# ---------------------------------------------------------------- status

def cmd_status(args):
    data = load(args.dir)
    t = totals(data)
    w = round_wins(data)
    order = data.get("turn_order") or [r["id"] for r in data["roles"]]
    name = {r["id"]: r["name"] for r in data["roles"]}

    print(f"《{data['title']}》")
    res = data.get("result") or {}
    print(f"  模式 {data['mode']} / 规则 {data['ruleset']} / "
          f"进度 {len({x['round'] for x in data['turns']})}/{data['rounds_total']} 回合 / 状态 {data['status']}")
    if res:
        wname = name.get(res.get("winner") or "", "")
        print(f"  终局：第 {res['round']} 回合 · {name.get(res['loser'], res['loser'])} "
              f"{res['label']}" + (f"，{wname} 胜" if wname else "")
              + f"（余下 {max(0, data['rounds_total'] - res['round'])} 回合未进行）")
    print()
    print(f"  {'角色':<10}{'总分':>8}{'胜回合':>8}")
    for rid in order:
        print(f"  {name.get(rid, rid):<10}{fmt_num(t.get(rid, 0)):>8}{w.get(rid, 0):>8}")
    camps = camp_totals(data)
    if camps:
        print(f"  {'阵营':<10}{'总分':>8}{'胜回合':>8}")
        for cname, v in camps.items():
            print(f"  {cname:<10}{fmt_num(v['score']):>8}{v['wins']:>8}")
        print()
    for turn in data["turns"]:
        print(f"  R{turn['round']:<3}{name.get(turn['speaker'], turn['speaker']):<8}"
              f"{turn.get('verdict') or '—'}")


# ---------------------------------------------------------------- render

def cmd_render(args):
    data = load(args.dir)
    md = render_md(data)
    out_md = os.path.join(args.dir, "论道实录.md")
    if os.path.exists(out_md):
        print(f"[arena] 覆盖上一版实录：{out_md}", file=sys.stderr)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[arena] 已出档：{out_md}")

    if args.html:
        out_html = os.path.join(args.dir, "论道实录.html")
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(render_html(data))
        print(f"[arena] 已出网页：{out_html}")


def render_md(data: dict) -> str:
    t = totals(data)
    w = round_wins(data)
    order = data.get("turn_order") or [r["id"] for r in data["roles"]]
    name = {r["id"]: r["name"] for r in data["roles"]}
    role = {r["id"]: r for r in data["roles"]}

    L = []
    L.append(f"# {data['title']}\n")
    L.append(f"> 论道台实录 · {data['mode']} · {data['ruleset']} · "
             f"{data['rounds_total']} 回合 · 生成于 {now_iso()}\n")

    if data.get("premise"):
        L.append(f"**前提**：{data['premise']}\n")

    L.append("\n## 座次\n")
    L.append("| 席位 | 角色 | 名分 | 立场 | 口吻 |")
    L.append("|---|---|---|---|---|")
    for rid in order:
        r = role[rid]
        L.append(f"| {rid} | {r['name']} | {r.get('mandate', '—')} | "
                 f"{r.get('stance', '—')} | {r.get('voice', '—')} |")
    L.append("")

    if data.get("constraints"):
        L.append("## 硬规矩\n")
        for c in data["constraints"]:
            L.append(f"- {c}")
        L.append("")

    L.append("## 回合\n")
    for turn in data["turns"]:
        rid = turn["speaker"]
        mark = "（盲判）" if turn.get("blind") else ""
        L.append(f"### 第 {turn['round']} 回合 · {name.get(rid, rid)}{mark}\n")
        L.append(turn["text"].strip() + "\n")
        if turn.get("evidence"):
            L.append(f"\n证据：[{EVIDENCE_LABELS.get(turn['evidence'], turn['evidence'])}]"
                     f"（{turn['evidence']}）\n")
        if turn.get("pivot"):
            L.append(f"\n> **自报要害**：{turn['pivot']}\n")
        if turn.get("verdict"):
            L.append(f"\n**裁判**：{turn['verdict']}\n")
        if turn.get("note"):
            L.append(f"\n{turn['note']}\n")
        L.append("")

    L.append("## 终局\n")
    res = data.get("result") or {}
    if res:
        wname = name.get(res.get("winner") or "", "")
        line = (f"**第 {res['round']} 回合 · {name.get(res['loser'], res['loser'])} {res['label']}"
                + (f"，{wname} 胜**" if wname else "**"))
        L.append(line)
        rest = max(0, data["rounds_total"] - int(res["round"]))
        if rest:
            L.append(f"\n余下 {rest} 回合未进行——认输或击穿要害即止，不必打满。\n")
        L.append("")
    L.append("| 席位 | 角色 | 总分 | 胜回合 |")
    L.append("|---|---|---:|---:|")
    for rid in order:
        L.append(f"| {rid} | {name.get(rid, rid)} | {fmt_num(t.get(rid, 0))} | {w.get(rid, 0)} |")
    L.append("")

    camps = camp_totals(data)
    if camps:
        L.append("### 阵营")
        L.append("")
        L.append("| 阵营 | 成员 | 总分 | 胜回合 |")
        L.append("|---|---|---:|---:|")
        for cname, v in camps.items():
            members = "、".join(name.get(m, m) for m in data["camp"][cname])
            L.append(f"| {cname} | {members} | {fmt_num(v['score'])} | {v['wins']} |")
        L.append("")

    if camps:
        L.append(conclusion_camp_md(data, camps))
    else:
        L.append(conclusion_md(data, t, w, order, name))
    return "\n".join(L)


def conclusion_md(data, t, w, order, name) -> str:
    if data.get("conclusion"):
        return "**裁决**：" + data["conclusion"].strip() + "\n"
    if not t:
        return ""
    # 总分是账，不是结论。按分自动宣布胜负，正是 judging.md 禁止的
    # 「拿总分代替裁决」——账面上的 1 分差，抹掉了「谁在哪一句上失守」。
    return ("**裁决**：未填写。跑 "
            "`arena.py conclude --dir ./juban --text-file ./裁决.txt` 补上；"
            "总分只记账，不作终局结论。\n")


def conclusion_camp_md(data, camps) -> str:
    if data.get("conclusion"):
        return "**裁决**：" + data["conclusion"].strip() + "\n"
    return ("**裁决**：未填写。阵营总分见上表；"
            "但阵营之间谁算赢，要写清是赢在哪一件事上，不是比总分。\n")


HTML_CSS = """
:root{--ink:#1a1a1a;--sub:#6b6b6b;--line:#e4e4e4;--bg:#fbfaf7;--card:#fff;--win:#8a6d3b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.85 "Songti SC","Noto Serif SC",Georgia,serif}
.wrap{max-width:760px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:30px;line-height:1.35;margin:0 0 8px;letter-spacing:.01em}
.meta{color:var(--sub);font-size:13px;letter-spacing:.04em;margin-bottom:40px}
h2{font-size:15px;letter-spacing:.18em;color:var(--sub);font-weight:600;
 margin:56px 0 20px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.turn{background:var(--card);border:1px solid var(--line);border-radius:14px;
 padding:26px 28px;margin:0 0 22px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
.turn h3{margin:0 0 14px;font-size:14px;letter-spacing:.1em;color:var(--win);font-weight:600}
.turn p{margin:0 0 12px;white-space:pre-wrap}
.turn p:last-child{margin-bottom:0}
.judge{margin-top:18px;padding-top:16px;border-top:1px dashed var(--line);
 font-size:14px;color:#4a4a4a;line-height:1.8}
.judge b{color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:14px;margin:0 0 8px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}
th{color:var(--sub);font-weight:600;font-size:13px;letter-spacing:.06em}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.verdict{margin-top:32px;padding:20px 24px;border-left:3px solid var(--win);
 background:#fff;font-size:15px}
.rules{font-size:14px;color:#4a4a4a}
.rules li{margin:4px 0}
"""


def render_html(data: dict) -> str:
    t = totals(data)
    w = round_wins(data)
    order = data.get("turn_order") or [r["id"] for r in data["roles"]]
    name = {r["id"]: r["name"] for r in data["roles"]}
    role = {r["id"]: r for r in data["roles"]}
    e = html.escape

    parts = [f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             f"<title>{e(data['title'])}</title><style>{HTML_CSS}</style></head><body>",
             "<div class='wrap'>",
             f"<h1>{e(data['title'])}</h1>",
             f"<div class='meta'>论道台实录 · {e(data['mode'])} · {e(data['ruleset'])} · "
             f"{data['rounds_total']} 回合 · {e(now_iso())}</div>"]

    if data.get("premise"):
        parts.append("<h2>前提</h2><p>" + e(data["premise"]) + "</p>")

    parts.append("<h2>座次</h2><table><tr><th>席位</th><th>角色</th><th>名分</th>"
                 "<th>立场</th><th>口吻</th></tr>")
    for rid in order:
        r = role[rid]
        parts.append(f"<tr><td>{e(rid)}</td><td>{e(r['name'])}</td>"
                     f"<td>{e(r.get('mandate', '—'))}</td>"
                     f"<td>{e(r.get('stance', '—'))}</td><td>{e(r.get('voice', '—'))}</td></tr>")
    parts.append("</table>")

    consts = data.get("constraints") or []
    if consts:
        parts.append("<h2>硬规矩</h2><ul class='rules'>")
        for c in consts:
            parts.append(f"<li>{e(c)}</li>")
        parts.append("</ul>")

    parts.append("<h2>回合</h2>")
    for turn in data["turns"]:
        rid = turn["speaker"]
        parts.append("<div class='turn'>")
        mark = "（盲判）" if turn.get("blind") else ""
        parts.append(f"<h3>第 {turn['round']} 回合 · {e(name.get(rid, rid))}{mark}</h3>")
        for para in turn["text"].strip().split("\n\n"):
            if para.strip():
                parts.append(f"<p>{e(para.strip())}</p>")
        if turn.get("evidence"):
            parts.append(f"<div class='judge'><b>证据</b>：["
                         f"{e(EVIDENCE_LABELS.get(turn['evidence'], turn['evidence']))}]"
                         f"（{e(turn['evidence'])}）</div>")
        if turn.get("pivot"):
            parts.append(f"<div class='judge'><b>自报要害</b>：{e(turn['pivot'])}</div>")
        if turn.get("verdict"):
            parts.append(f"<div class='judge'><b>裁判</b>：{e(turn['verdict'])}</div>")
        if turn.get("note"):
            parts.append(f"<div class='judge'>{e(turn['note'])}</div>")
        parts.append("</div>")

    res = data.get("result") or {}
    if res:
        wname = name.get(res.get("winner") or "", "")
        parts.append("<h2>终局</h2><p class='verdict'><b>第 "
                     + e(str(res["round"])) + " 回合 · "
                     + e(name.get(res["loser"], res["loser"])) + " " + e(res["label"])
                     + (("，" + e(wname) + " 胜") if wname else "") + "</b>"
                     + ("" if not max(0, data["rounds_total"] - int(res["round"]))
                        else "　余下 "
                        + e(str(max(0, data["rounds_total"] - int(res["round"]))))
                        + " 回合未进行——认输或击穿要害即止。")
                     + "</p>")
    else:
        parts.append("<h2>终局</h2>")
    parts.append("<table><tr><th>席位</th><th>角色</th>"
                 "<th class='n'>总分</th><th class='n'>胜回合</th></tr>")
    for rid in order:
        parts.append(f"<tr><td>{e(rid)}</td><td>{e(name.get(rid, rid))}</td>"
                     f"<td class='n'>{fmt_num(t.get(rid, 0))}</td>"
                     f"<td class='n'>{w.get(rid, 0)}</td></tr>")
    parts.append("</table>")

    camps = camp_totals(data)
    if camps:
        parts.append("<h2>阵营</h2><table><tr><th>阵营</th><th>成员</th>"
                     "<th class='n'>总分</th><th class='n'>胜回合</th></tr>")
        for cname, v in camps.items():
            members = "、".join(name.get(m, m) for m in data["camp"][cname])
            parts.append(f"<tr><td>{e(cname)}</td><td>{e(members)}</td>"
                         f"<td class='n'>{fmt_num(v['score'])}</td>"
                         f"<td class='n'>{v['wins']}</td></tr>")
        parts.append("</table>")

    if camps:
        concl = conclusion_camp_md(data, camps)
    else:
        concl = conclusion_md(data, t, w, order, name)
    concl = concl.replace("**裁决**：", "").strip()
    if concl:
        parts.append(f"<div class='verdict'>{e(concl)}</div>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------- brief（匿名判分视图）

def cmd_brief(args):
    """导出匿名判分视图：抹掉角色真名、只留席位牌，供裁判盲读。

    --blind 只是账本上的标记，不遮蔽署名；这个函数才是真正把名字拿掉的工具。
    固定按「回合 + 席位牌」排序，不透露 speaker id，也不打印 pivot/裁决（那些会泄底）。
    """
    data = load(args.dir)
    ids = [r["id"] for r in data["roles"]]
    seats = {rid: SEAT_LABELS[i] for i, rid in enumerate(ids)}
    turns = data.get("turns", [])
    if args.round is not None:
        turns = [t for t in turns if int(t["round"]) == int(args.round)]
        if not turns:
            die(f"第 {args.round} 回合没有记录")
    turns = sorted(turns, key=lambda t: (t["round"], ids.index(t["speaker"])))

    # 标题往往含真名（如「周瑜 vs 诸葛亮」），盲读视图一律用中性标题，杜绝泄底。
    L = ["# 匿名判分视图", ""]
    L.append(f"> 共 {len(turns)} 条发言 · {data['mode']} · {data['ruleset']}。")
    L.append("> 席位牌按座次顺序分配（A/B/C…），与角色 id 一一对应但不显示对应关系。")
    L.append("> 本视图刻意不含自报要害、比分与裁决，避免先入为主；判完分再回账本核名。")
    L.append("")
    last_round = None
    for t in turns:
        if t["round"] != last_round:
            L.append(f"## 第 {t['round']} 回合")
            L.append("")
            last_round = t["round"]
        L.append(f"### 席位 {seats.get(t['speaker'], '?')}")
        L.append("")
        L.append((t.get("text") or "").strip())
        L.append("")
    out = "\n".join(L) + "\n"

    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent and not os.path.isdir(parent):
            die(f"输出目录不存在：{parent}")
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[arena] 匿名视图已写入 {args.out}（{len(turns)} 条，{len(out)} 字）")
    else:
        sys.stdout.write(out)


# ---------------------------------------------------------------- check

def cmd_conclude(args):
    data = load(args.dir)
    if not os.path.exists(args.text_file):
        die(f"找不到裁决文件：{args.text_file}")
    with open(args.text_file, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        die("裁决正文为空：终局不能留白，也不能用总分顶替。")
    data["conclusion"] = text
    save(args.dir, data)
    print(f"[arena] 已写入终局裁决（{len(text)} 字）")


def cmd_check(args):
    """体检。语义按论道实际打法来：
    - 一回合可以只有一方发言（攻防交替），另一方的分照样可以在同一条里给。
    - 因此不校验「每回合双方各发言」，只校验真正会导致账错/出档残缺的项。
    """
    data = load(args.dir)
    ids = [r["id"] for r in data["roles"]]
    name = {r["id"]: r["name"] for r in data["roles"]}
    errors, warnings = [], []
    # 旧档豁免：本轮改造之前记的局没有 pivot/rubric/blind 三个字段，
    # 拿新尺子量旧账是冤枉它。旧档在 arena.json 里写 "legacy": true，
    # 或者体检时显式加 --legacy；--allow-missing 则是明知缺项仍要出档。
    legacy = bool(data.get("legacy")) or getattr(args, "legacy", False)
    strict = not legacy and not getattr(args, "allow_missing", False)
    # 证据门单独一档：默认只提示；显式 --strict-evidence 才拦。
    # 注意显式开关压过 legacy —— 用户既然点名要严格证据门，就不能被旧档标记悄悄豁免。
    strict_ev = bool(getattr(args, "strict_evidence", False))

    def gate(msg):
        (errors if strict else warnings).append(("旧档·" if legacy else "") + msg)

    seen = set()
    speakers_seen = set()
    scored_seen = set()
    round_sum = {}
    blind_n = 0
    for turn in data.get("turns", []):
        key = (turn["round"], turn["speaker"])
        if key in seen:
            errors.append(f"重复记录：第 {turn['round']} 回合 {turn['speaker']}")
        seen.add(key)
        speakers_seen.add(turn["speaker"])

        if not (turn.get("text") or "").strip():
            errors.append(f"空发言：第 {turn['round']} 回合 {turn['speaker']}")

        score = turn.get("score") or {}
        unknown = set(score) - set(ids)
        if unknown:
            errors.append(f"未知角色计分：{sorted(unknown)}，本局角色 {ids}")
        scored_seen |= set(score) & set(ids)

        if score:
            per = data.get("scoring", {}).get("per_round_total")
            allowed = data.get("scoring", {}).get("allowed_totals") or ([per, 2] if per else [])
            allowed = [float(x) for x in allowed]
            # 只在 duel 里按单条发言核每回合总额。camp/roundtable 一回合多人发言、
            # 每人各记一小份（常见 A:1,B:0 与 A:0,B:1 两条），按单条去比「每回合 3 分」
            # 是必然误报；整回合总额由下面的 round_sum 门兜。
            if (per and data.get("mode") == "duel"
                    and float(sum(score.values())) not in allowed):
                warnings.append(f"第 {turn['round']} 回合分值合计 {sum(score.values()):g}，"
                                f"规则写明每回合 {per} 分（2:0 与 1:1 为 2 分，属规则内）")

        # 四维评分与比分必须同向：评分项上更占优的一方，才该在多分的那一栏。
        rubric = turn.get("rubric") or {}
        if rubric and score and len(rubric) >= 2:
            rtot = {who: sum(d.values()) for who, d in rubric.items()}
            ranked_r = sorted(rtot.items(), key=lambda kv: -kv[1])
            if len(ranked_r) >= 2 and ranked_r[0][1] != ranked_r[1][1]:
                better, worse = ranked_r[0][0], ranked_r[1][0]
                if score.get(better, 0) < score.get(worse, 0):
                    warnings.append(
                        f"第 {turn['round']} 回合评分项与比分相反：{name.get(better, better)} "
                        f"四维合计 {rtot[better]}>{rtot[worse]}（{name.get(worse, worse)}），"
                        f"比分却给 {name.get(better, better)} {fmt_num(score.get(better, 0))} : "
                        f"{fmt_num(score.get(worse, 0))}")

        # 自报要害：本局要求每回合末尾交出「对方驳倒这一句即须认输」的那一句。
        # 认输那一回合不必给靶子——他已经认了，没有要害可守。
        concede_turn = bool((turn.get("concede") or "").strip())
        if (data.get("mode") == "duel" and not (turn.get("pivot") or "").strip()
                and not concede_turn):
            gate(f"第 {turn['round']} 回合 {name.get(turn['speaker'], turn['speaker'])} "
                 f"未自报要害（--pivot）——没有靶子，终局无从判「要害被击穿」")

        # 有分必有尺：四维是「先分项后总评」的落点，缺了就没法核比分从哪来。
        # 只有 rubric4 局要求四维；老的 rubric3 局按三分制记账，不追认新尺。
        if (score and not rubric and not concede_turn
                and data.get("scoring", {}).get("kind") == "rubric4"):
            gate(f"第 {turn['round']} 回合计了分却没给四维（--rubric）——"
                 f"比分无从核，只能算态度")

        if score:
            round_sum[turn["round"]] = round_sum.get(turn["round"], 0.0) + float(sum(score.values()))
        if turn.get("blind"):
            blind_n += 1

    # 一回合只该有一份账。同回合多位发言者各记一次，总分就会被算两遍
    # （2 营 2 回合各发一次 → 双方各 6 分 2 胜，比真实局面翻了一倍）。
    if data.get("mode") == "duel":
        by_round = {}
        for turn in data.get("turns", []):
            by_round.setdefault(turn["round"], []).append(turn["speaker"])
        for r, spk in sorted(by_round.items()):
            if len(spk) > 1:
                errors.append(f"第 {r} 回合记了 {len(spk)} 条发言（{'、'.join(spk)}）——"
                              f"duel 一回合只许一条；两条就是同一回合记了两份账")

    per = data.get("scoring", {}).get("per_round_total")
    if per:
        cap = max([float(x) for x in
                   (data.get("scoring", {}).get("allowed_totals") or [per])] + [float(per)])
        for r, s in sorted(round_sum.items()):
            if s > cap + 1e-9:
                errors.append(f"第 {r} 回合合计 {fmt_num(s)} 分，超过每回合上限 {fmt_num(cap)} 分"
                              f"——同一回合被重复记账，总分翻倍")

    # 盲判：裁判见了角色名就会偏袒有名的那一方。整局一次都不盲判，
    # 「盲判为默认」就只是文档里的一句话。
    if strict and len(data["turns"]) >= 4 and blind_n * 2 < len(data["turns"]):
        errors.append(f"盲判不足一半：{blind_n}/{len(data['turns'])} 条标了 --blind。"
                      f"补标，或用 --allow-missing 显式豁免，并在裁决里写明为什么没盲判")

    if data.get("status") == "finished" and not (data.get("conclusion") or "").strip():
        warnings.append("已终局但没有写裁决（conclusion）——出档时只会留下一句"
                        "「未填写」，不会替你按总分宣布胜负")

    over = sorted({t["round"] for t in data.get("turns", [])
                   if int(t["round"]) > int(data.get("rounds_total") or 0)})
    if over:
        errors.append(f"账本里有超出赛程 {data['rounds_total']} 回合的记录：{over}——"
                      f"要么赛程写错，要么账本被手改过")

    covered = {t["round"] for t in data["turns"]}
    res = data.get("result") or {}
    end_round = int(res.get("round") or 0) if res else int(data["rounds_total"])
    if res:
        if end_round > int(data["rounds_total"]):
            errors.append(f"终局回合 {end_round} 超出赛程 {data['rounds_total']} 回合")
        if res.get("loser") not in ids:
            errors.append(f"终局记录的输家 {res.get('loser')!r} 不在角色表里")
        # 被击穿的那个人，自己有没有报过要害？没报过，打的就是稻草人。
        loser = res.get("loser")
        if res.get("reason") == "ko" and loser:
            has_pivot = any((t.get("pivot") or "").strip()
                            for t in data["turns"] if t.get("speaker") == loser)
            if not has_pivot:
                warnings.append(f"第 {end_round} 回合判了击穿要害，但 "
                                f"{name.get(loser, loser)} 全程没自报过要害——"
                                f"被击穿的不是要害，是稻草人（或他根本没给靶子）")
            # KO 证据门：击穿是「主张还挂着，人已站不住」，必须落在可核对的证据上。
            # 靠编派（speculative）或干脆不标证据打出来的 KO，正是天道局方士那种
            # 「硬圆被拆穿」的翻版。默认提示，--strict-evidence 才升为错误。
            ko_turns = [t for t in data["turns"] if (t.get("ko") or "").strip()]
            ko_ev = ko_turns[0].get("evidence", "") if ko_turns else ""
            ko_msg = None
            if not ko_ev:
                ko_msg = (f"第 {end_round} 回合判了击穿，宣布击穿的那一发却没标证据等级"
                          f"（--evidence）——击穿必须落在可核对的证据上")
            elif ko_ev == "speculative":
                ko_msg = (f"第 {end_round} 回合的击穿建立在「存疑」证据上——"
                          f"用编派打出来的击穿不算数，换可核对的凭据")
            elif ko_ev == "to-verify":
                ko_msg = (f"第 {end_round} 回合的击穿证据仍「待核」——"
                          f"核实前别急着宣布要害被击穿")
            if ko_msg:
                (errors if strict_ev else warnings).append(ko_msg)
    missing = [r for r in range(1, end_round + 1) if r not in covered]
    if missing and not args.partial:
        errors.append(f"未打完的回合：{missing}（截断样本请加 --partial）")

    # 计了分却从没发过言的角色：账上没有他的正文，出档会出现「有分无辞」。
    # 终局时这是硬伤；局中只是提示（他还没轮到说话）。
    silent = sorted(scored_seen - speakers_seen)
    if silent and data.get("status") == "finished":
        errors.append("有计分但通篇无发言的角色："
                      + "、".join(f"{s}({name.get(s, s)})" for s in silent))
    never = [r for r in ids if r not in speakers_seen and r not in silent]
    if never:
        warnings.append("全程未发言的角色：" + "、".join(f"{s}({name.get(s, s)})" for s in never))

    # 提前终止建议：一方连续三回合 2:0，再打下去只是水局。
    ordered = sorted(data.get("turns", []), key=lambda t: (t["round"], t["speaker"]))
    streak_who, streak, best = None, 0, (None, 0)
    for turn in ordered:
        sc = turn.get("score") or {}
        if len(sc) < 2:
            continue
        top = max(sc.items(), key=lambda kv: kv[1])
        low = min(sc.values())
        if top[1] - low >= 2:
            if top[0] == streak_who:
                streak += 1
            else:
                streak_who, streak = top[0], 1
            if streak > best[1]:
                best = (streak_who, streak)
        else:
            streak_who, streak = None, 0
    if best[1] >= 3:
        warnings.append(f"提前终止建议：{name.get(best[0], best[0])} 已连续 {best[1]} 回合压制"
                        f"（净胜 ≥2，含 2:0/3:0/3:1），可提前收局并在裁决里写明理由")

    # 收敛警报：近期双方都在互相让步、没有新论据，说明这局已经不出东西了。
    recent = ordered[-4:]

    def _is_draw(turn) -> bool:
        sc = turn.get("score") or {}
        return len(sc) >= 2 and len(set(sc.values())) == 1

    if len(recent) >= 4 and all(_is_draw(t) for t in recent):
        warnings.append("收敛警报：最近四回合全是平手（1:1 或 2:2），"
                        "怀疑双方在互相让步——裁判应点名「这一轮谁都没被驳到」，或换更硬的命题")
    shutouts = [t for t in ordered if (t.get("score") or {}) and
                max(t["score"].values()) - min(t["score"].values()) >= 2]
    if len(ordered) >= 8 and not shutouts:
        warnings.append("整局没有一次 2:0——八回合以上还没出现明显压制，"
                        "要么两人势均，要么裁判没敢给分")

    if errors:
        print(f"[arena] 体检不通过：{len(errors)} 个错误"
              + (f"，{len(warnings)} 个提示" if warnings else ""), file=sys.stderr)
        for p in errors:
            print(f"  ✗ {p}", file=sys.stderr)
        for p in warnings:
            print(f"  · {p}", file=sys.stderr)
        raise SystemExit(2)

    print(f"[arena] 体检通过：{data['title']} — "
          f"{len(covered)}/{data['rounds_total']} 回合，{len(data['turns'])} 条发言"
          + ("（截断样本）" if args.partial and missing else "")
          + ("，含 " + str(len(warnings)) + " 个提示" if warnings else ""))
    for p in warnings:
        print(f"  · {p}")


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="arena.py", description="论道台：对局记账与出档")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="按 spec.json 建局")
    p.add_argument("--spec", required=True)
    p.add_argument("--dir", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("turn", help="记录一条发言及其计分")
    p.add_argument("--dir", required=True)
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--speaker", required=True)
    p.add_argument("--text", default="")
    p.add_argument("--text-file", default="")
    p.add_argument("--score", default="", help="形如 A:2,B:1")
    p.add_argument("--verdict", default="")
    p.add_argument("--note", default="")
    p.add_argument("--pivot", default="", help="本回合自报要害：对方驳倒这一句即须认输")
    p.add_argument("--rubric", default="", help="四维评分 'A:接2,据2,洽2,认1;B:接1,据1,洽2,认2'")
    p.add_argument("--evidence", default="",
                   help="证据等级：verified/reasoned/to-verify/speculative（或已核/推理/待核/存疑）")
    p.add_argument("--blind", action="store_true", help="本回合为盲判（判分时未见角色名）")
    p.add_argument("--concede", default="",
                   help="本回合发言者认输，局即刻终（记角色 id）")
    p.add_argument("--ko", default="",
                   help="本回合击穿某角色的要害，局即刻终（记被击穿者的 id）")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_turn)

    p = sub.add_parser("status", help="看当前比分与进度")
    p.add_argument("--dir", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("brief", help="导出匿名判分视图（抹掉署名，供盲读）")
    p.add_argument("--dir", required=True)
    p.add_argument("--round", type=int, default=None, help="只看某一回合，默认全部")
    p.add_argument("--out", default="", help="写入文件；缺省打印到 stdout")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("render", help="出实录（md / html）")
    p.add_argument("--dir", required=True)
    p.add_argument("--html", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("conclude", help="写入终局裁决")
    p.add_argument("--dir", required=True)
    p.add_argument("--text-file", required=True)
    p.set_defaults(func=cmd_conclude)

    p = sub.add_parser("check", help="体检对局文件")
    p.add_argument("--dir", required=True)
    p.add_argument("--partial", action="store_true", help="允许截断样本（未打满回合不算错）")
    p.add_argument("--legacy", action="store_true",
                   help="这是改造前记的旧档，不按要害/四维/盲判三项硬门量")
    p.add_argument("--allow-missing", action="store_true",
                   help="明知缺要害/四维/盲判仍要出档：降为提示，不拦")
    p.add_argument("--strict-evidence", action="store_true",
                   help="击穿证据缺失/存疑/待核时拦下（默认只提示）")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()