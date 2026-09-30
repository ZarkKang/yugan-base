"""
安全模块 - JWT 认证 + 密码处理
统一认证配置 - 与无人机数据系统共享 SECRET_KEY
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

# 统一 SECRET_KEY - 两套系统共享
SECRET_KEY = "CHANGE_ME_JWT_SECRET_KEY"
ALGORITHM = "HS256"

# Token 过期时间配置
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24      # 24小时（默认）
ACCESS_TOKEN_EXPIRE_DAYS = 7               # 7天（记住登录状态）

# 密码加密上下文
# bcrypt__truncate_error=False: 静默截断超过72字节的密码
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    # bcrypt 最大支持 72 字节
    return pwd_context.hash(password[:72])


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None, remember_me: bool = False) -> str:
    """创建 JWT token
    
    Args:
        data: 要编码的数据（如 {"sub": username, "role": role}）
        expires_delta: 自定义过期时间增量
        remember_me: 是否记住登录状态（7天过期）
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    elif remember_me:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """解码 JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

