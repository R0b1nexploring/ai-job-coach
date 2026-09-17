# DESIGN.md — Pricing Page

面向独立创作者的 AI 写作产品 · 定价页设计规范

参考基准（人工选定，不自动混合其他案例）：

- **D1 — Anthropic Claude** https://www.anthropic.com/pricing （克制、无渐变、边框强调、诚实披露）
- **A2 — Buttondown** https://buttondown.com/pricing （用量/规模决策控件、行式差异清单、诚实 FAQ）
- **C1 — Ghost** https://ghost.org/pricing/ （角色命名套餐、月/年切换、按主题分组对比表）

> 本文件只定义规则与结构，不定义最终文案。所有套餐名、功能项、价格、数字必须在实现时用真实产品事实替换；无真实来源的指标一律删除。

---

## Design Intent

**让一个独立写作者在三分钟内确信：这个工具不会替他写作，只会让他的文字更清楚；价格诚实、随时可退、没有隐藏条款。**

设计传递的感觉：安静、可信、克制、有编辑感。像一份排印考究的说明文档，而不是一张促销海报。

原因：目标用户是靠文字为生的人，他们对「被推销」和「被 AI 腔调冒犯」高度敏感。信任来自信息清晰与诚实，而不是视觉刺激。

---

## Design Principles

1. **Typography before decoration.** 层级只由字号、字重、颜色、留白四者承担；不靠卡片、阴影、背景块。
2. **One decision control.** 页面上只有一个主动控件：月付/年付切换。其余全部是静态信息。
3. **Space > Border > Background > Shadow.** 优先用留白划分，其次 1px 分隔线；背景色块仅用于表头或选中态；阴影默认不用。
4. **Say the real number.** 只写可核验的事实（真实价格、真实政策、真实用户原话）。无法核验的指标整段删除，不用「数千名用户」这类模糊量词。
5. **Remove before adding.** 任何不帮助「理解 / 决策 / 层级 / 识别」的元素，先删除，不美化。

---

## Color

限制为：3 个中性色 + 3 个有彩色（其中强调色出现次数受控）。

| Token | Hex | 角色 | 使用约束 |
|---|---|---|---|
| `canvas` | `#f5f6f3` | 页面底色（米白） | 全页背景 |
| `surface` | `#ffffff` | 卡片/表头面（纸白） | 仅套餐列、对比表头 |
| `text` | `#18211d` | 主文本（墨绿黑） | 标题、正文、价格数字 |
| `text-secondary` | `#5f6963` | 次级文本 | 描述、说明、对比表普通项 |
| `text-muted` | `#8a938d` | 弱文本 | 脚注、单位、占位 |
| `border` | `#e2e5df` | 细线 | 默认 1px 分隔线、卡片边框 |
| `border-strong` | `#cfd4cc` | 强线 | 表头下沿、对比表分组线 |
| `accent` | `#c76345` | 强调（陶土红） | **全页 ≤ 3 处**：推荐标记、年付节省金额、必要的状态提示 |
| `interactive` | `#2d6a4f` | 交互（鼠尾草绿） | 链接、focus ring、文本按钮 |

规则：

- 主 CTA 按钮为 **`text` 底 + `canvas` 字**（不是彩色按钮）。
- 次级按钮为 **1px `border-strong` 描边 + `text` 字**，透明底。
- 禁止在页面中新增任何第四种有彩色。
- 禁止渐变、glow、半透明玻璃、彩色阴影。

---

## Typography

字体栈（必须支持中文正文）：

```css
--font-display: "Newsreader", "Noto Serif SC", "Songti SC", Georgia, serif;
--font-sans: "Inter", "PingFang SC", "Noto Sans SC", system-ui, -apple-system, sans-serif;
```

- Latin 用 Newsreader / Inter，中文自动回退到 Noto Serif SC / PingFang SC。
- 衬线（`display`）**只用于 H1/H2 与价格数字**，正文与 UI 一律无衬线。全页衬线出现 ≤ 4 处。
- 所有价格数字使用 `font-variant-numeric: tabular-nums`。

