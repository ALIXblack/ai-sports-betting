import os
import requests
import json
import google.generativeai as genai
from datetime import datetime

# 1. 配置环境
ODDS_API_KEY = os.environ.get("ODDS_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# 2. 获取数据 (以英超为例，key可以换成其他联赛)
# 免费版 Odds API 额度有限，这里演示获取英超(soccer_epl)
def get_odds():
    url = f'https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={ODDS_API_KEY}&regions=uk&markets=h2h&oddsFormat=decimal'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error getting odds: {response.text}")
        return []

# 3. AI 预测逻辑
def predict_matches(odds_data):
    # 如果没有比赛数据，直接返回空
    if not odds_data:
        return {"error": "No matches found today."}

    # 为了节省 Token，只取前5场比赛给 AI 演示
    matches_snippet = json.dumps(odds_data[:5]) 
    
    # 核心 Prompt
    prompt = f"""
    你是一个精通足球赛事预测的AI专家。
    请分析以下 JSON 数据中的比赛赔率（h2h表示胜平负赔率）：
    {matches_snippet}
    
    请结合你的知识库（关于球队实力、历史表现），对每场比赛进行胜/平/负的预测。
    
    【重要】请必须只输出一段标准的 JSON 代码，不要包含 ```json 标记，格式如下，不要说废话：
    [
        {{
            "match": "Team A vs Team B",
            "prediction": "Home Win",
            "confidence": "High/Medium/Low",
            "reason": "简短的一句话理由"
        }}
    ]
    """
    
    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    try:
        response = model.generate_content(prompt)
        # 清洗一下 AI 可能带回来的 markdown 符号
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        return {"error": str(e), "raw_response": response.text}

# 4. 执行并保存
def main():
    print("Starting job...")
    odds = get_odds()
    print(f"Fetched {len(odds)} matches.")
    
    prediction = predict_matches(odds)
    
    final_output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "The Odds API + Gemini 1.5 Pro",
        "predictions": prediction
    }
    
    # 写入文件
    with open("result.json", "w", encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
    print("Detailed prediction saved to result.json")

if __name__ == "__main__":
    main()
