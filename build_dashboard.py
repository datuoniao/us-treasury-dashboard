#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国国债数据看板 - 数据处理与构建脚本 (纯本地, 不联网)

原始数据由 fetch_data.sh 用 curl 抓取到 data_raw/, 本脚本只做解析、重采样与页面生成。

数据源:
  - 美国财政部 收益率曲线 (名义 + TIPS 实际)  [日频 -> 本地重采样为周频]
  - Treasury Fiscal Data: Debt to the Penny / MSPD 债务结构 [日频 -> 周频 / 月频]
  - TIC: 各国持有美债 (mfhhis01 历史 + slt_table5 最新)  [月频]

输出: output/us_treasury_dashboard.html  (单文件自包含, 内联 ECharts + 数据)
"""
import csv
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "data_raw")
VENDOR_ECHARTS = os.path.join(BASE, "vendor", "echarts.min.js")
TEMPLATE = os.path.join(BASE, "template.html")
OUTDIR = os.path.join(BASE, "output")
OUTFILE = os.path.join(OUTDIR, "us_treasury_dashboard.html")
CACHE = os.path.join(BASE, "cache_data.json")

START_YEAR = 2006


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def load_text(name):
    with open(os.path.join(RAW, name), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ----------------------------------------------------------------------------
# 周频重采样
# ----------------------------------------------------------------------------
def week_friday(d):
    return d + timedelta(days=(4 - d.weekday()))


def to_weekly(pairs, how="mean", ndigits=3):
    buckets = {}
    for ds, v in pairs:
        if v is None:
            continue
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        buckets.setdefault(week_friday(d), []).append((d, v))
    out = []
    for f in sorted(buckets):
        items = sorted(buckets[f], key=lambda x: x[0])
        val = items[-1][1] if how == "last" else sum(x[1] for x in items) / len(items)
        out.append((f.isoformat(), round(val, ndigits)))
    return out


def to_monthly_last(pairs, ndigits=2):
    buckets = {}
    for ds, v in pairs:
        if v is None:
            continue
        buckets[ds[:7]] = v
    return [(m, round(v, ndigits)) for m, v in sorted(buckets.items())]


# ----------------------------------------------------------------------------
# 财政部收益率曲线
# ----------------------------------------------------------------------------
NOMINAL_MAP = {
    "1 Mo": "1月", "2 Mo": "2月", "3 Mo": "3月", "4 Mo": "4月", "6 Mo": "6月",
    "1 Yr": "1年", "2 Yr": "2年", "3 Yr": "3年", "5 Yr": "5年", "7 Yr": "7年",
    "10 Yr": "10年", "20 Yr": "20年", "30 Yr": "30年",
}
REAL_MAP = {"5 YR": "实际5年", "7 YR": "实际7年", "10 YR": "实际10年",
            "20 YR": "实际20年", "30 YR": "实际30年"}


def parse_mdy(s):
    m, d, y = s.strip().split("/")
    return "%04d-%02d-%02d" % (int(y), int(m), int(d))


def parse_tsy_file(path, cmap):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    reader = csv.reader(io.StringIO(text))
    header = None
    out = []
    for row in reader:
        if not row:
            continue
        if header is None:
            header = [c.strip().lstrip("\ufeff") for c in row]
            continue
        raw_d = row[0].strip()
        if not raw_d or "/" not in raw_d:
            continue
        try:
            iso = parse_mdy(raw_d)
        except ValueError:
            continue
        rec = {}
        for i, col in enumerate(header[1:], start=1):
            key = cmap.get(col)
            if not key or i >= len(row):
                continue
            v = row[i].strip()
            if v in ("", ".", "N/A", "n/a", "NA"):
                continue
            try:
                rec[key] = float(v)
            except ValueError:
                continue
        out.append((iso, rec))
    out.sort(key=lambda x: x[0])
    return out


def build_yields():
    log("解析财政部收益率曲线 ...")
    nom_rows, real_rows = [], []
    for y in range(START_YEAR, date.today().year + 1):
        pn = os.path.join(RAW, "tsy_nominal_%d.csv" % y)
        pr = os.path.join(RAW, "tsy_real_%d.csv" % y)
        if os.path.exists(pn):
            nom_rows.extend(parse_tsy_file(pn, NOMINAL_MAP))
        if os.path.exists(pr):
            real_rows.extend(parse_tsy_file(pr, REAL_MAP))
    nom_rows.sort(key=lambda x: x[0])
    real_rows.sort(key=lambda x: x[0])
    log("  名义 %d 个交易日, 实际(TIPS) %d 个交易日" % (len(nom_rows), len(real_rows)))

    terms = ["1月", "2月", "3月", "4月", "6月", "1年", "2年", "3年", "5年", "7年", "10年", "20年", "30年"]
    series = {}
    for k in terms:
        series[k] = to_weekly([(d, r.get(k)) for d, r in nom_rows if k in r], "mean", 3)

    # 关键利差 (自行计算)
    t2 = {d: r.get("2年") for d, r in nom_rows}
    t3m = {d: r.get("3月") for d, r in nom_rows}
    t10 = {d: r.get("10年") for d, r in nom_rows}
    sp_2y = [(d, round(t10[d] - t2[d], 3)) for d in sorted(t10)
             if t10.get(d) is not None and t2.get(d) is not None]
    sp_3m = [(d, round(t10[d] - t3m[d], 3)) for d in sorted(t10)
             if t10.get(d) is not None and t3m.get(d) is not None]
    spreads = {"10Y-2Y": to_weekly(sp_2y, "mean", 3), "10Y-3M": to_weekly(sp_3m, "mean", 3)}

    # 实际利率与隐含通胀预期
    real10 = {d: r.get("实际10年") for d, r in real_rows}
    be_pairs = [(d, t10[d] - real10[d]) for d in sorted(t10)
                if t10.get(d) is not None and real10.get(d) is not None]
    real = {
        "名义10年": to_weekly([(d, r.get("10年")) for d, r in nom_rows if "10年" in r], "mean", 3),
        "实际10年": to_weekly([(d, r.get("实际10年")) for d, r in real_rows if "实际10年" in r], "mean", 3),
        "通胀预期10年": to_weekly(be_pairs, "mean", 3),
    }
    return {"series": series, "spreads": spreads, "real": real}


# ----------------------------------------------------------------------------
# Fiscal Data
# ----------------------------------------------------------------------------
def build_debt():
    log("解析 Debt to the Penny ...")
    js = json.loads(load_text("fd_debt_to_penny.json"))
    rows = js.get("data", [])
    raw = {"total": [], "public": [], "intragov": []}
    for r in rows:
        d = r.get("record_date")
        if not d:
            continue
        try:
            raw["total"].append((d, float(r["tot_pub_debt_out_amt"]) / 1e9))
            raw["public"].append((d, float(r["debt_held_public_amt"]) / 1e9))
            raw["intragov"].append((d, float(r["intragov_hold_amt"]) / 1e9))
        except (TypeError, ValueError, KeyError):
            continue
    for k in raw:
        raw[k].sort(key=lambda x: x[0])
    log("  %d 条日频记录" % len(raw["total"]))
    return {
        "weekly": {k: to_weekly(raw[k], "last", 2) for k in raw},
        "monthly_public": to_monthly_last(raw["public"], 2),
        "monthly_total": to_monthly_last(raw["total"], 2),
    }


MARKETABLE_CLASSES = ["Bills", "Notes", "Bonds",
                      "Treasury Inflation-Protected Securities", "Floating Rate Notes"]
# 可流通债务中除上述 5 大类外的杂项（如 Federal Financing Bank）统一归入「其他」，
# 以保证旭日图父环数值 == 子项之和，不出现空白扇区。
MARKETABLE_OTHER = "Other"
CLASS_LABEL = {
    "Bills": "短期国库券 Bills",
    "Notes": "中期票据 Notes",
    "Bonds": "长期国债 Bonds",
    "Treasury Inflation-Protected Securities": "通胀保值债券 TIPS",
    "Floating Rate Notes": "浮动利率票据 FRN",
    MARKETABLE_OTHER: "其他 Other",
}


def build_structure():
    log("解析 MSPD 债务结构 ...")
    js = json.loads(load_text("fd_mspd_table1.json"))
    rows = js.get("data", [])
    log("  %d 条月度明细" % len(rows))
    # 分表存储：可流通 / 不可流通，避免两类同名 class 相互污染
    mkt_by_month = {}
    nonmkt_by_month = {}
    for r in rows:
        st = r.get("security_type_desc")
        sc = r.get("security_class_desc")
        if st not in ("Marketable", "Nonmarketable"):
            continue
        try:
            v = float(r["total_mil_amt"]) / 1000.0
        except (TypeError, ValueError, KeyError):
            continue
        bucket = mkt_by_month if st == "Marketable" else nonmkt_by_month
        bucket.setdefault(r["record_date"][:7], {})[sc] = v

    months = sorted(set(mkt_by_month) | set(nonmkt_by_month))
    all_classes = MARKETABLE_CLASSES + [MARKETABLE_OTHER]
    classes = {c: [] for c in all_classes}
    mkt_total, nonmkt = [], []
    for m in months:
        md = mkt_by_month.get(m, {})
        nd = nonmkt_by_month.get(m, {})
        for c in MARKETABLE_CLASSES:
            classes[c].append(round(md.get(c, 0.0), 1))
        # 未归入 5 大类的 Marketable 杂项（如 Federal Financing Bank）→「其他」
        classes[MARKETABLE_OTHER].append(
            round(sum(v for k, v in md.items() if k not in MARKETABLE_CLASSES), 1))
        # 父环 = 全部可流通项之和（与子项之和严格一致，杜绝旭日图空白）
        mkt_total.append(round(sum(v for v in md.values()), 1))
        nonmkt.append(round(sum(v for v in nd.values()), 1))

    latest_month = months[-1] if months else None
    latest_items = []
    if latest_month:
        for c in all_classes:
            latest_items.append({"name": CLASS_LABEL[c], "value": classes[c][-1]})
    return {
        "months": months,
        "classes": {CLASS_LABEL[c]: classes[c] for c in all_classes},
        "marketable_total": mkt_total,
        "nonmarketable_total": nonmkt,
        "latest_month": latest_month,
        "latest_items": latest_items,
        "latest_marketable": mkt_total[-1] if mkt_total else 0,
        "latest_nonmarketable": nonmkt[-1] if nonmkt else 0,
    }


# ----------------------------------------------------------------------------
# TIC
# ----------------------------------------------------------------------------
MONTHS_ABBR = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
               "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
CN_NAME = {
    "Japan": "日本", "China, Mainland": "中国大陆", "United Kingdom": "英国",
    "Belgium": "比利时", "Canada": "加拿大", "Luxembourg": "卢森堡",
    "Cayman Islands": "开曼群岛", "France": "法国", "Ireland": "爱尔兰",
    "Taiwan": "中国台湾", "Switzerland": "瑞士", "Singapore": "新加坡",
    "Hong Kong": "中国香港", "Norway": "挪威", "India": "印度", "Brazil": "巴西",
    "Saudi Arabia": "沙特阿拉伯", "Korea, South": "韩国", "Israel": "以色列",
    "Germany": "德国", "Bermuda": "百慕大", "United Arab Emirates": "阿联酋",
    "El Salvador": "萨尔瓦多", "Mexico": "墨西哥", "Thailand": "泰国",
    "Spain": "西班牙", "Australia": "澳大利亚", "Netherlands": "荷兰",
    "Kuwait": "科威特", "Italy": "意大利", "Philippines": "菲律宾",
    "All Other": "其他", "Grand Total": "合计",
}
# 解析时需保留 "Grand Total" / "Of Which: Foreign Official" 等聚合行(用于总量与官方/私人拆分),
# 仅在国家级排行/构成中排除它们。
PARSE_SKIP = {"Country", "Total", "Oil exporters", "Caribbean Banking Centers",
              "Belgium-Luxembourg"}
NON_COUNTRY = {"Grand Total", "All Other", "Of Which: Foreign Official",
               "Of Which: Foreign Official Treasury Bills",
               "Of Which: Foreign Official T-Bonds & Notes"}


def is_country(name):
    return name not in NON_COUNTRY and not name.startswith("Of Which")


def _num(s):
    s = s.strip().replace(",", "")
    if s in ("", "n.a.", "NA", "*", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# 历史文件中部分国家名带脚注编号, 如 "United Kingdom 2/"
FOOTNOTE_RE = re.compile(r"\s+\d+/\s*$")


def norm_name(s):
    return FOOTNOTE_RE.sub("", s.strip()).strip()


def parse_mfhhis(text):
    panel = {}
    key_cols = []
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    for cells in reader:
        if not cells:
            continue
        first = norm_name(cells[0])
        if first == "" and any(c.strip() in MONTHS_ABBR for c in cells[1:4]):
            mons = [MONTHS_ABBR[c.strip()] for c in cells[1:] if c.strip() in MONTHS_ABBR]
            if mons:
                key_cols = [(m, None) for m in mons]
            continue
        if first == "Country":
            years = []
            for c in cells[1:]:
                c = c.strip()
                years.append(int(c) if c.isdigit() else None)
            key_cols = [(key_cols[i][0], years[i]) if i < len(years) else (None, None)
                        for i in range(len(key_cols))]
            continue
        if not key_cols or first in PARSE_SKIP:
            continue
        for i, c in enumerate(cells[1:]):
            if i >= len(key_cols):
                break
            mm, yy = key_cols[i]
            if not mm or not yy:
                continue
            v = _num(c)
            if v is None:
                continue
            panel.setdefault("%04d-%02d" % (yy, mm), {})[first] = v
    return panel


def parse_slt5(text):
    panel = {}
    header = None
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    for cells in reader:
        if not cells:
            continue
        first = norm_name(cells[0])
        if first == "Country":
            header = [c.strip() for c in cells[1:]]
            continue
        if header is None or first in PARSE_SKIP:
            continue
        for i, c in enumerate(cells[1:]):
            if i >= len(header):
                break
            mk = header[i]
            if len(mk) != 7 or mk[4] != "-":
                continue
            v = _num(c)
            if v is None:
                continue
            panel.setdefault(mk, {})[first] = v
    return panel


def build_tic():
    log("解析 TIC 海外持仓 ...")
    panel = {}
    try:
        for k, v in parse_mfhhis(load_text("tic_mfhhis01.txt")).items():
            panel.setdefault(k, {}).update(v)
    except Exception as e:
        log("  ! mfhhis01: %s" % e)
    try:
        for k, v in parse_slt5(load_text("tic_slt_table5.txt")).items():
            panel.setdefault(k, {}).update(v)
    except Exception as e:
        log("  ! slt_table5: %s" % e)

    months = sorted(m for m in panel if m >= "%d-01" % START_YEAR)
    if not months:
        return None
    log("  %d 个月, 最新 %s" % (len(months), months[-1]))

    def spec(name):
        return [round(panel[m][name], 1) if name in panel[m] else None for m in months]

    total = spec("Grand Total")
    official = spec("Of Which: Foreign Official")
    private = [None if (t is None or o is None) else round(t - o, 1) for t, o in zip(total, official)]

    focus = ["Japan", "China, Mainland", "United Kingdom"]
    focus_series = [{"name": CN_NAME.get(n, n), "data": spec(n)} for n in focus]

    last = months[-1]
    rank = sorted([(n, v) for n, v in panel[last].items() if is_country(n)],
                  key=lambda x: -x[1])
    latest_rank = [{"name": CN_NAME.get(n, n), "en": n, "value": round(v, 1)} for n, v in rank[:15]]

    top8 = [n for n, _ in rank[:8]]
    comp = [{"name": CN_NAME.get(n, n), "data": spec(n)} for n in top8]
    other = []
    for i, m in enumerate(months):
        s, has = 0.0, False
        for n in top8:
            if n in panel[m]:
                s += panel[m][n]
                has = True
        other.append(round(total[i] - s, 1) if (has and total[i] is not None) else None)
    comp.append({"name": "其他", "data": other})

    return {
        "months": months, "focus": focus_series, "components": comp,
        "total": total, "official": official, "private": private,
        "latest_rank": latest_rank, "latest_month": last,
    }


# ----------------------------------------------------------------------------
# 日本对比：日本持仓(TIC) / 美元日元汇率 / 美日10年利差
# ----------------------------------------------------------------------------
JP_ERA_BASE = {"S": 1925, "H": 1988, "R": 2018}   # 昭和 / 平成 / 令和
JP_START = "2018-01-01"                            # 日频序列起点
JP_START_M = "2018-01"                             # 月频序列起点


def jp_era_to_iso(s):
    """日本年号日期 -> ISO。'H30.1.4' -> '2018-01-04'；无法识别返回 None。"""
    s = s.strip().lstrip("\ufeff")
    if len(s) < 3 or s[0] not in JP_ERA_BASE:
        return None
    parts = s[1:].split(".")
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(x) for x in parts)
        return date(JP_ERA_BASE[s[0]] + y, m, d).isoformat()
    except ValueError:
        return None


def load_jgb_10y():
    """日本财务省国债利率 CSV（Shift-JIS 编码 + 日本年号日期）-> [(iso_date, 10年利率)]"""
    merged = {}
    for name in ("jp_jgbcm_all.csv", "jp_jgbcm_current.csv"):
        path = os.path.join(RAW, name)
        if not os.path.exists(path):
            log("  ! 缺少 %s" % name)
            continue
        # 注意：该文件是 Shift-JIS，不能用 load_text（其按 utf-8 读）
        with open(path, "r", encoding="shift_jis", errors="replace") as f:
            lines = f.read().splitlines()
        hidx = next((i for i, ln in enumerate(lines[:6]) if "基準日" in ln), None)
        if hidx is None:
            log("  ! %s 未找到表头" % name)
            continue
        cols = [c.strip().lstrip("\ufeff") for c in lines[hidx].split(",")]
        if "10年" not in cols:
            log("  ! %s 无「10年」列" % name)
            continue
        ci = cols.index("10年")
        n = 0
        for ln in lines[hidx + 1:]:
            p = ln.split(",")
            if len(p) <= ci:
                continue
            iso = jp_era_to_iso(p[0])
            vs = p[ci].strip()
            if not iso or vs in ("", "-"):
                continue
            try:
                merged[iso] = float(vs)
                n += 1
            except ValueError:
                continue
        log("  %s: %d 条日频" % (name, n))
    return sorted(merged.items())


def build_japan(y10_weekly, tic, prev=None):
    log("解析日本对比数据（日本持仓 / 美元日元 / 美日10年利差）...")
    # 1) 美元日元汇率（FRED DEXJPUS，日频）
    fx = []
    if os.path.exists(os.path.join(RAW, "fx_usdjpy.csv")):
        for ln in load_text("fx_usdjpy.csv").splitlines()[1:]:
            p = ln.split(",")
            if len(p) < 2:
                continue
            ds, vs = p[0].strip(), p[1].strip()
            if not ds or vs in ("", ".", "NA", "NaN"):
                continue
            try:
                fx.append((ds, float(vs)))
            except ValueError:
                continue
    else:
        log("  ! 缺少 fx_usdjpy.csv")
    log("  美元日元 %d 条日频" % len(fx))

    # 全部日频 -> 周五周频（与看板其余部分口径一致）
    fx_w = dict(to_weekly(fx, "mean", 3))
    jp10_w = dict(to_weekly(load_jgb_10y(), "mean", 3))
    # 抓取不完整（为空，或比上次缓存明显短，例如全历史文件下载失败只剩当年文件）
    # 时复用上次缓存，避免整条线断裂或被截断。新序列正常应 >= 缓存长度。
    if prev:
        old_fx = prev.get("fx") or []
        old_jp = prev.get("jp10") or []
        if len(fx_w) < len(old_fx):
            log("  ! 美元日元仅 %d 点 < 缓存 %d 点，复用缓存" % (len(fx_w), len(old_fx)))
            fx_w = dict(old_fx)
        if len(jp10_w) < len(old_jp):
            log("  ! 日本10年仅 %d 点 < 缓存 %d 点，复用缓存" % (len(jp10_w), len(old_jp)))
            jp10_w = dict(old_jp)
    us10_w = {d: v for d, v in (y10_weekly or [])}

    # 2) 美日10年利差：美债10年 − 日本10年，在同一周五网格上对齐
    spread = [(d, round(us10_w[d] - jp10_w[d], 3))
              for d in sorted(set(us10_w) & set(jp10_w))
              if us10_w[d] is not None and jp10_w[d] is not None]

    # 3) 日本持仓（TIC，月频）
    holdings = []
    if tic and tic.get("months"):
        jp = next((s.get("data") for s in tic.get("focus", []) if s.get("name") == "日本"), None)
        if jp:
            holdings = [(m, v) for m, v in zip(tic["months"], jp) if v is not None]

    def cut(seq, start):
        return [(d, v) for d, v in sorted(seq) if d >= start]

    fx_w = cut(fx_w.items(), JP_START)
    jp10_w = cut(jp10_w.items(), JP_START)
    us10_w = cut(us10_w.items(), JP_START)
    spread = cut(spread, JP_START)
    holdings = cut(holdings, JP_START_M)

    log("  %s 之后: 汇率 %d / 日本10年 %d / 美债10年 %d / 利差 %d / 持仓 %d"
        % (JP_START, len(fx_w), len(jp10_w), len(us10_w), len(spread), len(holdings)))
    last = lambda s: s[-1][1] if s else None
    last_d = lambda s: s[-1][0] if s else None
    return {
        "start": JP_START,
        "fx": fx_w,
        "jp10": jp10_w,
        "us10": us10_w,
        "spread": spread,
        "holdings": holdings,
        "latest": {
            "spread_date": last_d(spread), "spread": last(spread),
            "fx_date": last_d(fx_w), "fx": last(fx_w),
            "jp10_date": last_d(jp10_w), "jp10": last(jp10_w),
            "us10_date": last_d(us10_w), "us10": last(us10_w),
            "holdings_month": last_d(holdings), "holdings": last(holdings),
        },
    }


# ----------------------------------------------------------------------------
# 曲线快照
# ----------------------------------------------------------------------------
def nearest_on_or_before(pairs, tgt):
    best = None
    for d, v in pairs:
        if d <= tgt:
            best = (d, v)
        else:
            break
    return best


def build_curve(yields, latest_iso):
    maturities = ["1月", "3月", "6月", "1年", "2年", "3年", "5年", "7年", "10年", "20年", "30年"]
    anchors = [("最新", 0), ("1个月前", 30), ("1年前", 365), ("5年前", 365 * 5),
               ("10年前", 365 * 10), ("20年前", 365 * 20)]
    base = date.fromisoformat(latest_iso)
    snaps = []
    for label, days in anchors:
        tgt = (base - timedelta(days=days)).isoformat()
        vals, ok = [], False
        for m in maturities:
            p = nearest_on_or_before(yields["series"].get(m, []), tgt)
            if p:
                vals.append(p[1]); ok = True
            else:
                vals.append(None)
        if ok:
            snaps.append({"label": label, "date": tgt, "values": vals})
    return {"maturities": maturities, "snapshots": snaps}


# ----------------------------------------------------------------------------
def main():
    data = {}
    prev = {}
    if os.path.exists(CACHE):
        try:
            with open(CACHE, "r", encoding="utf-8") as f:
                prev = json.load(f)
        except (ValueError, OSError):
            prev = {}
    data["yields"] = build_yields()
    data["debt"] = build_debt()
    data["structure"] = build_structure()
    data["tic"] = build_tic()
    data["japan"] = build_japan(data["yields"]["series"].get("10年"), data["tic"],
                                prev.get("japan"))

    y_dates = [d for s in data["yields"]["series"].values() for d, _ in s]
    latest_yield = max(y_dates) if y_dates else None
    if latest_yield:
        data["curve"] = build_curve(data["yields"], latest_yield)

    dw = data["debt"]["weekly"]["total"]
    data["meta"] = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start_year": START_YEAR,
        "latest_yield": latest_yield,
        "latest_debt": dw[-1][0] if dw else None,
        "latest_structure": data["structure"]["latest_month"],
        "latest_tic": data["tic"]["latest_month"] if data["tic"] else None,
        "sources": [
            "美国财政部 U.S. Treasury - Daily Treasury Par Yield Curve / Real Yield Curve (H.15 原始来源)",
            "美国财政部 Fiscal Data - Debt to the Penny / MSPD 月度债务报表",
            "美国财政部 TIC - Major Foreign Holders of Treasury Securities",
            "美国圣路易斯联储 FRED - DEXJPUS (美元/日元 日频汇率)",
            "日本财务省 Ministry of Finance Japan - 国債金利情報 (JGB 日频利率)",
        ],
    }

    if not data["structure"]["months"] or not (data["tic"] and data["tic"]["months"]) \
            or not data["yields"]["series"].get("10年"):
        if os.path.exists(CACHE):
            log("! 关键数据缺失, 复用上次缓存")
            with open(CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
    else:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    with open(TEMPLATE, "r", encoding="utf-8") as f:
        html = f.read()
    with open(VENDOR_ECHARTS, "r", encoding="utf-8") as f:
        echarts = f.read()

    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    echarts = echarts.replace("</script", "<\\/script")
    html = html.replace("/*__ECHARTS__*/", echarts).replace("__DASH_DATA__", data_json)

    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(html)

    log("完成 -> %s (%.2f MB)" % (OUTFILE, os.path.getsize(OUTFILE) / 1024 / 1024))
    log("  收益率最新 %s | 债务最新 %s | 结构最新 %s | TIC 最新 %s"
        % (data["meta"]["latest_yield"], data["meta"]["latest_debt"],
           data["meta"]["latest_structure"], data["meta"]["latest_tic"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