| Style | Font | Size | Weight | Line height | Tracking |
|---|---|---|---|---|---|
| Display（定价页 H1） | display | 44px / 2.75rem | 500 | 1.08 | -0.01em |
| H1（区块大标题） | display | 34px / 2.125rem | 500 | 1.15 | -0.01em |
| H2（区块标题） | display | 26px / 1.625rem | 500 | 1.25 | 0 |
| H3（组件标题） | sans | 19px / 1.1875rem | 600 | 1.35 | 0 |
| Body | sans | 16px / 1rem | 400 | 1.7 | 0 |
| Small | sans | 14px / 0.875rem | 400 | 1.6 | 0 |
| Label（区块标签） | sans | 12px / 0.75rem | 600 | 1.2 | 0.08em（Latin 大写；中文 0.05em，不转换大小写） |
| Pricing number | display | 44px / 2.75rem | 500 | 1.0 | -0.01em |
| Price unit / cadence | sans | 14px | 400 | 1.4 | 0 |
| Button | sans | 15px / 0.9375rem | 500 | 1.0 | 0 |

规则：

- 正文最大行宽 **60–68 字符（约 620–680px）**。
- 段落间距 = 1 个 `16` spacing step；不使用首行缩进。
- Label 用「小号 + 字重 + 字间距」区分，不用彩色、不用图标。
- 禁止全大写中文；禁止 letter-spacing 用于中文正文。

---

## Spacing

统一 scale，禁止使用 scale 外的值：

`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 / 128`

| 用途 | Step |
|---|---|
| 图标与文字间距 | 8 |
| 标签与数值 | 8 |
| 列表行内边距（纵向） | 12 |
| 段落之间 | 16 |
| 同组元素之间 | 24 |
| 组与组之间 | 32 |
| 子区块之间 | 48 |
| 区块之间 | 64 |
| 大区块之间 | 96 |
| 页面上下留白 | 128（桌面） |

规则：

- 列表行高统一 **44–48px**（内容 + 12px 上下 padding），保证可扫读列对齐。
- 不允许「差不多」的间距；出现新需求时优先复用 scale。

---

## Layout

| 项 | 值 |
|---|---|
| 页面最大宽度 | 1200px |
| 阅读区内容宽度（Hero / FAQ / 信任区） | 720px |
| 定价与对比区宽度 | 1080px |
| 栅格 | 桌面 12 列，gutter 24px |
| 套餐列 | ≥1024px 三列等宽；<1024px 单列堆叠，间距 24px |
| 对比表 | 桌面表格；<768px 折叠为按套餐分组的纵向列表，不横向滚动 |
| 区块间距 | 桌面 96px / 移动 64px |
| Breakpoints | sm 640 / md 768 / lg 1024 / xl 1280 |

页面信息顺序（结构即决策路径）：

1. **Navigation** — 极简：字标 + 定价 + 登录。不做多级菜单。
2. **Pricing header** — H1 一句话说清「这是什么、为谁」；紧接着月付/年付切换。
3. **Pricing options** — 3 档，角色命名，推荐项仅靠边框与 accent 标记区分。
4. **What every plan includes** — 共享能力清单，只出现一次。
5. **Difference list / comparison** — 按主题分组，默认只展开 1 组。
6. **Trust statement** — 一条真实陈述或真实政策（随时取消 / 不自动续费 / 数据归属）。
7. **FAQ** — 异议处理，按 2–3 类分组。
8. **Footer** — 极简。

规则：

- 首屏必须同时可见：H1、一句说明、切换控件、至少一档价格。禁止需要滚动才看到价格。
- 页面只有一个主动控件（月/年切换）。套餐选择通过 CTA 完成，不在页内做实时计算。
- 若产品确为用量计费，才允许增加 A2 式的「规模 → 价格」控件，且必须替换掉月/年切换（不同时存在两个控件）。

---

## Components

只定义以下组件。组件库里存在但本页不需要的一律不使用。

