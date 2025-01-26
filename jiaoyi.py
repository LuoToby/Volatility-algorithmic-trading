import time
import math
import logging
import decimal
import hmac
import hashlib
import requests
from urllib.parse import urlencode

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# 替换为你的 Binance API Key 和 Secret
api_key = "z1F3RxmK59r0DfRDYC7Tzb8Q7A0c2TqgwybOLIbdiakLxyCdQuMjSzUziy91GQIj"
api_secret = "e7WSzlwMXoGRvBqdZlcqKLdEk1RKOlSu7AvOd5xCDkt63pXHP8qga1yNvw0Hkmhk"
# Binance API 基础 URL
base_url = 'https://fapi.binance.com'

# 策略参数
symbol = "DOGEUSDT"
leverage = 75
risk_percentage = 0.01  # 按账户余额的10%用于交易
monitor_interval = 1  # 监控间隔，单位为秒
profit_target = 6.0  # 止盈阀值，默认为 6%
stop_loss_threshold = -3.0  # 止损阀值，默认为 -3%
price_change_threshold = 0.05  # 价格变动阀值，默认为 0.05%

# 签名请求
def sign_request(params):
    query_string = urlencode(params)
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    params['signature'] = signature
    return params

# 获取服务器时间
def get_server_time():
    response = requests.get(base_url + '/fapi/v1/time')
    return response.json()['serverTime']

# 获取账户持仓模式
def get_position_mode():
    timestamp = get_server_time()
    params = {
        'timestamp': timestamp
    }
    params = sign_request(params)
    headers = {'X-MBX-APIKEY': api_key}
    response = requests.get(base_url + '/fapi/v1/positionSide/dual', params=params, headers=headers)
    data = response.json()
    if 'dualSidePosition' in data:
        if data['dualSidePosition']:
            logger.info("账户处于对冲模式（Hedge Mode）。")
            return 'HEDGE'
        else:
            logger.info("账户处于单向模式（One-Way Mode）。")
            return 'ONE_WAY'
    else:
        logger.error(f"获取持仓模式时出错：{data}")
        return None

# 设置杠杆倍数
def set_leverage():
    timestamp = get_server_time()
    params = {
        'symbol': symbol,
        'leverage': leverage,
        'timestamp': timestamp
    }
    params = sign_request(params)
    headers = {'X-MBX-APIKEY': api_key}
    response = requests.post(base_url + '/fapi/v1/leverage', params=params, headers=headers)
    data = response.json()
    if 'leverage' in data:
        logger.info(f"杠杆已设置为 {data['leverage']}x")
    else:
        logger.error(f"设置杠杆时出错：{data}")

# 获取交易对的信息，包括精度和最小下单单位
def get_symbol_info():
    response = requests.get(base_url + '/fapi/v1/exchangeInfo')
    exchange_info = response.json()
    for info in exchange_info['symbols']:
        if info['symbol'] == symbol:
            min_notional = None
            step_size = None
            precision = None
            for f in info['filters']:
                if f['filterType'] == 'MIN_NOTIONAL':
                    min_notional = float(f['notional'])
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    precision = int(round(-math.log(step_size, 10), 0))
            return min_notional, step_size, precision
    # 默认值
    return 5.0, 1.0, 0

# 调整下单数量，符合精度要求
def adjust_quantity(quantity, step_size, precision):
    adjusted_qty = decimal.Decimal(quantity).quantize(decimal.Decimal(step_size), rounding=decimal.ROUND_DOWN)
    return float(round(adjusted_qty, precision))

# 获取当前市场价格
def get_current_price():
    response = requests.get(base_url + '/fapi/v1/ticker/price', params={'symbol': symbol})
    data = response.json()
    return float(data['price'])

# 获取账户余额
def get_usdt_balance():
    timestamp = get_server_time()
    params = {
        'timestamp': timestamp
    }
    params = sign_request(params)
    headers = {'X-MBX-APIKEY': api_key}
    response = requests.get(base_url + '/fapi/v2/balance', params=params, headers=headers)
    balances = response.json()
    for item in balances:
        if item['asset'] == 'USDT':
            return float(item['balance'])
    return 0.0

# 获取当前持仓信息
def get_positions():
    timestamp = get_server_time()
    params = {
        'timestamp': timestamp
    }
    params = sign_request(params)
    headers = {'X-MBX-APIKEY': api_key}
    response = requests.get(base_url + '/fapi/v2/positionRisk', params=params, headers=headers)
    positions = response.json()
    positions = [pos for pos in positions if pos['symbol'] == symbol and float(pos['positionAmt']) != 0.0]
    return positions

