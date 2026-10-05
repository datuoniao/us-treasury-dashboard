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

dl() { # dl <url> <outfile> [desc]
  local url="$1" out="$2" desc="${3:-$2}"
  local i
  for i in 1 2 3; do
    if curl -sSL --max-time 45 \
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

echo "== 抓取完成, 失败项: $FAIL =="
exit 0
