import os
import requests
import json
import time
from datetime import datetime
from duckduckgo_search import DDGS

# ================= 配置区域 =================
# 1. 从 Github Secrets 获取 Key
ODDS_API_KEY = os.environ.get("ODDS_KEY")     # 这里是你的国内API Key
GEMINI_API_KEY = os.environ.get("GEMINI_KEY") # 这里是你的 Yunwu.ai Key

# 2. 代理设置
PROXY_URL = "https://yunwu.ai/v1/chat/completions" # 通常代理都用这个OpenAI兼容路径
MODEL_NAME = "gemini-3-pro-preview"

# ================= 功能函数 =================

def get_domestic_data():
    """
    【请修改这里】获取国内 API 的实时盘口数据
    """
    print("正在从国内接口获取比赛数据...")
    
    # ------------------------------------------------------------------
    # TODO: 请在这个位置替换为你真实的国内 API 调用代码
    # 示例代码（假设你的国内API是这个格式，请根据实际情况修改 URL 和参数）：
    # url = "http://api.tuijian.com/matches/today"
    # params = {"key": ODDS_API_KEY, "league": "Premier League"}
    # response = requests.get(url, params=params)
    # return response.json() 
    # ------------------------------------------------------------------
    
    # !!! 假如你还没填写真实API，为了防止报错，我这里先模拟一条假数据供测试 !!!
    # 当你接入真实API后，请删除下面的模拟数据
    mock_data = [
        {
            "league": "英超",
            "match_time": "2024-05-20 22:00",
            "home_team": "曼城",
            "away_team": "西汉姆联",
            "odds": {"胜": 1.15, "平": 8.00, "负": 15.00}
        },
        {
            "league": "中超",
            "match_time": "2024-05-20 19:35",
            "home_team": "上海海港",
            "away_team": "成都蓉城",
            "odds": {"胜": 1.65, "平": 3.80, "负": 4.50}
        }
    ]
    return mock_data

def search_injury_news(home_team, away_team):
    """
    利用 DuckDuckGo 搜索两队的最新伤病名单
    """
    print(f"正在搜索伤病信息: {home_team} vs {away_team} ...")
    search_query = f"{home_team} vs {away_team} 伤病名单 缺席球员 最新新闻"
    news_summary = ""
    
    try:
        # 使用 DDGS 进行搜索 (max_results控制搜索条数，避免超时)
        results = DDGS().text(search_query, max_results=3)
        if results:
            for r in results:
                news_summary += f"- {r['title']}: {r['body']}\n"
        else:
            news_summary = "未搜索到相关具体的即时伤病新闻。"
    except Exception as e:
        print(f"搜索出错: {e}")
        news_summary = "搜索服务暂时不可用。"
        
    return news_summary

def call_gemini_proxy(prompt):
    """
    通过 Yunwu.ai 代理调用 Gemini-3
    """
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 构造 OpenAI 兼容格式的消息体
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "你是一个专业的体育赛事精算师。请直接输出JSON格式结果。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(PROXY_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            # 提取回复内容
            content = result['choices'][0]['message']['content']
            # 清洗一下 markdown 格式
            clean_content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_content)
        else:
            print(f"AI 请求失败: {response.status_code} - {response.text}")
            return {"error": "AI Service Unreachable"}
            
    except Exception as e:
        print(f"AI 连接异常: {e}")
        return {"error": str(e)}

# ================= 主程序 =================

def main():
    # 1. 获取比赛列表
    matches = get_domestic_data()
    
    if not matches:
        print("今日无比赛数据或API调用失败")
        return

    predictions_list = []

    # 2. 循环处理每场比赛 (为了演示稳定，这里只取前3场，你可以去掉 [:3])
    # 实际生产中建议每次处理 5-10 场，避免超时
    for match in matches[:5]: 
        home = match.get('home_team')
        away = match.get('away_team')
        
        # 3. 实时搜索伤病
        news = search_injury_news(home, away)
        
        # 4. 组装给 AI 的 Prompt
        prompt = f"""
        【比赛信息】
        赛事：{match.get('league')}
        时间：{match.get('match_time')}
        对阵：{home} (主) vs {away} (客)
        盘口数据：{json.dumps(match.get('odds'), ensure_ascii=False)}
        
        【网络搜索到的最新情报/伤病】
        {news}
        
        【任务】
        请根据盘口赔率和最新的伤病情报，预测本场比赛的胜平负。
        
        【必须输出格式】
        请仅返回一个 JSON 对象，格式如下：
        {{
            "match": "{home} vs {away}",
            "prediction_result": "主胜/平/客胜",
            "win_probability": "XX%",
            "analysis": "请用200字左右分析理由"
        }}
        """
        
        # 5. 调用 AI
        print(f"正在请求 AI 预测: {home} vs {away}...")
        ai_result = call_gemini_proxy(prompt)
        
        # 容错处理：如果AI返回列表或其他结构，统一放到列表里
        if isinstance(ai_result, list):
            predictions_list.extend(ai_result)
        else:
            predictions_list.append(ai_result)
            
        # 稍微暂停一下，防止并发太快被封
        time.sleep(2)

    # 6. 生成最终结果
    final_output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_used": MODEL_NAME,
        "results": predictions_list
    }
    
    # 7. 写入 result.json
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print("====================================")
    print("所有预测已完成，结果已保存至 result.json")
    print("====================================")

if __name__ == "__main__":
    main()