# 下市价单函数，根据持仓模式调整订单参数
def place_order_market(side, quantity, position_side=None, reduce_only=False):
    attempt = 0
    max_attempts = 3  # 限制重试次数
    while attempt < max_attempts:
        try:
            timestamp = get_server_time()
            params = {
                'symbol': symbol,
                'side': side,
                'type': 'MARKET',
                'quantity': quantity,
                'timestamp': timestamp,
            }

            position_mode = get_position_mode()

            if position_mode == 'HEDGE':
                # 对冲模式下，使用 positionSide 参数，不使用 reduceOnly
                params['positionSide'] = position_side
            elif position_mode == 'ONE_WAY':
                # 单向模式下，不使用 positionSide，根据需要使用 reduceOnly
                if reduce_only:
                    params['reduceOnly'] = 'true'

            params = sign_request(params)
            headers = {'X-MBX-APIKEY': api_key}
            logger.info(f"下单参数：{params}")
            response = requests.post(base_url + '/fapi/v1/order', params=params, headers=headers)
            data = response.json()
            logger.info(f"下单响应：{data}")

            if 'orderId' in data:
                return data['orderId']
            else:
                logger.error(f"下单失败：{data}")
                if 'code' in data and data['code'] == -2022:
                    # ReduceOnly Order is rejected
                    logger.error("ReduceOnly Order is rejected. 请检查订单参数。")
                    return None
        except Exception as e:
            logger.error(f"下市价单时出错：{e}，重试中...")

        attempt += 1
        time.sleep(1)  # 重试前等待1秒

    logger.error("多次尝试后下市价单失败。")
    return None

# 平仓函数，根据持仓模式和持仓信息平仓
def close_position(position_info):
    if not position_info:
        logger.error("没有持仓需要平仓。")
        return False

    position_amt = abs(float(position_info['positionAmt']))
    position_side = position_info['positionSide']
    position_amt_raw = position_info['positionAmt']
    # 平仓时，方向与持仓相反
    side = 'SELL' if float(position_amt_raw) > 0 else 'BUY'

    # 获取交易对精度信息
    _, step_size, precision = get_symbol_info()
    position_amt = adjust_quantity(position_amt, step_size, precision)

    logger.info(f"尝试平仓。方向：{side}，数量：{position_amt}，持仓方向：{position_side}")

    attempt = 0
    max_attempts = 5
    while attempt < max_attempts:
        position_mode = get_position_mode()
        if position_mode == 'HEDGE':
            # 对冲模式下，使用 positionSide 参数，不使用 reduceOnly
            order_id = place_order_market(side, position_amt, position_side=position_side)
        elif position_mode == 'ONE_WAY':
            # 单向模式下，不使用 positionSide，使用 reduceOnly=True
            order_id = place_order_market(side, position_amt, reduce_only=True)
        else:
            logger.error("无法确定账户的持仓模式，无法平仓。")
            return False

        if order_id:
            logger.info("成功平仓。")
            return True
        else:
            logger.error("下平仓单失败，重试中...")
        attempt += 1
        time.sleep(1)  # 等待1秒后重试
    logger.error("多次尝试后平仓失败。")
    return False

