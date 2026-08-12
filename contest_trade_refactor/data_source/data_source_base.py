import pandas as pd
from config.config import PROJECT_ROOT
from pathlib import Path

class DataSourceBase:
    
    def __init__(self, name: str):
        self.name = name
        self.data_cache_dir = Path(PROJECT_ROOT) / "data_source" / "data_cache" / self.name
        if not self.data_cache_dir.exists():
            self.data_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_data_cached(self, trigger_time: str) -> pd.DataFrame:
        """
        get data from data source, return format should be a pandas dataframe
        including cols: ['title', 'content', 'pub_time', 'url']
        """
        cache_file_name = trigger_time.replace(" ", "_").replace(":", "-")
        cache_file = self.data_cache_dir / f"{cache_file_name}.pkl"
        if cache_file.exists():
            df = pd.read_pickle(cache_file)
            if df['pub_time'].dtype == 'datetime64[ns]':
                df['pub_time'] = df['pub_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            return df
        else:
            return None

    def save_data_cached(self, trigger_time: str, data: pd.DataFrame): 
        cache_file_name = trigger_time.replace(" ", "_").replace(":", "-")
        cache_file = self.data_cache_dir / f"{cache_file_name}.pkl"
        data.to_pickle(cache_file)

    def cached_data_is_usable(self, df: pd.DataFrame) -> bool:
        """Return False when cached report is a known fetch-failure placeholder."""
        if df is None or df.empty or "content" not in df.columns:
            return False
        failure_markers = ("数据获取失败", "数据格式异常")
        contents = [str(value) for value in df["content"].dropna().tolist()]
        if not contents:
            return False
        return not any(marker in content for content in contents for marker in failure_markers)

    def cached_data_has_trade_date(self, df: pd.DataFrame, trade_date: str) -> bool:
        """Return True when cached report appears to belong to the expected trade date."""
        if df is None or df.empty:
            return False
        if not self.cached_data_is_usable(df):
            return False
        compact_date = str(trade_date or "").replace("-", "")
        dashed_date = f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}" if len(compact_date) == 8 else compact_date
        text_parts = []
        for column in ["title", "content"]:
            if column in df.columns:
                text_parts.extend(str(value) for value in df[column].dropna().tolist())
        text = "\n".join(text_parts)
        return compact_date in text or dashed_date in text

    def get_data(self, trigger_time: str) -> pd.DataFrame:
        """
        get data from data source, return format should be a pandas dataframe
        including cols: ['title', 'content', 'pub_time', 'url']
        """
        pass

if __name__ == "__main__":
    pass
