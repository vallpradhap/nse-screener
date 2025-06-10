from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__)

# Constants
MA_WINDOW = 44
CANDLES_BEFORE = 50
CANDLES_START = 2


def fetch_5min_data(symbol, start_date=None, end_date=None):
    try:
        if start_date and end_date:
            data = yf.download(symbol, interval="5m", start=start_date, end=end_date, auto_adjust=False)
        else:
            data = yf.download(symbol, interval="5m", period="7d", auto_adjust=False)

        if data.empty:
            return None

        data.index = pd.to_datetime(data.index)
        data.index = data.index.tz_localize('UTC').tz_convert('Asia/Kolkata')
        data = data.sort_index()
        data.columns = [str(col).title() for col in data.columns]

        return data
    except:
        return None


def resample_to_10min(df):
    df_10min = df.resample('10min', offset='15min').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()
    return df_10min


def get_44ma_on_52candles_from_date(symbol, start_date_str, data_5min=None):
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        prev5_date = start_date - timedelta(days=5)
        fetch_start = prev5_date.strftime("%Y-%m-%d")
        fetch_end = (start_date + timedelta(days=1)).strftime("%Y-%m-%d")

        if data_5min is None:
            data_5min = fetch_5min_data(symbol, fetch_start, fetch_end)

        if data_5min is None or data_5min.empty:
            return None

        data_10min = resample_to_10min(data_5min)
        data_10min['date'] = data_10min.index.date
        before_10min = data_10min[data_10min['date'] < start_date].drop(columns='date')
        start_10min = data_10min[data_10min['date'] == start_date].drop(columns='date')

        last50_before = before_10min.tail(CANDLES_BEFORE)
        first2_start = start_10min.head(CANDLES_START)
        combined_52 = pd.concat([last50_before, first2_start])

        combined_52['MA44'] = combined_52['Close'].rolling(window=MA_WINDOW).mean()
        return combined_52
    except:
        return None


def check_first2_against_ma44(df_10min, combined_52):
    if df_10min is None or combined_52 is None or len(df_10min) < 2 or len(combined_52) < 2:
        return "Not enough data"

    first2 = df_10min.head(2)
    last2_ma44 = combined_52['MA44'].tail(2)

    if first2.isnull().any().any() or last2_ma44.isnull().any():
        return "Not enough data"

    green = first2['Close'] > first2['Open']
    red = first2['Open'] > first2['Close']
    above_ma = (first2['Low'].values > last2_ma44.values)
    below_ma = (first2['High'].values < last2_ma44.values)

    if green.all() and above_ma.all():
        return "Bullish"
    elif red.all() and below_ma.all():
        return "Bearish"
    else:
        return "No Signal"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/screener', methods=['POST'])
def screener():
    data = request.json
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Live')
    date_str = data.get('date', '')

    today = datetime.now().date()
    if mode == 'Historical':
        try:
            start_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except:
            return jsonify({'error': 'Invalid date format'}), 400
    else:
        start_date = today

    end_date = start_date + timedelta(days=1)

    results = []

    for symbol in symbols:
        df_5min = fetch_5min_data(symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        if df_5min is None:
            results.append({"symbol": symbol, "signal": "No Data"})
            continue

        df_10min = resample_to_10min(df_5min)
        combined_52 = get_44ma_on_52candles_from_date(symbol, start_date.strftime("%Y-%m-%d"), df_5min)

        signal = check_first2_against_ma44(df_10min, combined_52)

        first_open = df_10min.iloc[0]['Open'] if len(df_10min) > 0 else ''
        first_close = df_10min.iloc[0]['Close'] if len(df_10min) > 0 else ''
        second_open = df_10min.iloc[1]['Open'] if len(df_10min) > 1 else ''
        second_close = df_10min.iloc[1]['Close'] if len(df_10min) > 1 else ''

        results.append({
            "symbol": symbol,
            "first_open": round(first_open, 2) if first_open else '',
            "first_close": round(first_close, 2) if first_close else '',
            "second_open": round(second_open, 2) if second_open else '',
            "second_close": round(second_close, 2) if second_close else '',
            "signal": signal
        })

    return jsonify(results)


if __name__ == '__main__':
    app.run(debug=True)