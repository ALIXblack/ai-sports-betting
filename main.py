import os
import requests
import json
import time
import random
from datetime import datetime
from duckduckgo_search import DDGS

# ================= 配置区域 =================

ODDS_API_KEY = os.environ.get("ODDS_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

PROXY_URL = "https://yunwu.ai/v1/chat/completions"
MODEL_NAME = "gemini-3-pro-preview"

# 【核心升级1】主流赛事白名单
# 只有包含以下关键词的联赛才会被处理。
# 你可以根据需要添加：'Chinese' (中超), 'J League' (日职联), 'Champions' (欧冠)
TARGET_KEYWORDS = [
    "NBA", 
    "Premier League",   # 英超
    "La Liga",          # 西甲
    "Bundesliga",       # 德甲
    "Serie A",          # 意甲
    "Ligue 1",          # 法甲
    "Chinese Super",    # 中超
    "Champions League", # 欧冠/亚冠
    "EuroLeague",       # 欧篮
    "Africa Cup"        # 非洲杯 (当前热门)
]

# ================= 功能函数 =================

def get_odds_data():
    """
    获取数据并进行白名单筛选
    """
    print("正在连接 The Odds API 获取全球赛事...")
    
    # 获取即将开始的比赛 (upcoming)
    url = f'https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={ODDS_API_KEY}&regions=uk&markets=h2h&oddsFormat=decimal'
    
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            print(f"API 异常: {response.text}")
            return []
            
        raw_data = response.json()
        print(f"API 返回了 {len(raw_data)} 场比赛，正在筛选主流赛事...")
        
        filtered_matches = []
        
        for item in raw_data:
            sport_title = item.get('sport_title', '')
            
            # --- 筛选逻辑 ---
            # 检查联赛名是否包含我们定义的关键词之一
            is_target = False
            for keyword in TARGET_KEYWORDS:
                if keyword in sport_title:
                    is_target = True
                    break
            
            if not is_target:
                continue # 如果不是主流联赛，跳过
            # ----------------
            
            home_team = item.get('home_team')
            away_team = item.get('away_team')
            commence_time = item.get('commence_time')
            
            # 提取赔率
            bookmakers = item.get('bookmakers', [])
            if not bookmakers: 
                continue
                
            # 优选主注公司
            selected_bookie = bookmakers[0]
            for b in bookmakers:
                if b['key'] in ['williamhill', 'bet365', 'unibet', 'pinnacle']:
                    selected_bookie = b
                    break
            
            markets = selected_bookie.get('markets', [])
            if not markets: continue
            
            outcomes = markets[0].get('outcomes', [])
            odds_display = {"主胜": "-", "平": "-", "客胜": "-"}
            
            for out in outcomes:
                price = out.get('price')
                name = out.get('name')
                if name == home_team: odds_display['主胜'] = price
                elif name == away_team: odds_display['客胜'] = price
                elif name == 'Draw': odds_display['平'] = price
            
            filtered_matches.append({
                "league": sport_title,
                "time": commence_time,
                "home": home_team,
                "away": away_team,
                "odds": odds_display,
                "bookie": selected_bookie['title']
            })
            
        print(f"筛选完毕！共保留 {len(filtered_matches)} 场主流重点赛事。")
        return filtered_matches

    except Exception as e:
        print(f"数据获取严重错误: {e}")
        return []

def search_news_detailed(home, away, league):
    """
    【核心升级2】针对伤病和名单的深度搜索
    """
    print(f"正在搜集情报: {home} vs {away}...")
    
    # 构造更精准的搜索词，包含 "injuries" (伤病) 和 "lineups" (阵容)
    # 针对中文环境用户，我们可以让搜索词混合一点，但英文源通常更新更快
    query = f"{home} vs {away} {league} injury news predicted lineups stats"
    
    try:
        # 增加随机等待，模拟人类，防止被 DuckDuckGo 封锁
        time.sleep(random.uniform(1.5, 3.5))
        
        results = DDGS().text(query, max_results=3) # 获取前3条新闻
        summary = ""
        if results:
            for r in results:
                summary += f"【Source: {r['title']}】\n{r['body']}\n"
        else:
            summary = "无具体网络伤病情报，仅基于历史实力分析。"
            
        return summary
        
    except Exception as e:
        print(f"搜索触发反爬风控/超时，跳过: {e}")
        return "网络搜索暂时不可用，模型将基于赔率和知识库预测。"

def call_ai_predict(match_data, news_text):
    """
    Gemini 预测模块
    """
    # 构造针对性 Prompt
    prompt = f"""
    You are a professional football/basketball analyst (Expert Bettor).
    
    【Task】
    Predict the match result based on Odds (Market Confidence) and News (Injuries/Lineups).
    
    【Match Information】
    - League: {match_data['league']}
    - Match: {match_data['home']} (Home) vs {match_data['away']} (Away)
    - Time (UTC): {match_data['time']}
    - Live Odds ({match_data['bookie']}): {json.dumps(match_data['odds'])}
    
    【Intelligence (Injuries & Lineups)】
    {news_text}
    
    【Instruction】
    1. Analyze the implied probability from the odds (Low odds = High probability).
    2. Consider any major injuries mentioned in the intelligence.
    3. Output strictly in JSON.
    
    【Output JSON Format】
    {{
        "match": "{match_data['home']} vs {match_data['away']}",
        "league": "{match_data['league']}",
        "prediction_result": "Home Win / Draw / Away Win (Choose one)",
        "win_probability": "XX%",
        "key_analysis": "Write a sharp analysis in CHINESE (中文). Mention key injuries if any.",
        "risk_level": "High/Medium/Low"
    }}
    """
    
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4 # 降低温度，让预测更保守稳定
    }
    
    try:
        req = requests.post(PROXY_URL, json=payload, headers=headers, timeout=60)
        if req.status_code == 200:
            res_json = req.json()
            content = res_json['choices'][0]['message']['content']
            clean = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        else:
            print(f"AI API Failed: {req.text}")
            return None
    except Exception as e:
        print(f"AI Timeout: {e}")
        return None

