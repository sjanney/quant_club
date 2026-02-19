import pandas as pd
import matplotlib.pyplot as plt

def clean_data():
    # We load in our filepath of our csv, and then created our dataframe
    filePath = "QFC_Data_Basics_sample_prices_raw.csv"
    dataframe = pd.read_csv(filePath)
    dataframe['date'] = pd.to_datetime(dataframe['date'])
    # Drop Null Values (assign result — dropna/drop_duplicates return new DataFrame)
    dataframe = dataframe.dropna(subset=['close'])
    dataframe = dataframe.drop_duplicates(subset=['date', 'ticker'], keep='first')
    return dataframe

def aggregate_data(dataframe):
    # We first sort the values by date
    dataframe = dataframe.sort_values(by='date')
    # We then forward fill the values based on the given tickers
    price_cols = ['close', 'adj_close']
    dataframe[price_cols] = dataframe.groupby('ticker')[price_cols].ffill()
    # We then return the dataframe
    return dataframe

def compute_returns(dataframe, price_col='adj_close'):
    # We compute the prices based on the formula new_price / old_price  - 1
    df = dataframe.sort_values(['ticker', 'date']).copy()
    df['return'] = df.groupby('ticker')[price_col].transform(lambda x: (x / x.shift(1)) - 1)
    return df

def plot_returns(dataframe):
    
    """Simply prints the graph of the returns based on the given data"""
    # We first grab the returns section of the dataframe
    df = dataframe.dropna(subset=['return'])
    # We then create some subplots
    fig, ax = plt.subplots(figsize=(14, 5))
    # THen for each ticker, we then go and calculate the return frrom
    for ticker in df['ticker'].unique():
        sub = df[df['ticker'] == ticker].sort_values('date')
        ax.plot(sub['date'], sub['return'], label=ticker, alpha=0.8)
    ax.set_xlabel('Date')
    ax.set_ylabel('Return (new/old - 1)')
    ax.set_title('Returns by Ticker')
    ax.legend(loc='best', fontsize=8)
    ax.axhline(0, color='gray', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

def main():
    df = clean_data()
    df = aggregate_data(df)
    df = compute_returns(df)
    print(df[['date', 'ticker', 'adj_close', 'return']].head(10))
    plot_returns(df)

if __name__ == '__main__':
    main()