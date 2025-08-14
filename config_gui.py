#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import pandas as pd
import streamlit as st

CONFIG_PATH = 'webull_config_with_allocation.json'
PORTFOLIO_PATH = 'portfolio.csv'

st.set_page_config(page_title='Webull Config Editor', layout='centered')
st.title('Webull 設定エディタ')

# Load config
if not os.path.exists(CONFIG_PATH):
    st.error(f'{CONFIG_PATH} が見つかりません')
    st.stop()

with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    cfg = json.load(f)

st.subheader('認証/アカウント')
app_key = st.text_input('app_key', value=cfg.get('app_key', ''), type='password')
app_secret = st.text_input('app_secret', value=cfg.get('app_secret', ''), type='password')
account_id = st.text_input('account_id', value=cfg.get('account_id', ''))
dry_run = st.checkbox('dry_run', value=cfg.get('dry_run', True))

st.subheader('API設定')
api_settings = cfg.get('api_settings', {})
max_retries = st.number_input('max_retries', min_value=0, value=int(api_settings.get('max_retries', 3)))
retry_delay = st.number_input('retry_delay (sec)', min_value=0.0, value=float(api_settings.get('retry_delay', 1.0)))
rate_limit_delay = st.number_input('rate_limit_delay (sec)', min_value=0.0, value=float(api_settings.get('rate_limit_delay', 2.0)))

st.subheader('Market Data 設定')
md = cfg.get('market_data_settings', {})
prefer = st.selectbox('prefer', options=['auto','mdata','quotes','yfinance'], index=['auto','mdata','quotes','yfinance'].index(md.get('prefer','auto')))
cache_ttl_seconds = st.number_input('cache_ttl_seconds', min_value=0, value=int(md.get('cache_ttl_seconds', 60)))
use_instrument_id = st.checkbox('use_instrument_id', value=bool(md.get('use_instrument_id', True)))
log_attempts = st.checkbox('log_attempts', value=bool(md.get('log_attempts', True)))

st.subheader('トレード設定（抜粋）')
tr = cfg.get('trading_settings', {})
price_slippage = st.number_input('price_slippage', min_value=0.0, value=float(tr.get('price_slippage', 0.01)))
order_timeout = st.number_input('order_timeout (sec)', min_value=0, value=int(tr.get('order_timeout', 300)))
conservative_price_margin = st.number_input('conservative_price_margin', min_value=0.0, value=float(tr.get('conservative_price_margin', 0.03)))

st.subheader('ポートフォリオ（CSV編集）')
if os.path.exists(PORTFOLIO_PATH):
    df = pd.read_csv(PORTFOLIO_PATH)
else:
    df = pd.DataFrame({'symbol': [], 'allocation_percentage': []})

edited_df = st.data_editor(df, num_rows='dynamic')

if st.button('保存'):
    # update config
    cfg['app_key'] = app_key
    cfg['app_secret'] = app_secret
    cfg['account_id'] = account_id
    cfg['dry_run'] = dry_run

    cfg['api_settings'] = {
        'max_retries': int(max_retries),
        'retry_delay': float(retry_delay),
        'rate_limit_delay': float(rate_limit_delay),
    }
    cfg['market_data_settings'] = {
        'prefer': prefer,
        'cache_ttl_seconds': int(cache_ttl_seconds),
        'use_instrument_id': bool(use_instrument_id),
        'log_attempts': bool(log_attempts),
    }
    # write files
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    edited_df.to_csv(PORTFOLIO_PATH, index=False)
    st.success('保存しました')

st.info('起動: streamlit run config_gui.py')


