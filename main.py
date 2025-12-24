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
    "NBA", "EuroLeague", "NBL", # 篮球
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
    try:
        dt_utc = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_bj = dt_utc.astimezone(timezone(timedelta(hours=8)))
        return dt_bj
    except:
        return datetime.now()

def generate_mock_ids(match_obj, index):
    """
    生成仿真 ID 和 编号
    【修复点】：这里现在正确引用 visit_team
    """
    dt_bj = utc_to_beijing(match_obj['commence_time'])
    
    # 唯一标识字符串
    unique_str = f"{match_obj['home_team']}{match_obj['visit_team']}{match_obj['commence_time']}"
    # 生成 hash 数字 ID
    hash_val = int(hashlib.sha256(unique_str.encode('utf-8')).hexdigest(), 16) % 10000000
    event_id = str(2000000 + hash_val) 
    
    # 生成 num (周X + 序号)
    weekday_str = WEEKDAY_MAP[dt_bj.weekday()]
    num_str = f"{weekday_str}{str(index + 1).zfill(3)}" 
    
    return event_id, num_str, dt_bj.strftime("%Y-%m-%d %H:%M:%S")

# ================= 核心逻辑 =================

def get_all_matches():
    """获取所有即将开始的比赛并筛选白名单"""
    print("正在连接 The Odds API 获取全球赛事池...")
    # 增加 regions=us,au 以确保 NBA 和 澳洲赛事能出来
    url = f'https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={ODDS_API_KEY}&regions=uk,eu,us,au&markets=h2h&oddsFormat=decimal'
    
    try:
        response = requests.get(url, timeout=25)
        if response.status_code != 200:
            print(f"API Error: {response.text}")
            return []
            
        raw_data = response.json()
        print(f"API 原始返回 {len(raw_data)} 场比赛，正在清洗...")
        
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
            
            # 优先找主流公司
            selected_bookie = bookmakers[0]
            for b in bookmakers:
                if b['key'] in ['williamhill', 'bet365', 'pinnacle', 'unibet']:
                    selected_bookie = b
                    break
            
            markets = selected_bookie.get('markets', [])
            if not markets: continue
            
            outcomes = markets[0].get('outcomes', [])
            
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
            
            # 篮球处理
            if odds_map['odds_1'] == "":
                odds_map['odds_1'] = "0.00"

            # 存入列表，使用 visit_team 统一命名
            target_matches.append({
                "source_league": league_name,
                "home_team": home_team,
                "visit_team": away_team, # 对应 KeyError 的修复点
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
    # 增加 translated query 尝试获取更准确信息
    query = f"{home} vs {away} {league} match prediction injury news lineups"
    try:
        # 随机休眠
        time.sleep(random.uniform(2, 4))
        results = DDGS().text(query, max_results=2)
        summary = ""
        if results:
            for r in results:
                summary += f"{r['body']}\n"
        return summary
    except:
        return "网络情报暂时不可用，模型将基于赔率和基本面数据库进行分析。"

def get_ai_prediction(match_info, intel, formatted_obj):
    """调用 AI 生成分析"""
    
    prompt = f"""
    你是一位拥有20年经验的资深体育评论员。
    
    【比赛信息】
    赛事：{formatted_obj['league']}
    对阵：{formatted_obj['host_team']} (主) vs {formatted_obj['visit_team']} (客)
    赔率数据：主胜 {formatted_obj['odds_3']} | 平 {formatted_obj['odds_1']} | 客胜 {formatted_obj['odds_0']}
    
    【最新情报】
    {intel}
    
    【写作要求】
    1. **深度分析 (200字左右)**：分析两队近况、关键球员伤停对技战术的影响、以及主客场因素。
    2. **禁止废话**：绝对不要以“从赔率来看”、“根据数据显示”、“综上所述”这种模版式语句开头。直接切入主题，例如：“曼城近期中场控制力明显下降...”。
    3. **预测结果**：明确给出胜平负方向。
    
    【必须输出 JSON】
    {{
        "prediction_result": "主胜/平/客胜",
        "analysis_text": "你的深度分析文案..."
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
    print("=== 全网主流赛事全自动预测系统启动 (Pro V2) ===")
    
    raw_matches = get_all_matches()
    
    if not raw_matches:
        print("未获取到比赛数据。")
        # 输出空列表保持格式正确
        with open("result.json", "w", encoding='utf-8') as f:
            json.dump([], f)
        return

    final_output_list = []
    
    # 根据你反馈只需要主流赛事，这里稍微放宽处理限制到 25 场
    # 如果比赛太多，GitHub Action 可能会跑满6小时，建议分批，但 25 场通常没问题
    matches_to_process = raw_matches[:25]
    
    print(f"准备深度分析前 {len(matches_to_process)} 场热门比赛...")
    
    for i, match in enumerate(matches_to_process):
        # 1. 格式化基础数据
        event_id, num_str, start_time_bj = generate_mock_ids(match, i)
        
        # 简单的中文清洗
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
        
        print(f"[{i+1}/{len(matches_to_process)}] {formatted_obj['host_team']} vs {formatted_obj['visit_team']}")
        
        # 2. 搜集情报
        intel_text = search_intel(match['home_team'], match['visit_team'], match['source_league'])
        
        # 3. AI 深度预测
        ai_res = get_ai_prediction(match, intel_text, formatted_obj)
        
        if ai_res:
            formatted_obj['ai_prediction'] = ai_res.get('prediction_result', '未知')
            formatted_obj['ai_analysis'] = ai_res.get('analysis_text', '暂无分析')
        else:
            formatted_obj['ai_prediction'] = "分析中"
            formatted_obj['ai_analysis'] = "数据获取超时，请关注临场指数变化。"
            
        final_output_list.append(formatted_obj)
        
        # 4. 冷却防封
        time.sleep(random.uniform(2, 4))

    # 保存最终结果
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output_list, f, ensure_ascii=False, indent=4)
        
    print(f"=== 任务完成，生成 {len(final_output_list)} 条预测数据 ===")

if __name__ == "__main__":
    main()
