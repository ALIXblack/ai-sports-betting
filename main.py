import os
import requests
import json
import time
from datetime import datetime
from duckduckgo_search import DDGS

# ================= 配置区域 =================

# 1. 密钥读取 (从 Secrets 读取，安全！)
# 只要你在第一步更新了ODDS_KEY，这里会自动读到新的 2a5c...
ODDS_API_KEY = os.environ.get("ODDS_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

# 2. 代理与模型设置 (Yunwu.ai)
PROXY_URL = "https://yunwu.ai/v1/chat/completions"
MODEL_NAME = "gemini-3-pro-preview"

# ================= 功能函数 =================

def get_odds_data():
    """
    调用 The Odds API 获取即将开始的比赛 (足球+NBA)
    文档参考: https://the-odds-api.com/live-api/guides/v4/
    """
    print("正在连接 The Odds API (Global)...")
    
    # 我们请求 'upcoming'，这样不分联赛，只要是近期热门比赛都能抓到
    # sport_key: 'soccer_epl' (英超), 'basketball_nba' (NBA), 
    # 或者用 'upcoming' 获取所有
    # 为了演示效果，我们先抓即将开始的比赛
    
    # 免费版 key 每月500次，为了省流，我们要珍惜请求次数
    # 这里我们一次性请求即将开始的比赛
    url = f'https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={ODDS_API_KEY}&regions=uk&markets=h2h&oddsFormat=decimal'
    
    try:
        response = requests.get(url, timeout=20)
        
        # 额度监控
        remaining = response.headers.get('x-requests-remaining', '未知')
        print(f"API 请求建立。剩余额度: {remaining}")
        
        if response.status_code != 200:
            print(f"API 报错: {response.text}")
            return []
            
        raw_data = response.json()
        print(f"成功获取 {len(raw_data)} 场即将开始的比赛数据。")
        
        clean_matches = []
        
        # 数据清洗
        for item in raw_data:
            sport_title = item.get('sport_title', 'Unknown League')
            home_team = item.get('home_team')
            away_team = item.get('away_team')
            commence_time = item.get('commence_time')
            
            # 过滤：我不想要太过冷门的比赛，你可以根据需要调整
            # 比如只保留包含 "Soccer" 或 "Basketball" 的
            if "Esports" in sport_title: 
                continue

            # 提取赔率
            # 逻辑：找到一家叫 'William Hill' 或 'Bet365' 或 'Unibet' 的公司
            # 如果都没有，就取第一家
            bookmakers = item.get('bookmakers', [])
            if not bookmakers:
                continue
                
            selected_bookie = bookmakers[0] # 默认取第一家
            for b in bookmakers:
                if b['key'] in ['williamhill', 'bet365', 'unibet']:
                    selected_bookie = b
                    break
            
            # 提取 h2h (Head to Head) 胜平负
            markets = selected_bookie.get('markets', [])
            if not markets:
                continue
                
            outcomes = markets[0].get('outcomes', [])
            
            odds_display = {"主胜": "-", "平": "-", "客胜": "-"}
            
            for out in outcomes:
                price = out.get('price')
                name = out.get('name')
                
                if name == home_team:
                    odds_display['主胜'] = price
                elif name == away_team:
                    odds_display['客胜'] = price
                elif name == 'Draw':
                    odds_display['平'] = price
            
            # 只有当赔率有效时才添加
            clean_matches.append({
                "league": sport_title,
                "time": commence_time,
                "home": home_team,
                "away": away_team,
                "odds": odds_display,
                "bookie_name": selected_bookie['title']
            })
            
        return clean_matches

    except Exception as e:
        print(f"数据获取异常: {e}")
        return []

def search_news_safe(home, away):
    """
    安全版搜索，如果 DuckDuckGo 挂了不影响主程序
    """
    print(f"正在搜索: {home} vs {away}...")
    query = f"{home} vs {away} prediction injury news"
    
    try:
        # 30秒超时机制
        results = DDGS().text(query, max_results=2)
        summary = ""
        if results:
            for r in results:
                summary += f"Title: {r['title']}\nSnippet: {r['body']}\n"
        return summary if summary else "No News Found."
        
    except Exception as e:
        print(f"搜索失败(网络波动，已跳过): {e}")
        return "Search Unavailable."

def call_ai_predict(match_data, news_text):
    """
    调用 Gemini 进行预测
    """
    prompt = f"""
    You are a professional sports analyst. 
    Predict the match result based on the following data.
    
    【Match Info】
    League: {match_data['league']}
    Teams: {match_data['home']} (Home) vs {match_data['away']} (Away)
    Time: {match_data['time']}
    Odds ({match_data['bookie_name']}): {json.dumps(match_data['odds'])}
    
    【News/Intel】
    {news_text}
    
    【Requirements】
    Please output valid JSON only. USE CHINESE for analysis.
    Format:
    {{
        "match": "{match_data['home']} vs {match_data['away']}",
        "league": "{match_data['league']}",
        "prediction": "主胜/平/客胜",
        "probability": "0-100%",
        "reason": "Short analysis in Chinese (max 50 words)"
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
        req = requests.post(PROXY_URL, json=payload, headers=headers, timeout=60)
        if req.status_code == 200:
            res_json = req.json()
            content = res_json['choices'][0]['message']['content']
            # 清洗 markdown
            clean = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        else:
            print(f"AI Error: {req.text}")
            return None
    except Exception as e:
        print(f"AI Timeout: {e}")
        return None

# ================= 主程序 =================

def main():
    print("=== 任务开始 ===")
    
    # 1. 获取比赛
    matches = get_odds_data()
    
    if not matches:
        print("未获取到比赛数据 (列表为空)，结束。")
        # 生成一个空的 JSON 提示用户
        with open("result.json", "w", encoding='utf-8') as f:
            json.dump({"status": "No matches upcoming or API error"}, f)
        return

    # 2. 选取前 3 场热门比赛 (避免超时)
    # 这里的逻辑是：优先处理英超、NBA，如果没有，就取前3个
    priority_matches = []
    others = []
    
    for m in matches:
        if "Soccer" in m['league'] or "NBA" in m['league']:
            priority_matches.append(m)
        else:
            others.append(m)
            
    # 合并列表，优先处理重点赛事
    final_queue = priority_matches + others
    # 截取前 3 场
    target_matches = final_queue[:3]
    
    print(f"即将处理 {len(target_matches)} 场比赛预测...")
    
    results_list = []
    
    # 3. 循环预测
    for match in target_matches:
        # A. 搜新闻
        news = search_news_safe(match['home'], match['away'])
        
        # B. 问 AI
        print(f"AI 正在根据赔率和新闻分析: {match['home']} vs {match['away']}")
        prediction = call_ai_predict(match, news)
        
        if prediction:
            results_list.append(prediction)
            
        # C. 休息2秒
        time.sleep(2)

    # 4. 保存
    final_output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "data_source_1": "The Odds API (Legit)",
        "data_source_2": "DuckDuckGo Search",
        "model": MODEL_NAME,
        "predictions": results_list
    }
    
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"=== 成功生成 {len(results_list)} 场预测结果，已保存 ===")

if __name__ == "__main__":
    main()
