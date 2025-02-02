import threading
import time
import my_function
from binance_api import MyClient
from unicorn_binance_websocket_api.manager import BinanceWebSocketApiManager
import talib
import numpy as np
import my_telegram
import json
import logging
import traceback

from utils import *
# from utils import check_rsi_condition

class MyBot:

    def __init__(self, client: MyClient):
        self.client = client
        self.bm = BinanceWebSocketApiManager(process_stream_data=self.update_socket_futures,
                                             exchange="binance.com-futures", output_default='dict',
                                             disable_colorama=True, stream_buffer_maxlen=1, close_timeout_default=60,
                                             ping_interval_default=60, ping_timeout_default=60)
        self.work = True  # Для работы (можно оптимизировать под визуал, или тг. бота, запускать перезапускать бота и т.д.)

        # Параметры
        self.symbol = 'TWTUSDT'  # Рабочая монета
        self.timeframe = '5m'  # Рабочий таймфрейм
        self.big_timeframe = '4h'  # Таймфрейм подтверждения.
        self.piramiding = 15  # Макс. количество ордеров
        self.qty_usdt = 15  # обьем ордера в USDT
        self.qty = 20  # Объём монеты которы продаём - покупаем.
        self.take_percent = 1  # Процент профита на котором закрываемся.
        self.name_candle = 'close'  # close - расчет по цене закрытия можно поставить: open, high, low, close
        self.limit = 150  # Количество загружаемых свечей

        self.ema_period = 100  # Период машки
        self.ema_percent_diff = 1  # Отклонение от машки (вниз)

        self.rsi_max = 49  # Верхняя граница RSI
        self.rsi_min = 35  # Нижняя граница RSI 30
        self.rsi_period = 12  # Период RSI
        self.big_rsi_min = 35  # Если рсай большого тф, выше этого значения. значит можем шортить.

        self.radius_diff = 2  # Если в этом радиусе цены (вверх-вниз) уже была сделка, то в этой цене не входим.
        self.distance_down = 1.5
        self.distance_up = 0

        # Используемые в коде параметры
        self.ema = {tf: [] for tf in self.client.timeframes}
        self.rsi = {tf: [] for tf in self.client.timeframes}
        self.price = 0.0  # Текущая цена (по закрытию свечи)
        self.price_5 = 0.0  # цена на -5 свече
        self.price_2 = 0.0  # цена на -2 свече
        # self.orders = []  # Ордера в виде списка. при покупке снова None
        # self.values = []  # объемы собираем в список
        self.data = {}
        self.close_candle_time = {tf: [] for tf in self.client.timeframes}  # Время закрытия свечи
        self.socket = None  # Сокет для онлайн-обновления свечей
        self.candles = {tf: [] for tf in self.client.timeframes}  # Список свечей.
        self.lastsell = 0
        self.ema_difff = 1
        self.flag_ord = 1

    def save_data_to_json(self, filename):
        with open(filename, 'w') as f:
            json.dump(self.data, f)

    def load_data_from_json(self, filename):
        try:
            with open(filename, 'r') as f:
                self.data = json.load(f)
        except FileNotFoundError:
            print("JSON file not found. Starting with empty data.")
            self.data = {}


    # def update_socket(self, msg, stream_buffer_name='False'):
    #     """Получает значения свечей"""
    #     try:
    #         if msg.get('stream'):
    #             candle = msg['data']['k']
    #             timeframe = candle['i']
    #             if msg['data']['k']['x']:
    #                 candle_new = {'close_time': candle['T'],
    #                               'open': float(candle['o']),
    #                               'close': float(candle['c']),
    #                               'high': float(candle['h']),
    #                               'low': float(candle['l']), }
    #                 self.candles[timeframe].append(candle_new)
    #                 self.candles[timeframe].pop(0)
    #                 return
    #             else:
    #                 self.candles[timeframe][-1]['close_time'] = candle['T']
    #                 self.candles[timeframe][-1]['open'] = float(candle['o'])
    #                 self.candles[timeframe][-1]['close'] = float(candle['c'])
    #                 self.candles[timeframe][-1]['high'] = float(candle['h'])
    #                 self.candles[timeframe][-1]['low'] = float(candle['l'])
    #     except Exception as err:
    #         print('error socket', err)

    def update_socket_futures(self, msg, stream_buffer_name='False'):
        """Получает значения свечей"""
        try:
            if msg.get('stream'):
                candle = msg['data']['k']
                timeframe = candle['i']
                if msg['data']['k']['x']:
                    candle_new = {'close_time': candle['T'],
                                  'open': float(candle['o']),
                                  'close': float(candle['c']),
                                  'high': float(candle['h']),
                                  'low': float(candle['l']), }
                    self.candles[timeframe].append(candle_new)
                    self.candles[timeframe].pop(0)
                    return
                else:
                    self.candles[timeframe][-1]['close_time'] = candle['T']
                    self.candles[timeframe][-1]['open'] = float(candle['o'])
                    self.candles[timeframe][-1]['close'] = float(candle['c'])
                    self.candles[timeframe][-1]['high'] = float(candle['h'])
                    self.candles[timeframe][-1]['low'] = float(candle['l'])
        except Exception as err:
            print('error socket', err)

    def start_socket(self):
        """Стартует сокет"""
        # Если таймфреймов нет, то выход.
        if not self.timeframe in self.client.timeframes or not self.big_timeframe in self.client.timeframes:
            print(f'error timeframe {self.timeframe}')
            return

        # Перед стартом сокета соберем нужные свечи
        self.candles[self.timeframe] = self.client.get_candlesticks(self.symbol, self.timeframe, self.limit,
                                                                    market='futures', returned='dict')
        self.candles[self.big_timeframe] = self.client.get_candlesticks(self.symbol, self.big_timeframe, self.limit,
                                                                        market='futures', returned='dict')

        # Старт сокетов
        channels = ['kline_' + self.timeframe, 'kline_' + self.big_timeframe]
        markets = [self.symbol.lower(), ]
        self.socket = self.bm.create_stream(channels, markets)
        print(f'start klines {self.timeframe} sockets', self.symbol)

    # def start_socket(self):
    #     """Стартует сокет"""
    #     # Если таймфреймов нет, то выход.
    #     if not self.timeframe in self.client.timeframes or not self.big_timeframe in self.client.timeframes:
    #         print(f'error timeframe {self.timeframe}')
    #         return
    #
    #     # Перед стартом сокета соберем нужные свечи
    #     self.candles[self.timeframe] = self.client.get_candlesticks(self.symbol, self.timeframe, self.limit,
    #                                                                 returned='dict', market='spot')
    #     self.candles[self.big_timeframe] = self.client.get_candlesticks(self.symbol, self.big_timeframe, self.limit,
    #                                                                     returned='dict', market='spot')
    #
    #     # Старт сокетов
    #     channels = ['kline_' + self.timeframe, 'kline_' + self.big_timeframe]
    #     markets = [self.symbol.lower(), ]
    #     self.socket = self.bm.create_stream(channels, markets)
    #     print(f'start klines {self.timeframe} sockets', self.symbol)

    def stop_socket(self, maximum=False):
        """maximum - полностью выключает сокеты (окончание работы кода)"""
        self.candles = list()
        if not self.socket is None:
            self.bm.stop_stream(self.socket)
        if maximum:
            self.bm.stop_manager_with_all_streams()

    def update_inds(self):
        """Обновляет значения индикаторов"""
        try:
            for frame, candles in self.candles.items():
                if candles:
                    self.close_candle_time[frame] = candles[-1]['close_time'] / 1000
                    prices = np.array([p[self.name_candle] for p in candles])
                    self.ema[frame] = talib.EMA(prices, timeperiod=self.ema_period).tolist()
                    self.rsi[frame] = talib.RSI(prices, timeperiod=self.rsi_period).tolist()
                    self.price = prices[-1]
                    self.price_5 = prices[-5]
                    self.price_2 = prices[-2]
        except Exception as err:
            print('error update_inds', err.__traceback__.tb_lineno, err)

    def check_trade(self):
        # order = self.client.futures_market_order(self.symbol, 'SELL', self.qty, "LONG")
        # print("Ордер")
        # time.sleep(100)
        """Проверяет можно ли торговать и торгует."""
        try:
            #order = self.client.futures_market_order(self.symbol, 'SELL', self.qty, "SHORT")
            #time.sleep(1000)
            #order = self.client.futures_market_order(self.symbol, 'BUY', self.qty, "SHORT")

            # Проверяем можем ли продать.
            if len(self.data) > 0 and my_function.check_rsi_condition_short(self.rsi, self.timeframe, self.rsi_max):
                qw, new_data = my_function.two_orders(self.flag_ord, self.take_percent, self.price, self.data)
                if qw is not None:
                    order = self.client.futures_market_order(self.symbol, 'SELL', qw, 'LONG')
                    if order['like']:
                        self.data = new_data
                        self.flag_ord = 0
                        print(f'close position, send market order SELL {self.symbol} close price {self.price}')
                        message_to_send = f'LONG_Закрыт объем {qw} {self.symbol} по цене {self.price} \n {self.data}'

                        my_telegram.send_to_user(my_telegram.your_user_id, message_to_send)
                    else:
                        print(f'error send marker order BUY {self.symbol} qty {qw}, close price {self.price}')


            # Проверяем можем ли мы купить.
            if my_function.check_rsi_condition(self.rsi, self.timeframe, self.rsi_min) and len(self.data) == 0:
                print("Первое условие выполнено")
                if my_function.chek_ema_dif(self.ema[self.timeframe][-1], self.price, self.ema_percent_diff):
                    self.qty = round(self.qty_usdt/self.price, 2)
                    order = self.client.futures_market_order(self.symbol, 'BUY', self.qty, 'LONG')
                    if order['like']:
                        self.data[self.price] = self.qty
                        self.flag_ord = 0
                        print(f'market order sell {self.symbol} qty {self.qty}')
                        message_to_send = f'LONG_Открыта сделка на объем {self.qty} {self.symbol} по цене {self.price} \n {self.data}' \

                        my_telegram.send_to_user(my_telegram.your_user_id, message_to_send)
                    else:
                        print('error send order symbol', self.symbol, 'qty', self.qty, 'BUY')
            else:
                    # Если уже есть открытая сделка
                if (len(self.data) > 0 and my_function.check_rsi_condition(self.rsi, self.timeframe, self.rsi_min)) or ((100-(self.price/self.price_5 * 100)) > 6 and len(self.data) > 0):  # my_function.ema_trand(self.ema[self.timeframe][-1], self.timeframe)
                    # and my_function.ema_trand(self.ema, self.timeframe)
                    last_key = float(list(self.data.keys())[-1])
                    last_value = list(self.data.values())[-1]
                    if self.price < (last_key - (last_key * self.radius_diff / 100)):

                            # qty = round(((len(self.data)) / self.price - 1) / 0.1 + 1) * last_value
                        qty_next = round(((((last_key - self.price) / (last_key / 100)) / 10) + 1) * (self.qty_usdt/self.price))    #* last_value)
                        order = self.client.futures_market_order(self.symbol, 'BUY', qty_next, 'LONG')
                        if order['like']:
                                # self.lastsell = float(self.price)
                                # self.orders.append(self.lastsell)
                                # self.values.append(qty)
                            self.flag_ord = 1   # разрешаем два ордера
                            self.data[self.price] = qty_next

                            print(f'send market order sell {self.symbol} qty {qty_next} all orders {len(self.data)}')
                            message_to_send = f'LONG_Усреднение на объем {qty_next} {self.symbol} по цене {self.price} \n {self.data}'

                            my_telegram.send_to_user(my_telegram.your_user_id, message_to_send)
                        else:
                            print('error send order symbol', self.symbol, 'qty', qty_next, 'BUY')
        except Exception as err:
            logging.error(traceback.format_exc())     #print('error check_trade', err.__traceback__.tb_lineno, err)

    def thread_worker(self):
        """Основной поток"""
        print('start worker')
        self.update_inds()
        while self.work:
            try:
                sleeping_time = self.close_candle_time[self.timeframe] - time.time()
                if sleeping_time > 0:
                    time.sleep(sleeping_time)
                    self.update_inds()
                    self.check_trade()
                    my_function.output_control(self.symbol, self.timeframe, self.rsi, self.price, self.ema, self.data)


                    self.update_inds()
                    time.sleep(1)
                else:
                    self.update_inds()
                    time.sleep(1)
            except Exception as err:
                print('error worker', err.__traceback__.tb_lineno, err)
                time.sleep(1)


