# 论道台 · Lundao Arena

> 一句话开一场跨时空的对攻：有名分的对手、逐回合攻防、裁判当场计分、输的人当场认输，
> 最后留下能当文章读的实录。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-41%20passed-brightgreen.svg)](tests/test_arena.py)
[![Python 3](https://img.shields.io/badge/python-3.x-blue.svg)](scripts/arena.py)

仓库地址：<https://github.com/guyue55/lundao-arena>

给 AI agent 用的技能（DSH skill）。装好后，你只需要说一句：

```
让周瑜和诸葛亮争：谁更有资格统一天下，十回合
```

剩下的——双方立场、名分、口吻、规则集、裁判尺、记账、出档——它自己摆好，然后**当场开打**。

---

## 它和别的「多智能体辩论」不一样

同类技能分两派：一派是**委员会**（开完会给一份决策建议书），一派是**赛事化**（真打、真判、真出档）。
论道台在第二派里，位置是「一句话开局、裁判逐回合计分」的那一格。

| 项目 | 做成什么 | 与论道台的关系 |
|---|---|---|
| [LeSingh1/debate-skill](https://github.com/LeSingh1/debate-skill) | 5 角色 3 轮 → Council Synthesizer 出可执行交付物 | 委员会派。学了它的「无声 moderator」与交付物导向 |
| [abdur-emon/claude-multi-agent-debate](https://github.com/abdur-emon/claude-multi-agent-debate) | 20 agent 全并行、twin merge、steelman claim card、ranked vote | 最值得学的一份。**自报要害**与「承认可以，投降不行」取自它 |
| [ngmeyer/council-review](https://github.com/ngmeyer/skills/blob/main/skills/productivity/council-review/SKILL.md) | 5 顾问 + 匿名互评 + 魔鬼代言人打共识 + 先评分项后总评 | 委员会派。**盲判**与**先分项后总评**来自它 |
| [csark0812/toolbox council](https://github.com/csark0812/toolbox/blob/main/council/SKILL.md) | persona 卡带 Falsifier/Boundary，「多数票不是证据」 | 给了「什么能驳倒这个角色」的设计语言 |
| [ClawHub debate-arena](https://clawhub.ai/updatedb/skills/debate-arena) | **最接近的同类**：正/反/裁判/主持/投票人，五标准轮，真人投票（2-1、3-0），归档到本地 | 它要 `init`+`add`+`set` 三条命令才开局，判定靠投票；论道台是三样都不要 |
| [ClawHub chinese-moa-debate](https://clawhub.ai/fitler-lin/skills/chinese-moa-debate) | 牛津联盟制：正方/反方/魔鬼辩手/主席/完整性裁判，最低通过分 7.5，达标提前停 | 学它的**提前终止**与「魔鬼辩手只打占上风的一方」 |
| [ClawHub roundtable-skills](https://clawhub.ai/lmf112358/skills/roundtable-skills) | 多 agent 对抗性思考，出共识／分歧／行动指南 | 委员会派 |
| [ClawHub multi-viewpoint-debates](https://clawhub.ai/latentfreedom/skills/multi-viewpoint-debates) | 隔离 subagent 扮演世界观，出综述 | 委员会派 |
| [salismt/multi-agent-debate](https://github.com/salismt/multi-agent-debate) | 对立 persona + 证据引用裁判 + chain-of-verification | 委员会派 |
| [zhjai/agent-arena](https://github.com/zhjai/agent-arena) | 「Evidence-first multi-agent debate」：独立提案→交叉评审→修订→综合，`使用 arena 讨论 X` 触发，`继续` 断点续跑 | **最强直接竞品**。它的 run state（armed/in_progress/complete/abandoned/superseded）比论道台的 running/finished 细，值得抄。注意：它也做 `blind judge scores` 与 rubric 判分、并会点名胜负（v1.1.0 核验更正，旧版曾误写「不收比分、不判胜负」）；两者的差别在论道台是逐回合赛事化计分 + 认输/击穿终局，它是一次性评审出综合稿 |
| [ClawHub xiaoba-dev/debate](https://clawhub.ai/xiaoba-dev/skills/debate) | cross-vendor adversarial review：把 brief 原样发给**别家厂商**的模型互评 | 它明说「一个模型演多个专家不算这个 skill」——**这一句戳中论道台最该讲清楚的边界** |
| [ClawHub moot-court-ai](https://clawhub.ai/baobaodawang-creater/skills/moot-court-ai) | 书记员/原告/被告/法官四角色模拟法庭，用确定性 Lobster workflow 控阶段 | 学它的「阶段推进不交给模型」；论道台的阶段推进在 CLI 里，同理 |
| [wan-huiyan/agent-review-panel](https://github.com/wan-huiyan/agent-review-panel) | 多评审面板 + `docs/demo.tape`、`record-demo.sh` 把演示录制脚本一起入库 | 手艺范本：showcase 要能一键复现，不是截一张图 |

**不采纳的一条**：council-review 引 M3MADBench 说「协作式辩论在决策质量上优于对抗式」——
论道优化的不是决策质量，是**对抗本身的质量与可看性**，所以对抗内核不动，只借它的裁判机制。

论道台赌的是另一件事：**这场对攻本身值得看。**

所以它保留了三样别人不要的东西：

1. **名分**。角色凭什么有资格说这话——官爵、学派、亲历、著作。没有名分的角色撑不过三个回合，
   会退化成无差别的观点输出。
2. **计分与认输**。每回合 3 分，判词必须引对方原文；被击穿要害必须当场认输，不许含糊过去。
   输赢是这局的产物，不是要回避的东西。
3. **实录**。`论道实录.md` / `.html`——衬线排版、回合卡片、判决块、终局表。是一份能直接发出去的稿子，
   不是一份会议纪要。

---

## 机制（这是它真正的分量）

### 三分制，先判交锋再判得分

一回合 3 分：`2:1` 分胜负、`2:0` 明显压制、`1:1` 势均。**1:1 是合法结果**——一场全是 1:1 的局
说明命题不可证伪，这是对局的结论，不是裁判的失败。

判词不许写「A 更有说服力」。合格判词长这样：

> A 答了「户存而口缩是丁口隐匿」这一处，B 的「人众」就没有落点了。

引不出原文，说明裁判没读懂，不许判。

### 先分项，后总评

每回合不先判「谁赢」，先按四维各打 0–2：**接招**（有没有正面回应对方要害）、
**新据**（有没有带来对方没有的东西）、**自洽**（前后有没有打架）、**认账**（该认的认了没有）。
四维打完，才合成 `2:1` / `2:0` / `1:1`。

理由很硬：先有胜负直觉再倒填理由，是 coherence bias（Kahneman/Lovallo/Sibony 2019）——
你一定会填得出来，而且填得很像回事。工具把四维与比分一起记账，**分项更占优的一方若不是多分的那一方，
`check` 就报警**。

### 自报要害

每条发言末尾必须有一行 `要害：<一句话>`——「对方驳倒这一句，我就得认输」。

它同时解决三件事：逼角色收口（不给靶子的发言可以一直含糊）、防裁判打稻草人（要害之外的角色可以不接）、
让认输可核（「被驳倒」退化成「那一句被驳倒没有」）。

### 三种裁判偏置，各有对策

LLM 当裁判有三个被反复测出来的病（[Justice or Prejudice?, ICLR 2025](https://arxiv.org/abs/2410.02736)；
MT-Bench 亦记录同类现象）：

| 偏置 | 表现 | 对策 |
|---|---|---|
| 位置偏置 | 先发言的天然占「立论」的便宜 | 出现**连续三回合**同一方赢，必须换序复核 |
| 冗长偏置 | 写得长就分高 | 发言按 250–500 字记，超长不加分；砍到等长再读一遍 |
| 自我增强偏置 | 偏袒与自己文风相近的一方 | **盲判**（至少一半回合，逐回合加 `--blind`）：先读无署名发言判分，判完再归属 |

盲判不是可选项，而且**没有「默认开启」**——CLI 不替你决定，匿名互评的实验一致显示，评委只要看见角色名就会偏袒——
这一条在 `council-review` 里是硬规矩，这里照搬。

注意 `--blind` 只是账本上的标记，**它不会自动遮蔽署名**。要真正盲读，用 `brief` 导出匿名视图：

```bash
python3 scripts/arena.py brief --dir ./juban [--round N] [--out ./盲读.txt]
```

它抹掉真名、自报要害、比分和含真名的标题，只留「席位 A/B」和正文。正确顺序是
`brief` 导出 → 读匿名稿判分 → 回账本 `turn --blind` 记分归属。
这不是多余的谨慎：EMNLP 2026 Findings 的实验显示，自我增强偏置在盲评下会消失——
反过来说明只要看得见署名，偏置就在。**文献把盲判从「好习惯」升级成了「有效手段」，工具则负责让它真的盲。**

### 终局：认输或击穿即止，不必打满

`rounds_total` 是赛程上限，不是必须交满的作业。一局三种结束法：

- **打满**：按总分与胜场裁决。
- **认输**：一方在自己报的要害上被驳倒，当场认下（`--concede`），对手胜，余下回合不打。
- **击穿**：裁判判定本回合击穿了对方报过的那一句（`--ko`），发言者胜。

门槛比「他说得有道理」高得多：认下对方没打到的点、认一半再给替代解释——都只记认账分，不结局。
判了击穿而被打的人从没报过要害，`check` 会直接点出「打的是稻草人」。

十回合互相恭维的局，不如三回合被驳倒的局值钱。

### 事实纪律

`historical` / `truthseeking` 局：凡「某某说过」必须指到出处，指不到本回合扣到 0 分，并在实录里
标注「此处引文有误」。这条最容易被跳过，也最影响可信度——实录里一旦掺进编造的史实，整场就废了。

光靠裁判「记得核」仍会漏。所以每条发言可挂一个证据等级，出档时亮牌（借鉴 `xiaoba-dev/debate`）：

| 标签 | 含义 | 判分 |
|---|---|---|
| `[已核] verified` | 指得到出处 / 可运行命令 / 可引用数据 | 全额采信 |
| `[推理] reasoned` | 从已核事实推出，链条可复核 | 采信，标出推理链 |
| `[待核] to-verify` | 声称有据但当场没核 | 打折采信，注明待核 |
| `[存疑] speculative` | 无出处、或已被对方拆穿的硬圆 | 不采信，立论方扣分 |

写法 `turn ... --evidence verified`（也认中文「已核/推理/待核/存疑」）。
**KO 证据门**：击穿是终局手段，宣布击穿那一发若没标证据、或标「存疑/待核」，`check` 默认提示，
加 `--strict-evidence` 升为硬错误。这把「击穿不是打出来的，是立出来的」再收紧一步——
天道局方士把「盗跖寿终」编成「无一夕贴席」被当场拆穿，正是这条门要拦的东西。

### 终局不比总分，比「他们是否在争同一个问题」

实测案例（周瑜 vs 诸葛亮，十回合 15:15，胜负严格交替）：两人从未争同一件事——一个争**名分**
（蜀之为蜀在一个「汉」字），一个争**位置**（取蜀、结马超、据襄阳，要江东不站在人下游）。
名分不承认上游，上游不承认名分，所以十回合打不出胜负。共同点是**人亡政息**：一个死在巴丘三十六岁，
图随人废；一个死在五丈原，二十九年而蜀亡。两人都没能把「应该」变成「能够」。

这个结论比「谁赢了」有用，所以裁决里必须写这一层。

---

## 三种局制

| 局制 | 用于 | 打法 |
|---|---|---|
| `duel` | 两方互斥立场 | 一回合一方，攻防交替；每回合自报要害 |
| `roundtable` | 3–5 方圆桌 | 顺时针各发一次，或裁判点名互诘 |
| `camp` | 团队对团队、三方争天下 | 队内先议、队外出一人；可结盟、可背刺 |

圆桌必须**并行**发消息——串行会让后发言的人读到前面所有人的话，独立判断被抹平。
阵营局允许「盟约」与「背刺」：背刺当回合得 3 分、下一回合全队 0 分，且裁判必须在实录里写明。

---

## 快速开始

```bash
# 1. 装（clone 到 DSH 技能目录）
git clone https://github.com/guyue55/lundao-arena.git ~/.dsh/skills/lundao-arena
# 若目录已存在，也可直接拷贝：cp -r . ~/.dsh/skills/lundao-arena

# 2. 一句话开一场（对你的 agent 说）
#    让王安石和司马光辩一辩：熙宁变法当不当行
```

手动跑工具：

```bash
SK=~/.dsh/skills/lundao-arena
python3 "$SK/scripts/arena.py" init   --spec "$SK/templates/spec.json" --dir ./juban
printf '第一回合的发言正文。\n' > ./r1.txt        # 发言先落成文件
python3 "$SK/scripts/arena.py" turn   --dir ./juban --round 1 --speaker A \
        --text-file ./r1.txt --score "A:2,B:1" --verdict "A 打中 X，B 未接" \
        --rubric "A:接2,据2,洽2,认1;B:接1,据1,洽2,认2" \
        --pivot "若你能指出…，我认。" --evidence verified --blind
python3 "$SK/scripts/arena.py" brief  --dir ./juban --out ./盲读.txt     # 盲判：导出无署名稿，判完分再归属
python3 "$SK/scripts/arena.py" status --dir ./juban
python3 "$SK/scripts/arena.py" check  --dir ./juban
printf '两人争的不是一件事……\n' > ./verdict.txt                                    # 终局裁决
python3 "$SK/scripts/arena.py" conclude --dir ./juban --text-file ./verdict.txt
python3 "$SK/scripts/arena.py" render --dir ./juban --html                          # 最后再出档
```

产物：`juban/论道实录.md`、`juban/论道实录.html`、`juban/arena.json`（唯一真相源，可断点续跑）。

> `check` 会报「未打完的回合」——局里还没打到第 8 回合时这是对的，不是故障。
> 只想体检已有回合就加 `--partial`。

---

## 仓库结构

```
SKILL.md                 # 给 agent 的操作手册（路由与流程）
references/
  rosters.md             # 现成班底：历史/学派/学科/虚构/势力，拿来即用
  modes.md               # duel / roundtable / camp 三种局制怎么打
  judging.md             # 裁判尺与三种偏置的防法
scripts/arena.py         # 记账 / 体检 / 出档（纯标准库，无依赖）
templates/spec.json      # 建局模板
tests/                   # 验证门：41 项，含一场真实对局的回放
examples/zhouyu-zhuge/   # 真实产物：周瑜 vs 诸葛亮第 4–10 回合实录（截断样本，legacy 档）
```

`examples/zhouyu-zhuge/论道实录.html` 是真实产出的样子——不是设计稿。

---

## 验证状态

```
$ python3 tests/test_arena.py
Ran 48 tests — OK
```

四十八项里，最关键的仍不是「函数返回 True」，是**回放**：把一场真打过的七回合论道按真实打法
（一回合只有一方发言、双方同时计分）记进账，再出档，逐字比对正文有没有丢。这项曾经挂过——
最初的体检把「一回合只有一方发言」当成错误，那是把「论道」误当成「双方各交一份作业」。

覆盖的错法：重复记录、空发言、未知角色计分、缺回合、终局有分无辞、阵营不重不漏、
提前终局被误判成缺回合、认输记在对手回合、击穿打了稻草人、重记终局那一回合后旧终局不失效、
2:0 与 1:1 被误判成「分值合计不符」、四维评分与比分相反、自报要害缺失、坏配置被放行。

另有一组**硬门**测试：文档里写「必须」的，脚本必须真的拦——缺自报要害、`rubric4` 有分没四维、
盲判不足一半、同一回合重复记账，都 `exit 2`；豁免只有 `--legacy`、`--allow-missing`、`--partial`、
`--strict-evidence` 四个显式开关，且 `--partial` 只放行「缺回合」这一项。
v1.1.0 新增七项测盲判视图（`brief` 不泄真名/要害、round 过滤、out 落盘）与证据标签
（四档渲染、非法值被拒、KO 无证据/存疑时 `--strict-evidence` 拦、有据时放行）。
还有一条专测「不撒谎」：终局没写裁决时，实录只能说「未填写」，**不许**按总分替你宣布「本局占胜」。

---

## 已知边界

- 「命题不可证伪」的局（谁更伟大、谁更先进）打不出胜负，会全程 1:1。这是对的，但先说清楚。
- `camp` 局成本高：两营各三人 8 回合约 70 次 agent 往返。超过 40 次的局，先告知用户再开。
- 依赖宿主提供 `subagent` / `send_message` / `wait_agent`。没有这三个工具的环境，只能用它记账出档，
  角色得由宿主自己调度。
- **角色同源**：默认两个角色来自同一个模型、同一个 provider，是两次演绎，不是两个独立智能体。
  这不影响「论道」的观赏性，**但影响结论强度**——同一模型的两次人格化，共享同一套偏见，
  它们打出的分歧比真跨厂商对打要小。要更强的对抗，把 `roles` 换成不同 provider 的 subagent
  （见 [xiaoba-dev/debate](https://clawhub.ai/xiaoba-dev/skills/debate) 的做法），论道台这边的记账不受影响。
- `examples/zhouyu-zhuge/` 是**截断样本**（只收第 4–10 回合），标了 `legacy`，不拿新尺子量；
  它能证明渲染与出档链路，不能证明「从头跑到尾」——后者要靠真实开局，见回炉清单。

---

MIT. 玩得开心。