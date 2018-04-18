import logging

from config.cst import CONFIG_ENABLED_OPTION
from trading.trader.order import OrderConstants
from trading.trader.trader import Trader


class TraderSimulator(Trader):
    def __init__(self, config, exchange):
        super().__init__(config, exchange)
        self.risk = self.config["simulator"]["risk"]
        self.logger = logging.getLogger(self.__class__.__name__)
        self.simulate = True

    def enabled(self):
        if self.config["simulator"][CONFIG_ENABLED_OPTION]:
            return True
        else:
            return False

    def create_order(self, order_type, symbol, quantity, price=None, stop_price=None):
        self.logger.info("Order creation : {0} | {1} | Price : {2}".format(symbol, order_type, price))

        order_class = OrderConstants.TraderOrderTypeClasses[order_type]
        order = order_class(self)
        order.new(order_type, symbol, quantity, price, stop_price)
        self.order_manager.add_order_to_list(order)

