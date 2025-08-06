import aiohttp
import pandas as pd
from sklearn.linear_model import LinearRegression
import asyncio
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from waitress import serve
import os
import sys
import traceback
from jsonschema import validate, ValidationError

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask應用
app = Flask(__name__)

# Navi API端點
POOLS_API = "https://open-api.naviprotocol.io/api/navi/pools"
REWARDS_API = "https://open-api.naviprotocol.io/api/navi/user/rewards?userAddress={userAddress}"

# 預測請求Schema
predict_schema = {
    "type": "object",
    "properties": {
        "apr": {"type": "number"},
        "tvl": {"type": "number"},
        "sui_price": {"type": "number"}
    },
    "required": ["apr", "tvl", "sui_price"]
}

# 模擬多日數據
def simulate_historical_data(latest_data, days=30):
    try:
        base_time = datetime.fromtimestamp(int(latest_data.get("lastUpdateTimestamp", str(int(datetime.now().timestamp() * 1000))) / 1000))
        base_apr = float(latest_data.get("supplyIncentiveApyInfo", {}).get("apy", 4.908))
        base_tvl = float(latest_data.get("totalSupplyAmount", 52969686454591258)) / 1e9
        base_price = float(latest_data.get("oracle", {}).get("price", 4.34833514))
        df = pd.DataFrame({
            "timestamp": [base_time - timedelta(days=i) for i in range(days)],
            "apr": [base_apr * (1 + 0.01 * (i % 5)) for i in range(days)],
            "tvl": [base_tvl * (1 - 0.005 * (i % 7)) for i in range(days)],
            "sui_price": [base_price * (1 + 0.02 * (i % 3)) for i in range(days)]
        })
        logger.debug(f"模擬歷史數據（前5筆）: {df.to_dict('records')[:5]}")
        return df
    except Exception as e:
        logger.error(f"模擬數據失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        return None

# 獲取Volo質押池數據
async def fetch_volo_data(pool_id="0x2::sui::SUI", days=30):
    async with aiohttp.ClientSession() as session:
        try:
            logger.debug(f"請求Navi Pools API: {POOLS_API}")
            async with session.get(POOLS_API, timeout=10) as response:
                logger.debug(f"Navi Pools API響應狀態: {response.status}")
                if response.status != 200:
                    logger.error(f"獲取Pools API失敗: {response.status}")
                    return {"error": f"無法獲取Navi Pools數據: HTTP {response.status}"}, 500
                data = await response.json()
                logger.debug(f"Navi Pools API原始數據（前2筆）: {data[:2]}")
                for pool in data:
                    if pool.get("coinType") == pool_id:
                        df = simulate_historical_data(pool, days)
                        if df is None:
                            return {"error": "數據模擬失敗"}, 500
                        logger.info(f"成功獲取SUI/vSUI池數據: APR={df['apr'][0]}%, TVL={df['tvl'][0]} SUI")
                        return {
                            "latest": {
                                "apr": float(pool.get("supplyIncentiveApyInfo", {}).get("apy", 4.908)),
                                "tvl": float(pool.get("totalSupplyAmount", 52969686454591258)) / 1e9,
                                "sui_price": float(pool.get("oracle", {}).get("price", 4.34833514)),
                                "timestamp": pool.get("lastUpdateTimestamp", str(int(datetime.now().timestamp() * 1000)))
                            },
                            "historical": df.to_dict('records')
                        }, 200
                logger.warning("未找到SUI/vSUI池，使用預設數據")
                default_data = {
                    "lastUpdateTimestamp": str(int(datetime.now().timestamp() * 1000)),
                    "supplyIncentiveApyInfo": {"apy": "4.908"},
                    "totalSupplyAmount": "52969686454591258",
                    "oracle": {"price": "4.34833514"}
                }
                df = simulate_historical_data(default_data, days)
                if df is None:
                    return {"error": "預設數據模擬失敗"}, 500
                logger.debug(f"預設池數據: {default_data}")
                return {
                    "latest": {
                        "apr": 4.908,
                        "tvl": 52969686454591258 / 1e9,
                        "sui_price": 4.34833514,
                        "timestamp": default_data["lastUpdateTimestamp"]
                    },
                    "historical": df.to_dict('records')
                }, 200
        except Exception as e:
            logger.error(f"獲取數據失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
            return {"error": f"獲取數據失敗: {str(e)}"}, 500

# 獲取用戶獎勵
async def fetch_rewards(user_address, pool_id="0x96df0fce3c471489f4debaaa762cf960b3d97820bd1f3f025ff8190730e958c5"):
    async with aiohttp.ClientSession() as session:
        try:
            logger.debug(f"請求Rewards API: {REWARDS_API.format(userAddress=user_address)}")
            async with session.get(REWARDS_API.format(userAddress=user_address), timeout=10) as response:
                logger.debug(f"Rewards API響應狀態: {response.status}")
                if response.status != 200:
                    logger.error(f"獲取Rewards API失敗: {response.status}")
                    return [], 200
                data = await response.json()
                logger.debug(f"Rewards API原始數據（前2筆）: {data[:2]}")
                rewards = [
                    {
                        "amount": float(reward.get("amount", 0)) / 1e9,
                        "timestamp": reward.get("timestamp", ""),
                        "token_price": float(reward.get("token_price", 0.144426003098488))
                    }
                    for reward in data
                    if reward.get("pool", "") == pool_id and reward.get("coin_type", "").endswith("::navx::NAVX")
                ]
                logger.info(f"獲取獎勵: {len(rewards)}筆")
                return rewards, 200
        except Exception as e:
            logger.error(f"獲取獎勵失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
            return [], 200

# AI預測最佳質押時機
def predict_optimal_stake(df):
    if df is None or len(df) < 5:
        logger.warning("數據不足，無法預測")
        return False
    try:
        X = df[["sui_price", "tvl"]]
        y = df["apr"]
        model = LinearRegression().fit(X, y)
        predicted_apr = model.predict(X[-1:])
        avg_apr = df["apr"].mean()
        logger.info(f"預測APR: {predicted_apr[0]:.2f}%，平均APR: {avg_apr:.2f}%")
        return predicted_apr[0] > avg_apr * 1.1
    except Exception as e:
        logger.error(f"預測失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        return False

# API端點：獲取池數據
@app.route("/api/volo-data", methods=["GET"])
def get_volo_data():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        data, status = loop.run_until_complete(fetch_volo_data())
        logger.debug(f"返回池數據: {data['latest'] if 'latest' in data else data}")
        return jsonify(data), status
    except Exception as e:
        logger.error(f"處理池數據失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        return jsonify({"error": f"處理數據失敗: {str(e)}"}), 500
    finally:
        loop.close()

# API端點：獲取獎勵
@app.route("/api/rewards", methods=["GET"])
def get_rewards():
    user_address = request.args.get("user_address")
    if not user_address:
        logger.error("缺少user_address參數")
        return jsonify({"error": "缺少user_address參數"}), 400
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        rewards, status = loop.run_until_complete(fetch_rewards(user_address))
        logger.debug(f"返回獎勵數據（前2筆）: {rewards[:2]}")
        return jsonify(rewards), status
    except Exception as e:
        logger.error(f"處理獎勵數據失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        return jsonify([]), 200
    finally:
        loop.close()

# API端點：AI預測
@app.route("/api/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("無輸入數據")
        validate(instance=data, schema=predict_schema)
        df = pd.DataFrame([{
            "apr": data["apr"],
            "tvl": data["tvl"],
            "sui_price": data["sui_price"]
        }])
        prediction = predict_optimal_stake(df)
        logger.debug(f"AI預測結果: {prediction}")
        return jsonify({"predict": prediction}), 200
    except ValidationError as e:
        logger.error(f"預測輸入無效: {str(e)} - 堆棧: {traceback.format_exc()}")
        return jsonify({"error": "無效輸入數據"}), 400
    except Exception as e:
        logger.error(f"預測失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        return jsonify({"error": f"預測失敗: {str(e)}"}), 500

# 啟動服務
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Server running on http://localhost:{port}")
    try:
        serve(app, host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"服務器啟動失敗: {str(e)} - 堆棧: {traceback.format_exc()}")
        sys.exit(1)