import inspect
import logging

from config.cst import EvaluatorMatrixTypes, CONFIG_TRADER_MODE, CONFIG_TRADER, CONFIG_EVALUATORS_WILDCARD, \
    START_PENDING_EVAL_NOTE
from evaluator.evaluator_creator import EvaluatorCreator
from evaluator.evaluator_matrix import EvaluatorMatrix
from evaluator.TA import TAEvaluator
from evaluator.RealTime import RealTimeTAEvaluator
from evaluator.Social import SocialEvaluator
from evaluator.Strategies import StrategiesEvaluator
from trading.trader import modes
from trading.trader.modes import AbstractTradingMode


class SymbolEvaluator:
    def __init__(self, config, symbol, crypto_currency_evaluator):
        self.crypto_currency_evaluator = crypto_currency_evaluator
        self.symbol = symbol
        self.trader_simulator = None
        self.config = config
        self.traders = None
        self.trader_simulators = None
        self.logger = logging.getLogger("{0} {1}".format(self.symbol, self.__class__.__name__))

        self.evaluator_thread_managers = {}
        self.trading_mode_instances = {}
        self.matrices = {}
        self.strategies_eval_lists = {}
        self.finalize_enabled_list = {}

        self.trading_mode_class = self.get_trading_mode_class()

        self.strategies_with_evaluators = {}

        self.evaluator_instances_by_strategies = {}

    def set_traders(self, trader):
        self.traders = trader

    def set_trader_simulators(self, simulator):
        self.trader_simulators = simulator

    def get_trading_mode_class(self):
        if CONFIG_TRADER in self.config and CONFIG_TRADER_MODE in self.config[CONFIG_TRADER]:
            if any(m[0] == self.config[CONFIG_TRADER][CONFIG_TRADER_MODE] and
                   hasattr(m[1], '__bases__') and
                   AbstractTradingMode in m[1].__bases__
                   for m in inspect.getmembers(modes)):
                return getattr(modes, self.config[CONFIG_TRADER][CONFIG_TRADER_MODE])

        raise Exception("Please specify a valid trading mode in your config file (trader -> mode)")

    def add_evaluator_thread_manager(self, exchange, time_frame, evaluator_thread):
        if exchange.get_name() in self.evaluator_thread_managers:
            self.evaluator_thread_managers[exchange.get_name()][time_frame] = evaluator_thread
        else:
            self.evaluator_thread_managers[exchange.get_name()] = {time_frame: evaluator_thread}

            self.matrices[exchange.get_name()] = EvaluatorMatrix(self.config)
            self.strategies_eval_lists[exchange.get_name()] = EvaluatorCreator.create_strategies_eval_list(self.config)
            self.finalize_enabled_list[exchange.get_name()] = False

            self.init_evaluator_instances_by_strategies()

            self.trading_mode_instances[exchange.get_name()] = self.trading_mode_class(self.config, self, exchange)

    def init_evaluator_instances_by_strategies(self):
        for exchange, strategy_list in self.strategies_eval_lists.items():
            if exchange not in self.evaluator_instances_by_strategies:
                self.evaluator_instances_by_strategies[exchange] = {}
            for strategy in strategy_list:
                strategy_class = strategy.__class__
                if strategy_class not in self.evaluator_instances_by_strategies[exchange]:
                    self.evaluator_instances_by_strategies[exchange][strategy_class] = {
                        TAEvaluator: set(),
                        SocialEvaluator: set(),
                        RealTimeTAEvaluator: set()
                    }

    def add_evaluator_instance_to_strategy_instances_list(self, evaluator, exchange):
        exchange_name = exchange.get_exchange().get_name()
        for strategy in self.evaluator_instances_by_strategies[exchange_name].keys():
            if EvaluatorCreator.is_relevant_evaluator(evaluator, strategy.get_required_evaluators()):
                evaluator_parents = evaluator.get_parent_evaluator_classes()
                for evaluator_type in self.evaluator_instances_by_strategies[exchange_name][strategy].keys():
                    if evaluator_type in evaluator_parents:
                        self.evaluator_instances_by_strategies[exchange_name][strategy][evaluator_type].add(evaluator)

    def update_strategies_eval(self, new_matrix, exchange, ignored_evaluator=None):
        for strategies_evaluator in self.get_strategies_eval_list(exchange):
            if strategies_evaluator.get_is_active():
                strategies_evaluator.set_matrix(new_matrix)
                if not strategies_evaluator.get_name() == ignored_evaluator and strategies_evaluator.get_is_evaluable():
                    strategies_evaluator.eval()

                new_matrix.set_eval(EvaluatorMatrixTypes.STRATEGIES, strategies_evaluator.get_name(),
                                    strategies_evaluator.get_eval_note())
            else:
                new_matrix.set_eval(EvaluatorMatrixTypes.STRATEGIES, strategies_evaluator.get_name(),
                                    START_PENDING_EVAL_NOTE)

    def _get_evaluators_from_strategy(self, strategy, ta_list, rt_list, social_list):
        for exchange, strategy_classes in self.evaluator_instances_by_strategies.items():
            for strategy_class in strategy_classes:
                if strategy.__class__ == strategy_class:
                    strategy_instances = self.evaluator_instances_by_strategies[exchange][strategy_class]
                    ta_list.update(strategy_instances[TAEvaluator])
                    rt_list.update(strategy_instances[RealTimeTAEvaluator])
                    social_list.update(strategy_instances[SocialEvaluator])

    @staticmethod
    def _filter_and_activate_or_deactivate_evaluator(to_change_eval, to_keep_eval, activate):
        for evaluator in to_change_eval:
            if activate or evaluator not in to_keep_eval:
                if not activate and evaluator.get_is_active():
                    evaluator.reset()
                evaluator.set_is_active(activate)

    def activate_deactivate_strategies(self, strategies, exchange, activate=True):
        to_change_ta = set()
        to_change_rt = set()
        to_change_social = set()

        for strategy in strategies:
            self._get_evaluators_from_strategy(strategy, to_change_ta, to_change_rt, to_change_social)
            strategy.set_is_active(activate)
            if not activate and strategy.get_is_active():
                strategy.reset()

        to_keep_ta = set()
        to_keep_rt = set()
        to_keep_social = set()
        for strategy in self.get_strategies_eval_list(exchange, True):
            self._get_evaluators_from_strategy(strategy, to_keep_ta, to_keep_rt, to_keep_social)

        # only deactivate realtime evaluators and TA evaluators
        self._filter_and_activate_or_deactivate_evaluator(to_change_rt, to_keep_rt, activate)
        self._filter_and_activate_or_deactivate_evaluator(to_change_ta, to_keep_ta, activate)

        thread_managers = self.evaluator_thread_managers[exchange.get_name()]
        for evaluator_thread_manager in thread_managers.values():
            # force refresh TA eval
            if activate:
                evaluator_thread_manager.get_evaluator().data_changed = True
                evaluator_thread_manager.get_evaluator().update_ta_eval()
            evaluator_thread_manager.refresh_matrix()

        # finally, refresh strategies
        self.update_strategies_eval(next(iter(thread_managers.values())).matrix, exchange, None)

        self.logger.info("{} activated: {}".format([s.get_name() for s in strategies], activate))

    def finalize(self, exchange):
        if not self.finalize_enabled_list[exchange.get_name()]:
            self._check_finalize(exchange)

        if self.finalize_enabled_list[exchange.get_name()]:
            for decider in self.trading_mode_instances[exchange.get_name()].get_deciders():
                decider.add_to_queue()

    def _check_finalize(self, exchange):
        self.finalize_enabled_list[exchange.get_name()] = True
        for evaluator_thread in self.evaluator_thread_managers[exchange.get_name()].values():
            if evaluator_thread.get_refreshed_times() == 0:
                self.finalize_enabled_list[exchange.get_name()] = False

    def get_trader(self, exchange):
        return self.traders[exchange.get_name()]

    def get_trader_simulator(self, exchange):
        return self.trader_simulators[exchange.get_name()]

    def get_deciders(self, exchange):
        return self.trading_mode_instances[exchange.get_name()].get_deciders()

    def has_exchange(self, exchange):
        return exchange.get_name() in self.trading_mode_instances

    def get_matrix(self, exchange):
        return self.matrices[exchange.get_name()]

    def get_evaluator_thread_managers(self, exchange):
        return self.evaluator_thread_managers[exchange.get_name()]

    def get_config(self):
        return self.config

    def get_strategies_eval_list(self, exchange, active_only=False):
        if not active_only:
            return self.strategies_eval_lists[exchange.get_name()]
        else:
            return [strategy
                    for strategy in self.strategies_eval_lists[exchange.get_name()]
                    if strategy.get_is_active()]

    def get_symbol(self):
        return self.symbol

    def get_crypto_currency_evaluator(self):
        return self.crypto_currency_evaluator
