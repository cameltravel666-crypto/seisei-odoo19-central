# -*- coding: utf-8 -*-
"""
Central OCR Service - Managed by Odoo 19
Handles all OCR API calls, tracks usage per tenant, hides API details from tenants.
Version 2.0.2 - Add explicit JSON examples and critical constraints
"""

import os
import json
import base64
import logging
import time
import asyncio
import re
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Literal
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncpg

# Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
DATABASE_URL = os.getenv('OCR_DATABASE_URL', 'postgresql://ocr:ocr@localhost:5432/ocr_service')
SERVICE_KEY = os.getenv('OCR_SERVICE_KEY', '')
FREE_QUOTA_PER_MONTH = int(os.getenv('OCR_FREE_QUOTA', '30'))
PRICE_PER_IMAGE = float(os.getenv('OCR_PRICE_PER_IMAGE', '20'))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db_pool: Optional[asyncpg.Pool] = None


# ============== PROMPTS ==============

# UNIFIED PROMPT - Japanese receipts/invoices with configurable output depth
PROMPT_UNIFIED_JP = '''あなたは日本の領収書・請求書・レシートに特化した会計OCRエンジンです。
以下の指示と制約を必ず厳守してください。

【対象】
- 日本国内の領収書・請求書・簡易レシート
- 消費税制度（8% / 10% / 非課税）
- 適格請求書発行事業者登録番号（T + 13桁）

【最重要原則】
1. 数字は本文よりも「合計欄（小計・消費税・合計）」を最優先で読む
2. ⚠️ **税率別（8% / 10%）の金額は必ずレシート底部の摘要行から直接読み取る**
   - 「外税額 8%」「内消費税8%」「8%対象」等の行を最優先で探す
   - 商品明細から計算・推測せず、記載された税率別の数値をそのまま使用
   - 混合税率の場合も必ず r8_tax と r10_tax を個別に抽出
3. 不明な情報は推測せず null を返す
4. 金額整合性は必ず検証する（±2円誤差許容）
5. ⚠️ 複数の商品を1つにまとめない - 個別に抽出せよ

────────────────
Step 1: 基本情報（全モード必須）
────────────────

以下を必ず抽出せよ：

- vendor_name（店舗名または会社名）
- invoice_reg_no（T+13桁、存在しない場合 null）
- document_date（YYYY-MM-DD、推定可）
- tax_included_type（外税 / 内税 / 不明）
- payment_method（支払方法：現金 / クレジットカード / 電子マネー / 不明）
  → キーワード判定：「お預り」「お釣り」→ 現金、「カード」→ クレジットカード
- total_items（買上点数 / 商品点数、存在する場合のみ）

金額：
- gross_amount（合計金額）
- net_amount（税抜小計）
- tax_amount（消費税合計）

税率別（レシート底部の摘要行から直接読み取る）：
⚠️ 重要：以下の行を探し、記載された数値をそのまま使用（計算禁止）
- r8_tax : 「外税額 8%」「内消費税8%」「消費税 8%」行の金額
- r10_tax: 「外税額 10%」「内消費税10%」「消費税 10%」行の金額
- r8_gross : 「8%対象」「税率8%対象額」行の金額（あれば）
- r10_gross: 「10%対象」「税率10%対象額」行の金額（あれば）

混合税率の例：
  外税額　8%  ¥592  → r8_tax = 592
  外税額　10% ¥1    → r10_tax = 1

検証：
- net_amount + tax_amount ≒ gross_amount
- 不一致の場合は reason を記録

────────────────
Step 2: 明細行（全モード必須）
────────────────

⚠️ 重要：両モードとも明細行を可能な限り抽出せよ

【抽出ルール】
1. 領収書に記載された商品リストを1行ずつ読み取る
2. 以下の情報を各行から抽出：
   - name（商品名・サービス名）
   - quantity（数量、例：2個、3点）
   - unit_price（単価、計算可能な場合）
   - tax_rate（8% / 10% / 非課税 / null）
   - net_amount（税抜金額）
   - tax_amount（消費税額）
   - gross_amount（税込金額）

3. ⚠️ 複数商品を「仕入高」などに集約しない
4. 読み取れない明細も可能な限り name と gross_amount を記録

【税率判定ロジック】
優先順位：
a) 各商品に税率表示あり → その税率を使用
b) 領収書末尾に「外税 8%」「消費税 10%」等の表示あり
   → すべての商品にその税率を適用
c) 判定不能 → tax_rate = null

【モード別要件】
- output_level = "summary"：
  - 明細が多い場合（10行以上）、代表的な5〜10行を抽出
  - 小計は正確に記録

- output_level = "accounting"：
  - 全明細を必ず抽出（省略禁止）
  - 不明瞭でも name + gross_amount だけでも記録
  - 買上点数がある場合、抽出した明細数と一致を検証

────────────────
Step 3: 会計科目推定（accounting のみ）
────────────────

まず document_category を判定：
- purchase（仕入・購入）
- sale（売上）
- expense（経費）

判定基準：
- 「スーパー」「コンビニ」で食品購入 → purchase
- 「交通費」「タクシー」 → expense
- 「売上」「ご利用明細」 → sale

次に以下ルールで suggested_account を付与せよ：

【expense】
- 電車/バス/タクシー → 旅費交通費
- 消耗品/文房具 → 消耗品費
- 通信/携帯/電話 → 通信費
- 電気/ガス/水道 → 水道光熱費
- 広告/宣伝 → 広告宣伝費
- 家賃 → 地代家賃
- 未分類 → 雑費

【purchase】
- 食品/飲料/食材 → 仕入高
- 商品/原材料 → 仕入高
- 部品/材料 → 原材料費
- 外注/委託 → 外注費
- 機械/PC → 工具器具備品

【sale】
- 商品/サービス → 売上高
- 送料 → 売上高（送料）

各 suggested_account には confidence（0.0〜1.0）を付与せよ。

会計仕訳（journal_entry）を生成：
- 借方（debit）：
  - purchase → 仕入高 + 仮払消費税
  - expense → 経費科目 + 仮払消費税
  - sale → 現金/売掛金
- 貸方（credit）：
  - purchase/expense → 現金 / 買掛金 / 未払金（payment_method に基づく）
  - sale → 売上高 + 仮受消費税

例（purchase、現金払い）：
{
  "debit": [
    {"account": "仕入高", "amount": 4714},
    {"account": "仮払消費税", "amount": 377}
  ],
  "credit": [
    {"account": "現金", "amount": 5091}
  ]
}

────────────────
Step 4: 検証
────────────────

summary：
- 合計整合性のみ検証

accounting：
- 行合計 → 税率別 → 総合計 の三層検証
- 買上点数 vs 明細行数の一致検証
- 不一致は validation.mismatches に記載

⚠️⚠️⚠️ 絶対に守ること ⚠️⚠️⚠️
────────────────────────

1. 【CRITICAL】複数商品を1行に集約することは厳禁
   - 各商品は必ず独立した line_item として抽出
   - 「仕入高」「経費」「費用」などの会計科目を商品名（name）に使わない

2. 【CRITICAL】line_items の長さは total_items と一致させる
   - 領収書に「買上点数：19点」とあれば、19個の独立した line_item を返す
   - 不足する場合は validation.warnings に記録

3. 【CRITICAL】tax_rate は必ず推定して設定
   - 領収書末尾の「外税 8%」から全商品の tax_rate = 8 を設定
   - 0 や null を返さない

4. 【CRITICAL】payment_method は必ずキーワードから判定
   - 「お預り」「お釣り」があれば payment_method = "現金"
   - journal_entry の credit 側は「現金」にする

────────────────
❌ 間違った出力例
────────────────

以下は絶対に避けること：

{
  "line_items": [
    {"name": "仕入高/経費 (OCR: 業務スーパー)", "gross_amount": 4714, "tax_rate": 0},
    {"name": "仮払消費税 8%", "gross_amount": 377, "tax_rate": 0}
  ],
  "journal_entry": {
    "debit": [{"account": "仕入高", "amount": 5091}],
    "credit": [{"account": "未払金", "amount": 5091}]
  }
}

問題点：
- ❌ 商品を集約している（19個 → 2個）
- ❌ 「仕入高」「経費」を商品名に使っている
- ❌ tax_rate が 0 になっている
- ❌ 貸方が「未払金」になっている（現金払いなのに）
- ❌ 借方が分割されていない（仕入高 + 仮払消費税）

────────────────
✅ 正しい出力例
────────────────

{
  "vendor_name": "業務スーパー 上野広小路店",
  "invoice_reg_no": "T4-0200-0113-7967",
  "document_date": "2025-12-16",
  "tax_included_type": "外税",
  "payment_method": "現金",
  "total_items": 19,

  "gross_amount": 5091,
  "net_amount": 4714,
  "tax_amount": 377,

  "r8_gross": 5091,
  "r8_tax": 377,
  "r10_gross": null,
  "r10_tax": null,

  "line_items": [
    {
      "name": "一夜風えのき茸",
      "quantity": "1個",
      "unit_price": 270,
      "tax_rate": 8,
      "net_amount": 250,
      "tax_amount": 20,
      "gross_amount": 270
    },
    {
      "name": "フレッシュもやし",
      "quantity": "2個",
      "unit_price": 38,
      "tax_rate": 8,
      "net_amount": 70,
      "tax_amount": 6,
      "gross_amount": 76
    },
    {
      "name": "3食焼そば",
      "quantity": "4個",
      "unit_price": 48,
      "tax_rate": 8,
      "net_amount": 177,
      "tax_amount": 15,
      "gross_amount": 192
    },
    {
      "name": "からっと香ばしい油揚げ",
      "quantity": "2個",
      "unit_price": 55,
      "tax_rate": 8,
      "net_amount": 102,
      "tax_amount": 8,
      "gross_amount": 110
    },
    {
      "name": "濃厚豆乳 木綿",
      "quantity": "2個",
      "unit_price": 120,
      "tax_rate": 8,
      "net_amount": 222,
      "tax_amount": 18,
      "gross_amount": 240
    },
    {
      "name": "神戸物産 ほんじり焼き",
      "quantity": "6個",
      "unit_price": 297,
      "tax_rate": 8,
      "net_amount": 1648,
      "tax_amount": 132,
      "gross_amount": 1780
    },
    {
      "name": "フレンチフライ",
      "quantity": "1個",
      "unit_price": 298,
      "tax_rate": 8,
      "net_amount": 276,
      "tax_amount": 22,
      "gross_amount": 298
    },
    {
      "name": "鶏皮串（加熱済み・タレ無）",
      "quantity": "1個",
      "unit_price": 1750,
      "tax_rate": 8,
      "net_amount": 1620,
      "tax_amount": 130,
      "gross_amount": 1750
    }
    // ... 残り11個の商品（合計19個）
  ],

  "document_category": "purchase",
  "suggested_account": "仕入高",
  "confidence": 0.95,

  "journal_entry": {
    "debit": [
      {"account": "仕入高", "amount": 4714},
      {"account": "仮払消費税 8%", "amount": 377}
    ],
    "credit": [
      {"account": "現金", "amount": 5091}
    ]
  },

  "validation": {
    "line_items_count": 19,
    "total_items_match": true,
    "amount_balance": true,
    "tax_rate_consistent": true,
    "warnings": []
  }
}

重要ポイント：
- ✅ line_items に19個の独立した商品
- ✅ 各商品の tax_rate = 8（領収書の「外税 8%」から推定）
- ✅ payment_method = "現金"（「お預り」から判定）
- ✅ journal_entry の借方が分割（仕入高 + 仮払消費税）
- ✅ journal_entry の貸方が「現金」
- ✅ 商品名は実際の商品名（「仕入高」などではない）

【出力は必ず JSON のみ】'''

