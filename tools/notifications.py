import logging
import pprint
from abc import ABCMeta
from enum import Enum

from config.cst import CONFIG_CATEGORY_NOTIFICATION, CONFIG_CATEGORY_SERVICES, CONFIG_GMAIL, \
    CONFIG_SERVICE_INSTANCE, CONFIG_TWITTER, CONFIG_TELEGRAM, CONFIG_NOTIFICATION_PRICE_ALERTS, \
    CONFIG_NOTIFICATION_TRADES
from services import TwitterService, TelegramService
from services.gmail_service import GmailService
from tools.pretty_printer import PrettyPrinter
from trading.trader.trades_manager import TradesManager


class Notification:
    __metaclass__ = ABCMeta

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.notification_type = self.config[CONFIG_CATEGORY_NOTIFICATION]["type"]
        self._enable = self.config[CONFIG_CATEGORY_NOTIFICATION]

    # return True if key is enabled
    # if key is not given, return True if at least one key is enabled
    def enabled(self, key=None):
        if self._enable:
            if not key:
                return True in self._enable.values()
            elif key in self._enable:
                return self._enable[key]
            else:
                return False
        else:
            return False

    def notify_with_all(self, message):
        try:
            # gmail
            self.gmail_notification_factory(message, message)

            # twitter
            self.twitter_notification_factory(message)

            # telegram
            self.telegram_notification_factory(message)
        except Exception as e:
            self.logger.error("Failed to notify all : {0}".format(e))

    def gmail_notification_available(self, key=None):
        if self.enabled(key) and NotificationTypes.MAIL.value in self.notification_type:
            if GmailService.is_setup_correctly(self.config):
                return True
        return False

    def gmail_notification_factory(self, subject, mail):
        if self.gmail_notification_available():
            gmail_service = self.config[CONFIG_CATEGORY_SERVICES][CONFIG_GMAIL][CONFIG_SERVICE_INSTANCE]
            result = gmail_service.send_mail(subject, mail)
            if result:
                self.logger.info("Mail sent")
        else:
            self.logger.debug("Mail disabled")

    def telegram_notification_available(self, key=None):
        if self.enabled(key) and NotificationTypes.TELEGRAM.value in self.notification_type:
            if TelegramService.is_setup_correctly(self.config):
                return True
        return False

    def telegram_notification_factory(self, message):
        if self.telegram_notification_available():
            telegram_service = self.config[CONFIG_CATEGORY_SERVICES][CONFIG_TELEGRAM][CONFIG_SERVICE_INSTANCE]
            result = telegram_service.send_message(message)
            if result:
                self.logger.info("Telegram message sent")
        else:
            self.logger.debug("Telegram disabled")

    def twitter_notification_available(self, key=None):
        if self.enabled(key) and NotificationTypes.TWITTER.value in self.notification_type:
            if TwitterService.is_setup_correctly(self.config):
                return True
        return False

    def twitter_notification_factory(self, tweet):
        if self.twitter_notification_available():
            twitter_service = self.config[CONFIG_CATEGORY_SERVICES][CONFIG_TWITTER][CONFIG_SERVICE_INSTANCE]
            result = twitter_service.post(tweet)
            if result is not None:
                self.logger.info("Twitter sent")
            return result
        else:
            self.logger.debug("Twitter notification disabled")
        return None

    def twitter_response_factory(self, tweet_instance, tweet):
        if self.twitter_notification_available():
            twitter_service = self.config[CONFIG_CATEGORY_SERVICES][CONFIG_TWITTER][CONFIG_SERVICE_INSTANCE]
            result = twitter_service.respond(tweet_instance.id, tweet)
            if result is not None:
                self.logger.info("Twitter sent")
            return result
        else:
            self.logger.debug("Twitter notification disabled")
        return None


