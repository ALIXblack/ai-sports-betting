import os
import requests
import json
import time
import random
import hashlib
from datetime import datetime, timedelta, timezone
from duckduckgo_search import DDGS

# ================= 配置区域 =================

ODDS_API_KEY = os.environ.get("ODDS_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

PROXY_URL = "https://yunwu.ai/v1/chat/completions"
MODEL_NAME = "gemini-3-pro-preview"

# 定义主流赛事关键词白名单 (覆盖你要的所有联赛)
MATCH_WHITELIST = [
    "Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1", # 五大联赛
    "Champions League", "Europa", # 欧战
    "Chinese Super", # 中超
    "NBA", "EuroLeague", # 篮球
    "Africa Cup", "Asian Cup", # 杯赛
    "FA Cup", "EFL Cup"
]

# 映射星期几 (0=周一, 6=周日)
WEEKDAY_MAP = {
    0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"
}

# ================= 工具函数 =================

def utc_to_beijing(utc_str):
    """将 UTC 时间字符串转为北京时间对象"""
    # API 格式: 2024-12-25T20:30:00Z
    try:
        dt_utc = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_bj = dt_utc.astimezone(timezone(timedelta(hours=8)))
        return dt_bj
    except:
        return datetime.now()

def generate_mock_ids(match_obj, index):
    """
    因为 The Odds API 没有竞彩的 event_id 和 num (周三001)，
    我们需要根据时间生成仿真数据以符合你的 JSON 格式要求。
    """
    dt_bj = utc_to_beijing(match_obj['commence_time'])
    
    # 生成仿真 event_id (基于 hash)
    unique_str = f"{match_obj['home_team']}{match_obj['away_team']}{match_obj['commence_time']}"
    hash_val = int(hashlib.sha256(unique_str.encode('utf-8')).hexdigest(), 16) % 10000000
    event_id = str(2000000 + hash_val) # 模拟 2036xxx
    
    # 生成仿真 num (周X + 序号)
    weekday_str = WEEKDAY_MAP[dt_bj.weekday()]
    # 简单的序号逻辑，保证不重复
    num_str = f"{weekday_str}{str(index + 1).zfill(3)}" 
    
    return event_id, num_str, dt_bj.strftime("%Y-%m-%d %H:%M:%S")

# ================= 核心逻辑 =================

def get_all_matches():
    """获取所有即将开始的比赛并筛选白名单"""
    print("正在连接 The Odds API 获取全球赛事池...")
    # 请求 upcoming，这会返回各大洲的比赛
    url = f'https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={ODDS_API_KEY}&regions=uk,eu&markets=h2h&oddsFormat=decimal'
    
    try:
        response = requests.get(url, timeout=25)
        if response.status_code != 200:
            print(f"API Error: {response.text}")
            return []
            
        raw_data = response.json()
        print(f"API 原始返回 {len(raw_data)} 场比赛，正在进行主流赛事清洗...")
        
        target_matches = []
        
        for item in raw_data:
            league_name = item.get('sport_title', '')
            
            # 1. 白名单筛选
            is_mainstream = False
            for keyword in MATCH_WHITELIST:
                if keyword in league_name:
                    is_mainstream = True
                    break
            
            if not is_mainstream:
                continue
                
            # 2. 提取赔率
            bookmakers = item.get('bookmakers', [])
            if not bookmakers: continue
            
            # 优先找 Bet365 或 William Hill
            selected_bookie = bookmakers[0]
            for b in bookmakers:
                if b['key'] in ['williamhill', 'bet365', 'pinnacle']:
                    selected_bookie = b
                    break
            
            markets = selected_bookie.get('markets', [])
            if not markets: continue
            
            outcomes = markets[0].get('outcomes', [])
            
            # 映射赔率：odds_3(主), odds_1(平), odds_0(客)
            # 注意：篮球通常没有平局(moneyline)，需要处理
            odds_map = {"odds_3": "", "odds_1": "", "odds_0": ""}
            home_team = item.get('home_team')
            away_team = item.get('away_team')
            
            for out in outcomes:
                if out['name'] == home_team:
                    odds_map['odds_3'] = str(out['price'])
                elif out['name'] == away_team:
                    odds_map['odds_0'] = str(out['price'])
                elif out['name'] == 'Draw':
                    odds_map['odds_1'] = str(out['price'])
            
            # 篮球可能没有平赔，设为 "-" 或 "0.00"
            if odds_map['odds_1'] == "":
                odds_map['odds_1'] = "0.00"

            target_matches.append({
                "source_league": league_name,
                "home_team": home_team,
                "visit_team": away_team,
                "commence_time": item.get('commence_time'),
                "odds_data": odds_map
            })
            
        print(f"筛选完成：共锁定 {len(target_matches)} 场主流赛事。")
        return target_matches

    except Exception as e:
        print(f"获取数据失败: {e}")
        return []

def search_intel(home, away, league):
    """搜索伤病和新闻"""
    print(f"正在挖掘情报: {home} vs {away}...")
    query = f"{home} vs {away} {league} team news injury lineups prediction"
    try:
        # 随机休眠防止封号
        time.sleep(random.uniform(2, 4))
        results = DDGS().text(query, max_results=3)
        summary = ""
        if results:
            for r in results:
                summary += f"{r['body']}\n"
        return summary
    except:
        return "无网络情报，基于基本面分析。"

def get_ai_prediction(match_info, intel, formatted_obj):
    """调用 AI 生成 200字 深度分析"""
    
    prompt = f"""
    你是一位拥有20年经验的资深足球/篮球赛事评论员。你的风格是犀利、专业、一针见血，通过球队近期技战术状态、伤病影响和历史交锋来判断比赛走势。
    
    【比赛信息】
    赛事：{formatted_obj['league']}
    对阵：{formatted_obj['host_team']} (主) vs {formatted_obj['visit_team']} (客)
    胜平负赔率：主胜({formatted_obj['odds_3']}) | 平({formatted_obj['odds_1']}) | 客胜({formatted_obj['odds_0']})
    
    【网络情报】
    {intel}
    
    【任务要求】
    1. 预测比赛结果（胜/平/负）。
    2. 写一段约 200 字的深度分析。
    3. **禁止**以“从赔率来看”、“威廉希尔显示”等废话开头。直接切入球队状态、核心球员伤缺、主客场战力对比。
    4. 必须输出严格的 JSON 格式。
    
    【输出 JSON 格式】
    {{
        "prediction_result": "主胜/平/客胜",
        "analysis_text": "这里写你的200字分析内容..."
    }}
    """
    
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }
    
    try:
        req = requests.post(PROXY_URL, json=payload, headers=headers, timeout=50)
        if req.status_code == 200:
            res = req.json()
            content = res['choices'][0]['message']['content']
            clean = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
    except Exception as e:
        print(f"AI Error: {e}")
    
    return None