# Legacy prompts (deprecated, kept for reference)
PROMPT_FAST = '''日本のレシート/請求書から**レシート下部の合計欄**の数字を正確に抽出してJSON形式で返す:
{
  "vendor": "店名/会社名",
  "tax_id": "T+13桁 または null",
  "date": "YYYY-MM-DD または null",
  "gross": 合計(数値),
  "net": 小計(数値),
  "tax": 消費税合計(数値),
  "r8_gross": 8%対象額(数値/0),
  "r8_tax": 8%税額(数値/0),
  "r10_gross": 10%対象額(数値/0),
  "r10_tax": 10%税額(数値/0),
  "line_items": [
    {
      "product_name": "商品名",
      "quantity": 数量,
      "unit_price": 単価,
      "tax_rate": "8%" or "10%",
      "amount": 金額
    }
  ]
}

【STEP 1: 必ず下記のキーワード行から数字を読み取る】商品明細を足し算してはいけない:
1. "小計" / "税抜合計" / "税抜" / "税前" → net
2. **税金行を優先的に探す**（以下のいずれかから税率別に抽出）:
   - "外税額 8%" / "外税額　8%" / "外税額(8%)"
   - "(内)消費税等 8%" / "(内)消費税 8%" / "消費税 8%" / "消費税等 8%"
   - "内消費税8%" / "内消費税 8%" / "内税8%"
   - "外税額 10%" / "外税額　10%" / "外税額(10%)"
   - "(内)消費税等 10%" / "(内)消費税 10%" / "消費税 10%" / "消費税等 10%"
   - "内消費税10%" / "内消費税 10%" / "内税10%"
   → これらの行から r8_tax と r10_tax を抽出
3. "合計" / "お会計" / "総合計" / "お支払い" / "お釣り前の金額" → gross
   **重要**: "小計"ではなく"合計"を gross として読み取る
4. "8%対象" / "8%対象額" / "税率8%対象額" / "(税率 8%対象額)" → r8_gross (あれば)
5. "10%対象" / "10%対象額" / "税率10%対象額" / "(税率 10%対象額)" → r10_gross (あれば)

【STEP 2: 外税 or 内税を判定】:
A) 「外税額」または「(内)消費税等」の表記がある → 外税形式
   → r8_gross = 0, r10_gross = 0 に強制設定
   → r8_tax と r10_tax のみ税金行から読取
   → tax = r8_tax + r10_tax

B) 「8%対象」「10%対象」の表記がある → 内税形式
   → r8_gross, r10_gross を「X%対象」または「税率X%対象額」行から読取
   → r8_tax, r10_tax を「内消費税X%」または「消費税X%」行から読取
   → tax = r8_tax + r10_tax

C) どちらでもない → net + tax = gross を検証して判定

【外税レシート例1（業務スーパー形式）】:
```
小計            ¥4,714  → net = 4714
外税額　8%      ¥377    → r8_tax = 377, r8_gross = 0
合計            ¥5,091  → gross = 5091
(税率 8%対象額  ¥5,091) → 無視（これは合計額）
(内)消費税等 8% ¥377    → r8_tax = 377（確認用）
```

【外税レシート例2（複数税率）】:
```
小計            ¥7,415  → net = 7415
外税額　8%      ¥592    → r8_tax = 592, r8_gross = 0
外税額　10%     ¥1      → r10_tax = 1, r10_gross = 0
合計            ¥8,008  → gross = 8008
```

【内税レシート例（r8_gross/r10_gross に値あり）】:
```
8%対象          ¥7,953  → r8_gross = 7953
内消費税8%      ¥588    → r8_tax = 588
10%対象         ¥55     → r10_gross = 55
内消費税10%     ¥5      → r10_tax = 5
合計            ¥8,008  → gross = 8008
```

【必須検証】:
✓ net + tax = gross (±2円の誤差許容)
✓ r8_tax + r10_tax = tax (±1円)
✓ 外税形式の場合: r8_gross = 0 AND r10_gross = 0
✓ 全ての金額は正の整数

【STEP 3: 明細行の抽出（可能な場合のみ）】:
**重要**: 合計欄の抽取を優先。明細行は**ベストエフォート**で抽出する
- 明細行が明確に記載されている場合のみ抽出
- 各明細行から以下を抽出:
  * product_name: 商品名/品名
  * quantity: 数量（デフォルト1）
  * unit_price: 単価（税抜）
  * tax_rate: "8%" または "10%" （デフォルト"8%"）
  * amount: 金額（その行の税抜金額、または税込なら推定）
- 明細行がない/不明確な場合: line_items = []
- 明細行の合計は net に近い値になるべき

【出力】:
- 数字のみ（カンマ・円記号なし）
- 見つからない項目は 0 または null
- T番号なし→tax_id:null
- 明細なし→line_items:[]
- JSONのみ出力（説明文不要）'''

