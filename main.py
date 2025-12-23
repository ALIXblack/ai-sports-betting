import os
import requests
import json
import time
from datetime import datetime
from duckduckgo_search import DDGS

# ================= 配置区域 =================

# 1. 密钥配置
# 对于这个特定的API，其实不需要ODDS_KEY，但为了保持结构我们留着
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

# 2. 代理与模型设置 (Yunwu.ai)
PROXY_URL = "https://yunwu.ai/v1/chat/completions"
MODEL_NAME = "gemini-3-pro-preview"

# 3. 数据源地址 (竞彩官方接口)
DATA_API_URL = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c&poolCode=had"

# ================= 功能函数 =================

def get_domestic_data():
    """
    从竞彩官方API获取数据，并清洗为 AI 可读的标准格式
    """
    print("正在连接竞彩官方API获取数据...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(DATA_API_URL, headers=headers, timeout=10)
        response.raise_for_status()
        raw_data = response.json()
        
        # 1. 检查 API 是否成功
        if not raw_data.get('success'):
            print("API 返回错误:", raw_data.get('errorMessage'))
            return []

        clean_matches = []
        
        # 2. 解析复杂的嵌套结构
        # 结构：value -> matchInfoList (按日期分组) -> subMatchList (比赛列表)
        match_groups = raw_data.get('value', {}).get('matchInfoList', [])
        
        for group in match_groups:
            sub_list = group.get('subMatchList', [])
            
            for m in sub_list:
                # 3. 提取核心字段
                league = m.get('leagueAllName', '未知联赛')
                match_time = f"{m.get('matchDate')} {m.get('matchTime')}"
                home_team = m.get('homeTeamAllName', '主队')
                away_team = m.get('awayTeamAllName', '客队')
                
                # 4. 提取赔率 (字段名为 had)
                # had 结构: {'h': '1.37', 'd': '4.05', 'a': '6.70'}，代表 主胜/平/客胜
                odds_info = m.get('had', {})
                
                # 如果这场比赛没有开售胜平负(had为空)，则跳过
                if not odds_info or not odds_info.get('h'):
                    continue

                # 整理好的单场数据
                match_item = {
                    "league": league,
                    "time": match_time,
                    "home": home_team,
                    "away": away_team,
                    "odds": {
                        "主胜": odds_info.get('h'),
                        "平": odds_info.get('d'),
                        "客胜": odds_info.get('a')
                    }
                }
                clean_matches.append(match_item)

        print(f"成功获取并清洗了 {len(clean_matches)} 场比赛数据。")
        return clean_matches

    except Exception as e:
        print(f"获取数据失败: {e}")
        return []

def search_injury_news(home_team, away_team):
    """
    DuckDuckGo 搜索两队的最新伤病/新闻
    """
    print(f"正在搜索情报: {home_team} vs {away_team} ...")
    # 构造搜索词，增加"足球"关键词提高准确度
    query = f"{home_team} vs {away_team} 预测 伤病 缺席 首发 足球"
    news_summary = ""
    
    try:
        # max_results=2 稍微减少一点，提高速度
        results = DDGS().text(query, max_results=2)
        if results:
            for r in results:
                news_summary += f"- {r['title']}: {r['body']}\n"
        else:
            news_summary = "暂无具体即时伤病新闻。"
    except Exception as e:
        print(f"搜索服务跳过: {e}")
        news_summary = "搜索暂不可用。"
        
    return news_summary

def call_gemini_proxy(prompt):
    """
    调用 Yunwu.ai (Gemini-3)
    """
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system", 
                "content": "你是一个专业的足球赛事精算师。你的任务是基于赔率和基本面新闻预测赛果。请务必输出合法的JSON格式。"
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.5 # 稍微降低温度，让预测更理性
    }
    
    try:
        response = requests.post(PROXY_URL, headers=headers, json=payload, timeout=50)
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            # 清洗 markdown 代码块符号
            clean_content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_content)
        else:
            print(f"AIAPI Error: {response.text}")
            return {"error": "AI调用失败", "details": response.text}
            
    except Exception as e:
        print(f"AI Net Error: {e}")
        return {"error": str(e)}

# ================= 主程序 =================

def main():
    # 1. 抓取真实数据
    matches = get_domestic_data()
    
    if not matches:
        print("没有获取到比赛数据，结束任务。")
        return

    predictions_list = []
    
    # 2. 遍历比赛 (控制数量，防止超时)
    # 每次运行处理前 6 场比赛。
    # 如果你想处理更多，请修改 [:6] 为 [:10] 或者直接去掉切片
    target_matches = matches[:6]

    for match in target_matches:
        home = match['home']
        away = match['away']
        
        # 3. 搜索新闻
        news = search_injury_news(home, away)
        
        # 4. 构造 Prompt
        prompt = f"""
        【赛事数据】
        联赛：{match['league']}
        时间：{match['time']}
        对阵：{home} (主) vs {away} (客)
        官方竞彩赔率：{json.dumps(match['odds'], ensure_ascii=False)}
        
        【网络搜索情报】
        {news}
        
        【预测任务】
        请结合上述赔率（注意：1.x通常代表强队，高赔率代表弱队）和情报，预测比赛结果。
        
        【输出格式要求】
        请仅返回一个JSON对象（不要列表，不要Markdown），包含以下字段：
        {{
            "match": "{home} vs {away}",
            "prediction_result": "主胜 / 平 / 客胜",
            "win_probability": "胜率数值（例如 75%）",
            "score_prediction": "预测比分（例如 2:1）",
            "analysis": "简短分析（50字以内）"
        }}
        """
        
        print(f"AI 正在思考: {home} vs {away}...")
        ai_result = call_gemini_proxy(prompt)
        
        if ai_result:
            predictions_list.append(ai_result)
        
        # 休息 2 秒用于防封
        time.sleep(2)

    # 5. 保存结果
    final_output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Sporttery Official + Gemini 3 Pro + DuckDuckGo",
        "total_matches_found": len(matches),
        "results": predictions_list
    }
    
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print("任务全部完成，结果已保存。")

if __name__ == "__main__":
    main()