# ================= 主程序 =================

def main():
    print("=== 全网主流赛事全自动预测系统启动 ===")
    
    raw_matches = get_all_matches()
    
    if not raw_matches:
        print("无比赛数据。")
        return

    final_output_list = []
    
    # 限制处理数量，虽然我们想跑所有，但为了防止 GitHub Action 超时（免费版有限制）
    # 我们设定一个较高的上限，比如 30 场。
    process_limit = 30
    matches_to_process = raw_matches[:process_limit]
    
    print(f"准备处理 {len(matches_to_process)} 场比赛...")
    
    for i, match in enumerate(matches_to_process):
        # 1. 格式化基础数据 (构造用户要求的严格 JSON 结构)
        event_id, num_str, start_time_bj = generate_mock_ids(match, i)
        
        # 汉化联赛名 (简单映射，如果是复杂英文 AI 会在分析里自动处理)
        league_cn = match['source_league'].replace("Soccer", "").replace("Basketball", "").strip()
        
        formatted_obj = {
            "event_id": event_id,
            "start_time": start_time_bj,
            "league": league_cn,
            "host_team": match['home_team'],
            "visit_team": match['visit_team'],
            "num": num_str,
            "odds_3": match['odds_data']['odds_3'],
            "odds_1": match['odds_data']['odds_1'],
            "odds_0": match['odds_data']['odds_0'],
            "status": "未开始"
        }
        
        print(f"[{i+1}/{len(matches_to_process)}] 分析: {formatted_obj['host_team']} vs {formatted_obj['visit_team']}")
        
        # 2. 搜集情报
        intel_text = search_intel(match['home_team'], match['visit_team'], match['source_league'])
        
        # 3. AI 深度预测
        ai_res = get_ai_prediction(match, intel_text, formatted_obj)
        
        if ai_res:
            # 将 AI 的结果合并进对象
            formatted_obj['ai_prediction'] = ai_res.get('prediction_result', '未知')
            formatted_obj['ai_analysis'] = ai_res.get('analysis_text', '暂无分析')
            
            final_output_list.append(formatted_obj)
        else:
            # 如果AI失败，至少保留基础数据
            formatted_obj['ai_prediction'] = "分析超时"
            formatted_obj['ai_analysis'] = "AI 服务繁忙，仅提供数据参考。"
            final_output_list.append(formatted_obj)
            
        # 4. 冷却防封
        time.sleep(random.uniform(2, 5))

    # 保存最终结果 (严格列表格式)
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output_list, f, ensure_ascii=False, indent=4)
        
    print(f"=== 任务完成，已生成 {len(final_output_list)} 场比赛的深度分析 ===")

if __name__ == "__main__":
    main()