- **Navigation** — 字标（sans 600）+ 2 个文本链接 + 1 个次级按钮。高度 64px，底部 1px `border`。
- **Billing toggle** — 两段文本（月付 / 年付），选中项 `text` 色，未选中 `text-muted`；下方 `border-strong` 下划线随选中项移动（120ms）。年付旁用 `accent` 标注「省 X%」（≤ 6 字）。
- **Pricing option** — 竖列。包含：套餐名（H3）→ 一句 ≤12 字角色定位（Small, `text-secondary`）→ 价格数字 + 单位 → 一句计费口径 → CTA → 差异项列表。推荐项：1px `text` 边框 + 顶部 `accent` 小标签「最常选择」，其余用 1px `border`。无阴影、无放大、无背景填充。
- **Feature group / difference list** — 行式列表：左「名称」，右「数值或状态」，行间 1px `border`。数值列右对齐并使用 tabular-nums。
- **Comparison table** — 表头 `surface` 底 + 1px `border-strong` 下沿；分组名用 Label 样式；分组默认折叠，展开动画 160ms；每行高 ≥40px。
- **CTA** — 全站文案统一为一个动词短语（如「开始写作」）。主/次两种，见 Color。焦点态用 `interactive` 2px outline + 2px offset。
- **FAQ** — 原生 `details/summary` 或等效 disclosure。问题用 H3，回答用 Body，回答允许 2–4 句完整句子。禁止营销套话。
- **Trust statement** — 最多 4 条，每条 ≤18 字 + 一行说明，用分隔线而非卡片。
- **Footer** — 单行链接 + 版权。无社交图标墙。

明确不使用：Bento grid、Dashboard mockup、装饰性 Orb/Blob、logo 墙、评分组件、浮动客服气泡、Cookie 横幅式浮层。

---

## Radius / Border / Shadow

**Radius（4 档，禁止超出）**：`0 / 2 / 4 / 6`

- 输入框、按钮、标签：4px
- 套餐列、对比表容器：6px
- 分隔线、表头：0
- **禁止 `rounded-2xl` 及更大圆角；禁止全站统一同一圆角。**

**Border**

- 默认：1px `#e2e5df`
- 强调：1px `#18211d`（推荐套餐）
- 分组：1px `#cfd4cc`
- 不使用 >1px 的边框。

**Shadow**

- 默认 **不使用阴影**。`shadow-lift` 在本页禁用。
- 唯一例外：移动端底部吸底 CTA 条，可使用 1px 上边框替代阴影。

---

## Motion

只允许以下用途，时长 100–160ms，`ease-out`：

| 用途 | 时长 |
|---|---|
| Billing toggle 数值切换 | 120ms |
| FAQ / 对比表分组展开 | 160ms |
| Hover / focus 反馈 | 100ms |
| 下划线随选中项移动 | 120ms |

- 禁止：入场动画、滚动 reveal、全模块统一 fade-in、视差、装饰性位移、脉冲、发光。
- 必须实现 `prefers-reduced-motion: reduce`：所有过渡降为 0ms，仅保留状态切换。

---

## 明确禁止项

- 蓝紫 AI 渐变、Neon、Glow、Glassmorphism
- 巨大圆角、无意义 Card、Bento Grid 滥用、Floating UI
- 装饰性 Orb / Blob、背景特效、多余装饰
- 过度阴影、无意义图标、无功能动效
- 所有模块统一 Fade-in
- 模板化 SaaS Hero（居中标题 + 胶囊 Badge + 双按钮）
- 假客户 Logo、假评价、假用户数量、假增长数据
- 模板化文案：Unlock the power of AI / Supercharge your workflow / Write 10x faster / The future of… / Revolutionary / Next-generation / Seamless / Effortless
- 中文化后对应的空话：「赋能」「颠覆」「重新定义」「让创作效率提升 10 倍」「开启智能写作新时代」

---

## Reference Review（实现后逐项对照）

- Typography 是否偏离（衬线是否滥用、行宽是否超 680px）
- Layout density 是否偏离（是否开始堆卡片）
- Spacing 是否过密（是否出现 scale 外的值）
- Card 是否变多（套餐列之外是否又新增卡片）
- Color 是否被擅自增加（是否出现第四种有彩色）
- Radius 是否越来越大（是否超过 6px）
- Shadow 是否没有必要（是否出现 `shadow-lift`）
- Motion 是否没有功能（是否有入场/装饰动画）
- Copy 是否退回 SaaS 模板文案
- 是否出现了虚构 Social Proof

## AI-Slop Audit（发布前检查）

- 所有内容是否都被装进 Card
- 圆角是否完全一样
- Section 结构是否高度重复
- 是否机械重复 Label + Heading + Paragraph
- 是否有蓝紫 Gradient / Glow / Bento Grid / Floating UI
- 是否有无意义 Badge / Icon / Dashboard Mockup
- 是否过度规则、对称、均匀
- 是否有模板化 SaaS Copy 或虚构 Social Proof
- 是否有装饰性动画

> 若某元素不帮助「信息理解 / 操作 / 层级 / 品牌识别」，**优先删除，不要继续美化**。