# FULL PROMPT - For detailed line-by-line extraction (~25-35s)
PROMPT_FULL = '''你是日本会计（日本基準/JGAAP）与适格請求書（インボイス制度）解析引擎。请从输入的小票/发票/请款单文本中，抽取"开票方信息 + 明细行 + 税率汇总 + 会计科目建议"，并进行严格交叉验证，尽量提高识别率。

【必须抽取的核心字段】
1) issuer（开票方）
- issuer_name：开票方名称（商号/店名/公司名）
- invoice_reg_no：税务识别号码（适格請求書発行事業者登録番号），形如 "T"+13位数字（例如 T1234567890123）
  - 若文本中找不到任何注册号/登録番号/適格請求書発行事業者番号/インボイス番号，则 invoice_reg_no 直接输出 "0000000000000"（十三个0，不带T）
- issuer_tel、issuer_address：能识别则填，否则为 null

2) document（单据）
- doc_type：receipt | invoice | unknown
- doc_date：YYYY-MM-DD 或 null
- currency：JPY
- category（必须输出且仅能取以下之一）：purchase | sale | expense
  - category 识别优先级：
    A. 文本明确：請求書/納品書/領収書/レシート/見積書 等 + 语义（売上/請求/支払/仕入/経費）
    B. 若出现"御請求/請求金額/お支払い"且对方为客户语境，倾向 sale
    C. 若出现"仕入/買掛/発注/納入/支払先/振込先"倾向 purchase
    D. 若出现大量费用类关键词（交通費/宿泊/会議/広告/通信/消耗品 等）倾向 expense
    E. 无法判断时：默认 expense，并在 notes 说明

3) lines（逐行明细，必须输出）
每一行必须输出：
- line_no：从1开始
- name：行名称（原文）
- tax_rate：枚举 ["10%","8%","exempt","unknown"]
  - 行税率判定优先级：
    A. 行内/附近出现 10%/8%/税10/税8/標準/軽減/外税10/内税8 等
    B. 汇总区的 "10%対象 / 8%対象 / 軽減対象 / 税率別" 对照（若能）
    C. 找不到税率：强制默认 "8%"
    D. 出现 非課税/不課税/免税/対象外：设为 "exempt"
- net_amount：净额（不含税金额，数值JPY；若只能得到含税则允许推导或置 null）
- tax_amount：税额（数值JPY；无法确定则 null）
- gross_amount：总额（含税金额，数值JPY；无法确定则 null）
- amount_source：说明三者来源与推导方式，枚举：
  ["all_on_doc","net+tax=gross","gross->net_by_rate","net->tax_by_rate","unknown"]
- qty、unit_price：能识别则填，否则 null
- suggested_account：建议会计科目（勘定科目名，日文）
- suggested_account_code：可选（若能给出常见代码体系则填，否则 null）
- suggested_account_confidence：0~1
- raw：原文片段用于追溯

【会计科目建议规则（结合日本会计准则的常见实务）】
你必须基于 category + 行名称关键词，给出 suggested_account：
A) category = purchase（采购：存货/进货/材料等）
- 默认：仕入高
- 若关键词包含：原材料/材料/部品/資材 → 原材料費 or 仕入高（择优）
- 若为固定资产/设备：PC/パソコン/サーバ/機械/備品/什器/工具/ソフトウェア → 工具器具備品 or ソフトウェア（金额大且耐用倾向固定资产）
- 若为外包：外注/業務委託/制作/開発 → 外注費
- 若为运费：送料/配送/運賃 → 荷造運賃
- 税处理提示（notes中给出）：对 purchase 通常对应 仮払消費税（但你仍需输出行税额）

B) category = sale（销售：对外开票/收入）
- 默认：売上高
- 若关键词包含：手数料/利用料/サブスク/課金 → 売上高（内可加"役務収益"类说明但科目仍输出売上高）
- 若为运费：送料/配送料 → 売上高（或 売上高(送料) 说明）
- 税处理提示（notes中给出）：对 sale 通常对应 仮受消費税（但你仍需输出行税额）

C) category = expense（费用：日常经费）
按关键词映射（优先级从高到低，命中即用）：
- 旅費交通費：電車/バス/タクシー/交通/切符/IC/出張
- 会議費：会議/打合せ/ミーティング
- 交際費：接待/贈答/お土産/懇親
- 通信費：通信/携帯/電話/インターネット/回線
- 水道光熱費：電気/ガス/水道
- 消耗品費：消耗品/文房具/日用品/備品（小额）
- 広告宣伝費：広告/宣伝/Google/Meta/販促
- 支払手数料：手数料/決済/振込手数料
- 地代家賃：家賃/賃料/レンタル
- 修繕費：修理/修繕/メンテ
- 福利厚生費：福利/健康/社内イベント
- 研修費：研修/セミナー/講座
- 未命中：雑費（并降低置信度）

【净额/税额/总额推导规则（必须执行）】
1) 若同一行同时出现"税抜/税別/本体"与"税込/合計"：
- 优先把税抜作为 net_amount，税込作为 gross_amount，税额为 gross-net（若可计算）
2) 若只出现含税金额 gross_amount，且税率明确为 10% 或 8%：
- 推导 net = round(gross / (1+rate))（JPY四舍五入；并在 amount_source 标注 gross->net_by_rate）
- tax = gross - net
3) 若只出现净额 net_amount，且税率明确：
- tax = round(net * rate)（JPY四舍五入；amount_source=net->tax_by_rate）
- gross = net + tax
4) 若 tax_rate="exempt"：tax_amount=0，gross=net（若可）
5) 若税率缺失：强制视为 8% 进行推导（并在 notes 标注"默认8%"）

【汇总区抽取（若存在）】
你必须尽最大努力抽取以下关键词附近的金额：
- total_gross（合計/総合計/請求金額/お会計/税込合計）
- total_tax（消費税/税額/内消費税）
- by_rate_summary（若有）：10%対象、8%対象、軽減対象、税率別、標準税率、軽減税率
并标注每个汇总值的来源：on_doc 或 derived（从行汇总推导）

【交叉验证（必须输出validation）】
你必须做三层校验，并给出 pass/fail/partial：
A) 行内校验（line-level）
- 对每行：若三者齐全，检查 net + tax == gross
- 若不等，给出 diff，并尝试解释：四舍五入/折扣/内税外税/OCR错位
B) 分税率校验（by-rate）
- 按 tax_rate 分组汇总 net/tax/gross（折扣行要计入，折扣为负数）
- 若票面存在 8%/10%対象 与 税额：对比差异
C) 总计校验（grand total）
- 所有行汇总 vs 票面 total_gross/total_tax（若存在）
- 若票面无总计，则输出 derived_total

【容差（考虑日元四舍五入与分摊）】
- 单行容差：±1 JPY
- 分税率税额容差：±1 JPY
- 总税额容差：±2 JPY
- 总金额容差：±2 JPY
超出容差必须列入 mismatches，并给出最可能修正建议（例如：某行税率应为10%而不是8%，或该金额为税抜而被当成税込）。

【输出格式要求】
只能输出 JSON（不要 markdown，不要解释文本），结构如下：
{
  "currency": "JPY",
  "document": {
    "doc_type": "receipt|invoice|unknown",
    "doc_date": "YYYY-MM-DD|null",
    "category": "purchase|sale|expense"
  },
  "issuer": {
    "issuer_name": "string|null",
    "invoice_reg_no": "T1234567890123|string(13 zeros)",
    "issuer_tel": "string|null",
    "issuer_address": "string|null"
  },
  "totals_on_doc": {
    "total_gross": 0|null,
    "total_tax": 0|null,
    "by_rate": {
      "10%": { "net": 0|null, "tax": 0|null, "gross": 0|null, "source": "on_doc|derived" },
      "8%":  { "net": 0|null, "tax": 0|null, "gross": 0|null, "source": "on_doc|derived" },
      "exempt": { "net": 0|null, "tax": 0|null, "gross": 0|null, "source": "on_doc|derived" }
    }
  },
  "lines": [
    {
      "line_no": 1,
      "name": "string",
      "tax_rate": "10%|8%|exempt|unknown",
      "net_amount": 0|null,
      "tax_amount": 0|null,
      "gross_amount": 0|null,
      "amount_source": "all_on_doc|net+tax=gross|gross->net_by_rate|net->tax_by_rate|unknown",
      "qty": 0|null,
      "unit_price": 0|null,
      "suggested_account": "string",
      "suggested_account_code": "string|null",
      "suggested_account_confidence": 0.0,
      "raw": "string"
    }
  ],
  "validation": {
    "tolerances": { "line": 1, "by_rate_tax": 1, "total_tax": 2, "total_gross": 2 },
    "checks": [
      { "name": "line_level", "status": "pass|fail|partial", "details": "string" },
      { "name": "by_rate", "status": "pass|fail|partial", "details": "string" },
      { "name": "grand_total", "status": "pass|fail|partial", "details": "string" }
    ],
    "mismatches": [
      {
        "scope": "line|8%|10%|exempt|total",
        "field": "net|tax|gross",
        "expected": 0,
        "actual": 0,
        "diff": 0,
        "reason": "string",
        "candidate_fix": {
          "line_no": 0|null,
          "suggest_tax_rate": "10%|8%|exempt|null",
          "suggest_amount_interpretation": "tax_inclusive|tax_exclusive|null",
          "confidence": 0.0
        }
      }
    ]
  },
  "notes": [
    "string"
  ]
}

【强制约束】
- 如果 invoice_reg_no 缺失：必须输出 "0000000000000"（十三个0）
- 如果行税率缺失：必须默认 "8%"
- 不能省略 lines；即使识别困难也要尽量输出候选行并用 null 标注不确定值'''