class EvaluatorNotification(Notification):
    def __init__(self, config):
        super().__init__(config)
        self.tweet_instance = None

    def notify_state_changed(self, notify_content):
        if self.twitter_notification_available(CONFIG_NOTIFICATION_PRICE_ALERTS):
            self.tweet_instance = self.twitter_notification_factory(notify_content)

        if self.telegram_notification_available(CONFIG_NOTIFICATION_PRICE_ALERTS):
            self.telegram_notification_factory(notify_content)

        return self

    def notify_alert(self, final_eval, crypto_currency_evaluator, symbol, trader, result, matrix):
        if self.gmail_notification_available(CONFIG_NOTIFICATION_PRICE_ALERTS):
            profitability, profitability_percent, _ = trader.get_trades_manager().get_profitability()

            self.gmail_notification_factory(
                "CRYPTO BOT ALERT : {0} / {1}".format(crypto_currency_evaluator.crypto_currency,
                                                      result),
                "CRYPTO BOT ALERT : {0} / {1} \n {2} \n Current portfolio "
                "profitability : {3} "
                "{4} ({5}%)".format(
                    crypto_currency_evaluator.crypto_currency,
                    result,
                    pprint.pformat(matrix),
                    round(profitability, 2),
                    TradesManager.get_reference_market(self.config),
                    round(profitability_percent, 2)))

        alert_content = PrettyPrinter.cryptocurrency_alert(
            crypto_currency_evaluator.crypto_currency,
            symbol,
            result,
            final_eval)

        if self.twitter_notification_available(CONFIG_NOTIFICATION_PRICE_ALERTS):
            self.tweet_instance = self.twitter_notification_factory(alert_content)

        if self.telegram_notification_available(CONFIG_NOTIFICATION_PRICE_ALERTS):
            self.telegram_notification_factory(alert_content)

        return self

    def get_tweet_instance(self):
        return self.tweet_instance


class OrdersNotification(Notification):
    def __init__(self, config):
        super().__init__(config)
        self.evaluator_notification = None

    def notify_create(self, evaluator_notification, orders):
        if orders:
            content = orders[0].trader.trader_type_str
            if evaluator_notification is not None:
                self.evaluator_notification = evaluator_notification

            content += "Order(s) creation "
            for order in orders:
                content += "\n- {0}".format(PrettyPrinter.open_order_pretty_printer(order))

            if self.twitter_notification_available(CONFIG_NOTIFICATION_TRADES) \
                    and self.evaluator_notification is not None \
                    and self.evaluator_notification.get_tweet_instance() is not None:
                tweet_instance = self.evaluator_notification.get_tweet_instance()
                self.twitter_response_factory(tweet_instance, content)

            if self.telegram_notification_available(CONFIG_NOTIFICATION_TRADES):
                self.telegram_notification_factory(content)

    def notify_end(self,
                   order_filled,
                   orders_canceled,
                   trade_profitability,
                   portfolio_profitability,
                   portfolio_diff,
                   profitability=False):

        content = ""

        if order_filled is not None:
            content += "\n{0}Order(s) filled : \n- {1}".format(
                order_filled.trader.trader_type_str,
                PrettyPrinter.open_order_pretty_printer(order_filled))

        if orders_canceled is not None and len(orders_canceled) > 0:
            content += "\n{0}Order(s) canceled :".format(orders_canceled[0].trader.trader_type_str)
            for order in orders_canceled:
                content += "\n- {0}".format(PrettyPrinter.open_order_pretty_printer(order))

        if trade_profitability is not None and profitability:
            content += "\n\nTrade profitability : {0}{1}%".format(
                "+" if trade_profitability >= 0 else "",
                round(trade_profitability * 100, 7))

        if portfolio_profitability is not None and profitability:
            content += "\nGlobal Portfolio profitability : {0}% {1}{2}%".format(
                round(portfolio_profitability, 5),
                "+" if portfolio_diff >= 0 else "",
                round(portfolio_diff, 7))

        if self.twitter_notification_available(CONFIG_NOTIFICATION_TRADES) \
                and self.evaluator_notification is not None \
                and self.evaluator_notification.get_tweet_instance() is not None:
            tweet_instance = self.evaluator_notification.get_tweet_instance()

            self.twitter_response_factory(tweet_instance, content)

        if self.telegram_notification_available(CONFIG_NOTIFICATION_TRADES):
            self.telegram_notification_factory(content)


class NotificationTypes(Enum):
    MAIL = 1
    TWITTER = 2
    TELEGRAM = 3