# 主策略函数
def trading_strategy():
    # 获取账户持仓模式
    position_mode = get_position_mode()
    if not position_mode:
        logger.error("无法获取账户的持仓模式，退出程序。")
        return

    set_leverage()
    price_history = []
    average_price = None
    min_notional, step_size, precision = get_symbol_info()

    while True:
        try:
            current_price = get_current_price()
            if current_price is None:
                time.sleep(monitor_interval)
                continue

            logger.info(f"当前价格：{current_price}")

            # 更新价格历史，用于计算平均价格
            price_history.append(current_price)
            if len(price_history) > 100:
                price_history.pop(0)
            average_price = sum(price_history) / len(price_history)
            logger.info(f"平均价格：{average_price}")

            # 获取当前持仓信息
            positions = get_positions()
            if positions:
                # 遍历所有持仓，分别处理
                for position in positions:
                    position_info = {
                        'positionAmt': position['positionAmt'],
                        'entryPrice': float(position['entryPrice']),
                        'unRealizedProfit': float(position['unRealizedProfit']),
                        'positionSide': position.get('positionSide', 'BOTH'),
                    }

                    logger.info(f"当前持仓：{position_info}")

                    entry_price = position_info['entryPrice']
                    position_amt = float(position_info['positionAmt'])
                    position_side = position_info['positionSide']
                    unrealized_profit = position_info['unRealizedProfit']

                    # 计算初始保证金
                    initial_margin = (entry_price * abs(position_amt)) / leverage
                    if initial_margin == 0:
                        logger.error("初始保证金为零，无法计算盈利百分比。")
                        continue

                    # 计算未实现利润百分比
                    unrealized_profit_percentage = (unrealized_profit / initial_margin) * 100
                    logger.info(f"未实现利润：{unrealized_profit_percentage:.2f}%")

                    # 当盈利或亏损超过设定阀值时平仓
                    if unrealized_profit_percentage >= profit_target or unrealized_profit_percentage <= stop_loss_threshold:
                        success = close_position(position_info)
                        if success:
                            logger.info("持仓已平仓，等待新的机会。")
                            price_history.clear()  # 清空价格历史，重新开始
                        else:
                            logger.warning("多次尝试后平仓失败，停止交易。")
                            return  # 如果无法平仓，退出程序
                        time.sleep(monitor_interval)
                        continue
                    else:
                        # 持仓未满足平仓条件，继续监控
                        logger.info("持仓未满足平仓条件，继续监控。")
                time.sleep(monitor_interval)
                continue
            else:
                # 没有持仓，检查是否满足开仓条件
                usdt_balance = get_usdt_balance()

                # 计算下单数量
                quantity = get_minimum_quantity(current_price, usdt_balance, min_notional, step_size, precision)
                notional = quantity * current_price
                logger.info(f"计算的下单数量：{quantity}, 名义价值：{notional}")

                if notional < min_notional:
                    logger.warning(f"订单名义价值（{notional}）小于最小要求（{min_notional}），跳过此机会。")
                    time.sleep(monitor_interval)
                    continue

                # 判断价格相对于平均价格的变化
                price_change = (current_price - average_price) / average_price
                price_change_percentage = price_change * 100
                logger.info(f"价格相对于平均价格的变化：{price_change_percentage:.2f}%")

                if abs(price_change_percentage) >= price_change_threshold:
                    side = 'BUY' if price_change > 0 else 'SELL'
                    position_side = 'LONG' if side == 'BUY' else 'SHORT'

                    # 调整数量精度
                    quantity = adjust_quantity(quantity, step_size, precision)

                    logger.info(f"尝试下单：方向：{side}, 持仓方向：{position_side}, 数量：{quantity}")

                    if position_mode == 'HEDGE':
                        # 对冲模式下，使用 positionSide 参数
                        order_id = place_order_market(side, quantity, position_side=position_side)
                    elif position_mode == 'ONE_WAY':
                        # 单向模式下，不使用 positionSide
                        order_id = place_order_market(side, quantity)
                    else:
                        logger.error("无法确定账户的持仓模式，无法下单。")
                        return

                    if order_id:
                        logger.info(f"已在价格 {current_price} 下单。")
                        # 开仓后，进入下一次循环监控持仓
                        time.sleep(monitor_interval)
                        continue
                    else:
                        logger.error("由于保证金不足或其他错误，无法开仓。")
                        # 无法开仓，等待下一次机会
                        time.sleep(monitor_interval)
                        continue

            time.sleep(monitor_interval)
        except Exception as e:
            logger.error(f"交易循环中发生意外错误：{e}")
            time.sleep(monitor_interval)

# 获取最小下单数量，确保订单名义价值大于最小名义价值
def get_minimum_quantity(current_price, balance, min_notional, step_size, precision):
    notional_value = balance * risk_percentage  # 使用账户余额的10%
    max_notional = notional_value * leverage  # 考虑杠杆后的最大名义价值
    min_quantity = max(max_notional / current_price, min_notional / current_price)
    # 调整为合约的最小数量单位
    min_quantity = adjust_quantity(min_quantity, step_size, precision)
    return max(min_quantity, float(step_size))  # 确保至少下单最小单位

# 主函数
if __name__ == "__main__":
    try:
        logger.info("开始执行交易策略...")
        trading_strategy()
    except KeyboardInterrupt:
        logger.info("交易策略已被用户停止。")
