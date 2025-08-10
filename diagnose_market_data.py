#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Market Data Diagnostics
- ポートフォリオ銘柄や任意のシンボルの価格取得を試行し、どのAPI/メソッドが成功したかを一覧表示します。
"""

import csv
import json
import os
import sys
from typing import List

from webull_bot_unified import WebullBotUnified


def load_symbols_from_portfolio(csv_path: str) -> List[str]:
    symbols = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                sym = (row.get('symbol') or '').strip()
                if sym:
                    symbols.append(sym)
    except Exception:
        pass
    return symbols


def main():
    # 引数: 追加シンボル（カンマ区切り）
    extra_symbols = []
    if len(sys.argv) > 1 and sys.argv[1]:
        extra_symbols = [s.strip().upper() for s in sys.argv[1].split(',') if s.strip()]

    bot = WebullBotUnified(dry_run=True)

    symbols = []
    portfolio_csv = bot.config.get('portfolio_config_file', 'portfolio.csv')
    symbols += load_symbols_from_portfolio(portfolio_csv)
    symbols += extra_symbols

    # 重複排除
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        symbols = ['SPY', 'QQQ', 'AAPL', 'MSFT', 'XLU']

    print('=== Market Data Diagnostics ===')
    print(f'Target symbols: {", ".join(symbols)}')

    for sym in symbols:
        price = bot.get_stock_price(sym)
        method = bot._last_price_method_by_symbol.get(sym, 'n/a')
        print(f'{sym}: price={price} via={method}')

    print('\nNote: 詳細な試行ログは logs/webull_bot_YYYYMMDD.log を参照してください。')


if __name__ == '__main__':
    main()
