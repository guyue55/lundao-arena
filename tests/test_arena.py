#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论道台工具链验证门：拿真实对局数据跑一遍全流程。

跑法：python3 tests/test_arena.py
（也可 python3 -m unittest discover -s tests -p 'test_*.py'）

验证的不是「函数返回 True」，是「一份真打过十个回合的论道，能不能
按真实打法记进账、出成实录、并且在数据有问题时真的报错」。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLI = os.path.join(REPO, "scripts", "arena.py")
FIX = os.path.join(HERE, "fixtures", "zhouyu-zhuge")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _dump(obj, p, **kw):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)


def run(*args, cwd=None):
    return subprocess.run([sys.executable, CLI, *args],
                          cwd=cwd or REPO, capture_output=True, text=True)


class ArenaE2E(unittest.TestCase):
    """真实回放：周瑜/诸葛亮第 4–10 回合。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arena-test-")
        self.dir = os.path.join(self.tmp, "game")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self):
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)

        turns = json.loads(_read(os.path.join(FIX, "turns.json")))
        for t in turns:
            tf = os.path.join(self.tmp, f"t{t['round']}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(t["text"])
            score = ",".join(f"{k}:{v}" for k, v in t["score"].items())
            r = run("turn", "--dir", self.dir, "--round", str(t["round"]),
                    "--speaker", t["speaker"], "--text-file", tf,
                    "--score", score, "--verdict", t["verdict"])
            self.assertEqual(r.returncode, 0, f"R{t['round']} 记录失败：{r.stderr}")
        return turns

    # ------------------------------------------------ 主链路

    def test_full_pipeline(self):
        turns = self._build()

        # 1) 体检：截断样本应通过，且不能把「一回合只有一方发言」当错
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 0, f"体检不应失败：{r.stderr}")
        self.assertIn("体检通过", r.stdout)

        # 2) 不声明截断时，缺回合必须报错
        r = run("check", "--dir", self.dir)
        self.assertEqual(r.returncode, 2, "缺回合时 check 必须拒绝")
        self.assertIn("未打完的回合", r.stderr)

        # 3) 比分：周瑜 11 : 诸葛亮 10（只算第 4–10 回合）
        r = run("status", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("11", r.stdout)
        self.assertIn("10", r.stdout)

        # 4) 出档
        r = run("render", "--dir", self.dir, "--html")
        self.assertEqual(r.returncode, 0, r.stderr)
        md = os.path.join(self.dir, "论道实录.md")
        ht = os.path.join(self.dir, "论道实录.html")
        self.assertTrue(os.path.exists(md) and os.path.exists(ht))
        body = _read(md)
        self.assertGreater(len(body), 3000)
        self.assertIn("周瑜", body)
        self.assertIn("第 10 回合", body)
        # 正文必须逐字落进实录，不能被截断或改写
        self.assertIn(turns[0]["text"].split("\n")[0], body)
        self.assertIn(turns[-1]["text"].split("\n")[0], body)
        # HTML 自包含：不许引用外部样式
        h = _read(ht)
        self.assertNotIn("<link", h)
        self.assertNotIn("http://", h)

    # ------------------------------------------------ 坏数据必须被拦

    def test_rejects_duplicate_turn(self):
        self._build()
        tf = os.path.join(self.tmp, "dup.txt")
        _write(tf, "再来一次")
        r = run("turn", "--dir", self.dir, "--round", "4", "--speaker", "A",
                "--text-file", tf, "--score", "A:2,B:1")
        self.assertNotEqual(r.returncode, 0, "重复记录必须拒绝")
        self.assertIn("已记录", r.stderr)

    def test_rejects_unknown_speaker(self):
        self._build()
        r = run("turn", "--dir", self.dir, "--round", "11", "--speaker", "曹操",
                "--text", "孤来也", "--score", "A:2,B:1")
        self.assertNotEqual(r.returncode, 0)

    def test_rejects_empty_text(self):
        self._build()
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "   ", "--score", "A:2,B:1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("正文为空", r.stderr)

    def test_rejects_bad_score_sum(self):
        """分值合计不符规则只报警告，不吞数据。"""
        self._build()
        tf = os.path.join(self.tmp, "bad.txt")
        _write(tf, "只有一分")
        r = run("turn", "--dir", self.dir, "--round", "4", "--speaker", "B",
                "--text-file", tf, "--score", "A:1,B:0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("每回合 3 分", r.stderr)

    def test_round_beyond_schedule_is_rejected(self):
        """跳到赛程外记回合，会把「打了几回合」算错，必须拦。"""
        self._build()
        r = run("turn", "--dir", self.dir, "--round", "11", "--speaker", "A",
                "--text", "第 11 回合。", "--score", "A:2,B:1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("超出赛程", r.stderr)

    def test_shutout_and_draw_are_legal_totals(self):
        """2:0 与 1:1 都是规则内的 2 分形态，不该被当成「合计不符」报警。"""
        self.assertFalse(os.path.exists(self.dir), "先建局")
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rnd, spk, sc in ((1, "A", "A:2,B:0"), (2, "B", "A:1,B:1")):
            r = run("turn", "--dir", self.dir, "--round", str(rnd), "--speaker", spk,
                    "--text", f"第{rnd}回合发言", "--score", sc)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("每回合 3 分", r.stderr, f"{sc} 不该报警告")

    def test_pivot_and_blind_are_recorded_and_rendered(self):
        """自报要害与盲判标记必须进账、进档。"""
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "正文。", "--score", "A:2,B:1",
                "--pivot", "若你能指出去年同一笔账，我认。", "--blind")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(_read(os.path.join(self.dir, "arena.json")))
        t = d["turns"][0]
        self.assertEqual(t["pivot"], "若你能指出去年同一笔账，我认。")
        self.assertTrue(t["blind"])
        r = run("render", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("自报要害", body)
        self.assertIn("若你能指出去年同一笔账，我认。", body)
        self.assertIn("（盲判）", body)

    def test_rubric_contradicting_score_warns(self):
        """四维评分说 A 更强、比分却给 B 更多分 —— 必须提示，不许悄悄过去。"""
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "正文。", "--score", "A:1,B:2",
                "--rubric", "A:接2,据2,洽2,认1;B:接0,据0,洽1,认0")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 0, "只是提示，不该拦")
        self.assertIn("评分项与比分相反", r.stdout + r.stderr)

    def test_rubric_agreeing_with_score_is_quiet(self):
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "正文。", "--score", "A:2,B:1", "--pivot", "要害在此。",
                "--rubric", "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertNotIn("评分项与比分相反", r.stdout + r.stderr)
        self.assertNotIn("未自报要害", r.stdout + r.stderr)

    def _quick_duel(self, n=2):
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        for i in range(1, n + 1):
            spk = "A" if i % 2 else "B"
            r = run("turn", "--dir", self.dir, "--round", str(i), "--speaker", spk,
                    "--text", f"第{i}回合正文。", "--score", f"{spk}:2" + (
                        ",B:1" if spk == "A" else ",A:1"),
                    "--pivot", f"第{i}回合我的要害。")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_ko_ends_match_without_playing_all_rounds(self):
        """击穿要害即终局：8 回合的赛程打到第 3 回合就该算打完，不是缺回合。"""
        self._quick_duel(2)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "这一处你接不住。", "--score", "A:3,B:0",
                "--pivot", "我的要害在此。", "--ko", "B")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("终局", r.stdout)
        # 不加 --partial 也必须通过——提前终局是合法的，不是截断
        r = run("check", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, f"提前终局不该算缺回合：{r.stderr}")
        d = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertEqual(d["status"], "finished")
        self.assertEqual(d["result"]["reason"], "ko")
        self.assertEqual(d["result"]["winner"], "A")
        self.assertEqual(d["result"]["loser"], "B")
        # 出档必须写明终局与余下未打的回合
        r = run("render", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("要害被击穿", body)
        self.assertIn("未进行", body)

    def test_concede_ends_match(self):
        """认输即终局，且必须记在认输者自己那一回合。"""
        self._quick_duel(2)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "我认。", "--score", "A:0,B:3", "--concede", "A")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertEqual(d["result"]["reason"], "concede")
        self.assertEqual(d["result"]["winner"], "B")
        self.assertEqual(run("check", "--dir", self.dir).returncode, 0)

    def test_concede_must_be_the_speaker(self):
        self._quick_duel(2)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "我认。", "--concede", "B")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("认输者自己那一回合", r.stderr)

    def test_ko_on_strawman_warns(self):
        """被击穿的人从没报过要害 —— 打的是稻草人，必须点出来。"""
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "先手。", "--score", "A:2,B:1", "--pivot", "我的要害。")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                "--text", "你错了。", "--score", "A:1,B:2")   # B 没报要害
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "击穿。", "--score", "A:3,B:0", "--ko", "B")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", self.dir)
        self.assertIn("稻草人", r.stdout + r.stderr)

    def test_rerecording_voids_old_result(self):
        """重记终局那一回合，旧终局要作废，局回到 running。"""
        self._quick_duel(2)
        r = run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                "--text", "我认。", "--concede", "B", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                "--text", "改了，我不认。", "--score", "A:1,B:2", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertNotIn("result", d)
        self.assertEqual(d["status"], "running")

    def test_bad_rubric_format_is_rejected(self):
        r = run("init", "--spec", os.path.join(FIX, "spec.json"), "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "正文。", "--rubric", "A:9,9")
        self.assertNotEqual(r.returncode, 0, "评分项格式不对必须拒绝")
        self.assertIn("四项", r.stderr)

    def _add_silent_scorer(self):
        p = os.path.join(self.dir, "arena.json")
        d = json.loads(_read(p))
        d["roles"].append({"id": "C", "name": "鲁肃", "stance": "和", "voice": "温"})
        d["turn_order"].append("C")
        d["turns"][0]["score"] = {"A": 1, "B": 1, "C": 1}
        _dump(d, p, indent=2)
        return p

    def test_silent_scorer_midgame_is_quiet(self):
        """局中「有分无辞」是必然（一回合只一方发言），此时不该报——这是噪音。"""
        self._build()
        self._add_silent_scorer()
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("有计分但通篇无发言", r.stdout + r.stderr)

    def test_silent_scorer_at_finish_is_error(self):
        """终局还有人只有分没有辞：出档会残缺，必须报错。"""
        self._build()
        p = self._add_silent_scorer()
        d = json.loads(_read(p))
        d["status"] = "finished"
        d["rounds_total"] = 10
        _dump(d, p, indent=2)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("有计分但通篇无发言", r.stderr)

    def test_camp_mode_roundtrip(self):
        """阵营局：建局、三营各发言一次、出阵营表。"""
        g = os.path.join(self.tmp, "camp")
        sp = os.path.join(self.tmp, "camp.json")
        _dump({
            "title": "三方争天下", "mode": "camp", "ruleset": "historical",
            "rounds_total": 3, "turn_order": ["A", "B", "C"],
            "camp": {"曹魏": ["A"], "蜀汉": ["B"], "东吴": ["C"]},
            "roles": [{"id": "A", "name": "曹魏", "stance": "奉天子", "voice": "峻"},
                      {"id": "B", "name": "蜀汉", "stance": "汉贼不两立", "voice": "静"},
                      {"id": "C", "name": "东吴", "stance": "据江东", "voice": "锐"}],
            "scoring": {"kind": "rubric3", "per_round_total": 3},
        }, sp)
        self.assertEqual(run("init", "--spec", sp, "--dir", g).returncode, 0)
        for i, (spk, sc) in enumerate(
                [("A", "A:2,B:1,C:0"), ("B", "A:1,B:2,C:0"), ("C", "A:0,B:1,C:2")], 1):
            tf = os.path.join(self.tmp, f"c{i}.txt")
            _write(tf, f"第{i}回合发言")
            r = run("turn", "--dir", g, "--round", str(i), "--speaker", spk,
                    "--text-file", tf, "--score", sc)
            self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", g)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("render", "--dir", g, "--html")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = _read(os.path.join(g, "论道实录.md"))
        self.assertIn("### 阵营", body)
        self.assertIn("蜀汉", body)

    def test_camp_must_cover_all_roles(self):
        sp = os.path.join(self.tmp, "bad.json")
        _dump({
            "title": "坏阵营", "mode": "camp", "rounds_total": 1,
            "camp": {"魏": ["A"], "蜀": ["C"]},
            "roles": [{"id": "A", "name": "甲"}, {"id": "B", "name": "乙"}, {"id": "C", "name": "丙"}],
        }, sp)
        r = run("init", "--spec", sp, "--dir", os.path.join(self.tmp, "x"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不重不漏", r.stderr)


class ConfigGuards(unittest.TestCase):
    """建局时的护栏：错配置要在开局就炸，不要打到一半才发现。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arena-cfg-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spec(self, **over):
        base = {
            "title": "测试局", "mode": "duel", "ruleset": "adversarial",
            "rounds_total": 3,
            "roles": [{"id": "A", "name": "甲", "stance": "x", "voice": "y"},
                      {"id": "B", "name": "乙", "stance": "x", "voice": "y"}],
            "turn_order": ["A", "B"],
        }
        base.update(over)
        p = os.path.join(self.tmp, "spec.json")
        _dump(base, p)
        return p

    def test_bad_mode(self):
        r = run("init", "--spec", self._spec(mode="debate"), "--dir",
                os.path.join(self.tmp, "g"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mode", r.stderr)

    def test_duplicate_roles(self):
        sp = self._spec(roles=[{"id": "A", "name": "甲"}, {"id": "A", "name": "乙"}])
        r = run("init", "--spec", sp, "--dir", os.path.join(self.tmp, "g"))
        self.assertNotEqual(r.returncode, 0)

    def test_no_force_does_not_overwrite(self):
        sp = self._spec()
        g = os.path.join(self.tmp, "g")
        self.assertEqual(run("init", "--spec", sp, "--dir", g).returncode, 0)
        r = run("init", "--spec", sp, "--dir", g)
        self.assertNotEqual(r.returncode, 0, "无 --force 不得覆盖已有对局")
        self.assertIn("已存在", r.stderr)


TPL = os.path.join(REPO, "templates", "spec.json")


class StrictGates(unittest.TestCase):
    """硬门：要害、四维、盲判、每回合一份账、终局裁决。

    这一组测的不是「能跑」，是「文档里写了必须，脚本就得真的拦」。
    每条都先把它撞红一次，再证明豁免口是显式的。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arena-gate-")
        self.dir = os.path.join(self.tmp, "game")
        r = run("init", "--spec", TPL, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _turn(self, rnd, spk, score="A:2,B:1", pivot="要害在此。", rubric=None, extra=()):
        args = ["turn", "--dir", self.dir, "--round", str(rnd), "--speaker", spk,
                "--text", f"第{rnd}回合正文。", "--score", score]
        if pivot:
            args += ["--pivot", pivot]
        if rubric:
            args += ["--rubric", rubric]
        args += list(extra)
        return run(*args)

    def test_turn_without_pivot_is_rejected(self):
        self.assertEqual(self._turn(1, "A", pivot=None).returncode, 0)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2, "缺要害必须拦，不能只提示")
        self.assertIn("未自报要害", r.stderr)

    def test_rubric4_turn_without_rubric_is_rejected(self):
        self.assertEqual(self._turn(1, "A").returncode, 0)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2)
        self.assertIn("没给四维", r.stderr)

    def test_allow_missing_downgrades_to_warning(self):
        self._turn(1, "A", pivot=None)
        r = run("check", "--dir", self.dir, "--partial", "--allow-missing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未自报要害", r.stdout)

    def test_legacy_archive_is_exempt(self):
        self._turn(1, "A", pivot=None)
        p = os.path.join(self.dir, "arena.json")
        d = json.loads(_read(p))
        d["legacy"] = True
        _dump(d, p, indent=2)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 0, "旧档不该拿新尺子量")

    def test_no_blind_judging_at_all_is_rejected(self):
        for i in range(1, 5):
            spk = "A" if i % 2 else "B"
            self.assertEqual(self._turn(i, spk, rubric="A:接2,据2,洽2,认1;B:接1,据1,洽2,认2").returncode, 0)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2)
        self.assertIn("盲判不足一半", r.stderr)

    def test_same_round_counted_twice_is_rejected(self):
        """两个人都记满 3 分在同一回合 —— 总分翻倍，必须拦。"""
        self.assertEqual(self._turn(1, "A", rubric="A:接2,据2,洽2,认1;B:接1,据1,洽2,认2").returncode, 0)
        self.assertEqual(self._turn(1, "B", rubric="A:接1,据1,洽2,认2;B:接2,据2,洽2,认1").returncode, 0)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2)
        self.assertIn("被重复记账", r.stderr)

    def test_finished_without_conclusion_does_not_declare_a_winner(self):
        for i in range(1, 3):
            spk = "A" if i % 2 else "B"
            sc = "A:3,B:0" if i == 1 else "A:0,B:3"
            self.assertEqual(self._turn(i, spk, score=sc, rubric="A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                                       extra=("--blind",)).returncode, 0)
        self.assertEqual(run("check", "--dir", self.dir, "--partial").returncode, 0)
        r = run("render", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("未填写", body)
        self.assertNotIn("本局占胜", body)
        self.assertNotIn("本局平手", body)

    def test_conclude_writes_the_verdict(self):
        for i in range(1, 3):
            spk = "A" if i % 2 else "B"
            self.assertEqual(self._turn(i, spk, rubric="A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                                       extra=("--blind",)).returncode, 0)
        vf = os.path.join(self.tmp, "verdict.txt")
        _write(vf, "两人争的不是一件事：一个争名分，一个争上游，故不判胜负。")
        r = run("conclude", "--dir", self.dir, "--text-file", vf)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(run("render", "--dir", self.dir).returncode, 0)
        body = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("争的不是一件事", body)
        self.assertNotIn("未填写", body)

    def test_empty_conclusion_is_rejected(self):
        vf = os.path.join(self.tmp, "empty.txt")
        _write(vf, "   \n")
        r = run("conclude", "--dir", self.dir, "--text-file", vf)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不能留白", r.stderr)

    def test_roster_shows_mandate(self):
        run("render", "--dir", self.dir)
        body = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("名分", body)
        self.assertIn("参知政事", body)



class ReviewFixes(unittest.TestCase):
    """独立复评提出的四条硬伤，逐条钉住。

    这些不是「新功能」，是「文档说了、代码没做」——改完之后必须有测试替它守着。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arena-rv-")
        self.dir = os.path.join(self.tmp, "game")
        r = run("init", "--spec", TPL, "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concede_turn_needs_neither_pivot_nor_rubric(self):
        """自然认输：只说「我认」，不该被要求报靶子和四维——他已经没有靶子了。"""
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "王安石论青苗。", "--score", "A:2,B:1",
                "--rubric", "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                "--pivot", "若州县无抑配，我认。", "--blind")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                "--text", "差役未减，是我算错。这一处我认。", "--score", "A:3,B:0",
                "--concede", "B")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, "认输即止的局必须能直接出档：" + r.stderr)
        body = _read(os.path.join(self.dir, "arena.json"))
        self.assertIn('"concede": "B"', body, "认输要落盘，否则豁免条件永远不成立")

    def test_duel_round_cannot_be_recorded_twice(self):
        """duel 一回合只有一方发言；记两条就是同一回合两份账。"""
        for spk in ("A", "B"):
            r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", spk,
                    "--text", "同一回合的另一条。", "--score", "A:1,B:1",
                    "--rubric", "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                    "--pivot", "要害。", "--blind")
            self.assertEqual(r.returncode, 0, r.stderr)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2)
        self.assertIn("duel 一回合只许一条", r.stderr)

    def test_bad_turn_order_is_caught_at_init(self):
        """turn_order 漏了某个角色：建局时就该拦，不要等到记第一条才抛 ValueError。"""
        sp = os.path.join(self.tmp, "bad.json")
        d = json.loads(_read(TPL))
        d["turn_order"] = ["A"]
        _dump(d, sp)
        r = run("init", "--spec", sp, "--dir", os.path.join(self.tmp, "bad"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("turn_order", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_cannot_keep_recording_after_the_match_ended(self):
        """认输封盘之后还能往账上记，属账本污染——必须拦。"""
        self.assertEqual(run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                             "--text", "开篇。", "--score", "A:2,B:1",
                             "--rubric", "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                             "--pivot", "要害。", "--blind").returncode, 0)
        self.assertEqual(run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                             "--text", "我认。", "--score", "A:3,B:0",
                             "--concede", "B").returncode, 0)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "终局之后又记一条。", "--score", "A:3,B:0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("已在第 2 回合终局", r.stderr)

    def test_ledger_round_beyond_schedule_is_caught_by_check(self):
        """手改账本塞一个赛程外的回合：check 也得拦，不能只看写入路径。"""
        p = os.path.join(self.dir, "arena.json")
        d = json.loads(_read(p))
        d["turns"].append({"round": 99, "speaker": "A", "text": "越界回合",
                           "score": {"A": 1, "B": 0}, "verdict": "", "note": "",
                           "pivot": "", "rubric": {}, "blind": False,
                           "concede": "", "ko": "", "at": "2026-01-01T00:00:00+08:00"})
        _dump(d, p, indent=2)
        r = run("check", "--dir", self.dir, "--partial")
        self.assertEqual(r.returncode, 2)
        self.assertIn("超出赛程", r.stderr)

    def test_force_cannot_record_rounds_after_the_match_ended(self):
        """--force 只用于重记终局那一回合，不能当成「终局之后继续记」的后门。

        复评抓到：R2 认输封盘后 `turn --round 3 --force` 被接受，result 仍停在 R2、
        status 仍 finished、check 仍 0，出档时第 3 回合正文排在了终局横幅之后。
        """
        self.assertEqual(run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                             "--text", "开篇。", "--score", "A:2,B:1",
                             "--rubric", "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2",
                             "--pivot", "要害。", "--blind").returncode, 0)
        self.assertEqual(run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                             "--text", "我认。", "--score", "A:3,B:0",
                             "--concede", "B").returncode, 0)
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "用 force 绕过封盘。", "--score", "A:3,B:0", "--force")
        self.assertNotEqual(r.returncode, 0, "--force 不该放行终局之后的回合")
        self.assertIn("只能重记终局那一回合", r.stderr)
        # 终局之前的回合也一样：改了更早的回合会把 result 清空，而终局那条还挂在账上。
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "回头改第一回合。", "--score", "A:2,B:1", "--force")
        self.assertNotEqual(r.returncode, 0, "--force 也不该绕过终局去改更早的回合")
        body = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertIsNotNone(body.get("result"), "被拒的 force 不得动到终局")
        # 反过来：用 --force 重记终局那一回合本身仍然允许，并且旧终局作废。
        r = run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
                "--text", "我不认了，重新打。", "--score", "A:1,B:2", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertIsNone(body.get("result"), "重记终局回合后旧终局必须作废")
        self.assertEqual(body["status"], "running")

    def test_multi_speaker_round_is_not_warned_per_turn(self):
        """camp/roundtable 一回合多人各记一分，按「整回合 3 分」去数每条切片是误报。"""
        g = os.path.join(self.tmp, "rt")
        sp = os.path.join(self.tmp, "rt.json")
        _dump({
            "title": "圆桌", "mode": "roundtable", "ruleset": "truthseeking",
            "rounds_total": 3, "turn_order": ["A", "B"],
            "roles": [{"id": "A", "name": "甲", "stance": "主战", "voice": "峻"},
                      {"id": "B", "name": "乙", "stance": "主守", "voice": "静"}],
            "scoring": {"kind": "rubric3", "per_round_total": 3},
        }, sp)
        self.assertEqual(run("init", "--spec", sp, "--dir", g).returncode, 0)
        for spk, sc in (("A", "A:1,B:0"), ("B", "A:0,B:1")):
            r = run("turn", "--dir", g, "--round", "1", "--speaker", spk,
                    "--text", "同回合的一小份。", "--score", sc)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("本回合分值合计", r.stderr,
                             "多角色局不该按单条切片去核对每回合总分")
        # check 端也不能重复报同一件事——只修写入端、不改校验端，等于没修。
        r = run("check", "--dir", g, "--partial")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("分值合计", r.stderr, "check 端也不该按单条切片核每回合总额")

    def test_camp_conclusion_is_printed_once(self):
        g = os.path.join(self.tmp, "camp")
        sp = os.path.join(self.tmp, "camp.json")
        _dump({
            "title": "三方争天下", "mode": "camp", "ruleset": "historical",
            "rounds_total": 3, "turn_order": ["A", "B", "C"],
            "camp": {"曹魏": ["A"], "蜀汉": ["B"], "东吴": ["C"]},
            "roles": [{"id": "A", "name": "曹魏", "stance": "奉天子", "voice": "峻"},
                      {"id": "B", "name": "蜀汉", "stance": "汉贼不两立", "voice": "静"},
                      {"id": "C", "name": "东吴", "stance": "据江东", "voice": "锐"}],
            "scoring": {"kind": "rubric3", "per_round_total": 3},
        }, sp)
        self.assertEqual(run("init", "--spec", sp, "--dir", g).returncode, 0)
        for i, (spk, sc) in enumerate(
                [("A", "A:2,B:1,C:0"), ("B", "A:1,B:2,C:0"), ("C", "A:0,B:1,C:2")], 1):
            self.assertEqual(run("turn", "--dir", g, "--round", str(i), "--speaker", spk,
                                 "--text", f"第{i}回合", "--score", sc).returncode, 0)
        vf = os.path.join(self.tmp, "v.txt")
        _write(vf, "三营相持，魏得地，蜀得名，吴得利。")
        self.assertEqual(run("conclude", "--dir", g, "--text-file", vf).returncode, 0)
        self.assertEqual(run("render", "--dir", g).returncode, 0)
        body = _read(os.path.join(g, "论道实录.md"))
        self.assertEqual(body.count("三营相持"), 1, "裁决在 md 里只该出现一次")
        self.assertEqual(run("render", "--dir", g, "--html").returncode, 0)
        html = _read(os.path.join(g, "论道实录.html"))
        self.assertEqual(html.count("三营相持"), 1, "裁决在 html 里也只该出现一次")


