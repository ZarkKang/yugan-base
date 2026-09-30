"""
数据库种子数据 - 创建默认管理员用户和测试无人机
"""
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from .database import SessionLocal
from ..models.models import User, Drone, SystemConfig
from ..core.security import get_password_hash, verify_password

logger = logging.getLogger(__name__)

# 默认管理员账户
DEFAULT_ADMIN = {
    "username": "admin",
    "email": "admin@yugan.local",
    "password": "CHANGE_ME_DB_PASSWORD",
    "full_name": "系统管理员",
    "role": "admin",
}

# 默认测试无人机
DEFAULT_DRONE = {
    "drone_code": "DRONE001",
    "drone_name": "测试无人机",
    "model": "DJI-M300",
    "status": "offline",
    "battery_level": 100.0,
}

# 航点视频截取默认配置
DEFAULT_CLIP_CONFIGS = [
    {"key": "waypoint_clip_capture_enabled", "value": "true", "value_type": "boolean",
     "description": "航点视频截取总开关"},
    {"key": "waypoint_clip_capture_delay_seconds", "value": "0", "value_type": "float",
     "description": "航点到达后延迟截取秒数"},
    {"key": "waypoint_clip_capture_duration_seconds", "value": "10", "value_type": "float",
     "description": "截取片段时长秒数"},
    {"key": "waypoint_clip_position_tolerance_meters", "value": "0.2", "value_type": "float",
     "description": "到达位置验证容差(米)"},
]


def _user_exists(db: Session, username: str) -> bool:
    """检查用户是否已存在"""
    return db.query(User).filter(User.username == username).first() is not None


def _drone_exists(db: Session, drone_code: str) -> bool:
    """检查无人机是否已存在"""
    return db.query(Drone).filter(Drone.drone_code == drone_code).first() is not None


def seed_data() -> None:
    """初始化默认管理员用户和测试无人机"""
    db = SessionLocal()
    try:
        # 创建或修复管理员
        admin_user = db.query(User).filter(User.username == DEFAULT_ADMIN["username"]).first()
        if admin_user is None:
            admin_user = User(
                username=DEFAULT_ADMIN["username"],
                email=DEFAULT_ADMIN["email"],
                hashed_password=get_password_hash(DEFAULT_ADMIN["password"]),
                full_name=DEFAULT_ADMIN["full_name"],
                role=DEFAULT_ADMIN["role"],
                is_active=True,
            )
            db.add(admin_user)
            logger.info(f"✅ 默认管理员创建成功: {DEFAULT_ADMIN['username']}")
        else:
            # 每次都验证密码兼容性，防止bcrypt版本变更导致hash不兼容
            try:
                if not verify_password(DEFAULT_ADMIN["password"], admin_user.hashed_password):
                    admin_user.hashed_password = get_password_hash(DEFAULT_ADMIN["password"])
                    logger.info("🔄 管理员密码哈希已刷新（旧hash不兼容）")
            except Exception:
                admin_user.hashed_password = get_password_hash(DEFAULT_ADMIN["password"])
                logger.warning("🔄 管理员密码重置（验证异常，可能是bcrypt版本变更）")
            if not admin_user.is_active:
                admin_user.is_active = True
                logger.info("🔄 管理员账户已重新激活")

        # 创建测试无人机
        if _drone_exists(db, DEFAULT_DRONE["drone_code"]):
            logger.info("测试无人机已存在，跳过创建")
        else:
            drone = Drone(
                drone_code=DEFAULT_DRONE["drone_code"],
                drone_name=DEFAULT_DRONE["drone_name"],
                model=DEFAULT_DRONE["model"],
                status=DEFAULT_DRONE["status"],
                battery_level=DEFAULT_DRONE.get("battery_level", 100.0),
            )
            db.add(drone)
            logger.info(f"✅ 测试无人机创建成功: {DEFAULT_DRONE['drone_code']}")

        # 创建航点视频截取默认配置（幂等：ON CONFLICT DO NOTHING）
        for cfg in DEFAULT_CLIP_CONFIGS:
            exists = db.query(SystemConfig).filter(SystemConfig.key == cfg["key"]).first()
            if exists is None:
                db.add(SystemConfig(**cfg))
                logger.info(f"✅ 系统配置创建: {cfg['key']}={cfg['value']}")

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"种子数据创建失败: {e}")
    finally:
        db.close()