# ================= 主程序 =================

def main():
    print("=== 全自动预测任务启动 (Mainstream Batch) ===")
    
    # 1. 获取并筛选比赛
    matches = get_odds_data()
    
    if not matches:
        print("未找到符合条件的主流赛事。")
        with open("result.json", "w", encoding='utf-8') as f:
            json.dump({"status": "No mainstream matches found today"}, f)
        return

    # 【重要】为了防止比赛非常多导致超时（GitHub Action限制6小时，但我们最好控制在10分钟内）
    # 如果比赛超过 15 场，我们只取前 15 场（此时列表已经是我们想要的白名单赛事了）
    # 15场 * 10秒/场 = 2.5分钟，非常安全
    max_matches = 15
    target_matches = matches[:max_matches]
    
    print(f"今日主流赛事共 {len(matches)} 场，将处理前 {len(target_matches)} 场...")
    
    predictions = []
    
    # 2. 批量处理
    for i, match in enumerate(target_matches):
        print(f"\n--- 处理进度 [{i+1}/{len(target_matches)}] : {match['home']} vs {match['away']} ---")
        
        # A. 深度搜索
        news = search_news_detailed(match['home'], match['away'], match['league'])
        
        # B. AI 预测
        ai_res = call_ai_predict(match, news)
        
        if ai_res:
            predictions.append(ai_res)
        else:
            print("该场次 AI 预测失败，跳过。")
            
        # C. 随机长休眠 (非常重要！)
        #为了不让 DDG 封IP，每处理完一场，休息 3-6 秒
        sleep_time = random.uniform(3, 6)
        print(f"冷却 {sleep_time:.1f} 秒...")
        time.sleep(sleep_time)

    # 3. 最终交付
    final_output = {
        "update_time_utc": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_matches_predicted": len(predictions),
        "source": "Official Odds + Web Intelligence + Gemini",
        "results": predictions
    }
    
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"\n=== 任务全部完成，共生成 {len(predictions)} 场预测 ===")

if __name__ == "__main__":
    main()