class V11BlindEvidence(unittest.TestCase):
    """v1.1.0：盲判工具化（brief）+ 证据标签层（--evidence / KO 证据门）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arena-v11-")
        self.dir = os.path.join(self.tmp, "game")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self):
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        for i, (spk, sc) in enumerate([("A", "A:2,B:1"), ("B", "A:1,B:2")], 1):
            r = run("turn", "--dir", self.dir, "--round", str(i), "--speaker", spk,
                    "--text", f"第{i}回合，署名 {spk} 的正文。", "--score", sc,
                    "--pivot", f"我的要害{i}。", "--evidence", "verified")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_brief_hides_real_names_and_verdicts(self):
        self._build()
        r = run("brief", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("席位 A", r.stdout)
        self.assertIn("席位 B", r.stdout)
        # 真名（周瑜/诸葛亮，fixture 里 A/B 的 name）与要害都不该出现在盲读视图
        body = json.loads(_read(os.path.join(self.dir, "arena.json")))
        real_names = {role["name"] for role in body["roles"]}
        for nm in real_names:
            self.assertNotIn(nm, r.stdout, f"盲读视图漏出了真名 {nm}")
        self.assertNotIn("我的要害", r.stdout, "自报要害会泄底，不该出现在盲读视图")

    def test_brief_respects_round_filter_and_out(self):
        self._build()
        out = os.path.join(self.tmp, "brief.txt")
        r = run("brief", "--dir", self.dir, "--round", "2", "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = _read(out)
        self.assertIn("第 2 回合", body)
        self.assertNotIn("第 1 回合", body)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "brief.txt")))

    def test_evidence_recorded_and_rendered(self):
        self._build()
        body = json.loads(_read(os.path.join(self.dir, "arena.json")))
        self.assertEqual(body["turns"][0]["evidence"], "verified")
        self.assertEqual(run("render", "--dir", self.dir).returncode, 0)
        md = _read(os.path.join(self.dir, "论道实录.md"))
        self.assertIn("[已核]", md)
        self.assertEqual(run("render", "--dir", self.dir, "--html").returncode, 0)
        self.assertIn("已核", _read(os.path.join(self.dir, "论道实录.html")))

    def test_bad_evidence_rejected(self):
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "正文。", "--evidence", "胡编")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--evidence", r.stderr)

    def test_ko_without_evidence_strict_blocks_default_warns(self):
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
            "--text", "先手。", "--score", "A:2,B:1", "--pivot", "要害。")
        run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
            "--text", "接招。", "--score", "A:1,B:2", "--pivot", "要害。")
        r = run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
                "--text", "击穿。", "--score", "A:3,B:0", "--pivot", "要害。", "--ko", "B")
        self.assertEqual(r.returncode, 0, r.stderr)
        # 默认只提示，不拦
        r = run("check", "--dir", self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("没标证据等级", r.stdout + r.stderr)
        # 显式严格门才拦
        r = run("check", "--dir", self.dir, "--strict-evidence")
        self.assertEqual(r.returncode, 2)
        self.assertIn("没标证据等级", r.stderr)

    def test_ko_on_speculative_evidence_strict_blocks(self):
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
            "--text", "先手。", "--score", "A:2,B:1", "--pivot", "要害。")
        run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
            "--text", "接招。", "--score", "A:1,B:2", "--pivot", "要害。")
        run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
            "--text", "击穿。", "--score", "A:3,B:0", "--pivot", "要害。",
            "--ko", "B", "--evidence", "speculative")
        r = run("check", "--dir", self.dir, "--strict-evidence")
        self.assertEqual(r.returncode, 2)
        self.assertIn("存疑", r.stderr)

    def test_ko_on_verified_evidence_passes_strict(self):
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
            "--text", "先手。", "--score", "A:2,B:1", "--pivot", "要害。",
            "--evidence", "verified")
        run("turn", "--dir", self.dir, "--round", "2", "--speaker", "B",
            "--text", "接招。", "--score", "A:1,B:2", "--pivot", "要害。")
        run("turn", "--dir", self.dir, "--round", "3", "--speaker", "A",
            "--text", "击穿。", "--score", "A:3,B:0", "--pivot", "要害。",
            "--ko", "B", "--evidence", "verified")
        self.assertEqual(run("check", "--dir", self.dir, "--strict-evidence").returncode, 0)

    def _install_ledger(self, turns_spec, loser, end_round):
        """手工装一份账：turns_spec=[(round, speaker, ko, evidence, at), ...]。
        用于精确构造多 KO 场景——CLI 状态机下难以稳定复现。"""
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        path = os.path.join(self.dir, "arena.json")
        d = json.loads(_read(path))
        turns = []
        for rnd, spk, ko, ev, at in turns_spec:
            turns.append({"round": rnd, "speaker": spk, "text": "论辩正文。",
                          "score": {}, "verdict": "", "note": "", "pivot": "要害在此。",
                          "rubric": {}, "evidence": ev, "blind": True, "concede": "",
                          "ko": ko, "at": at})
        d["turns"] = turns
        d["result"] = {"round": end_round, "loser": loser, "winner": None,
                       "reason": "ko", "label": "要害被击穿", "note": ""}
        d["status"] = "finished"
        _dump(d, path)

    def test_brief_anonymizes_real_names_inside_body(self):
        """回归：正文里自称/提及真名时，brief 必须也换成席位牌，否则盲读被还原。"""
        self.assertEqual(run("init", "--spec", os.path.join(FIX, "spec.json"),
                             "--dir", self.dir).returncode, 0)
        r = run("turn", "--dir", self.dir, "--round", "1", "--speaker", "A",
                "--text", "周瑜亲率轻骑，与诸葛亮、张飞会于江夏；诸葛亮设伏。",
                "--score", "A:2,B:1", "--pivot", "要害。")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = run("brief", "--dir", self.dir)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("席位 A", out.stdout)
        self.assertNotIn("周瑜", out.stdout, "正文真名『周瑜』泄漏到盲读视图")
        self.assertNotIn("诸葛亮", out.stdout, "正文真名『诸葛亮』泄漏到盲读视图")

    def test_ko_gate_false_negative_multiple_ko(self):
        """回归（假阴性）：旁 KO 是 verified、生效终局 KO 却是 speculative 时，
        严格门必须拦——旧实现取 ko_turns[0] 会误放行。"""
        self._install_ledger(
            [(1, "A", "B", "verified", "2026-01-01T00:00:01+08:00"),
             (1, "B", "A", "speculative", "2026-01-01T00:00:02+08:00")],
            loser="A", end_round=1)
        r = run("check", "--dir", self.dir, "--strict-evidence")
        self.assertEqual(r.returncode, 2,
                         f"生效 KO 是编派却放行（假阴性）：{r.stdout}{r.stderr}")
        self.assertIn("存疑", r.stderr)

    def test_ko_gate_no_false_positive_wrong_round(self):
        """回归（假阳性）：旁 KO 是 speculative、生效终局 KO 是 verified 时，
        应放行，且不拿旁 KO 的证据张冠李戴报在终局回合上。"""
        self._install_ledger(
            [(1, "A", "B", "speculative", "2026-01-01T00:00:01+08:00"),
             (3, "B", "A", "verified", "2026-01-01T00:00:03+08:00")],
            loser="A", end_round=3)
        r = run("check", "--dir", self.dir, "--strict-evidence", "--partial")
        self.assertEqual(r.returncode, 0,
                         f"生效 KO 已核实却被误报（假阳性）：{r.stdout}{r.stderr}")
        self.assertNotIn("存疑", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)