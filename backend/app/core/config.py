"""
应用配置模块
"""
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # 应用配置
    APP_NAME: str = Field(default="UI-Automation", description="应用名称")
    APP_VERSION: str = Field(default="1.0.0", description="应用版本")
    APP_ENV: str = Field(default="development", description="运行环境")
    DEBUG: bool = Field(default=True, description="调试模式")

    # 安全配置
    SECRET_KEY: str = Field(default="ui-automation-secret-key-change-in-production", description="JWT密钥")
    
    # 服务配置
    HOST: str = Field(default="0.0.0.0", description="服务地址")
    PORT: int = Field(default=8000, description="服务端口")
    
    # 数据库配置
    DB_HOST: str = Field(default="localhost", description="数据库地址")
    DB_PORT: int = Field(default=3306, description="数据库端口")
    DB_USER: str = Field(default="root", description="数据库用户")
    DB_PASSWORD: str = Field(default="", description="数据库密码")
    DB_NAME: str = Field(default="ui_automation", description="数据库名称")
    DB_ECHO: bool = Field(default=False, description="SQL日志输出")
    
    # SQLite配置（开发环境使用，生产切换MySQL）
    USE_SQLITE: bool = Field(default=True, description="使用SQLite（开发环境）")
    SQLITE_PATH: str = Field(default="data/ui_automation.db", description="SQLite文件路径")

    @property
    def DATABASE_URL(self) -> str:
        """数据库连接URL"""
        if self.USE_SQLITE:
            return f"sqlite:///{self.SQLITE_PATH}"
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
    
    # 日志配置
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")
    LOG_PATH: str = Field(default="logs", description="日志路径")
    
    # 文件上传配置
    UPLOAD_DIR: str = Field(default="uploads", description="上传目录")
    MAX_UPLOAD_SIZE: int = Field(default=10485760, description="最大上传大小")

    # 报告目录配置
    REPORT_DIR: str = Field(default="reports", description="测试报告输出目录")
    
    # Agent配置
    AGENT_TYPE: str = Field(default="mock", description="Agent类型")
    AGENT_TIMEOUT: int = Field(default=300, description="Agent超时时间")
    
    # AI服务配置（预留）
    UITARS_API_KEY: Optional[str] = Field(default=None, description="UI-TARS API密钥")
    UITARS_API_URL: Optional[str] = Field(default=None, description="UI-TARS API地址")
    
    DEEPSEEK_API_KEY: Optional[str] = Field(default=None, description="DeepSeek API密钥")
    DEEPSEEK_API_URL: Optional[str] = Field(default=None, description="DeepSeek API地址")

    # 通义千问配置
    QWEN_API_KEY: Optional[str] = Field(default=None, description="通义千问API密钥(DASHSCOPE)")
    QWEN_API_URL: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", description="通义千问API地址")
    QWEN_MODEL: str = Field(default="qwen-vl-plus", description="通义千问视觉模型名称")

    OLLAMA_HOST: str = Field(default="http://localhost:11434", description="Ollama地址")
    
    # 向量数据库配置
    MILVUS_HOST: str = Field(default="localhost", description="Milvus地址")
    MILVUS_PORT: int = Field(default=19530, description="Milvus端口")

    # Embedding配置
    EMBEDDING_PROVIDER: str = Field(default="dashscope", description="Embedding提供者: dashscope/local")
    EMBEDDING_MODEL: str = Field(default="text-embedding-v3", description="Embedding模型名称")
    EMBEDDING_DIM: int = Field(default=1024, description="Embedding向量维度")
    
    # 图数据库配置（预留）
    NEO4J_URI: str = Field(default="bolt://localhost:7687", description="Neo4j URI")
    NEO4J_USER: str = Field(default="neo4j", description="Neo4j用户")
    NEO4J_PASSWORD: str = Field(default="password", description="Neo4j密码")

    # ===== R2R / AnythingChat 知识服务配置 =====
    KNOWLEDGE_PROVIDER: str = Field(default="r2r", description="知识提供者: r2r | local")
    R2R_BASE_URL: str = Field(default="http://localhost:7272", description="R2R/AnythingChat服务地址")
    R2R_API_KEY: Optional[str] = Field(default=None, description="R2R API Key")

    @property
    def r2r_headers(self) -> dict:
        """R2R API 请求头（自动注入 API Key）"""
        headers = {"Content-Type": "application/json"}
        if self.R2R_API_KEY:
            headers["Authorization"] = f"Bearer {self.R2R_API_KEY}"
        return headers

    @property
    def is_r2r_enabled(self) -> bool:
        """是否启用 R2R 知识服务"""
        return self.KNOWLEDGE_PROVIDER.lower() == "r2r"

    # ===== Redis 配置 =====
    REDIS_HOST: str = Field(default="localhost", description="Redis地址")
    REDIS_PORT: int = Field(default=6379, description="Redis端口")
    REDIS_PASSWORD: str = Field(default="", description="Redis密码")
    REDIS_DB: int = Field(default=0, description="Redis数据库")
    REDIS_ENABLED: bool = Field(default=False, description="是否启用Redis队列")

    @property
    def redis_url(self) -> str:
        """Redis连接URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


# 全局配置实例
settings = Settings()