def main():
    client = MyClient(api_key='bgKOQGu2wTIO6Pdt3LR2OaPOvQ7Rd2UaUX7BRom3K54Yrarc16BarL5re7LnLceU',
                      api_secret='4M1XpcUzwWQem9JOB1WmppALNN1F9uSJBcjDxtyz34ylVTSe3lGalSdIc3Sr3DP6')
    # bot = MyBot(client)
    # bot.symbol = 'TWTBUSD'
    # bot.start_socket()
    # bot.thread_worker()
    bots_dict = {}

    currencies = {'TWTUSDT': {'qty_usdt': 15, 'ema_period': 100}}   #, 'ATOMUSDT': {'qty': 0.3, 'ema_period': 120}}

    # Создаем объекты MyBot и добавляем их в словарь bots_dict
    for symbol, info in currencies.items():
        bot = MyBot(client)
        bots_dict[symbol] = bot

        bot.symbol = symbol
        for key, value in info.items():
            bot.__setattr__(key, value)

        decision = input(f"Do you want to clear {symbol}_long_data.json before starting? (yes/no): ")
        if decision.lower() == 'yes':
            bot.load_data_from_json(f'{symbol}_long_data.json')
            bot.data = {}  # Очищаем данные перед началом
        elif decision.lower() == 'no':
            bot.load_data_from_json(f'{symbol}_long_data.json')
        else:
            print("Invalid input. Defaulting to not clearing the data.")
            bot.load_data_from_json(f'{symbol}_long_data.json')

    # Продолжаем запуск ботов
    bots = []
    for symbol, bot in bots_dict.items():
        bot.start_socket()

        th = threading.Thread(target=bot.thread_worker)
        th.start()
        bots.append({'bot': bot, 'thread': th})
        print(f'start {symbol} bot')

    # Здесь нам нужно чем-то занять основной поток программы, мы можем сделать просто while цикл
    # Или следить за работок потоков у какого-нибудь бота bots[-1]['thread'].join() - ждёт пока поток закончит работу
    while True:
        # Так же в этом цикле можем сделать вывод какой-нибудь информации, или менюшку для управления всеми ботами.
        # Сразу из консоли. и так далее..
        time.sleep(0.1)
        try:
            # Save data to JSON file periodically
            for symbol, bot in bots_dict.items():
                bot.save_data_to_json(f'{symbol}_long_data.json')
            time.sleep(60)  # Save data every minute
        except KeyboardInterrupt:
            # Handle KeyboardInterrupt to stop the program gracefully
            print("Stopping the program...")
            for bot in bots:
                bot['bot'].stop_socket(maximum=True)
                bot['thread'].join()
            break

if __name__ == '__main__':
    main()