# ============== LIFESPAN ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool lifecycle"""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS ocr_usage (
                    id SERIAL PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    year_month VARCHAR(7) NOT NULL,
                    image_count INTEGER DEFAULT 0,
                    billable_count INTEGER DEFAULT 0,
                    total_cost DECIMAL(10,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(tenant_id, year_month)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS ocr_requests (
                    id SERIAL PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    request_time TIMESTAMP DEFAULT NOW(),
                    success BOOLEAN,
                    error_code VARCHAR(50),
                    processing_time_ms INTEGER,
                    file_size_bytes INTEGER,
                    output_level VARCHAR(20)
                )
            ''')
            # Add output_level column if not exists (migration from prompt_version)
            await conn.execute('''
                DO $$
                BEGIN
                    ALTER TABLE ocr_requests ADD COLUMN IF NOT EXISTS output_level VARCHAR(20);
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            ''')
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        db_pool = None

    yield

    if db_pool:
        await db_pool.close()


# ============== APP ==============

app = FastAPI(
    title="Central OCR Service",
    description="Centralized OCR service with unified Japanese prompt and configurable output levels",
    version="2.0.2",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== MODELS ==============

class OCRRequest(BaseModel):
    image_data: str  # Base64 encoded
    mime_type: str = 'image/jpeg'
    output_level: Literal['summary', 'accounting'] = 'summary'  # Default to summary
    template_fields: List[str] = []
    tenant_id: str = 'default'

    # Deprecated field for backward compatibility
    prompt_version: Optional[Literal['fast', 'full']] = None


class OCRResponse(BaseModel):
    success: bool
    extracted: Optional[Dict[str, Any]] = None
    raw_response: Optional[str] = None
    error_code: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    output_level: Optional[str] = None
    processing_time_ms: Optional[int] = None


class UsageResponse(BaseModel):
    tenant_id: str
    year_month: str
    image_count: int
    free_remaining: int
    billable_count: int
    total_cost: float


# ============== AUTH ==============

async def verify_service_key(x_service_key: Optional[str] = Header(None)):
    if SERVICE_KEY and x_service_key != SERVICE_KEY:
        raise HTTPException(status_code=401, detail="Invalid service key")
    return True


# ============== CORE ==============

def extract_json_from_text(text: str) -> dict:
    """Extract JSON from text response"""
    # Try markdown code block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from code block: {e}")

    # Try raw JSON (Gemini JSON mode returns plain JSON)
    try:
        # Gemini with responseMimeType='application/json' returns plain JSON
        parsed = json.loads(text)
        logger.info(f"[DEBUG] Successfully parsed JSON directly")
        return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse raw JSON: {e}")
        # Fallback: try to extract JSON from text
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end > start:
                extracted_json = text[start:end]
                logger.info(f"[DEBUG] Extracted JSON substring from {start} to {end}")
                return json.loads(extracted_json)
        except json.JSONDecodeError as e2:
            logger.error(f"Failed to parse extracted JSON: {e2}")

    logger.error(f"All JSON extraction methods failed, returning raw_text")
    return {'raw_text': text}


async def call_gemini_api(
    image_data: str,
    mime_type: str,
    output_level: str = 'summary'
) -> Dict[str, Any]:
    """Call Gemini API with unified prompt and dynamic output_level parameter"""
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not configured")
        return {'success': False, 'error_code': 'service_error'}

    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'

    # Build prompt with output_level parameter
    prompt_with_param = f"{PROMPT_UNIFIED_JP}\n\n【今回の output_level】: {output_level}"

    # Configure based on output_level
    if output_level == 'summary':
        config = {
            'temperature': 0,
            'maxOutputTokens': 2048,
            'responseMimeType': 'application/json',  # JSON mode for faster response
        }
        timeout = 30
    else:  # accounting
        config = {
            'temperature': 0,
            'maxOutputTokens': 4096,
            'responseMimeType': 'application/json',
        }
        timeout = 60

    payload = {
        'contents': [{
            'parts': [
                {'inline_data': {'mime_type': mime_type, 'data': image_data}},
                {'text': prompt_with_param}
            ]
        }],
        'generationConfig': config
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                )

            if response.status_code == 429:
                wait_time = (attempt + 1) * 3
                logger.warning(f"Rate limited, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                continue

            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.status_code} - {response.text[:200]}")
                return {'success': False, 'error_code': 'service_error'}

            result = response.json()
            candidates = result.get('candidates', [])
            if not candidates:
                return {'success': False, 'error_code': 'processing_failed'}

            content = candidates[0].get('content', {})
            parts = content.get('parts', [])
            if not parts:
                return {'success': False, 'error_code': 'processing_failed'}

            raw_text = parts[0].get('text', '')
            logger.info(f"[DEBUG] Gemini raw_text (first 500 chars): {raw_text[:500]}")
            extracted = extract_json_from_text(raw_text)
            logger.info(f"[DEBUG] Extracted keys: {list(extracted.keys())}")
            logger.info(f"[DEBUG] Extracted data: {extracted}")

            return {
                'success': True,
                'extracted': extracted,
                'raw_response': raw_text,
            }

        except httpx.TimeoutException:
            logger.warning(f"Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            return {'success': False, 'error_code': 'timeout'}
        except Exception as e:
            logger.exception(f"Gemini API error: {e}")
            return {'success': False, 'error_code': 'service_error'}

    return {'success': False, 'error_code': 'max_retries'}


async def update_usage(
    tenant_id: str,
    success: bool,
    processing_time_ms: int,
    file_size: int,
    output_level: str = 'summary'
):
    """Update usage tracking"""
    if not db_pool:
        return None

    year_month = datetime.now().strftime('%Y-%m')

    try:
        async with db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO ocr_requests (tenant_id, success, processing_time_ms, file_size_bytes, output_level)
                VALUES ($1, $2, $3, $4, $5)
            ''', tenant_id, success, processing_time_ms, file_size, output_level)

            if success:
                await conn.execute('''
                    INSERT INTO ocr_usage (tenant_id, year_month, image_count, billable_count, total_cost)
                    VALUES ($1, $2, 1,
                        CASE WHEN 1 > $3 THEN 1 ELSE 0 END,
                        CASE WHEN 1 > $3 THEN $4 ELSE 0 END)
                    ON CONFLICT (tenant_id, year_month) DO UPDATE SET
                        image_count = ocr_usage.image_count + 1,
                        billable_count = CASE
                            WHEN ocr_usage.image_count >= $3 THEN ocr_usage.billable_count + 1
                            ELSE ocr_usage.billable_count
                        END,
                        total_cost = CASE
                            WHEN ocr_usage.image_count >= $3 THEN ocr_usage.total_cost + $4
                            ELSE ocr_usage.total_cost
                        END,
                        updated_at = NOW()
                ''', tenant_id, year_month, FREE_QUOTA_PER_MONTH, PRICE_PER_IMAGE)

                row = await conn.fetchrow('''
                    SELECT image_count, billable_count, total_cost
                    FROM ocr_usage WHERE tenant_id = $1 AND year_month = $2
                ''', tenant_id, year_month)

                if row:
                    return {
                        'image_count': row['image_count'],
                        'free_remaining': max(0, FREE_QUOTA_PER_MONTH - row['image_count']),
                        'billable_count': row['billable_count'],
                        'total_cost': float(row['total_cost']),
                    }
    except Exception as e:
        logger.exception(f"Usage update error: {e}")

    return None


