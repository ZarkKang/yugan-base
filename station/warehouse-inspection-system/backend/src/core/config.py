"""
配置文件 - 应用配置管理
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "Warehouse Inspection System"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库配置
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""  # set via env POSTGRES_PASSWORD
    POSTGRES_DB: str = "warehouse_inspection"

    # Redis配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # 串口配置
    SERIAL_PORT: str = "/dev/ttyUSB0"
    SERIAL_BAUDRATE: int = 9600

    # 以太网配置
    ETHERNET_HOST: str = "192.168.1.100"
    ETHERNET_PORT: int = 8080

    # RFID 自动扫描配置（应用启动时自动连接并开始连续扫描）
    # 默认关闭：无硬件环境（CI、纯前端调试）不应因连接失败而阻塞启动
    RFID_AUTO_CONNECT_ON_START: bool = False
    RFID_AUTO_SCAN_ON_START: bool = False

    # 安全配置
    SECRET_KEY: str = ""  # set via env SECRET_KEY

    # 日志配置
    LOG_LEVEL: str = "INFO"

    # API配置
    API_PREFIX: str = "/api/v1"

    # CORS配置
    CORS_ORIGINS: str = '["http://localhost:3000"]'

    # 覆盖用URL（留空则自动生）
    DATABASE_URL: str = ""
    REDIS_URL: str = ""

    def model_post_init(self, _context):
        """Pydantic v2 初始化后处理：自动生 URL"""
        if not self.DATABASE_URL:
            object.__setattr__(self, "DATABASE_URL",
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        if not self.REDIS_URL:
            object.__setattr__(self, "REDIS_URL",
                f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

