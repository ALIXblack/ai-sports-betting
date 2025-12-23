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
    【修复版】强力提取数据，不挑食模式
    """
    print("正在连接竞彩官方API获取数据...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(DATA_API_URL, headers=headers, timeout=15)
        raw_data = response.json()
        
        # 调试打印：把API返回的前200个字打出来，确认真的拿到数据了
        print(f"API 响应状态: {raw_data.get('errorMessage', '无消息')}")

        clean_matches = []
        
        # 暴力穿透：直接找所有列表
        match_groups = raw_data.get('value', {}).get('matchInfoList', [])
        
        for group in match_groups:
            sub_list = group.get('subMatchList', [])
            for m in sub_list:
                # 1. 既然是预测，如果没有胜平负(had)赔率，我们尝试拿不让球赔率
                # 有时候数据里 key 叫 had, 有时候可能有变体，这里做多重防护
                odds = m.get('had', {})
                
                # 如果 odds 是空的，或者里面全是空字符串，说明没开盘
                if not odds or odds == {}:
                    # 为了测试，哪怕没赔率也先把比赛抓下来看看！
                    h_odd = "未开售"
                else:
                    h_odd = odds.get('h', '0')

                # 2. 只有当比赛状态是 Selling (销售中) 才提取
                # (如果你想看所有比赛，把下面这行 if 注释掉)
                # if m.get('matchStatus') != 'Selling':
                #    continue

                match_item = {
                    "league": m.get('leagueAbbName', m.get('leagueAllName', '未知联赛')),
                    "time": f"{m.get('matchDate')} {m.get('matchTime')}",
                    "home": m.get('homeTeamAbbName', m.get('homeTeamAllName', '主队')),
                    "away": m.get('awayTeamAbbName', m.get('awayTeamAllName', '客队')),
                    "odds": {
                        "主胜": odds.get('h', '-'),
                        "平": odds.get('d', '-'),
                        "客胜": odds.get('a', '-')
                    }
                }
                clean_matches.append(match_item)

        print(f"========================================")
        print(f"【调试信息】共提取到 {len(clean_matches)} 场比赛")
        if len(clean_matches) > 0:
            print(f"第一场数据示例: {clean_matches[0]}")
        print(f"========================================")
        
        return clean_matches

    except Exception as e:
        print(f"严重错误: 解析数据时崩溃 - {e}")
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