# ============== ENDPOINTS ==============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.0.2",
        "output_levels": ["summary", "accounting"],
        "prompt_type": "unified_japanese_with_examples",
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/v1/ocr/process", response_model=OCRResponse)
async def process_ocr(
    request: OCRRequest,
    _: bool = Depends(verify_service_key)
):
    """Process OCR request with unified prompt and configurable output_level"""
    start_time = time.time()
    file_size = len(request.image_data) * 3 // 4

    # Handle backward compatibility: map prompt_version to output_level
    output_level = request.output_level
    if request.prompt_version:
        logger.warning(f"Deprecated prompt_version '{request.prompt_version}' used, mapping to output_level")
        output_level = 'summary' if request.prompt_version == 'fast' else 'accounting'

    logger.info(f"OCR request from {request.tenant_id}, output_level={output_level}")

    result = await call_gemini_api(
        request.image_data,
        request.mime_type,
        output_level
    )

    processing_time_ms = int((time.time() - start_time) * 1000)
    logger.info(f"OCR completed in {processing_time_ms}ms, output_level={output_level}, success={result.get('success')}")

    usage = await update_usage(
        request.tenant_id,
        result.get('success', False),
        processing_time_ms,
        file_size,
        output_level
    )

    if result.get('success'):
        return OCRResponse(
            success=True,
            extracted=result.get('extracted'),
            raw_response=result.get('raw_response'),
            usage=usage,
            output_level=output_level,
            processing_time_ms=processing_time_ms
        )
    else:
        return OCRResponse(
            success=False,
            error_code=result.get('error_code', 'processing_failed'),
            output_level=output_level,
            processing_time_ms=processing_time_ms
        )


