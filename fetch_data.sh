#!/usr/bin/env bash
# 抓取美国国债看板的全部原始数据到 data_raw/
# 说明: 沙箱内由 shell 直接调用 curl 最稳定, 故网络抓取与 Python 处理分离。
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
RAW="$DIR/data_raw"
mkdir -p "$RAW"
START_YEAR=2006
CUR_YEAR=$(date +%Y)
FAIL=0

dl() { # dl <url> <outfile> [desc] [extra_curl_flags] [max_time]
  local url="$1" out="$2" desc="${3:-$2}" extra="${4:-}" mt="${5:-60}"
  local i
  for i in 1 2 3; do
    if curl -sSL --max-time "$mt" ${extra} \
        -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36" \
        -H "Accept: */*" "$url" -o "$out" && [ -s "$out" ]; then
      printf "  ok   %-30s %8s B\n" "$desc" "$(wc -c < "$out" | tr -d ' ')"
      return 0
    fi
    sleep $((i))
  done
  printf "  FAIL %s\n" "$desc"
  FAIL=$((FAIL+1))
  return 1
}

dl_noua() { # 不发送自定义 UA 的变体：FRED 收到浏览器 UA 会重置连接 (curl rc=56)
  local url="$1" out="$2" desc="${3:-$2}" extra="${4:-}" mt="${5:-60}"
  local i
  for i in 1 2 3; do
    if curl -sSL --max-time "$mt" ${extra} "$url" -o "$out" && [ -s "$out" ]; then
      printf "  ok   %-30s %8s B\n" "$desc" "$(wc -c < "$out" | tr -d ' ')"
      return 0
    fi
    sleep $((i))
  done
  printf "  FAIL %s\n" "$desc"
  FAIL=$((FAIL+1))
  return 1
}

BASE="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"

echo "== 美国财政部 收益率曲线 (名义 + TIPS实际) ${START_YEAR}-${CUR_YEAR} =="
for Y in $(seq "$START_YEAR" "$CUR_YEAR"); do
  dl "${BASE}/${Y}/all?type=daily_treasury_yield_curve&field_tdr_date_value=${Y}&page&_format=csv" \
     "$RAW/tsy_nominal_${Y}.csv" "nominal ${Y}"
  sleep 0.25
  dl "${BASE}/${Y}/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=${Y}&page&_format=csv" \
     "$RAW/tsy_real_${Y}.csv" "real ${Y}"
  sleep 0.25
done

echo "== Treasury Fiscal Data =="
dl "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?filter=record_date:gte:${START_YEAR}-01-01&fields=record_date,debt_held_public_amt,intragov_hold_amt,tot_pub_debt_out_amt&sort=record_date&page%5Bsize%5D=10000&page%5Bnumber%5D=1" \
   "$RAW/fd_debt_to_penny.json" "Debt to the Penny"
dl "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_1?filter=record_date:gte:${START_YEAR}-01-01&fields=record_date,security_type_desc,security_class_desc,total_mil_amt&sort=record_date&page%5Bsize%5D=10000&page%5Bnumber%5D=1" \
   "$RAW/fd_mspd_table1.json" "MSPD 债务结构"

echo "== TIC 海外持仓 =="
dl "https://ticdata.treasury.gov/Publish/mfhhis01.txt" \
   "$RAW/tic_mfhhis01.txt" "TIC 历史(2001-)"
dl "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/slt_table5.txt" \
   "$RAW/tic_slt_table5.txt" "TIC 最新(SLT T5)"

echo "== 日本对比模块 (2018-) =="
# 美元/日元 汇率 (FRED DEXJPUS)
# 两个坑: ① fred.stlouisfed.org 的 CA 吊销检查不可达, 必须带 -k;
#         ② 发送浏览器 UA 会被对端重置连接 (curl rc=56), 故用 dl_noua 不发送自定义 UA。
dl_noua "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS&cosd=2018-01-01" \
   "$RAW/fx_usdjpy.csv" "美元日元 DEXJPUS" "-k"
# 日本财务省 国债利率 (Shift-JIS 编码, 日本年号日期); 全历史文件约 1.2MB 需较长超时
dl "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv" \
   "$RAW/jp_jgbcm_all.csv" "JGB 利率全历史" "" 180
dl "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv" \
   "$RAW/jp_jgbcm_current.csv" "JGB 利率当年"

echo "== 抓取完成, 失败项: $FAIL =="
exit 0
