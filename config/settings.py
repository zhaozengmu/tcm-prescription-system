# Django 5.x 配置
# ============ 基础配置 ============
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# 密钥从环境变量注入，生产环境禁止硬编码
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-do-not-use-in-prod")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# ============ 应用注册 ============
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 五大功能模块 App
    "apps.users",          # 用户与医师管理
    "apps.patients",       # 患者信息管理
    "apps.prescriptions",  # 处方开具管理
    "apps.reviews",        # 处方审核管理
    "apps.stats",          # 历史查询与统计
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ============ 数据库 ============
# 默认使用 SQLite 便于课程实训快速启动；生产环境通过环境变量切换 MySQL
DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite")
if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", "tcm_rms"),
            "USER": os.environ.get("DB_USER", "root"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ============ 缓存 ============
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    # 无 Redis 时降级为本地内存缓存，保证开发环境可用
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

# ============ 密码与安全 ============
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 会话与 Cookie 安全
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 30  # 30 分钟会话过期

# 登录失败锁定：连续 5 次锁定 10 分钟
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 600

# ============ 国际化 ============
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# ============ 静态与媒体 ============
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# 文件上传限制：仅允许 PDF/JPG，单文件不超过 5MB
MAX_UPLOAD_SIZE = 5 * 1024 * 1024
ALLOWED_UPLOAD_TYPES = ["application/pdf", "image/jpeg", "image/png"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 自定义用户模型
AUTH_USER_MODEL = "users.User"

LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "stats:dashboard"