@app.get("/api/v1/usage/{tenant_id}", response_model=UsageResponse)
async def get_usage(
    tenant_id: str,
    year_month: Optional[str] = None,
    _: bool = Depends(verify_service_key)
):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    if not year_month:
        year_month = datetime.now().strftime('%Y-%m')

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT tenant_id, year_month, image_count, billable_count, total_cost
            FROM ocr_usage WHERE tenant_id = $1 AND year_month = $2
        ''', tenant_id, year_month)

    if row:
        return UsageResponse(
            tenant_id=row['tenant_id'],
            year_month=row['year_month'],
            image_count=row['image_count'],
            free_remaining=max(0, FREE_QUOTA_PER_MONTH - row['image_count']),
            billable_count=row['billable_count'],
            total_cost=float(row['total_cost'])
        )
    else:
        return UsageResponse(
            tenant_id=tenant_id,
            year_month=year_month,
            image_count=0,
            free_remaining=FREE_QUOTA_PER_MONTH,
            billable_count=0,
            total_cost=0
        )


@app.get("/api/v1/usage")
async def list_all_usage(
    year_month: Optional[str] = None,
    _: bool = Depends(verify_service_key)
):
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    if not year_month:
        year_month = datetime.now().strftime('%Y-%m')

    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT tenant_id, year_month, image_count, billable_count, total_cost
            FROM ocr_usage WHERE year_month = $1
            ORDER BY image_count DESC
        ''', year_month)

    return {
        'year_month': year_month,
        'free_quota': FREE_QUOTA_PER_MONTH,
        'price_per_image': PRICE_PER_IMAGE,
        'tenants': [
            {
                'tenant_id': row['tenant_id'],
                'image_count': row['image_count'],
                'free_remaining': max(0, FREE_QUOTA_PER_MONTH - row['image_count']),
                'billable_count': row['billable_count'],
                'total_cost': float(row['total_cost'])
            }
            for row in rows
        ]
    }


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
